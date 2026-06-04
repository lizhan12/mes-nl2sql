"""LangGraph 工作流节点实现。

对应原 Dify 工作流的 7 个节点：
  1. 意图理解 (LLM)
  2. 并行检索 (向量检索)
  3. BFS 图扩展 (代码逻辑)
  4. Schema 组装 (代码逻辑)
  5. SQL 生成 (LLM)
  6. 安全校验 (代码逻辑)
  7. SQL 执行与修复 (代码逻辑 + LLM，最多重试 3 次)
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

import psycopg

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
from src.services.llm import get_intent_llm, get_llm
from src.services.vector_store import hybrid_search_schema, search_few_shot
from src.utils.sql_validator import validate_sql

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
  "sub_queries": [],
  "anchor_tables": [],
  "search_queries": ["查询词1","查询词2","查询词3"],
  "intent_domains": [],
  "time_range": "",
  "filters": [],
  "ambiguity": "",
  "reference_history": false
}}

规则：
- intent_domains：从 production/quality/warehouse/equipment/master 中选，可多选
- anchor_tables：只填100%确定的表名，不确定宁可留空
- search_queries：包含"用户没说但逻辑上必要"的词（如说"良品率"要补"合格数"）
- query_type：如果用户问了多个独立的数据查询需求（如"分别查询A以及B"、"查询A和B"中A与B是不同维度），填 "multi"；否则填 "single"
- sub_queries：仅当 query_type 为 "multi" 时填写，每项包含 question（独立完整的问题描述）和 description（简短标签，如"过站记录"）。拆分子问题时，每个子问题必须是独立可执行的完整查询，不要有代词引用
- 【重要】如果当前问题是简略指代（如"改成DAH02"、"换成昨天的"、"查一下ABC"、"第二个呢"），必须结合对话历史中的上一轮问题来理解：将当前问题扩展为完整查询，继承历史中的表、筛选条件、查询类型（single/multi），只替换被指定的部分
- reference_history：如果当前问题是对上一轮查询的修改、细化、补充（如改条件、增减字段、切换视角但查同一批数据），填 true；如果是全新的独立查询话题，填 false

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


def _load_prompt(filename: str) -> str:
    path = Path(__file__).parent.parent.parent / "data" / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
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


def _load_runtime_regression_cases() -> dict[str, dict[str, Any]]:
    runtime_cases: dict[str, dict[str, Any]] = {}
    for rule in load_runtime_rules():
        if not isinstance(rule, dict):
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


def _find_regression_case(query: str) -> dict[str, Any] | None:
    normalized = normalize_question(query)
    runtime_cases = _load_runtime_regression_cases()
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


def _build_query_constraints(query: str, llm_intent: dict[str, Any]) -> tuple[dict[str, Any], str]:
    guidance_lines: list[str] = []
    required_tables: list[str] = []
    required_joins: list[str] = []
    preferred_main_table = ""

    regression_case = _find_regression_case(query)
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
    anchor_tables = (
        list(llm_intent.get("anchor_tables", [])) if isinstance(llm_intent.get("anchor_tables"), list) else []
    )

    if preferred_main_table:
        anchor_tables.insert(0, preferred_main_table)
        search_queries.append(preferred_main_table)
    anchor_tables.extend(required_tables)
    search_queries.extend(required_tables)

    llm_intent["anchor_tables"] = _dedupe_keep_order(anchor_tables)
    llm_intent["search_queries"] = _dedupe_keep_order([query, *search_queries])
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


# ---- 节点函数 ----

# 全局 store 引用（由 workflow 初始化时注入）
_schema_store = None
_few_shot_store = None


def init_stores(schema_store, few_shot_store):
    """初始化向量存储引用。"""
    global _schema_store, _few_shot_store
    _schema_store = schema_store
    _few_shot_store = few_shot_store


def _format_conversation_history(messages: list, max_turns: int = 3) -> str:
    """格式化对话历史为文本（用于 SQL 生成上下文）。

    重要：AI 回复只保留 SQL 语句摘要，绝不传入查询结果数据，避免上下文膨胀。
    """
    if not messages:
        return ""
    recent = messages[-(max_turns * 2) :]  # 每轮 = 用户消息 + AI 消息
    lines: list[str] = []
    for msg in recent:
        role = getattr(msg, "type", "human") if hasattr(msg, "type") else "human"
        content = msg.content if hasattr(msg, "content") else str(msg)
        if role == "human":
            lines.append(f"用户：{content}")
        elif role == "ai":
            # 只提取 SQL 摘要，不使用 raw content 截断，防止摄入查询结果数据
            sql_summary = _extract_sql_summary(content)
            if sql_summary:
                lines.append(f"助手SQL：{sql_summary}")
            # 无 SQL 时跳过，不纳入上下文（避免把执行状态/错误信息混入历史）
    return "\n".join(lines) if lines else ""


def _format_intent_history(messages: list, max_turns: int = 3) -> str:
    """格式化对话历史为文本（用于意图理解）。

    包含用户问题以及上轮 SQL 使用的表名，
    帮助意图 LLM 正确扩展简略指代（如"改查DAH02"、"去掉过站时间"）。
    """
    if not messages:
        return ""
    human_msgs: list[str] = []
    ai_tables_list: list[set[str]] = []
    for msg in messages:
        role = getattr(msg, "type", "human") if hasattr(msg, "type") else "human"
        content = msg.content if hasattr(msg, "content") else str(msg)
        if role == "human":
            human_msgs.append(content)
        elif role == "ai":
            ai_tables_list.append(_extract_tables_from_sql(content))
    if not human_msgs:
        return ""
    recent_human = human_msgs[-max_turns:]
    recent_ai_tables = ai_tables_list[-max_turns:] if ai_tables_list else []
    lines: list[str] = []
    for i, q in enumerate(recent_human):
        lines.append(f"{i + 1}. {q}")
        if i < len(recent_ai_tables) and recent_ai_tables[i]:
            lines.append(f"   (上轮SQL使用表: {', '.join(sorted(recent_ai_tables[i]))})")
    return "\n".join(lines)


def _extract_sql_summary(ai_content: str) -> str:
    """从 AI 回复中提取 SQL 摘要。
    压缩空白后截断到 500 字符，确保 FROM/JOIN/WHERE 关键结构得以保留。
    """
    # 查找 SQL 代码块
    match = re.search(r"```sql\n(.*?)```", ai_content, re.DOTALL)
    if match:
        sql = re.sub(r"\s+", " ", match.group(1).strip())
        return sql[:500] + ("..." if len(sql) > 500 else "")
    # 找 SELECT 开头的内容（兼容 "SQL: SELECT ..." 前缀格式）
    match = re.search(r"(?:SQL:\s*)?(SELECT\s+.+?)(?:;|$)", ai_content, re.IGNORECASE | re.DOTALL)
    if match:
        sql = re.sub(r"\s+", " ", match.group(1).strip())
        return sql[:500] + ("..." if len(sql) > 500 else "")
    return ""


def _extract_tables_from_sql(text: str) -> set[str]:
    """从 SQL 文本中提取表名（FROM/JOIN 后的表名）。"""
    tables: set[str] = set()
    for match in _SQL_TABLE_PATTERN.finditer(text):
        table = match.group(1)
        if table.upper() not in _SQL_KEYWORDS:
            tables.add(table)
    return tables


def _extract_tables_from_history(messages: list) -> list[str]:
    """从对话历史的 AI 消息中提取所有使用过的表名（去重保持顺序）。"""
    all_tables: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        role = getattr(msg, "type", "human") if hasattr(msg, "type") else "human"
        if role != "ai":
            continue
        content = msg.content if hasattr(msg, "content") else str(msg)
        for table in _extract_tables_from_sql(content):
            if table not in seen:
                seen.add(table)
                all_tables.append(table)
    return all_tables


def node_1_intent_understanding(state: GraphState) -> dict:
    """节点1：意图理解 - 解析用户问题，输出结构化 JSON。"""
    llm = get_intent_llm()
    query = state["query"]

    # 注入对话历史上下文（含用户问题及上轮 SQL 使用的表名）
    messages = state.get("messages", [])
    history_text = _format_intent_history(messages)
    if history_text:
        query = f"对话历史：\n{history_text}\n\n当前问题：{query}"

    prompt = _INTENT_PROMPT.format(user_question=query)
    response = llm.invoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)

    # 清理可能的 markdown 包裹
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    intent = _parse_intent_json(content)
    enriched_intent, query_guidance = _build_query_constraints(state["query"], intent)

    # 仅当意图 LLM 判定当前问题与上轮对话有关联时，才将历史表名强制注入
    # 避免全新话题被历史表名污染
    if intent.get("reference_history") is True:
        history_tables = _extract_tables_from_history(messages)
        if history_tables:
            existing = list(enriched_intent.get("required_tables", []))
            for t in history_tables:
                if t not in existing:
                    existing.append(t)
            enriched_intent["required_tables"] = existing
            # 同步更新 anchor_tables，确保 BFS 检索也覆盖这些表
            anchor_tables = list(enriched_intent.get("anchor_tables", []))
            for t in history_tables:
                if t not in anchor_tables:
                    anchor_tables.append(t)
            enriched_intent["anchor_tables"] = anchor_tables

    # 提取多 SQL 意图
    query_type = intent.get("query_type", "single")
    sub_queries: list[dict] = []
    if query_type == "multi" and isinstance(intent.get("sub_queries"), list):
        sub_queries = [sq for sq in intent["sub_queries"] if isinstance(sq, dict) and sq.get("question")]
    multi_sql = len(sub_queries) > 0

    return {
        "intent_json": json.dumps(enriched_intent, ensure_ascii=False),
        "query_guidance": query_guidance,
        "sub_queries": sub_queries,
        "multi_sql": multi_sql,
    }


def node_2_parallel_retrieval(state: GraphState) -> dict:
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

    for sq in search_queries[:3]:  # 最多用 3 个搜索词
        try:
            # 混合检索：向量语义 + 关键词精确匹配
            for doc in hybrid_search_schema(
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
            for doc in search_few_shot(_few_shot_store, sq):
                if doc not in seen_few:
                    seen_few.add(doc)
                    few_shot_docs_list.append(doc)
        except Exception as e:
            logger.warning("节点2: few_shot_search 失败 (query=%s): %s", sq[:50], e)

    # 对规则层明确要求的表，直接补充精确 schema，避免向量召回缺失。
    required_tables = [t for t in intent.get("required_tables", []) if isinstance(t, str) and t.strip()]
    preferred_main_table = str(intent.get("preferred_main_table", "")).strip()
    if preferred_main_table:
        required_tables.insert(0, preferred_main_table)
    for table_name in _dedupe_keep_order(required_tables):
        doc = _SCHEMA_LOOKUP.get(table_name)
        if doc and doc not in seen_schema:
            seen_schema.add(doc)
            schema_docs_list.append(doc)

    evolved_few_shot_text = load_evolved_few_shot_text()
    if evolved_few_shot_text and evolved_few_shot_text not in seen_few:
        seen_few.add(evolved_few_shot_text)
        few_shot_docs_list.append(evolved_few_shot_text)

    schema_docs_raw = "\n---\n".join(schema_docs_list)
    few_shot_docs_raw = "\n---\n".join(few_shot_docs_list)

    # 按条数截断，防止 prompt 上下文溢出
    schema_docs_raw = _truncate_chunks_by_count(schema_docs_raw, settings.max_schema_context_items)
    few_shot_docs_raw = _truncate_chunks_by_count(few_shot_docs_raw, settings.max_few_shot_total_items)

    return {
        "schema_docs": schema_docs_raw,
        "few_shot_docs": few_shot_docs_raw,
    }


def node_3_bfs_expand(state: GraphState) -> dict:
    """节点3：BFS 图扩展 + 跨表路径查找。

    两步策略：
      1. BFS 辐射扩展：从所有种子表出发，找到周围的相关表
      2. 跨表路径查找：如果意图中锚定了多个表（如"工单→设备"），
         找它们之间的最短 JOIN 路径，解决"只知首尾、不知中间表"的问题
    """
    # ---- 收集种子表 ----
    seed_tables: list[str] = []
    anchor_tables: list[str] = []

    intent = _parse_intent_json(state.get("intent_json", "{}"))
    anchors = intent.get("anchor_tables", [])
    if isinstance(anchors, list):
        anchor_tables = [a for a in anchors if isinstance(a, str)]
        seed_tables.extend(anchor_tables)

    preferred_main_table = str(intent.get("preferred_main_table", "")).strip()
    required_tables = [t for t in intent.get("required_tables", []) if isinstance(t, str)]
    required_joins = [j for j in intent.get("required_joins", []) if isinstance(j, str)]

    if preferred_main_table and preferred_main_table not in seed_tables:
        seed_tables.insert(0, preferred_main_table)
    for table_name in required_tables:
        if table_name not in seed_tables:
            seed_tables.append(table_name)

    # 从检索文档中提取表名
    schema_docs = state.get("schema_docs", "")
    table_pattern = re.compile(r"表名：(\w+)")
    for match in table_pattern.finditer(schema_docs):
        tname = match.group(1)
        if tname not in seed_tables:
            seed_tables.append(tname)

    if not seed_tables:
        return {"expanded_tables": "", "join_hints": "", "warning": ""}

    # ---- 提取 intent_domains ----
    intent_domains = [d for d in intent.get("intent_domains", []) if isinstance(d, str)]

    # ---- 步骤1: BFS 辐射扩展 ----
    result = bfs_expand(
        seed_tables,
        max_hops=settings.bfs_max_hops,
        max_tables=settings.bfs_max_tables,
        intent_domains=intent_domains,
    )
    all_tables = set(result["tables"])
    all_join_paths = list(result["join_paths"])
    warning = result.get("warning", "")

    # ---- 步骤2: 跨表路径查找 ----
    # 如果意图中有多个锚定表，找它们之间的最短路径
    chain_hints_text = ""
    if len(anchor_tables) >= 2:
        # 以第一个锚定表为起点，依次找与其他锚定表的路径
        start = anchor_tables[0]
        for end in anchor_tables[1:]:
            path = find_path_between(start, end, max_depth=4)
            if path:
                # 将路径中的中间表加入结果集
                for t in path:
                    all_tables.add(t)
                # 将路径中的边加入 join_paths
                path_edges = build_path_join_hints(path)
                for pe in path_edges:
                    # 避免重复
                    already = any(jp["from"] == pe["from"] and jp["to"] == pe["to"] for jp in all_join_paths)
                    if not already:
                        all_join_paths.append(pe)
                # 生成链式 JOIN 提示
                chain_hints_text = build_chain_join_hints(path)

    # ---- 组装输出 ----
    join_hints = build_join_hints(all_join_paths)
    if chain_hints_text:
        join_hints = chain_hints_text + "\n\n" + join_hints

    enforced_lines: list[str] = []
    if preferred_main_table:
        enforced_lines.append(f"-- [主表硬约束] FROM 必须从 {preferred_main_table} 开始")
    if required_tables:
        enforced_lines.append(f"-- [必含表] {', '.join(_dedupe_keep_order(required_tables))}")
    if required_joins:
        enforced_lines.append("-- [必选 JOIN]")
        enforced_lines.extend(f"-- {join_expr}" for join_expr in _dedupe_keep_order(required_joins))
    if enforced_lines:
        join_hints = "\n".join(enforced_lines) + ("\n\n" + join_hints if join_hints else "")

    return {
        "expanded_tables": ",".join(sorted(all_tables | set(required_tables))),
        "join_hints": join_hints,
        "warning": warning,
    }


def node_4_schema_assembly(state: GraphState) -> dict:
    """节点4：Schema 组装 - 从检索结果中提取对应表的 DDL 描述。"""
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
    selected: list[str] = []
    for chunk in chunks:
        for tname in target_tables:
            if f"表名：{tname}" in chunk:
                selected.append(chunk.strip())
                break

    return {"schema_context": "\n\n".join(selected)}


def node_5_sql_generation(state: GraphState) -> dict:
    """节点5：SQL 生成 - 组装 prompt 调用 LLM 生成 SQL。

    多意图时，逐条为每个子问题生成独立 SQL。
    """
    llm = get_llm()
    intent = _parse_intent_json(state.get("intent_json", "{}"))
    multi_sql = state.get("multi_sql", False)
    sub_queries = state.get("sub_queries", [])
    schema_context = state.get("schema_context", "")
    join_hints = state.get("join_hints", "")
    query_guidance = state.get("query_guidance", "（无额外硬约束）")
    few_shot_docs = state.get("few_shot_docs", "")
    warning = state.get("warning", "")
    history_text = _format_conversation_history(state.get("messages", []))

    def _build_prompt(question: str) -> str:
        sql_prompt_template = _load_prompt("dify_sql_prompt.txt")
        p = sql_prompt_template.replace("{{schema_context}}", schema_context)
        p = p.replace("{{join_hints}}", join_hints)
        p = p.replace("{{query_guidance}}", query_guidance)
        p = p.replace("{{few_shot_examples}}", few_shot_docs)
        user_question = question
        if history_text:
            user_question = f"对话历史：\n{history_text}\n\n当前问题：{user_question}"
        p = p.replace("{{user_question}}", user_question)
        if warning:
            p = p.replace(
                "{% if warning %}\n⚠️ 注意：{{warning}}，建议生成SQL后人工核实\n{% endif %}",
                f"⚠️ 注意：{warning}，建议生成SQL后人工核实",
            )
        else:
            p = p.replace("{% if warning %}\n⚠️ 注意：{{warning}}，建议生成SQL后人工核实\n{% endif %}", "")
        return p

    def _call_llm_and_extract_sql(prompt: str) -> str:
        # prompt 总长度硬保护
        if len(prompt) > settings.max_prompt_chars:
            logger.warning(
                "节点5: prompt 超长 (%d > %d)，截断后半部分",
                len(prompt),
                settings.max_prompt_chars,
            )
            prompt = prompt[: settings.max_prompt_chars]
        logger.info(
            "节点5: 调用 LLM (model=%s, base_url=%s, prompt_len=%d)",
            settings.llm_model,
            settings.openai_base_url,
            len(prompt),
        )
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return content.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip()

    def _with_constraint_check(sql: str, prompt: str) -> str:
        constraint_feedback = _build_sql_constraint_feedback(sql, intent)
        if constraint_feedback:
            retry_prompt = "\n\n".join(
                [prompt, "## 上一版 SQL", f"```sql\n{sql}\n```", "## 纠偏反馈", constraint_feedback]
            )
            return _call_llm_and_extract_sql(retry_prompt)
        return sql

    if multi_sql and sub_queries:
        # 多意图：逐条为每个子问题生成 SQL
        generated_sqls: list[str] = []
        for i, sq in enumerate(sub_queries):
            sub_question = sq.get("question", "")
            logger.info("节点5: 生成第 %d/%d 条 SQL，子问题: %s", i + 1, len(sub_queries), sub_question[:80])
            prompt = _build_prompt(sub_question)
            sql = _call_llm_and_extract_sql(prompt)
            sql = _with_constraint_check(sql, prompt)
            generated_sqls.append(sql)
        return {"generated_sqls": generated_sqls}
    else:
        # 单意图：保持原有逻辑
        prompt = _build_prompt(state["query"])
        sql = _call_llm_and_extract_sql(prompt)
        sql = _with_constraint_check(sql, prompt)
        return {"generated_sqls": [sql]}


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


def _get_db_url() -> str:
    """将 asyncpg 格式的数据库 URL 转为 psycopg 兼容格式。"""
    return settings.execution_database_url.replace("+asyncpg", "")


def _execute_sql(sql: str) -> dict:
    """执行 SQL 并返回结果。

    Returns:
        {"success": bool, "rows": int, "columns": [...], "preview": [...], "error": str}
    """
    try:
        with psycopg.connect(_get_db_url()) as conn, conn.cursor() as cur:
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
        with psycopg.connect(_get_db_url()) as conn, conn.cursor() as cur:
            cur.execute(f"EXPLAIN (FORMAT JSON) {sql}")
            plan = cur.fetchone()[0]
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

        with psycopg.connect(_get_db_url()) as conn, conn.cursor() as cur:
            # 1) 统计总行数
            cur.execute(count_sql)
            total_rows = cur.fetchone()[0]

            # 2) 查询分页数据
            cur.execute(page_sql)
            if cur.description:
                columns = [d.name for d in cur.description]
                rows_data = cur.fetchall()
                rows = [dict(zip(columns, row, strict=True)) for row in rows_data]
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


def _get_table_columns(table_name: str) -> list[str] | None:
    """从数据库查询表的实际列名列表。"""
    try:
        with psycopg.connect(_get_db_url()) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
                (table_name,),
            )
            return [row[0] for row in cur.fetchall()]
    except Exception:
        return None


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


def _build_col_not_found_hint(sql: str, error_msg: str) -> str:
    """当错误是'column does not exist'时，查询真实列名并生成修复提示。"""
    col_match = re.search(r"column ([a-zA-Z_][\w\.]*) does not exist", error_msg, re.IGNORECASE)
    if not col_match:
        return ""
    missing_col = col_match.group(1)
    # 提取可能涉及的表名
    table_names = _extract_table_names(sql)
    if not table_names:
        return ""

    hint_parts: list[str] = [f"错误：列 '{missing_col}' 不存在。以下是可以使用的真实列名："]
    for tname in table_names[:3]:
        cols = _get_table_columns(tname)
        if cols:
            hint_parts.append(f"- {tname} 的列: {', '.join(cols[:20])}")
            if len(cols) > 20:
                hint_parts[-1] += f" ... 共 {len(cols)} 列"
    return "\n".join(hint_parts)


def _repair_sql(
    sql: str,
    error_msg: str,
    schema_context: str,
    user_query: str,
    join_hints: str,
    query_guidance: str,
) -> str:
    """调用 LLM 修复出错的 SQL。"""
    llm = get_llm()

    # 如果是列名错误，补充真实列名信息
    col_hint = _build_col_not_found_hint(sql, error_msg)

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

    response = llm.invoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)
    # 清理 markdown 包裹
    repaired = content.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip()
    return repaired


def node_7_execute_and_repair(state: GraphState) -> dict:
    """节点7：通过 EXPLAIN 校验 SQL 正确性，失败则通过 LLM 修复并重试（最多 3 次）。

    实际数据查询由 /execute/page 接口处理，这里只做语法/语义校验。

    多 SQL 模式：逐条校验，首次失败尝试修复一次，不循环重试。
    单 SQL 模式：保持原有重试逻辑。
    """
    retry_count = state.get("retry_count", 0)
    multi_sql = state.get("multi_sql", False)
    sub_queries = state.get("sub_queries", [])
    final_sqls = state.get("final_sqls", [])

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
                results.append(result)
                logger.info("节点7: SQL [%s] EXPLAIN 通过", desc)
                continue

            # 执行失败：内联重试最多 3 次
            logger.warning("节点7: SQL [%s] EXPLAIN 失败: %s", desc, result["error"][:120])
            repaired_success = False
            last_error = result["error"]

            for retry in range(_MAX_RETRIES):
                logger.info("节点7: SQL [%s] 第 %d/%d 次修复重试...", desc, retry + 1, _MAX_RETRIES)
                repaired_sql = _repair_sql(
                    current_sql,
                    last_error,
                    state.get("schema_context", ""),
                    sub_question,
                    state.get("join_hints", ""),
                    state.get("query_guidance", ""),
                )
                repaired_result = _explain_sql(repaired_sql)
                if repaired_result["success"]:
                    repaired_result["description"] = desc + (
                        "（已修复）" if retry == 0 else f"（第{retry + 1}次修复成功）"
                    )
                    repaired_result["question"] = sub_question
                    repaired_result["repaired"] = True
                    repaired_result["retry_count"] = retry + 1
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
            "retry_count": _MAX_RETRIES,  # 多SQL不循环重试
        }

    # 单 SQL 模式：保持原有逻辑
    sql = final_sqls[0]

    logger.info("节点7: EXPLAIN SQL (第 %d/%d 次)", retry_count + 1, _MAX_RETRIES)

    result = _explain_sql(sql)

    if result["success"]:
        logger.info("节点7: SQL EXPLAIN 通过")
        return {
            "execution_results": json.dumps([result], ensure_ascii=False, default=str),
        }

    # 执行失败
    error_msg = result["error"]
    logger.warning("节点7: SQL EXPLAIN 失败: %s", error_msg[:120])

    if retry_count < _MAX_RETRIES - 1:
        logger.info("节点7: 第 %d 次修复重试...", retry_count + 1)
        schema_context = state.get("schema_context", "")
        repaired_sql = _repair_sql(
            sql,
            error_msg,
            schema_context,
            state.get("query", ""),
            state.get("join_hints", ""),
            state.get("query_guidance", ""),
        )

        return {
            "final_sqls": [repaired_sql],
            "retry_count": retry_count + 1,
            "error": error_msg,
            "execution_results": json.dumps([result], ensure_ascii=False, default=str),
        }

    # 已达最大重试次数
    logger.warning("节点7: 已达最大重试次数 (%d)，退出", _MAX_RETRIES)
    return {
        "execution_results": json.dumps([result], ensure_ascii=False, default=str),
        "retry_count": _MAX_RETRIES,
        "error": f"SQL 校验失败（已重试 {retry_count} 次）: {error_msg}",
    }
