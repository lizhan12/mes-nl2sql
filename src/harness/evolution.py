"""Harness 失败进化逻辑。"""

from __future__ import annotations

import re
from typing import Any

from src.harness.knowledge import normalize_question

_KEYWORDS = {
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


def should_promote_report_item(item: dict[str, Any]) -> bool:
    execution = item.get("generated_execution_result") or {}
    generated_ok = bool(execution.get("success"))
    structure_ok = bool(item.get("generation_correct"))
    retry_count = int(item.get("generated_retry_count") or 0)
    return (not generated_ok) or (not structure_ok) or retry_count > 0


def build_runtime_rule(item: dict[str, Any]) -> dict[str, Any]:
    question = str(item.get("question", "")).strip()
    return {
        "rule_id": f"rule::{normalize_question(question)}",
        "source": "harness_evolution",
        "question": question,
        "normalized_question": normalize_question(question),
        "preferred_main_table": item.get("expected_main_table", ""),
        "required_tables": [
            value
            for value in [
                item.get("expected_main_table", ""),
                *(item.get("expected_related_tables") or []),
            ]
            if value
        ],
        "required_joins": item.get("expected_joins") or [],
        "evolution_reason": {
            "generated_retry_count": item.get("generated_retry_count"),
            "generated_error": item.get("generated_error", ""),
            "missing_related_tables": item.get("missing_related_tables") or [],
            "missing_expected_joins": item.get("missing_expected_joins") or [],
            "main_table_match": bool(item.get("main_table_match")),
        },
    }


def _parse_tables(sql: str) -> tuple[str, list[str], dict[str, str]]:
    alias_map: dict[str, str] = {}
    tables: list[str] = []
    pattern = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w\.]*)\s*(?:AS\s+)?([a-zA-Z_][\w]*)?", re.IGNORECASE)
    for match in pattern.finditer(sql):
        table = match.group(1)
        alias = match.group(2) or table
        if alias.upper() in _KEYWORDS:
            alias = table
        alias_map[alias] = table
        alias_map[table] = table
        if table not in tables:
            tables.append(table)
    return (tables[0] if tables else ""), tables, alias_map


