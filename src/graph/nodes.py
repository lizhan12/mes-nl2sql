"""LangGraph 工作流节点实现。

对应原 Dify 工作流的 7 个节点：
  1. 意图理解 (LLM)
  2. 并行检索 (向量检索)
  3. BFS 图扩展 (代码逻辑)
  4. Schema 组装 (代码逻辑)
  5. SQL 生成 (LLM)
  6. 安全校验 (代码逻辑)
  7. SQL 执行与修复 (代码逻辑 + LLM，最多重试 3 次)

LLM 输出模式：
  - streaming=True: 通过 get_stream_writer() 逐 token 输出到 SSE 流
  - streaming=False: 一次性返回完整结果
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from langgraph.config import get_stream_writer

from src.core.config import settings
from src.graph.state import GraphState
from src.harness.knowledge import load_evolved_few_shot_text, load_runtime_rules, normalize_question
from src.services.bfs import (
    bfs_expand,
    build_chain_join_hints,
    build_join_hints,
    build_path_join_hints,
    find_path_between,
)
from src.services.db_pool import execution_connection
from src.services.vector_store import _get_schema_lookup, hybrid_search_schema, search_few_shot
from src.trace.tracer import trace_llm_call, trace_llm_call_astream, trace_node
from src.utils import strip_thinking
from src.utils.sql_validator import semantic_sanity_check, validate_sql

logger = logging.getLogger(__name__)

# ---- 常量 ----
_MAX_RETRIES = 3

# ---- Prompt 模板 ----

_INTENT_PROMPT = """你是MES系统数据分析专家。分析用户问题，输出结构化查询意图。

MES业务域：
- production(t_pd_)：工单、SN追溯、过站、不良、计划
- quality(t_qm_)：IQC/IPQC/FQC检验、质量文件
- warehouse(t_wms_)：库存、入出库、领退料
- equipment(t_ems_)：设备台账、报修、保养、点检
- master(t_bd_)：料号、BOM、产线、工序（基础数据，几乎总是需要）

仅输出JSON，不加任何说明：
{{
  "query_type": "single",
  "query_complexity": "medium",
  "sub_queries": [],
  "intent_domains": [],
  "anchor_tables": [],
  "search_queries": [],
  "semantic_expansion": [],
  "aggregation_hint": false,
  "group_by_hint": [],
  "time_range": "",
  "filters": [],
  "confidence": 1.0,
  "low_confidence_reason": ""
}}

字段规则：

【intent_domains】
从 production/quality/warehouse/equipment/master 中选，可多选。
master 几乎总是需要，除非问题纯粹是设备或库存类。

【anchor_tables】
只填 100% 确定的表名，不确定宁可留空。
判断标准：该表在该业务场景下唯一且明确，不存在同义替代表。

【search_queries】
用于向量检索 view/table 的关键词，3-5 个为宜。
要求：贴近元数据中的表名、视图名、字段注释的描述风格。
示例："良品率" → ["检验结果", "合格数量", "首次通过"]

【semantic_expansion】
业务语义扩展词，补充用户没说但逻辑上必要的概念。
与 search_queries 区别：这里是业务术语扩展，不直接用于检索。
示例："良品率" → ["FPY", "直通率", "返工标记", "最终工站"]

【query_type】
判断标准：能否用一条 SQL 返回所有所需数据。
- single：一条 SQL 可满足
- multi：必须分多条独立 SQL 执行再合并
注意：同一查询的多个聚合列（如"发料数量和退料数量"）属于 single。

【query_complexity】
查询复杂度，影响 BFS 扩展跳数。
- simple：单表查询，直接查字段，无需跨表 JOIN（如"查工单状态"）
- medium：常规跨表 JOIN，2 跳以内可到达目标表（如"查工单的料号信息"）
- complex：多跳追溯、跨域串联，需要 3 跳以上（如"追溯 SN 从投料到入库的完整过站记录"）

【sub_queries】
仅当 query_type 为 multi 时填写。
每项包含：
- question：独立完整的问题描述，不含代词引用
- description：简短标签（如"过站记录"、"不良统计"）

【aggregation_hint】
布尔值。问题包含"统计/汇总/合计/平均/最多/占比/率"等聚合语义时为 true。

【group_by_hint】
当 aggregation_hint 为 true 时填写，列出用户明确或隐含的分组维度。
示例："按工单统计" → ["工单号"]；"各产线对比" → ["产线编号"]

【time_range】
用户明确提及的时间范围，原样保留自然语言描述。
未提及则留空，不要推断默认值。

【filters】
用户明确指定的过滤条件，格式为自然语言描述。
不要推断隐含的业务过滤规则（如"只算最终工站"），那是 view 层的职责。

【confidence】
0.0-1.0，反映意图识别的整体置信度。
- 1.0：关键词明确，业务域唯一，无歧义
- 0.7-0.9：语义可推断，但存在轻微歧义
- < 0.7：存在明显歧义，必须填写 low_confidence_reason

【low_confidence_reason】
confidence < 0.7 时必填。
描述歧义点，格式："'XXX'可能指[A]或[B]，需要进一步确认"。
不要在这里做裁定，只描述歧义。

