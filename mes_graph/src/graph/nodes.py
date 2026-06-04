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
from src.services.vector_store import search_few_shot, search_schema
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
  "anchor_tables": [],
  "search_queries": ["查询词1","查询词2","查询词3"],
  "intent_domains": [],
  "time_range": "",
  "filters": [],
  "ambiguity": ""
}}

规则：
- intent_domains：从 production/quality/warehouse/equipment/master 中选，可多选
- anchor_tables：只填100%确定的表名，不确定宁可留空
- search_queries：包含"用户没说但逻辑上必要"的词（如说"良品率"要补"合格数"）

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
    """从 LangGraph messages 列表提取最近 N 轮对话历史，用于注入 prompt。"""
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
            # 截断过长的 AI 回复，只保留关键 SQL
            content_short = content[:200]
            lines.append(f"助手：{content_short}")
    return "\n".join(lines) if lines else ""


def node_1_intent_understanding(state: GraphState) -> dict:
    """节点1：意图理解 - 解析用户问题，输出结构化 JSON。"""
    llm = get_intent_llm()
    query = state["query"]

    # 注入对话历史上下文
    history_text = _format_conversation_history(state.get("messages", []))
    if history_text:
        query = f"对话历史：\n{history_text}\n\n当前问题：{query}"

    prompt = _INTENT_PROMPT.format(user_question=query)
    response = llm.invoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)

    # 清理可能的 markdown 包裹
    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    intent = _parse_intent_json(content)
    enriched_intent, query_guidance = _build_query_constraints(state["query"], intent)

    return {
        "intent_json": json.dumps(enriched_intent, ensure_ascii=False),
        "query_guidance": query_guidance,
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
            for doc in search_schema(_schema_store, sq):
                if doc not in seen_schema:
                    seen_schema.add(doc)
                    schema_docs_list.append(doc)
        except Exception as e:
            logger.warning("节点2: schema_search 失败 (query=%s): %s", sq[:50], e)
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

    return {
        "schema_docs": "\n---\n".join(schema_docs_list),
        "few_shot_docs": "\n---\n".join(few_shot_docs_list),
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
    """节点5：SQL 生成 - 组装 prompt 调用 LLM 生成 SQL。"""
    llm = get_llm()
    intent = _parse_intent_json(state.get("intent_json", "{}"))

    sql_prompt_template = _load_prompt("dify_sql_prompt.txt")
    prompt = sql_prompt_template.replace("{{schema_context}}", state.get("schema_context", ""))
    prompt = prompt.replace("{{join_hints}}", state.get("join_hints", ""))
    prompt = prompt.replace("{{query_guidance}}", state.get("query_guidance", "（无额外硬约束）"))
    prompt = prompt.replace("{{few_shot_examples}}", state.get("few_shot_docs", ""))

    # 注入对话历史上下文
    history_text = _format_conversation_history(state.get("messages", []))
    user_question = state["query"]
    if history_text:
        user_question = f"对话历史：\n{history_text}\n\n当前问题：{user_question}"
    prompt = prompt.replace("{{user_question}}", user_question)

    # 处理 warning 占位符：Jinja 风格的条件块
    warning = state.get("warning", "")
    if warning:
        prompt = prompt.replace(
            "{% if warning %}\n⚠️ 注意：{{warning}}，建议生成SQL后人工核实\n{% endif %}",
            f"⚠️ 注意：{warning}，建议生成SQL后人工核实",
        )
    else:
        prompt = prompt.replace("{% if warning %}\n⚠️ 注意：{{warning}}，建议生成SQL后人工核实\n{% endif %}", "")

    logger.info("节点5: 调用 LLM (model=%s, base_url=%s, prompt_len=%d)",
                settings.llm_model, settings.openai_base_url, len(prompt))
    response = llm.invoke(prompt)
    sql = response.content if hasattr(response, "content") else str(response)
    sql = sql.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip()

    constraint_feedback = _build_sql_constraint_feedback(sql, intent)
    if constraint_feedback:
        retry_prompt = "\n\n".join(
            [
                prompt,
                "## 上一版 SQL",
                f"```sql\n{sql}\n```",
                "## 纠偏反馈",
                constraint_feedback,
            ]
        )
        retry_response = llm.invoke(retry_prompt)
        retried_sql = retry_response.content if hasattr(retry_response, "content") else str(retry_response)
        sql = retried_sql.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip()

    return {"generated_sql": sql}


def node_6_safety_check(state: GraphState) -> dict:
    """节点6：安全校验 - 过滤危险操作，自动补 LIMIT。"""
    result = validate_sql(state.get("generated_sql", ""), settings.default_limit)
    return {
        "final_sql": result["final_sql"],
        "safe": result["safe"],
        "error": result["error"],
        "retry_count": 0,  # 初始化重试计数
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
    prompt = _SQL_REPAIR_PROMPT.format(
        user_query=user_query,
        schema_context=schema_context or "（无额外表结构信息）",
        join_hints=join_hints or "（无额外 JOIN 提示）",
        query_guidance=query_guidance or "（无额外硬约束）",
        sql=sql,
        error_msg=error_msg,
    )
    response = llm.invoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)
    # 清理 markdown 包裹
    repaired = content.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip()
    return repaired


def node_7_execute_and_repair(state: GraphState) -> dict:
    """节点7：执行 SQL，失败则通过 LLM 修复并重试（最多 3 次）。

    逻辑：
      - 若 safe=False，跳过执行
      - 执行 final_sql
      - 成功 → 返回 execution_result
      - 失败且 retry_count < 3 → LLM 修复 SQL → 更新 final_sql → retry_count+1
      - 失败且 retry_count >= 3 → 返回错误
    """
    retry_count = state.get("retry_count", 0)

    if not state.get("safe", False):
        return {
            "execution_result": json.dumps(
                {"success": False, "error": "SQL 未通过安全校验，跳过执行"}, ensure_ascii=False
            ),
        }

    sql = state.get("final_sql", "")
    if not sql:
        return {
            "execution_result": json.dumps({"success": False, "error": "SQL 为空，跳过执行"}, ensure_ascii=False),
        }

    logger.info("节点7: 执行 SQL (第 %d/%d 次)", retry_count + 1, _MAX_RETRIES)

    result = _execute_sql(sql)

    if result["success"]:
        logger.info("节点7: SQL 执行成功，返回 %d 行", result["rows"])
        return {
            "execution_result": json.dumps(result, ensure_ascii=False, default=str),
        }

    # 执行失败
    error_msg = result["error"]
    logger.warning("节点7: SQL 执行失败: %s", error_msg[:120])

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
            "final_sql": repaired_sql,
            "retry_count": retry_count + 1,
            "error": error_msg,
            "execution_result": json.dumps(result, ensure_ascii=False, default=str),
        }

    # 已达最大重试次数
    logger.warning("节点7: 已达最大重试次数 (%d)，退出", _MAX_RETRIES)
    return {
        "execution_result": json.dumps(result, ensure_ascii=False, default=str),
        "retry_count": _MAX_RETRIES,
        "error": f"SQL 执行失败（已重试 {retry_count} 次）: {error_msg}",
    }