def _parse_joins(sql: str, alias_map: dict[str, str]) -> list[str]:
    joins: list[str] = []
    pattern = re.compile(
        r"\bJOIN\s+[a-zA-Z_][\w\.]*\s*(?:AS\s+)?(?:[a-zA-Z_][\w]*)?\s+ON\s+(.+?)(?=\b(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|;|$)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(sql):
        clause = match.group(1)
        for piece in re.split(r"\bAND\b", clause, flags=re.IGNORECASE):
            piece = piece.strip().strip("()")
            if not piece:
                continue
            joins.append(_normalize_join(piece, alias_map))
    return joins


def _normalize_join(expr: str, alias_map: dict[str, str]) -> str:
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
    ordered = sorted([f"{left_table}.{left_col}", f"{right_table}.{right_col}"])
    return f"{ordered[0]} = {ordered[1]}"


def build_runtime_rule_from_successful_sql(item: dict[str, Any]) -> dict[str, Any]:
    question = str(item.get("query_text") or item.get("question") or "").strip()
    sql = str(item.get("final_sql") or item.get("sql") or "").strip()
    preferred_main_table, tables, alias_map = _parse_tables(sql)
    joins = _parse_joins(sql, alias_map)
    return {
        "rule_id": f"rule::{normalize_question(question)}",
        "source": "online_harness_successful_sql",
        "question": question,
        "normalized_question": normalize_question(question),
        "preferred_main_table": preferred_main_table,
        "required_tables": tables,
        "required_joins": joins,
        "evolution_reason": {
            "generated_retry_count": int(item.get("retry_count", 0)),
            "generated_error": str(item.get("execution_error") or item.get("error_text") or ""),
            "derived_from": "successful_final_sql",
        },
    }


def _split_multi_sql(sql_text: str) -> list[str]:
    """拆分多条 SQL（按分号分割，过滤空行）。

    Args:
        sql_text: 可能包含多条 SQL 的文本

    Returns:
        拆分后的 SQL 列表
    """
    sqls = [s.strip() for s in sql_text.split(";") if s.strip()]
    return sqls


def build_runtime_rules_from_successful_sql(item: dict[str, Any]) -> list[dict[str, Any]]:
    """从成功 SQL 抽取规则，支持多 SQL 场景。

    当 final_sql 包含多条 SQL 时，为每条 SQL 单独生成规则，避免表和 JOIN 混合。

    Args:
        item: 包含 query_text 和 final_sql 的字典

    Returns:
        规则列表（单 SQL 返回 1 条，多 SQL 返回多条）
    """
    question = str(item.get("query_text") or item.get("question") or "").strip()
    sql_text = str(item.get("final_sql") or item.get("sql") or "").strip()
    normalized = normalize_question(question)

    sqls = _split_multi_sql(sql_text)

    # 单条 SQL，走原有逻辑
    if len(sqls) <= 1:
        return [build_runtime_rule_from_successful_sql(item)]

    # 多条 SQL，分别抽取规则
    rules: list[dict[str, Any]] = []
    for idx, sql in enumerate(sqls, 1):
        preferred_main_table, tables, alias_map = _parse_tables(sql)
        joins = _parse_joins(sql, alias_map)

        rule = {
            "rule_id": f"rule::{normalized}::part{idx}",
            "source": "online_harness_multi_sql",
            "question": question,
            "normalized_question": normalized,
            "preferred_main_table": preferred_main_table,
            "required_tables": tables,
            "required_joins": joins,
            "evolution_reason": {
                "generated_retry_count": int(item.get("retry_count", 0)),
                "generated_error": str(item.get("execution_error") or item.get("error_text") or ""),
                "derived_from": "multi_sql_part",
                "sql_index": idx,
                "total_sqls": len(sqls),
            },
            "sql_part": sql,
        }
        rules.append(rule)

    return rules


def build_few_shot_item_from_successful_sql(item: dict[str, Any]) -> dict[str, Any]:
    question = str(item.get("query_text") or item.get("question") or "").strip()
    sql = str(item.get("final_sql") or item.get("sql") or "").strip()
    preferred_main_table, tables, _ = _parse_tables(sql)
    related_tables = tables[1:] if len(tables) > 1 else []
    return {
        "question": question,
        "expected_main_table": preferred_main_table,
        "expected_related_tables": related_tables,
        "expected_sql": sql,
    }


def build_rule_candidate_from_failure_and_recovery(
    failure_case: dict[str, Any],
    recovered_request: dict[str, Any],
) -> dict[str, Any]:
    query_text = str(failure_case.get("query_text", "")).strip()
    normalized = normalize_question(query_text)
    runtime_rule = build_runtime_rule_from_successful_sql(recovered_request)
    few_shot_item = build_few_shot_item_from_successful_sql(recovered_request)
    return {
        "candidate_key": f"recovered::{normalized}",
        "candidate_type": "recovered_failure_rule",
        "pattern_type": "normalized_query",
        "pattern_key": normalized,
        "question_example": query_text,
        "proposed_rule_json": runtime_rule,
        "proposed_few_shot_text": build_few_shot_chunk(few_shot_item),
        "confidence": 0.95 if int(recovered_request.get("retry_count", 0)) == 0 else 0.85,
        "evidence_json": {
            "failure_case_id": failure_case.get("id"),
            "failure_type": failure_case.get("failure_type", ""),
            "failure_error": failure_case.get("error_text", ""),
            "recovered_request_id": recovered_request.get("request_id", ""),
            "recovered_retry_count": recovered_request.get("retry_count", 0),
        },
    }


def build_observation_candidate_from_failure(failure_case: dict[str, Any]) -> dict[str, Any]:
    query_text = str(failure_case.get("query_text", "")).strip()
    normalized = normalize_question(query_text)
    return {
        "candidate_key": f"observe::{normalized}",
        "candidate_type": "failure_cluster_observation",
        "pattern_type": "normalized_query",
        "pattern_key": normalized,
        "question_example": query_text,
        "proposed_rule_json": {},
        "proposed_few_shot_text": "",
        "confidence": 0.4,
        "evidence_json": {
            "failure_case_id": failure_case.get("id"),
            "failure_type": failure_case.get("failure_type", ""),
            "failure_error": failure_case.get("error_text", ""),
            "note": "未找到同问题成功恢复样本，建议人工补充正确 SQL 或标注。",
        },
    }


def build_rule_candidate_from_labeled_failure(failure_case: dict[str, Any]) -> dict[str, Any]:
    query_text = str(failure_case.get("query_text", "")).strip()
    normalized = normalize_question(query_text)
    correct_sql = str(failure_case.get("correct_sql", "")).strip()
    recovered_request = {
        "query_text": query_text,
        "final_sql": correct_sql,
        "retry_count": 0,
        "execution_error": "",
    }
    runtime_rule = build_runtime_rule_from_successful_sql(recovered_request)
    few_shot_item = build_few_shot_item_from_successful_sql(recovered_request)
    return {
        "candidate_key": f"labeled::{normalized}",
        "candidate_type": "labeled_failure_rule",
        "pattern_type": "normalized_query",
        "pattern_key": normalized,
        "question_example": query_text,
        "proposed_rule_json": runtime_rule,
        "proposed_few_shot_text": build_few_shot_chunk(few_shot_item),
        "confidence": 0.99,
        "evidence_json": {
            "failure_case_id": failure_case.get("id"),
            "failure_type": failure_case.get("failure_type", ""),
            "failure_error": failure_case.get("error_text", ""),
            "label_id": failure_case.get("label_id"),
            "label_note": failure_case.get("label_note", ""),
            "derived_from": "human_labeled_correct_sql",
        },
    }


def merge_runtime_rules(
    existing_rules: list[dict[str, Any]],
    new_rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rule in existing_rules + new_rules:
        key = str(rule.get("normalized_question") or normalize_question(str(rule.get("question", ""))))
        if not key:
            continue
        merged[key] = {
            **merged.get(key, {}),
            **rule,
            "normalized_question": key,
        }
    return list(merged.values())


def build_few_shot_chunk(item: dict[str, Any], source: str = "harness_evolution") -> str:
    question = str(item.get("question", "")).strip()
    expected_main_table = str(item.get("expected_main_table", "")).strip()
    expected_related = "、".join(item.get("expected_related_tables") or []) or "无"
    expected_sql = item.get("expected_sql") or item.get("reference_sql") or ""

    source_label = {
        "harness_evolution": "Harness 失败进化样本",
        "user_liked": "用户点赞样本",
    }.get(source, "Harness 失败进化样本")

    return "\n".join(
        [
            f"场景：{source_label}（主表={expected_main_table}，关联表={expected_related}）",
            f"用户问题：{question}",
            "SQL：",
            str(expected_sql).strip(),
        ]
    ).strip()


def build_evolved_few_shot_text(items: list[dict[str, Any]], source: str = "harness_evolution") -> str:
    chunks = [
        build_few_shot_chunk(item, source=source)
        for item in items
        if str(item.get("expected_sql") or item.get("reference_sql") or "").strip()
    ]
    return "\n---\n".join(chunk for chunk in chunks if chunk)


def build_llm_verified_candidate(
    request_item: dict[str, Any],
    confidence: float,
    candidate_type: str,
    review_note: str,
    dimension_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """根据 LLM 验证重试成功请求的结果构建候选规则。

    重试成功的请求仅说明 SQL 无语法错误，不代表符合用户需求。
    通过 LLM 多维度评估验证后，再决定是否采纳。

    Args:
        request_item: 重试成功的请求记录
        confidence: LLM 评估置信度
        candidate_type: 候选类型（llm_auto_approved / llm_labeled_failure / llm_low_confidence_failure）
        review_note: 审核备注
        dimension_details: 多维度评估详细信息

    Returns:
        候选规则 dict，可直接 upsert 到 nl2sql_rule_candidate
    """
    query_text = str(request_item.get("query_text", "")).strip()
    sql = str(request_item.get("final_sql", "")).strip()
    normalized = normalize_question(query_text)
    few_shot_item = {
        "question": query_text,
        "expected_sql": sql,
    }
    runtime_rule = build_runtime_rule_from_successful_sql(request_item)
    return {
        "candidate_key": f"llm_verified::{normalized}",
        "candidate_type": candidate_type,
        "pattern_type": "normalized_query",
        "pattern_key": normalized,
        "question_example": query_text,
        "source_request_ids": [str(request_item.get("request_id", ""))],
        "source_failure_case_ids": [],
        "proposed_rule_json": runtime_rule,
        "proposed_few_shot_text": build_few_shot_chunk(few_shot_item),
        "confidence": confidence,
        "evidence_json": {
            "request_id": str(request_item.get("request_id", "")),
            "retry_count": int(request_item.get("retry_count", 0)),
            "analysis_method": "llm_multi_dimension_verification",
            "dimension_details": dimension_details or {},
            "review_note": review_note,
        },
        "review_note": review_note,
        "status": "approved" if candidate_type == "llm_auto_approved" else "pending",
    }


def build_llm_labeled_candidate(
    query_text: str,
    corrected_sql: str,
    confidence: float,
    candidate_type: str,
    review_note: str,
    failure_case_id: int | None = None,
    dimension_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """根据 LLM 自动标注结果构建候选规则。

    Args:
        query_text: 用户原始问题
        corrected_sql: LLM 生成的修正 SQL
        confidence: 综合置信度
        candidate_type: 候选类型（llm_auto_approved / llm_labeled_failure / llm_low_confidence_failure）
        review_note: 审核备注
        failure_case_id: 关联的失败案例 ID
        dimension_details: 多维度评估详细信息

    Returns:
        候选规则 dict，可直接 upsert 到 nl2sql_rule_candidate
    """
    normalized = normalize_question(query_text)
    few_shot_item = {
        "question": query_text,
        "expected_sql": corrected_sql,
    }
    runtime_rule = build_runtime_rule_from_successful_sql(
        {"query_text": query_text, "final_sql": corrected_sql, "retry_count": 0, "execution_error": ""}
    )
    return {
        "candidate_key": f"llm_labeled::{normalized}",
        "candidate_type": candidate_type,
        "pattern_type": "normalized_query",
        "pattern_key": normalized,
        "question_example": query_text,
        "source_request_ids": [],
        "source_failure_case_ids": [failure_case_id] if failure_case_id else [],
        "proposed_rule_json": runtime_rule,
        "proposed_few_shot_text": build_few_shot_chunk(few_shot_item),
        "confidence": confidence,
        "evidence_json": {
            "failure_case_id": failure_case_id,
            "analysis_method": "llm_multi_dimension",
            "dimension_details": dimension_details or {},
            "review_note": review_note,
        },
        "review_note": review_note,
        "status": "approved" if candidate_type == "llm_auto_approved" else "pending",
    }