用户问题：{user_question}"""

_SQL_TABLE_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w\.]*)\s*(?:AS\s+)?([a-zA-Z_][\w]*)?", re.IGNORECASE)
_SQL_JOIN_PATTERN = re.compile(
    r"\bJOIN\s+[a-zA-Z_][\w\.]*\s*(?:AS\s+)?(?:[a-zA-Z_][\w]*)?\s+ON\s+(.+?)(?=\b(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|;|$)",
    re.IGNORECASE | re.DOTALL,
)
_SQL_KEYWORDS = {
    "WHERE",
    "GROUP",
    "ORDER",
    "LIMIT",
    "LEFT",
    "RIGHT",
    "INNER",
    "FULL",
    "CROSS",
    "JOIN",
    "ON",
}


def _truncate_chunks_by_count(text: str, max_items: int) -> str:
    """按 "\n---\n" 分隔的 chunk 粒度截断，保留前 max_items 条。"""
    if not text or not text.strip():
        return text
    chunks = text.split("\n---\n")
    if len(chunks) <= max_items:
        return text
    logger.info("截断 chunks: %d -> %d 条", len(chunks), max_items)
    return "\n---\n".join(chunks[:max_items])


_GENERIC_TERM_TABLES = [
    ("料号名称", ["t_bd_part"]),
    ("料号", ["t_bd_part"]),
    ("物料", ["t_bd_part"]),
    ("单位", ["t_bd_unit"]),
    ("仓库", ["t_wms_warehouse"]),
    ("供应商", ["t_bd_supplier"]),
    ("客户", ["t_bd_customer"]),
    ("单据类型", ["t_wms_doc_type"]),
    ("部门", ["t_bd_department"]),
    ("工序", ["t_bd_process"]),
    ("工作站", ["t_bd_terminal"]),
    ("设备型号", ["t_ems_model"]),
    ("设备", ["t_ems_equipment"]),
    ("标签组", ["t_lb_label_group"]),
    ("标签", ["t_lb_label"]),
    ("编码规则组", ["t_bc_encode_rule_group"]),
    ("编码规则", ["t_bc_encode_rule"]),
    ("包装规则", ["t_packing_rule"]),
]


_PROMPT_CACHE: dict[str, str] = {}


def _load_prompt(filename: str) -> str:
    """加载 prompt 模板（模块级缓存，避免每次构建 prompt 都读磁盘）。"""
    if filename in _PROMPT_CACHE:
        return _PROMPT_CACHE[filename]
    path = Path(__file__).parent.parent.parent / "data" / filename
    if path.exists():
        _PROMPT_CACHE[filename] = path.read_text(encoding="utf-8")
        return _PROMPT_CACHE[filename]
    return ""


def _normalize_join_expr(expr: str, alias_map: dict[str, str]) -> str:
    match = re.search(
        r"([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\s*=\s*([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)",
        expr,
        re.IGNORECASE,
    )
    if not match:
        return re.sub(r"\s+", " ", expr.strip())

    left_alias, left_col, right_alias, right_col = match.groups()
    left_table = alias_map.get(left_alias, left_alias)
    right_table = alias_map.get(right_alias, right_alias)
    left = f"{left_table}.{left_col}"
    right = f"{right_table}.{right_col}"
    ordered = sorted([left, right])
    return f"{ordered[0]} = {ordered[1]}"


def _load_schema_lookup() -> dict[str, str]:
    path = Path(__file__).parent.parent.parent / "data" / "mes_knowledge_base.txt"
    if not path.exists():
        return {}

    lookup: dict[str, str] = {}
    for chunk in path.read_text(encoding="utf-8").split("\n---\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = re.search(r"表名：(\w+)", chunk)
        if match:
            lookup[match.group(1)] = chunk
    return lookup


async def _load_runtime_regression_cases() -> dict[str, dict[str, Any]]:
    runtime_cases: dict[str, dict[str, Any]] = {}
    for rule in await load_runtime_rules():
        if not isinstance(rule, dict):
            continue
        # 跳过已禁用的规则
        if rule.get("enabled") is False:
            continue
        question = str(rule.get("question", "")).strip()
        normalized = str(rule.get("normalized_question") or normalize_question(question))
        if not normalized:
            continue
        runtime_cases[normalized] = {
            "question": question,
            "preferred_main_table": str(rule.get("preferred_main_table", "")).strip(),
            "required_tables": [
                item for item in rule.get("required_tables", []) if isinstance(item, str) and item.strip()
            ],
            "required_joins": [
                item for item in rule.get("required_joins", []) if isinstance(item, str) and item.strip()
            ],
        }
    return runtime_cases


_SCHEMA_LOOKUP = _load_schema_lookup()


def _parse_intent_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


async def _find_regression_case(query: str) -> dict[str, Any] | None:
    """查找匹配的运行时规则，支持向量检索和精确匹配。"""
    # 优先使用向量检索（模糊匹配）
    if _runtime_rule_store:
        try:
            from src.services.vector_store import search_runtime_rules

            rules = await search_runtime_rules(
                _runtime_rule_store, query, k=1, threshold=settings.runtime_rule_similarity_threshold
            )
            if rules:
                return rules[0]
        except Exception as e:
            logger.warning("runtime_rule 向量检索失败: %s", e)

    # 回退到精确匹配
    normalized = normalize_question(query)
    runtime_cases = await _load_runtime_regression_cases()
    return runtime_cases.get(normalized)


def _derive_generic_constraints(query: str) -> dict[str, Any]:
    required_tables: list[str] = []
    guidance_lines: list[str] = []

    for term, tables in _GENERIC_TERM_TABLES:
        if term in query:
            required_tables.extend(tables)

    lowered_query = query.lower()
    preferred_main_table = ""
    if "明细" in query or "细项" in query:
        if "工单领料单" in query:
            preferred_main_table = "t_wms_wo_material_bill_detail"
        elif "生产退料单" in query:
            preferred_main_table = "t_wms_wo_rb_detail"
        elif "bom" in lowered_query:
            preferred_main_table = "t_bd_bom_detail"
        elif "生产计划" in query:
            preferred_main_table = "t_pd_plan_detail"

    if preferred_main_table:
        guidance_lines.append(f"- 该问题包含明细语义，主表优先使用 `{preferred_main_table}`。")

    return {
        "preferred_main_table": preferred_main_table,
        "required_tables": _dedupe_keep_order(required_tables),
        "required_joins": [],
        "guidance_lines": guidance_lines,
    }


async def _build_query_constraints(query: str, llm_intent: dict[str, Any]) -> tuple[dict[str, Any], str]:
    guidance_lines: list[str] = []
    required_tables: list[str] = []
    required_joins: list[str] = []
    preferred_main_table = ""

    regression_case = await _find_regression_case(query)
    if regression_case:
        preferred_main_table = regression_case["preferred_main_table"]
        required_tables = list(regression_case["required_tables"])
        required_joins = list(regression_case["required_joins"])
        guidance_lines.extend(
            [
                "- 该问题命中已知联表回归用例，必须严格按以下结构生成 SQL。",
                f"- 主表必须使用 `{preferred_main_table}`。",
                f"- 必须覆盖以下表：{', '.join(required_tables)}。",
                "- 必须满足以下 JOIN：",
                *[f"  - `{join_expr}`" for join_expr in required_joins],
            ]
        )
    else:
        derived = _derive_generic_constraints(query)
        preferred_main_table = derived["preferred_main_table"]
        required_tables = list(derived["required_tables"])
        required_joins = list(derived["required_joins"])
        guidance_lines.extend(derived["guidance_lines"])

    search_queries = (
        list(llm_intent.get("search_queries", [])) if isinstance(llm_intent.get("search_queries"), list) else []
    )
    semantic_expansion = (
        list(llm_intent.get("semantic_expansion", [])) if isinstance(llm_intent.get("semantic_expansion"), list) else []
    )
    anchor_tables = (
        list(llm_intent.get("anchor_tables", [])) if isinstance(llm_intent.get("anchor_tables"), list) else []
    )

    if preferred_main_table:
        anchor_tables.insert(0, preferred_main_table)
        search_queries.append(preferred_main_table)
    anchor_tables.extend(required_tables)
    search_queries.extend(required_tables)

    # 验证 anchor_tables 中的表名是否在知识库中真实存在，过滤意图 LLM 幻觉的表名
    schema_lookup = _get_schema_lookup()
    validated_anchors: list[str] = []
    for t in _dedupe_keep_order(anchor_tables):
        if t in schema_lookup:
            validated_anchors.append(t)
            continue
        # 前缀匹配兜底：如 t_wms 不存在，但 t_wms_warehouse / t_wms_wo_rb 存在
        candidates = [k for k in schema_lookup if k.startswith(t + "_")]
        if len(candidates) == 1:
            logger.warning("anchor_table '%s' 不存在于知识库，前缀匹配替换为 '%s'", t, candidates[0])
            validated_anchors.append(candidates[0])
        elif candidates:
            logger.warning("anchor_table '%s' 不存在于知识库且前缀匹配到多个候选 %s，跳过以避免歧义", t, candidates)
        else:
            logger.warning("anchor_table '%s' 不存在于知识库，跳过", t)
    anchor_tables = validated_anchors

    llm_intent["anchor_tables"] = _dedupe_keep_order(anchor_tables)
    llm_intent["search_queries"] = _dedupe_keep_order([query, *search_queries])
    llm_intent["semantic_expansion"] = _dedupe_keep_order(semantic_expansion)
    llm_intent["preferred_main_table"] = preferred_main_table
    llm_intent["required_tables"] = _dedupe_keep_order(required_tables)
    llm_intent["required_joins"] = _dedupe_keep_order(required_joins)

    query_guidance = "\n".join(guidance_lines).strip() or "（无额外硬约束）"
    return llm_intent, query_guidance


def _extract_sql_tables(sql: str) -> tuple[str, list[str], dict[str, str]]:
    alias_map: dict[str, str] = {}
    tables: list[str] = []

    for match in _SQL_TABLE_PATTERN.finditer(sql):
        table = match.group(1)
        alias = match.group(2) or table
        if alias.upper() in _SQL_KEYWORDS:
            alias = table
        alias_map[alias] = table
        alias_map[table] = table
        if table not in tables:
            tables.append(table)

    main_table = tables[0] if tables else ""
    return main_table, tables, alias_map


def _extract_sql_joins(sql: str, alias_map: dict[str, str]) -> list[str]:
    joins: list[str] = []
    for match in _SQL_JOIN_PATTERN.finditer(sql):
        clause = match.group(1)
        for piece in re.split(r"\bAND\b", clause, flags=re.IGNORECASE):
            piece = piece.strip().strip("()")
            if not piece:
                continue
            joins.append(_normalize_join_expr(piece, alias_map))
    return joins


def _build_sql_constraint_feedback(sql: str, intent: dict[str, Any]) -> str:
    preferred_main_table = str(intent.get("preferred_main_table", "")).strip()
    required_tables = [t for t in intent.get("required_tables", []) if isinstance(t, str)]
    required_joins = [j for j in intent.get("required_joins", []) if isinstance(j, str)]

    main_table, tables, alias_map = _extract_sql_tables(sql)
    joins = _extract_sql_joins(sql, alias_map)
    violations: list[str] = []

    if preferred_main_table and main_table != preferred_main_table:
        violations.append(f"- 当前 SQL 主表是 `{main_table}`，但必须使用 `{preferred_main_table}` 作为 FROM 主表。")

    missing_tables = [table for table in required_tables if table not in tables]
    if missing_tables:
        violations.append(f"- 当前 SQL 缺少必须覆盖的表：{', '.join(f'`{table}`' for table in missing_tables)}。")

    missing_joins = [join_expr for join_expr in required_joins if join_expr not in joins]
    if missing_joins:
        violations.append("- 当前 SQL 缺少必须满足的 JOIN：")
        violations.extend(f"  - `{join_expr}`" for join_expr in missing_joins)

    if not violations:
        return ""

    return "\n".join(
        [
            "上一版 SQL 未满足结构约束，请严格重写。",
            *violations,
            "- 只能输出新的完整 SQL，不要解释。",
        ]
    )


def _parse_columns_from_schema(schema_context: str) -> dict[str, set[str]]:
    """从 schema_context 文本中提取 {表名 -> {列名小写集合}} 映射。

    schema_context 格式：
        表名：t_pd_sn_material
        关键字段：
          sn (varchar(200)) -- 主条码
          item_part_no (varchar(40)) -- 子件料号
          ...
    """
    result: dict[str, set[str]] = {}
    chunks = schema_context.split("\n---\n")
    for chunk in chunks:
        table_match = re.search(r"表名：(\w+)", chunk)
        if not table_match:
            continue
        table_name = table_match.group(1)
        columns: set[str] = set()
        in_fields = False
        for line in chunk.split("\n"):
            line = line.strip()
            if line == "关键字段：":
                in_fields = True
                continue
            if in_fields and line.startswith(("关联关系：", "适用场景：")):
                break
            if in_fields:
                m = re.match(r"(\w+)\s*\(", line)
                if m:
                    columns.add(m.group(1).lower())
        if columns:
            result[table_name] = columns
    return result


def _build_column_feedback(sql: str, schema_context: str) -> str:
    """校验 SQL 中 alias.column 是否存在于 schema_context 或数据库中。

    优先从 schema_context 文本中提取列名（零 IO）；
    若表不在 schema_context 中，则回退到数据库查询 information_schema.columns。
    对不存在的列名用编辑距离模糊匹配推荐最相似的列名。
    """
    alias_map = _extract_alias_table_map(sql)
    schema_columns = _parse_columns_from_schema(schema_context)
    if not alias_map:
        return ""

    # 收集需要从数据库查询的表（schema_context 中没有的）
    db_tables_needed: set[str] = set()
    for match in re.finditer(r"\b([a-z_]\w*)\.(\w+)", sql):
        alias = match.group(1).lower()
        if alias not in alias_map:
            continue
        table_name = alias_map[alias].lower()
        if table_name not in schema_columns:
            db_tables_needed.add(table_name)

    # 从数据库补充缺失表的列名
    db_columns_cache: dict[str, set[str]] = {}
    for table_name in db_tables_needed:
        cols = _get_table_columns(table_name)
        if cols:
            db_columns_cache[table_name] = {c.lower() for c in cols}

    # 合并两个来源的列名
    all_columns: dict[str, set[str]] = {**schema_columns, **db_columns_cache}
    if not all_columns:
        return ""

    violations: list[str] = []
    for match in re.finditer(r"\b([a-z_]\w*)\.(\w+)", sql):
        alias, col = match.group(1).lower(), match.group(2).lower()
        if alias not in alias_map:
            continue
        table_name = alias_map[alias].lower()
        if table_name not in all_columns:
            continue
        if col not in all_columns[table_name]:
            similar = _fuzzy_best_columns(col, list(all_columns[table_name]), top_n=5)
            hint = f"列 '{alias}.{col}' 在表 {table_name} 中不存在"
            if similar:
                hint += f"，最相似的列名: {', '.join(similar)}"
            violations.append(hint)

    if violations:
        return "列名校验发现以下问题：\n" + "\n".join(f"- {v}" for v in violations)
    return ""


# ---- 节点函数 ----

# 全局 store 引用（由 workflow 初始化时注入）
_schema_store = None
_few_shot_store = None
_evolved_few_shot_store = None
_runtime_rule_store = None


def init_stores(schema_store, few_shot_store, evolved_few_shot_store=None, runtime_rule_store=None):
    """初始化向量存储引用。"""
    global _schema_store, _few_shot_store, _evolved_few_shot_store, _runtime_rule_store
    _schema_store = schema_store
    _few_shot_store = few_shot_store
    _evolved_few_shot_store = evolved_few_shot_store
    _runtime_rule_store = runtime_rule_store


# ── LLM 调用辅助：统一处理流式/非流式 ──


async def _call_llm(
    prompt: str,
    *,
    node_name: str,
    model: str = "",
    streaming: bool = False,
    retry_seq: int = 0,
) -> str:
    """统一 LLM 调用入口，根据 streaming 参数选择流式或一次性输出。

    Args:
        prompt: 完整的 prompt 文本
        node_name: 节点名
        model: LLM 模型名
        streaming: 是否启用流式输出
        retry_seq: 重试序号

    Returns:
        清理后的 LLM 响应文本（已去 thinking / markdown 包裹）
    """
    if streaming:
        sw = get_stream_writer()
        raw = await trace_llm_call_astream(
            prompt,
            node_name=node_name,
            model=model,
            retry_seq=retry_seq,
            stream_writer=sw,
        )
        content = raw  # trace_llm_call_astream 内部已 strip_thinking
    else:
        response = trace_llm_call(prompt, node_name=node_name, model=model, retry_seq=retry_seq)
        content = strip_thinking(response.content if hasattr(response, "content") else str(response))

    return content


def _sanitize_column_aliases(sql: str) -> str:
    """对 AS 别名中特殊字符（/、-、空格等）自动加双引号。

    PostgreSQL 中 AS 后的别名如果包含 /、-、空格等特殊字符，
    会被解析为运算符或语法错误，需要用双引号包裹。
    例如：AS 物料批次/UPN → AS "物料批次/UPN"
    """

    def _wrap_alias(m: re.Match) -> str:
        alias = m.group(1).strip()
        # 已有引号包裹，跳过
        if (alias.startswith('"') and alias.endswith('"')) or (alias.startswith("'") and alias.endswith("'")):
            return m.group(0)
        # 含特殊字符则加双引号
        if re.search(r"[/\-\s\(\)（）]", alias):
            return m.group(0).replace(alias, f'"{alias}"')
        return m.group(0)

    return re.sub(r"\bAS\s+([^\s,]+)", _wrap_alias, sql, flags=re.IGNORECASE)


def _clean_sql_output(content: str) -> str:
    """清理 LLM 输出的 SQL 文本：去除 markdown 包裹、首尾空白，并修正别名特殊字符。"""
    sql = content.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip()
    return _sanitize_column_aliases(sql)


@trace_node("intent")
async def node_1_intent_understanding(state: GraphState) -> dict:
    """节点1：意图理解 - 解析用户问题，输出结构化 JSON。"""
    query = state["query"]
    streaming = state.get("streaming", False)

    prompt = _INTENT_PROMPT.format(user_question=query)
    content = await _call_llm(prompt, node_name="intent", model=settings.intent_model, streaming=streaming)

    # 清理可能的 markdown 包裹
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    intent = _parse_intent_json(content)
    enriched_intent, query_guidance = await _build_query_constraints(state["query"], intent)

    # 提取多 SQL 意图
    query_type = intent.get("query_type", "single")
    sub_queries: list[dict] = []
    if query_type == "multi" and isinstance(intent.get("sub_queries"), list):
        sub_queries = [sq for sq in intent["sub_queries"] if isinstance(sq, dict) and sq.get("question")]
    multi_sql = len(sub_queries) > 0

    # 提取置信度
    confidence = float(intent.get("confidence", 1.0))

    return {
        "intent_json": json.dumps(enriched_intent, ensure_ascii=False),
        "query_guidance": query_guidance,
        "sub_queries": sub_queries,
        "multi_sql": multi_sql,
        "intent_confidence": confidence,
    }


@trace_node("retrieval")
async def node_2_parallel_retrieval(state: GraphState) -> dict:
    """节点2：并行检索 - 同时检索表结构库和 SQL 示例库。"""
    query = state["query"]

    # 从意图 JSON 中提取 search_queries 作为扩展检索词
    search_queries = [query]
    intent = _parse_intent_json(state.get("intent_json", "{}"))
    sqs = intent.get("search_queries", [])
    if sqs:
        search_queries.extend(sqs)

    # 合并多个搜索词的结果
    schema_docs_list: list[str] = []
    few_shot_docs_list: list[str] = []
    seen_schema = set()
    seen_few = set()

    retrieval_details: list[dict] = []

    for sq in search_queries[:3]:  # 最多用 3 个搜索词
        sq_schema_before = len(schema_docs_list)
        sq_few_before = len(few_shot_docs_list)

        try:
            # 混合检索：向量语义 + 关键词精确匹配
            for doc in await hybrid_search_schema(
                _schema_store,
                sq,
                similarity_threshold=settings.retrieval_similarity_threshold,
            ):
                if doc not in seen_schema:
                    seen_schema.add(doc)
                    schema_docs_list.append(doc)
        except Exception as e:
            logger.warning("节点2: hybrid_schema_search 失败 (query=%s): %s", sq[:50], e)
        try:
            for doc in await search_few_shot(_few_shot_store, sq):
                if doc not in seen_few:
                    seen_few.add(doc)
                    few_shot_docs_list.append(doc)
        except Exception as e:
            logger.warning("节点2: few_shot_search 失败 (query=%s): %s", sq[:50], e)

        retrieval_details.append(
            {
                "query": sq,
                "schema_added": len(schema_docs_list) - sq_schema_before,
                "few_shot_added": len(few_shot_docs_list) - sq_few_before,
            }
        )

    # 对规则层明确要求的表，直接补充精确 schema，避免向量召回缺失。
    # 这些 chunk 优先级最高，单独收集，截断时不计入上限。
    required_tables = [t for t in intent.get("required_tables", []) if isinstance(t, str) and t.strip()]
    preferred_main_table = str(intent.get("preferred_main_table", "")).strip()
    if preferred_main_table:
        required_tables.insert(0, preferred_main_table)
    required_schema_docs: list[str] = []
    for table_name in _dedupe_keep_order(required_tables):
        doc = _SCHEMA_LOOKUP.get(table_name)
        if doc and doc not in seen_schema:
            seen_schema.add(doc)
            required_schema_docs.append(doc)

    evolved_few_shot_text = await load_evolved_few_shot_text()
    if evolved_few_shot_text and evolved_few_shot_text not in seen_few:
        seen_few.add(evolved_few_shot_text)
        few_shot_docs_list.append(evolved_few_shot_text)

    # 使用向量检索 evolved_few_shot（替代全量加载）
    if _evolved_few_shot_store:
        try:
            from src.services.vector_store import search_evolved_few_shot

            for sq in search_queries[:3]:
                evolved_docs = await search_evolved_few_shot(_evolved_few_shot_store, sq, k=2)
                for doc in evolved_docs:
                    if doc not in seen_few:
                        seen_few.add(doc)
                        few_shot_docs_list.append(doc)
        except Exception as e:
            logger.warning("节点2: evolved_few_shot 向量检索失败: %s", e)

    # 截断策略：required_schema_docs 优先保留（不计入截断上限），
    # 向量检索结果用剩余配额截断，最后 required 在前拼接。
    vector_schema_raw = "\n---\n".join(schema_docs_list)
    vector_schema_raw = _truncate_chunks_by_count(vector_schema_raw, settings.max_schema_context_items)

    if required_schema_docs:
        required_schema_raw = "\n---\n".join(required_schema_docs)
        schema_docs_raw = (
            f"{required_schema_raw}\n---\n{vector_schema_raw}" if vector_schema_raw else required_schema_raw
        )
    else:
        schema_docs_raw = vector_schema_raw

    few_shot_docs_raw = "\n---\n".join(few_shot_docs_list)
    few_shot_docs_raw = _truncate_chunks_by_count(few_shot_docs_raw, settings.max_few_shot_total_items)

    return {
        "schema_docs": schema_docs_raw,
        "few_shot_docs": few_shot_docs_raw,
    }


# ---- 歧义检测：同一业务概念对应多张候选表 ----
# 格式：业务术语 → 可能对应的表名列表
_AMBIGUOUS_TABLE_MAPPINGS: list[tuple[str, list[str]]] = [
    ("发料单", ["t_wms_issue", "t_wms_wo_material_bill", "t_wms_wo_material_bill_detail"]),
    ("退料单", ["t_wms_return", "t_wms_wo_rb", "t_wms_wo_rb_detail"]),
    ("领料单", ["t_wms_issue", "t_wms_wo_material_bill", "t_wms_wo_material_bill_detail"]),
    ("入库单", ["t_wms_stock_in", "t_wms_stock_in_detail"]),
    ("出库单", ["t_wms_stock_out", "t_wms_stock_out_detail"]),
    ("工单", ["t_pd_wo", "t_pd_wo_detail"]),
    ("检验单", ["t_qm_iqc", "t_qm_ipqc", "t_qm_fqc"]),
    ("设备台账", ["t_ems_equipment", "t_ems_equipment_detail"]),
]


def _detect_table_ambiguity(
    primary_seeds: list[str],
    secondary_seeds: list[str],
    search_queries: list[str],
    intent_domains: list[str],
) -> str:
    """检测是否存在同一业务术语匹配多张候选表的歧义情况。

    在检索到候选表之后运行，检查 search_queries 中的业务术语是否
    同时命中了多张可能表，生成歧义警告供后续 SQL 生成参考。
    """
    all_candidates = set(primary_seeds) | set(secondary_seeds)
    if not all_candidates:
        return ""

    ambiguity_lines: list[str] = []
    for term, candidate_tables in _AMBIGUOUS_TABLE_MAPPINGS:
        # 检查 search_queries 中是否包含该业务术语
        term_lower = term.lower()
        matched_in_query = any(term_lower in sq.lower() or sq.lower() in term_lower for sq in search_queries)
        if not matched_in_query:
            continue

        # 检查候选表中是否同时命中了多张
        hits = [t for t in candidate_tables if t in all_candidates]
        if len(hits) >= 2:
            ambiguity_lines.append(
                f"- 业务术语「{term}」可能对应多张表：{', '.join(f'`{t}`' for t in hits)}，请根据业务场景确认正确的表"
            )
            logger.info("歧义检测: 术语 '%s' 命中多张表 %s", term, hits)

    if not ambiguity_lines:
        return ""

    return "⚠️ 表歧义警告：\n" + "\n".join(ambiguity_lines)


@trace_node("bfs")
async def node_3_bfs_expand(state: GraphState) -> dict:
    """节点3：BFS 图扩展 + 跨表路径查找。

    两步策略：
      1. BFS 辐射扩展：从所有种子表出发，找到周围的相关表
      2. 跨表路径查找：如果意图中锚定了多个表（如"工单→设备"），
         找它们之间的最短 JOIN 路径，解决"只知首尾、不知中间表"的问题
    """
    # ---- 收集种子表（分优先级） ----
    intent = _parse_intent_json(state.get("intent_json", "{}"))
    anchors = intent.get("anchor_tables", [])
    anchor_tables = [a for a in anchors if isinstance(a, str)] if isinstance(anchors, list) else []

    preferred_main_table = str(intent.get("preferred_main_table", "")).strip()
    required_tables = [t for t in intent.get("required_tables", []) if isinstance(t, str)]
    required_joins = [j for j in intent.get("required_joins", []) if isinstance(j, str)]

    # 一级种子（锚定表）：意图明确指定的表 → 需要 BFS 扩展
    primary_seeds: list[str] = list(anchor_tables)
    if preferred_main_table and preferred_main_table not in primary_seeds:
        primary_seeds.insert(0, preferred_main_table)
    for table_name in required_tables:
        if table_name not in primary_seeds:
            primary_seeds.append(table_name)

    # 二级种子（候选表）：向量检索命中的其他表 → 不扩展，仅作为独立候选
    schema_docs = state.get("schema_docs", "")
    table_pattern = re.compile(r"表名：(\w+)")
    secondary_seeds: list[str] = []
    for match in table_pattern.finditer(schema_docs):
        tname = match.group(1)
        if tname not in primary_seeds:
            secondary_seeds.append(tname)

    if not primary_seeds and not secondary_seeds:
        return {"expanded_tables": "", "join_hints": "", "warning": ""}

    # ---- 提取 intent_domains ----
    intent_domains = [d for d in intent.get("intent_domains", []) if isinstance(d, str)]

    # ---- 根据 query_complexity 动态调整 BFS 跳数 ----
    query_complexity = intent.get("query_complexity", "medium")
    complexity_hops_map = {"simple": 1, "medium": 2, "complex": 3}
    adaptive_max_hops = complexity_hops_map.get(query_complexity, settings.bfs_max_hops)
    if adaptive_max_hops != settings.bfs_max_hops:
        logger.info("BFS 跳数自适应: query_complexity=%s → max_hops=%d", query_complexity, adaptive_max_hops)

    # ---- 步骤1: BFS（仅从一级种子扩展） ----
    all_join_paths: list[dict] = []
    if primary_seeds:
        result = await bfs_expand(
            primary_seeds,
            max_hops=adaptive_max_hops,
            max_tables=settings.bfs_max_tables,
            intent_domains=intent_domains,
        )
        all_tables = set(result["tables"])
        all_join_paths = list(result["join_paths"])
        warning = result.get("warning", "")

        # 回退：如果一级种子 BFS 没有找到任何新表（种子表都不在图谱中或没有边），
        # 用二级种子（retrieval 命中的表）作为回退种子重新 BFS，确保能产出 JOIN 提示
        new_from_primary = all_tables - set(primary_seeds)
        if not new_from_primary and secondary_seeds:
            logger.warning(
                "BFS 从一级种子 %s 未找到新表，用 retrieval 命中表 %s 作为回退种子",
                primary_seeds,
                secondary_seeds[: min(5, len(secondary_seeds))],
            )
            fallback_result = await bfs_expand(
                secondary_seeds[: settings.bfs_max_tables],
                max_hops=adaptive_max_hops,
                max_tables=settings.bfs_max_tables,
                intent_domains=intent_domains,
            )
            all_tables |= set(fallback_result["tables"])
            all_join_paths.extend(fallback_result["join_paths"])
    else:
        all_tables: set[str] = set()
        warning = ""

    # 合并二级种子（只加表本身，不做 BFS 扩展）
    all_tables |= set(secondary_seeds)

    # ---- 步骤2: 跨表路径查找 ----
    # 如果意图中有多个锚定表，找它们之间的最短路径
    chain_hints_text = ""
    if len(anchor_tables) >= 2:
        # 以第一个锚定表为起点，依次找与其他锚定表的路径
        start = anchor_tables[0]
        for end in anchor_tables[1:]:
            path = await find_path_between(start, end, max_depth=4)
            if path:
                # 将路径中的中间表加入结果集
                for t in path:
                    all_tables.add(t)
                # 将路径中的边加入 join_paths
                path_edges = await build_path_join_hints(path)
                for pe in path_edges:
                    # 避免重复
                    already = any(jp["from"] == pe["from"] and jp["to"] == pe["to"] for jp in all_join_paths)
                    if not already:
                        all_join_paths.append(pe)
                # 生成链式 JOIN 提示
                chain_hints_text = await build_chain_join_hints(path)

    # ---- 组装输出 ----
    join_hints = build_join_hints(all_join_paths)
    if chain_hints_text:
        join_hints = chain_hints_text + "\n\n" + join_hints

    # 硬约束物理分离：enforced_lines 单独输出为 hard_constraints，
    # join_hints 只保留 BFS 推断的参考性 JOIN 提示
    enforced_lines: list[str] = []
    if preferred_main_table:
        enforced_lines.append(f"FROM 必须从 {preferred_main_table} 开始（不可更改）")
    if required_tables:
        enforced_lines.append(f"必须包含以下表：{', '.join(_dedupe_keep_order(required_tables))}")
    if required_joins:
        enforced_lines.append("必须满足以下 JOIN：")
        enforced_lines.extend(f"  - {join_expr}" for join_expr in _dedupe_keep_order(required_joins))
    hard_constraints = "\n".join(enforced_lines) if enforced_lines else ""

    # ---- 歧义检测：检索后检查是否存在同一业务概念匹配多张候选表的情况 ----
    ambiguity_warnings = _detect_table_ambiguity(
        primary_seeds=primary_seeds,
        secondary_seeds=list(secondary_seeds),
        search_queries=intent.get("search_queries", []),
        intent_domains=intent_domains,
    )
    if ambiguity_warnings:
        if warning:
            warning += "\n" + ambiguity_warnings
        else:
            warning = ambiguity_warnings

    return {
        "expanded_tables": ",".join(sorted(all_tables | set(required_tables))),
        "join_hints": join_hints,
        "hard_constraints": hard_constraints,
        "warning": warning,
    }


def _strip_relations_from_chunk(chunk: str) -> str:
    """去除 chunk 中的"关联关系"段，JOIN 信息由 Neo4j 单独管理。"""
    # 匹配 "关联关系：" 及其后续内容（直到下一个顶级段或结尾）
    return re.sub(r"\n关联关系：[\s\S]*?(?=\n表名：|\n模块：|\n适用场景：|\Z)", "", chunk)


async def _prune_schema_context(schema_context: str, join_hints: str, relevant_fields: list[dict]) -> str:
    """对 schema_context 做字段剪裁。

    保留规则（按优先级）：
    1. 始终保留主键字段（从 Neo4j Field 节点 is_pk=true 获取）
    2. 保留 join_hints 中涉及的外键字段（正则提取 table.field 模式）
    3. 保留 relevant_fields 中向量检索命中的字段
    4. 如果某表没有任何字段被保留，保留全部字段（安全回退）
    """
    if not schema_context:
        return schema_context

    # 从 join_hints 提取外键字段 {table_name: {field_name}}
    fk_fields: dict[str, set[str]] = {}
    for m in re.finditer(r"(\w+)\.(\w+)\s*=", join_hints):
        fk_fields.setdefault(m.group(1), set()).add(m.group(2))
    for m in re.finditer(r"=\s*(\w+)\.(\w+)", join_hints):
        fk_fields.setdefault(m.group(1), set()).add(m.group(2))

    # 从 Neo4j 获取主键字段
    pk_fields: dict[str, set[str]] = {}
    try:
        from src.services.neo4j_graph import get_table_fields

        for table_name in re.findall(r"表名：(\w+)", schema_context):
            fields = await get_table_fields(table_name)
            for f in fields:
                if f["is_pk"]:
                    pk_fields.setdefault(table_name, set()).add(f["name"])
    except Exception:
        pass

    # 从 relevant_fields 按表名分组
    rf_by_table: dict[str, set[str]] = {}
    for rf in relevant_fields:
        rf_by_table.setdefault(rf["table_name"], set()).add(rf["field_name"])

    # 对每个 chunk（以 \n\n 分隔）做剪裁
    chunks = schema_context.split("\n\n")
    pruned_chunks: list[str] = []
    for chunk in chunks:
        table_match = re.search(r"表名：(\w+)", chunk)
        if not table_match:
            pruned_chunks.append(chunk)
            continue
        table_name = table_match.group(1)

        # 汇集保留字段
        keep = set()
        if table_name in pk_fields:
            keep |= pk_fields[table_name]
        if table_name in fk_fields:
            keep |= fk_fields[table_name]
        if table_name in rf_by_table:
            keep |= rf_by_table[table_name]

        # 安全回退：无任何保留字段则保留全部
        if not keep:
            pruned_chunks.append(chunk)
            continue

        # 执行剪裁：遍历字段行，只保留 keep 中的字段
        lines = chunk.split("\n")
        pruned_lines: list[str] = []
        in_field_section = False
        for line in lines:
            if line.startswith("关键字段："):
                pruned_lines.append(line)
                in_field_section = True
                continue
            if in_field_section:
                # 检查是否是字段行（以两个空格开头）
                if line.startswith("  "):
                    field_name_match = re.match(r"  (\w+)", line)
                    if field_name_match and field_name_match.group(1) in keep:
                        pruned_lines.append(line)
                else:
                    # 退出字段段
                    in_field_section = False
                    pruned_lines.append(line)
                continue
            pruned_lines.append(line)

        pruned_chunks.append("\n".join(pruned_lines))

    return "\n\n".join(pruned_chunks)


@trace_node("schema")
async def node_4_schema_assembly(state: GraphState) -> dict:
    """节点4：Schema 组装 - 从检索结果中提取对应表的 DDL 描述。

    对 BFS 展开但向量检索未命中的表，从本地知识库直接补全 schema，
    避免 LLM 因缺少表结构而盲目猜字段。
    """
    expanded = state.get("expanded_tables", "")
    if not expanded:
        return {"schema_context": ""}

    target_tables = [t.strip() for t in expanded.split(",") if t.strip()]
    intent = _parse_intent_json(state.get("intent_json", "{}"))
    for table_name in intent.get("required_tables", []):
        if isinstance(table_name, str) and table_name.strip() and table_name not in target_tables:
            target_tables.append(table_name)
    schema_docs = state.get("schema_docs", "")

    chunks = schema_docs.split("\n---\n")
    # 当 BFS 未产出任何 JOIN 提示时（如锚定表幻觉、图谱缺失），
    # 保留知识库自带的"关联关系"信息，避免 LLM 完全无 JOIN 指导而臆造列名
    join_hints = state.get("join_hints", "")
    keep_relations = not join_hints
    selected: list[str] = []
    found_tables: set[str] = set()
    for chunk in chunks:
        for tname in target_tables:
            if f"表名：{tname}" in chunk:
                processed = chunk.strip()
                if not keep_relations:
                    processed = _strip_relations_from_chunk(processed)
                selected.append(processed)
                found_tables.add(tname)
                break

    # 补全：BFS 展开的表如果检索未命中，从本地知识库直接查找
    missing_tables = [t for t in target_tables if t not in found_tables]
    if missing_tables:
        schema_lookup = _get_schema_lookup()
        for tname in missing_tables:
            chunk = schema_lookup.get(tname)
            if chunk:
                if keep_relations:
                    selected.append(chunk)
                else:
                    selected.append(_strip_relations_from_chunk(chunk))
                logger.info("节点4: 从本地知识库补全表 %s 的 schema", tname)

    schema_context = "\n\n".join(selected)

    # 字段剪裁：仅在字段索引就绪时执行
    try:
        from src.services.neo4j_graph import field_has_embeddings
        from src.services.vector_store import search_fields

        if await field_has_embeddings():
            relevant_fields = await search_fields(state.get("query", ""), k=30)
            schema_context = await _prune_schema_context(
                schema_context,
                state.get("join_hints", ""),
                relevant_fields,
            )
    except Exception:
        pass  # 字段索引不可用时回退到全量输出

    return {"schema_context": schema_context}


@trace_node("sql_gen")
async def node_5_sql_generation(state: GraphState) -> dict:
    """节点5：SQL 生成 - 组装 prompt 调用 LLM 生成 SQL。

    多意图时，逐条为每个子问题生成独立 SQL。
    """
    intent = _parse_intent_json(state.get("intent_json", "{}"))
    multi_sql = state.get("multi_sql", False)
    sub_queries = state.get("sub_queries", [])
    schema_context = state.get("schema_context", "")
    join_hints = state.get("join_hints", "")
    hard_constraints = state.get("hard_constraints", "")
    query_guidance = state.get("query_guidance", "（无额外硬约束）")
    few_shot_docs = state.get("few_shot_docs", "")
    warning = state.get("warning", "")
    streaming = state.get("streaming", False)

    def _build_prompt(question: str) -> str:
        sql_prompt_template = _load_prompt("dify_sql_prompt.txt")
        from src.graph.ddl_renderer import render_ddl

        rendered_schema = render_ddl(schema_context)
        p = sql_prompt_template.replace("{{hard_constraints}}", hard_constraints or "（无硬约束）")
        p = p.replace("{{schema_context}}", rendered_schema)
        p = p.replace("{{join_hints}}", join_hints or "（无 JOIN 提示）")
        p = p.replace("{{query_guidance}}", query_guidance)
        p = p.replace("{{few_shot_examples}}", few_shot_docs)
        user_question = question
        p = p.replace("{{user_question}}", user_question)
        if warning:
            p = p.replace(
                "{% if warning %}\n⚠️ 注意：{{warning}}，建议生成SQL后人工核实\n{% endif %}",
                f"⚠️ 注意：{warning}，建议生成SQL后人工核实",
            )
        else:
            p = p.replace("{% if warning %}\n⚠️ 注意：{{warning}}，建议生成SQL后人工核实\n{% endif %}", "")
        return p

    async def _call_llm_and_extract_sql(prompt: str) -> str:
        # prompt 总长度硬保护
        if len(prompt) > settings.max_prompt_chars:
            logger.warning(
                "节点5: prompt 超长 (%d > %d)，截断后半部分",
                len(prompt),
                settings.max_prompt_chars,
            )
            prompt = prompt[: settings.max_prompt_chars]
        logger.info(
            "节点5: 调用 LLM (model=%s, base_url=%s, prompt_len=%d, streaming=%s)",
            settings.llm_model,
            settings.openai_base_url,
            len(prompt),
            streaming,
        )
        content = await _call_llm(prompt, node_name="sql_gen", model=settings.llm_model, streaming=streaming)
        return _clean_sql_output(content)

    async def _with_constraint_check(sql: str, prompt: str) -> str:
        constraint_feedback = _build_sql_constraint_feedback(sql, intent)
        column_feedback = _build_column_feedback(sql, schema_context)
        combined_feedback = "\n\n".join(fb for fb in [constraint_feedback, column_feedback] if fb)
        if combined_feedback:
            retry_prompt = "\n\n".join(
                [prompt, "## 上一版 SQL", f"```sql\n{sql}\n```", "## 纠偏反馈", combined_feedback]
            )
            return await _call_llm_and_extract_sql(retry_prompt)
        return sql

    if multi_sql and sub_queries:
        # 多意图：逐条为每个子问题生成 SQL
        generated_sqls: list[str] = []
        for i, sq in enumerate(sub_queries):
            sub_question = sq.get("question", "")
            logger.info("节点5: 生成第 %d/%d 条 SQL，子问题: %s", i + 1, len(sub_queries), sub_question[:80])
            prompt = _build_prompt(sub_question)
            sql = await _call_llm_and_extract_sql(prompt)
            sql = await _with_constraint_check(sql, prompt)
            generated_sqls.append(sql)
        return {"generated_sqls": generated_sqls}
    else:
        # 单意图：保持原有逻辑
        prompt = _build_prompt(state["query"])
        sql = await _call_llm_and_extract_sql(prompt)
        sql = await _with_constraint_check(sql, prompt)
        return {"generated_sqls": [sql]}


@trace_node("safety")
def node_6_safety_check(state: GraphState) -> dict:
    """节点6：安全校验 - 过滤危险操作，自动补 LIMIT。逐条校验所有 SQL。"""
    generated_sqls = state.get("generated_sqls", [])
    if not generated_sqls:
        return {
            "final_sqls": [],
            "safe": False,
            "error": "没有可校验的 SQL",
            "retry_count": 0,
        }

    final_sqls: list[str] = []
    all_safe = True
    errors: list[str] = []

    for sql in generated_sqls:
        result = validate_sql(sql, settings.default_limit)
        final_sqls.append(result["final_sql"])
        if not result["safe"]:
            all_safe = False
            errors.append(result["error"])

    return {
        "final_sqls": final_sqls,
        "safe": all_safe,
        "error": "; ".join(errors) if errors else "",
        "retry_count": 0,
    }


# ---- 节点7：SQL 执行与修复 ----

_SQL_REPAIR_PROMPT = """你是 PostgreSQL SQL 修复专家。以下 SQL 执行时出错，请根据错误信息和表结构修复 SQL。

