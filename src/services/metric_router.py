"""路由决策器。

整合术语归一化、参数提取、SQL 组装，决定查询走指标通道还是 NL2SQL 通道。

路由结果：
  - channel="metric": 命中指标，直接执行视图 SQL
  - channel="clarify": 歧义术语，需要追问用户
  - channel="nl2sql": 未命中指标，走 LangGraph 工作流
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.services.metric_registry import get_metric
from src.services.param_extractor import extract_params_with_llm, extract_slots_with_confidence
from src.services.sql_assembler import assemble_sql, build_explain
from src.services.term_normalizer import get_clarification_prompt, normalize

logger = logging.getLogger(__name__)

# 分析性查询触发词 — 即使命中指标也应降级到 NL2SQL
# 这些词表示用户需要跨指标对比、原因分析、趋势分析等，视图无法直接回答
ANALYSIS_TRIGGERS = [
    "为什么",
    "原因",
    "对比",
    "比较",
    "趋势",
    "变化",
    "走势",
    "相关",
    "影响",
    "哪个",
    "哪些",  # 排名/筛选类查询，需要 NL2SQL
]

# 跨对象对比正则
_COMPARISON_PATTERN = re.compile(r"(?:和|与|跟).*(?:相比|比|对比|比较)")


def _has_analysis_trigger(query: str) -> bool:
    """检查查询是否包含分析性触发词，需要降级到 NL2SQL。"""
    for word in ANALYSIS_TRIGGERS:
        if word in query:
            return True
    return bool(_COMPARISON_PATTERN.search(query))


@dataclass
class RouteResult:
    """路由决策结果。"""

    channel: str = "nl2sql"  # metric / clarify / ask / multi_metric / nl2sql
    query: str = ""  # 原始查询
    metric_id: str = ""  # 指标 ID（单指标时）
    metric_name: str = ""  # 指标名称（单指标时）
    sql: str = ""  # 组装后的 SQL（参数化模板，含 %s 占位符）
    sql_params: list = field(default_factory=list)  # 参数化 SQL 的参数值列表
    explain: str = ""  # 查询说明（单指标时）
    params: dict = field(default_factory=dict)  # 提取的参数（单指标时）
    matched_term: str = ""  # 命中的术语
    clarification_prompt: str = ""  # 歧义追问 / 槽位追问提示
    candidates: list[dict] = field(default_factory=list)  # 歧义候选指标
    # 多指标相关
    multi_metric_ids: list[str] = field(default_factory=list)  # 多指标时的指标 ID 列表
    multi_sqls: list[dict] = field(default_factory=list)  # [{metric_id, metric_name, sql, sql_params, explain}]


async def route(query: str) -> RouteResult:
    """路由决策完整流程。

    1. 术语归一化 → 检查是否命中指标
    2. 歧义 → 返回 channel="clarify"
    3. 多指标 → 返回 channel="multi_metric"
    4. 明确命中 → 参数提取 → SQL 组装 → 返回 channel="metric"
    5. 未命中 → 返回 channel="nl2sql"
    """
    # 1. 术语归一化
    result = normalize(query)

    if not result.matched_term and not result.multi_match:
        # 未命中任何指标，走 NL2SQL
        return RouteResult(channel="nl2sql", query=query)

    # 1.5 分析性查询降级检查：即使命中指标，如果是跨指标对比/原因分析/趋势分析，
    # 也应降级到 NL2SQL（视图无法回答这类问题）
    if _has_analysis_trigger(query):
        logger.info("metric_route: 触发分析性词语降级 → NL2SQL, query=%s", query)
        return RouteResult(channel="nl2sql", query=query)

    if result.ambiguous:
        # 歧义术语，需要追问
        return RouteResult(
            channel="clarify",
            query=query,
            matched_term=result.matched_term,
            candidates=result.candidates,
            clarification_prompt=get_clarification_prompt(result.matched_term, result.candidates),
        )

    if result.multi_match:
        # 多个指标，分别组装 SQL
        multi_sqls = []
        for mid in result.multi_metric_ids:
            metric = get_metric(mid)
            if not metric:
                continue
            params = await extract_params_with_llm(query, metric.params)
            sql_template, sql_params = assemble_sql(mid, params)
            explain = build_explain(mid, params)
            multi_sqls.append(
                {
                    "metric_id": mid,
                    "metric_name": metric.name,
                    "sql": sql_template,
                    "sql_params": sql_params,
                    "explain": explain,
                }
            )
        return RouteResult(
            channel="multi_metric",
            query=query,
            multi_metric_ids=result.multi_metric_ids,
            multi_sqls=multi_sqls,
        )

    # 2. 明确命中 → 参数提取 + 槽位检查
    metric = get_metric(result.metric_id)
    if not metric:
        return RouteResult(channel="nl2sql", query=query)

    # 2.1 槽位置信度检查：如果有 edit_dist 匹配的槽位，追问确认
    # 限制条件：仅当查询长度 >= 5 且匹配的 token 非已知指标术语时触发
    # 避免 "WIP" 这类短查询误触发 pdline 追问
    slot_results = extract_slots_with_confidence(query, metric.params)
    uncertain_slots = [
        (pdef, sr)
        for pdef, sr in zip(metric.params, slot_results, strict=True)
        if sr.confidence == "edit_dist" and sr.value
    ]
    if uncertain_slots and len(query) >= 5:
        pdef, sr = uncertain_slots[0]
        # 检查匹配值是否在已知指标别名中（避免指标术语触发槽位追问）
        from src.services.metric_registry import TERM_ALIAS_MAP

        if sr.value.lower() not in TERM_ALIAS_MAP:
            ask_prompt = f"您说的是「{sr.value}」吗？"
            if pdef.prompt:
                ask_prompt = pdef.prompt + " " + ask_prompt
            return RouteResult(
                channel="ask",
                query=query,
                clarification_prompt=ask_prompt,
                metric_id=result.metric_id,
                metric_name=metric.name,
            )

    # 2.2 提取参数
    params = await extract_params_with_llm(query, metric.params)

    # 3. SQL 组装
    sql_template, sql_params = assemble_sql(result.metric_id, params)
    explain = build_explain(result.metric_id, params)

    return RouteResult(
        channel="metric",
        query=query,
        metric_id=result.metric_id,
        metric_name=metric.name,
        sql=sql_template,
        sql_params=sql_params,
        explain=explain,
        params=params,
        matched_term=result.matched_term,
    )


async def route_clarification(query: str, selected_metric_id: str) -> RouteResult:
    """用户选择了歧义指标后，再次路由。

    Args:
        query: 原始查询
        selected_metric_id: 用户选择的指标 ID
    """
    metric = get_metric(selected_metric_id)
    if not metric:
        return RouteResult(channel="nl2sql", query=query)

    params = await extract_params_with_llm(query, metric.params)
    sql_template, sql_params = assemble_sql(selected_metric_id, params)
    explain = build_explain(selected_metric_id, params)

    return RouteResult(
        channel="metric",
        query=query,
        metric_id=selected_metric_id,
        metric_name=metric.name,
        sql=sql_template,
        sql_params=sql_params,
        explain=explain,
        params=params,
    )


async def route_slot_answer(query: str, confirmed_metric_id: str) -> RouteResult:
    """用户确认槽位值后，重新路由（跳过置信度检查）。

    用于槽位填充追问场景：当用户查询被返回 channel="ask" 后，
    用户确认（点击"是"），调用此函数跳过置信度检查直接组装 SQL。

    Args:
        query: 原始查询
        confirmed_metric_id: 追问时确认的指标 ID
    """
    metric = get_metric(confirmed_metric_id)
    if not metric:
        return RouteResult(channel="nl2sql", query=query)

    params = await extract_params_with_llm(query, metric.params)
    sql_template, sql_params = assemble_sql(confirmed_metric_id, params)
    explain = build_explain(confirmed_metric_id, params)

    return RouteResult(
        channel="metric",
        query=query,
        metric_id=confirmed_metric_id,
        metric_name=metric.name,
        sql=sql_template,
        sql_params=sql_params,
        explain=explain,
        params=params,
    )