## 原始用户问题
{user_query}

## 数据库表结构
{schema_context}

## JOIN 提示
{join_hints}

## 额外约束
{query_guidance}

## 出错的 SQL
```sql
{sql}
```

## 错误信息
{error_msg}

## 要求
- 只输出修复后的完整 SQL，不加任何解释文字
- 保持原有查询意图不变
- 如果错误是字段名/表名拼写问题，修正为表结构中存在的名称
- 如果错误是 JOIN 条件问题，根据表结构修正
- 如果错误是语法问题，修正为合法的 PostgreSQL 语法
- 字段名必须严格来自表结构，禁止臆造不存在的列名"""


def _execute_sql(sql: str) -> dict:
    """执行 SQL 并返回结果。

    Returns:
        {"success": bool, "rows": int, "columns": [...], "preview": [...], "error": str}
    """
    try:
        with execution_connection() as conn, conn.cursor() as cur:
            cur.execute(sql)
            if cur.description:
                columns = [d.name for d in cur.description]
                rows = cur.fetchall()
                preview = [dict(zip(columns, row, strict=True)) for row in rows[:5]]
                return {
                    "success": True,
                    "rows": len(rows),
                    "columns": columns,
                    "preview": preview,
                    "error": "",
                }
            else:
                return {
                    "success": True,
                    "rows": 0,
                    "columns": [],
                    "preview": [],
                    "error": "",
                }
    except Exception as e:
        return {
            "success": False,
            "rows": 0,
            "columns": [],
            "preview": [],
            "error": str(e),
        }


def _explain_sql(sql: str) -> dict:
    """通过 EXPLAIN 验证 SQL 正确性，不实际执行查询。

    实际数据查询由 /execute/page 接口处理，这里只做语法/语义校验。

    Returns:
        {"success": bool, "explain_plan": dict, "error": str}
    """
    try:
        with execution_connection() as conn, conn.cursor() as cur:
            cur.execute(f"EXPLAIN (FORMAT JSON) {sql}")
            plan = list(cur.fetchone().values())[0]
            return {
                "success": True,
                "rows": 0,
                "columns": [],
                "preview": [],
                "explain_plan": plan,
                "error": "",
            }
    except Exception as e:
        return {
            "success": False,
            "rows": 0,
            "columns": [],
            "preview": [],
            "explain_plan": {},
            "error": str(e),
        }


def execute_paginated_sql(sql: str, page: int = 1, page_size: int = 20) -> dict:
    """分页执行 SQL，返回指定页的数据。

    Args:
        sql: 原始 SQL 语句
        page: 页码（从 1 开始）
        page_size: 每页行数

    Returns:
        {"success": bool, "total_rows": int, "page": int, "page_size": int,
         "total_pages": int, "columns": [...], "rows": [...], "error": str}
    """
    try:
        # 去掉末尾分号及安全校验添加的 LIMIT，由外层 LIMIT/OFFSET 控制分页
        sql = sql.rstrip().rstrip(";").rstrip()
        sql = re.sub(r"\s+LIMIT\s+\d+\s*$", "", sql, flags=re.IGNORECASE)
        offset = (page - 1) * page_size
        count_sql = f"SELECT COUNT(*) FROM ({sql}) AS _cnt"
        page_sql = f"SELECT * FROM ({sql}) AS _page LIMIT {page_size} OFFSET {offset}"

        with execution_connection() as conn, conn.cursor() as cur:
            # 1) 统计总行数
            cur.execute(count_sql)
            total_rows = list(cur.fetchone().values())[0]

            # 2) 查询分页数据
            cur.execute(page_sql)
            if cur.description:
                columns = [d.name for d in cur.description]
                rows_data = cur.fetchall()
                rows = [{col: row[col] for col in columns} for row in rows_data]
            else:
                columns = []
                rows = []

        total_pages = max(1, (total_rows + page_size - 1) // page_size)

        return {
            "success": True,
            "total_rows": total_rows,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "columns": columns,
            "rows": rows,
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "total_rows": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
            "columns": [],
            "rows": [],
            "error": str(e),
        }


_TABLE_COLUMNS_CACHE: dict[str, list[str]] = {}


def _get_table_columns(table_name: str) -> list[str] | None:
    """从数据库查询表的实际列名列表（带进程级缓存）。"""
    if table_name in _TABLE_COLUMNS_CACHE:
        return _TABLE_COLUMNS_CACHE[table_name]
    try:
        with execution_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
                (table_name,),
            )
            cols = [row["column_name"] for row in cur.fetchall()]
            _TABLE_COLUMNS_CACHE[table_name] = cols
            return cols
    except Exception:
        return None


def _extract_alias_table_map(sql: str) -> dict[str, str]:
    """从 SQL 中提取别名→表名的映射。

    匹配模式如：
      - FROM t_pd_wo wo          → {"wo": "t_pd_wo"}
      - JOIN t_bd_part AS p       → {"p": "t_bd_part"}

    只有别名的表才加入映射，不带别名的表会自动跳过。
    """
    alias_map: dict[str, str] = {}
    # 匹配: FROM/JOIN table_name [AS] alias
    for match in re.finditer(
        r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w\.]*)\s+(?:AS\s+)?([a-zA-Z_][\w]*)",
        sql,
        re.IGNORECASE,
    ):
        table_name = match.group(1).lower()
        alias = match.group(2).lower()
        # 跳过 SQL 关键字被误匹配为别名的情况
        if alias in (
            "on",
            "where",
            "left",
            "right",
            "inner",
            "outer",
            "cross",
            "natural",
            "full",
            "limit",
            "order",
            "group",
            "union",
            "except",
            "intersect",
        ):
            continue
        if "." not in table_name:
            alias_map[alias] = table_name
    return alias_map


def _extract_table_names(sql: str) -> list[str]:
    """从 SQL 中提取表名（不含别名前缀）。"""
    tables: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w\.]*)", sql, re.IGNORECASE):
        name = match.group(1).lower()
        if "." not in name and name not in seen:
            seen.add(name)
            tables.append(name)
    return tables


def _extract_pg_hint_suggestions(error_msg: str) -> list[str]:
    """从 PostgreSQL 错误信息的 HINT 中提取建议列名。

    例如 HINT: 'Perhaps you meant to reference the column "wo.panel_qty" or the column "wo.split_qty".'
    返回: ["panel_qty", "split_qty"]
    """
    hints: list[str] = []
    for match in re.finditer(r'Perhaps you meant to reference the column "[\w\.]+\.([\w]+)"', error_msg, re.IGNORECASE):
        hints.append(match.group(1))
    return hints


def _fuzzy_best_columns(missing_col: str, columns: list[str], top_n: int = 5) -> list[str]:
    """使用编辑距离（Levenshtein）从真实列名中找出与缺失列名最相似的前 N 个。"""
    if not columns:
        return []
    scored = []
    ml = missing_col.lower()
    for c in columns:
        cl = c.lower()
        # 计算 Levenshtein 距离
        if len(ml) < len(cl):
            d = _levenshtein(ml, cl)
            # 含有关键词整体匹配子串的情况给予奖励
            bonus = 2 if ml in cl else 0
        else:
            d = _levenshtein(ml, cl)
            bonus = 2 if cl in ml else 0
        scored.append((c, d - bonus))
    scored.sort(key=lambda x: x[1])
    return [c for c, _ in scored[:top_n]]


def _levenshtein(s1: str, s2: str) -> int:
    """计算两个字符串之间的编辑距离。"""
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1, 1):
        curr = [i]
        for j, c2 in enumerate(s2, 1):
            curr.append(
                min(
                    prev[j] + 1,  # 删除
                    curr[j - 1] + 1,  # 插入
                    prev[j - 1] + (0 if c1 == c2 else 1),  # 替换
                )
            )
        prev = curr
    return prev[-1]


def _build_col_not_found_hint(sql: str, error_msg: str, schema_context: str = "") -> str:
    """当错误是'column does not exist'时，用多种手段生成精准修复提示。

    手段（按优先级）：
    1. 提取 PostgreSQL HINT 中已建议的列名
    2. 解析别名定位到具体表，查询该表全部列名
    3. 编辑距离模糊匹配，找出最相似的 Top-5 列名
    4. 若 DB 查询失败，回退从 schema_context 文本中提取列名
    """
    col_match = re.search(r"column ([a-zA-Z_][\w\.]*) does not exist", error_msg, re.IGNORECASE)
    if not col_match:
        return ""

    full_col = col_match.group(1)
    missing_col = full_col.split(".")[-1]
    alias = full_col.split(".")[0] if "." in full_col else ""

    hint_parts: list[str] = [f"⚠️ 错误：列 '{full_col}' 不存在，请替换为真实存在的列名。"]

    # ---- 手段1：提取 PostgreSQL HINT 建议 ----
    pg_suggestions = _extract_pg_hint_suggestions(error_msg)
    if pg_suggestions:
        hint_parts.append(f"PostgreSQL 建议使用的列名: {', '.join(pg_suggestions)}")

    # ---- 手段2：通过别名定位到具体表 ----
    alias_map = _extract_alias_table_map(sql)
    target_table = None
    if alias and alias in alias_map:
        target_table = alias_map[alias]
    else:
        table_names = _extract_table_names(sql)
        if table_names:
            target_table = table_names[0]

    all_cols: list[str] | None = None
    fallback_used = False
    if target_table:
        all_cols = _get_table_columns(target_table)
        # 手段4：DB 查询失败时，回退从 schema_context 文本中提取列名
        if not all_cols and schema_context:
            schema_cols = _parse_columns_from_schema(schema_context)
            if target_table in schema_cols:
                all_cols = sorted(schema_cols[target_table])
                fallback_used = True

    if all_cols:
        source_note = "（来源：schema 文本）" if fallback_used else ""
        hint_parts.append(f"表 {target_table} 的完整列名{source_note}（共 {len(all_cols)} 列）:")
        hint_parts.append(", ".join(all_cols[:50]))
        if len(all_cols) > 50:
            hint_parts[-1] += f" ... 共 {len(all_cols)} 列"

        fuzzy_cols = _fuzzy_best_columns(missing_col, all_cols)
        if fuzzy_cols:
            hint_parts.append(f"与 '{missing_col}' 最相似的列名: {', '.join(fuzzy_cols)}")
    else:
        hint_parts.append(f"（无法获取表 {target_table or '未知'} 的列信息，请参考 schema_context 中的字段定义）")

    return "\n".join(hint_parts)


async def _repair_sql(
    sql: str,
    error_msg: str,
    schema_context: str,
    user_query: str,
    join_hints: str,
    query_guidance: str,
    retry_seq: int = 0,
    streaming: bool = False,
    extra_errors: list[str] | None = None,
) -> str:
    """调用 LLM 修复出错的 SQL。"""
    # 如果是列名错误，补充真实列名信息
    col_hint = _build_col_not_found_hint(sql, error_msg, schema_context)

    prompt = _SQL_REPAIR_PROMPT.format(
        user_query=user_query,
        schema_context=schema_context or "（无额外表结构信息）",
        join_hints=join_hints or "（无额外 JOIN 提示）",
        query_guidance=query_guidance or "（无额外硬约束）",
        sql=sql,
        error_msg=error_msg,
    )
    if col_hint:
        prompt += f"\n\n## 真实列名\n{col_hint}"

    # 累积错误历史：让 LLM 同时看到之前修复后仍存在的错误
    if extra_errors:
        history_lines = [f"第 {i + 1} 次修复后仍报错: {err}" for i, err in enumerate(extra_errors)]
        prompt += "\n\n## 历次修复记录\n" + "\n".join(history_lines)
        prompt += "\n\n请一次性修正当前错误和历次修复记录中的所有问题，不要只修当前报错。"

    content = await _call_llm(
        prompt, node_name="execute", model=settings.llm_model, streaming=streaming, retry_seq=retry_seq
    )
    repaired = _clean_sql_output(content)
    return repaired


@trace_node("execute")
async def node_7_execute_and_repair(state: GraphState) -> dict:
    """节点7：通过 EXPLAIN 校验 SQL 正确性，失败则通过 LLM 修复并重试（最多 3 次）。"""
    retry_count = state.get("retry_count", 0)
    multi_sql = state.get("multi_sql", False)
    sub_queries = state.get("sub_queries", [])
    final_sqls = state.get("final_sqls", [])
    streaming = state.get("streaming", False)

    if not state.get("safe", False):
        return {
            "execution_results": json.dumps(
                [{"success": False, "error": "SQL 未通过安全校验，跳过执行"}], ensure_ascii=False
            ),
        }

    if not final_sqls:
        return {
            "execution_results": json.dumps([{"success": False, "error": "SQL 为空，跳过执行"}], ensure_ascii=False),
        }

    # 多 SQL 模式：逐条执行，失败内联重试最多 3 次
    if multi_sql:
        results: list[dict] = []
        for i, sql in enumerate(final_sqls):
            desc = sub_queries[i].get("description", f"查询 {i + 1}") if i < len(sub_queries) else f"查询 {i + 1}"
            sub_question = (
                sub_queries[i].get("question", state.get("query", ""))
                if i < len(sub_queries)
                else state.get("query", "")
            )
            logger.info("节点7: 执行第 %d/%d 条 SQL [%s]", i + 1, len(final_sqls), desc)

            current_sql = sql
            result = _explain_sql(current_sql)

            if result["success"]:
                result["description"] = desc
                result["question"] = sub_question
                # 语义检查：拦截 EXPLAIN 无法发现的静默错误
                semantic_issues = semantic_sanity_check(current_sql)
                if semantic_issues:
                    result["semantic_warnings"] = semantic_issues
                    logger.warning(
                        "节点7: SQL [%s] 语义检查发现 %d 个潜在问题: %s",
                        desc,
                        len(semantic_issues),
                        "; ".join(semantic_issues),
                    )
                results.append(result)
                logger.info("节点7: SQL [%s] EXPLAIN 通过", desc)
                continue

            # 执行失败：内联重试最多 3 次
            logger.warning("节点7: SQL [%s] EXPLAIN 失败: %s", desc, result["error"][:120])
            repaired_success = False
            last_error = result["error"]
            previous_errors: list[str] = []

            for retry in range(_MAX_RETRIES):
                logger.info("节点7: SQL [%s] 第 %d/%d 次修复重试...", desc, retry + 1, _MAX_RETRIES)
                repaired_sql = await _repair_sql(
                    current_sql,
                    last_error,
                    state.get("schema_context", ""),
                    sub_question,
                    state.get("join_hints", ""),
                    state.get("query_guidance", ""),
                    retry_seq=retry + 1,
                    streaming=streaming,
                    extra_errors=previous_errors,
                )
                repaired_result = _explain_sql(repaired_sql)
                if repaired_result["success"]:
                    repaired_result["description"] = desc + (
                        "（已修复）" if retry == 0 else f"（第{retry + 1}次修复成功）"
                    )
                    repaired_result["question"] = sub_question
                    repaired_result["repaired"] = True
                    repaired_result["retry_count"] = retry + 1
                    # 语义检查：拦截 EXPLAIN 无法发现的静默错误
                    semantic_issues = semantic_sanity_check(repaired_sql)
                    if semantic_issues:
                        repaired_result["semantic_warnings"] = semantic_issues
                        logger.warning(
                            "节点7: SQL [%s] 修复后语义检查发现 %d 个潜在问题: %s",
                            desc,
                            len(semantic_issues),
                            "; ".join(semantic_issues),
                        )
                    results.append(repaired_result)
                    repaired_success = True
                    logger.info("节点7: SQL [%s] 第 %d 次修复后 EXPLAIN 通过", desc, retry + 1)
                    break
                else:
                    logger.warning(
                        "节点7: SQL [%s] 第 %d 次修复后 EXPLAIN 仍失败: %s",
                        desc,
                        retry + 1,
                        repaired_result["error"][:120],
                    )
                    previous_errors.append(last_error)
                    current_sql = repaired_sql
                    last_error = repaired_result["error"]

            if not repaired_success:
                result["description"] = desc
                result["question"] = sub_question
                result["error"] = f"校验失败（已重试 {_MAX_RETRIES} 次修复）: {last_error}"
                result["repaired"] = False
                results.append(result)
                logger.warning("节点7: SQL [%s] 已达最大重试次数", desc)

        return {
            "execution_results": json.dumps(results, ensure_ascii=False, default=str),
            "retry_count": _MAX_RETRIES,
        }

    # 单 SQL 模式
    sql = final_sqls[0]
    logger.info("节点7: EXPLAIN SQL (第 %d/%d 次)", retry_count + 1, _MAX_RETRIES)
    result = _explain_sql(sql)

    if result["success"]:
        logger.info("节点7: SQL EXPLAIN 通过")
        # 语义检查：拦截 EXPLAIN 无法发现的静默错误
        semantic_issues = semantic_sanity_check(sql)
        if semantic_issues:
            result["semantic_warnings"] = semantic_issues
            logger.warning("节点7: 语义检查发现 %d 个潜在问题: %s", len(semantic_issues), "; ".join(semantic_issues))
        return {"execution_results": json.dumps([result], ensure_ascii=False, default=str)}

    error_msg = result["error"]
    logger.warning("节点7: SQL EXPLAIN 失败: %s", error_msg[:120])

    if retry_count < _MAX_RETRIES - 1:
        logger.info("节点7: 第 %d 次修复重试...", retry_count + 1)
        repaired_sql = await _repair_sql(
            sql,
            error_msg,
            state.get("schema_context", ""),
            state.get("query", ""),
            state.get("join_hints", ""),
            state.get("query_guidance", ""),
            retry_seq=retry_count,
            streaming=streaming,
        )
        return {
            "final_sqls": [repaired_sql],
            "retry_count": retry_count + 1,
            "error": error_msg,
            "execution_results": json.dumps([result], ensure_ascii=False, default=str),
        }

    logger.warning("节点7: 已达最大重试次数 (%d)，退出", _MAX_RETRIES)
    return {
        "execution_results": json.dumps([result], ensure_ascii=False, default=str),
        "retry_count": _MAX_RETRIES,
        "error": f"SQL 校验失败（已重试 {retry_count} 次）: {error_msg}",
    }
