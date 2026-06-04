"""Harness 执行器。"""

from __future__ import annotations

import concurrent.futures
import csv
import json
import re
from pathlib import Path
from typing import Any

import psycopg
import requests

from src.core.config import settings
from src.harness.knowledge import normalize_join_expr, parse_expected_joins, split_cn_list

KEYWORDS = {
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


def parse_tables(sql: str) -> tuple[str, list[str], dict[str, str]]:
    alias_map: dict[str, str] = {}
    tables: list[str] = []

    pattern = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w\.]*)\s*(?:AS\s+)?([a-zA-Z_][\w]*)?", re.IGNORECASE)
    for match in pattern.finditer(sql):
        table = match.group(1)
        alias = match.group(2) or table
        if alias.upper() in KEYWORDS:
            alias = table
        alias_map[alias] = table
        alias_map[table] = table
        if table not in tables:
            tables.append(table)

    return (tables[0] if tables else ""), tables, alias_map


def parse_actual_joins(sql: str, alias_map: dict[str, str]) -> list[str]:
    joins: list[str] = []
    pattern = re.compile(
        r"\bJOIN\s+[a-zA-Z_][\w\.]*\s*(?:AS\s+)?(?:[a-zA-Z_][\w]*)?\s+ON\s+(.+?)(?=\b(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|;|$)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(sql):
        for piece in re.split(r"\bAND\b", match.group(1), flags=re.IGNORECASE):
            piece = piece.strip().strip("()")
            if piece:
                joins.append(normalize_join_expr(piece, alias_map))
    return joins


def build_probe_sql(sql: str) -> str:
    return f"SELECT * FROM ({sql.strip().rstrip(';')}) AS probe_q LIMIT 1;"


def execute_sql(conn: psycopg.Connection, sql: str) -> dict[str, Any]:
    try:
        with conn.cursor() as cur:
            cur.execute(build_probe_sql(sql))
            preview_rows = cur.fetchmany(1) if cur.description else []
            columns = [d.name for d in cur.description] if cur.description else []
            preview = [dict(zip(columns, row, strict=True)) for row in preview_rows] if columns else []
            return {
                "success": True,
                "rows": len(preview_rows),
                "columns": columns,
                "preview": preview,
                "error": "",
            }
    except Exception as exc:
        conn.rollback()
        return {
            "success": False,
            "rows": 0,
            "columns": [],
            "preview": [],
            "error": str(exc),
        }


def load_cases_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig", newline="")))
    cases: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        cases.append(
            {
                "case_id": f"csv_{index:03d}",
                "source": "csv_bootstrap",
                "question": row["问题"].strip(),
                "expected_main_table": row["预期主表"].strip(),
                "expected_related_tables": split_cn_list(row["预期关联表"]),
                "expected_joins": parse_expected_joins(row["预期 join"]),
                "expected_sql": row["完整SQL"].strip(),
                "tags": ["join_regression"],
            }
        )
    return cases


def call_api(base_url: str, question: str) -> dict[str, Any]:
    session = requests.Session()
    try:
        response = session.post(base_url.rstrip("/") + "/nl2sql", json={"query": question}, timeout=300)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {
            "query": question,
            "safe": False,
            "retry_count": -1,
            "sql": "",
            "error": f"HTTP request failed: {exc}",
            "execution_result": {"success": False, "rows": 0, "error": str(exc)},
        }


def _build_report_item(conn: psycopg.Connection, case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case.get("case_id"),
        "source": case.get("source", ""),
        "question": case["question"],
        "expected_sql": case.get("expected_sql", ""),
        "expected_sql_exec": execute_sql(conn, case.get("expected_sql", "")),
        "expected_main_table": case.get("expected_main_table", ""),
        "expected_related_tables": case.get("expected_related_tables", []),
        "expected_joins": case.get("expected_joins", []),
        "generated_safe": None,
        "generated_retry_count": None,
        "generated_error": "",
        "generated_execution_result": None,
        "generated_sql": "",
        "generated_main_table": "",
        "generated_tables": [],
        "generated_joins": [],
        "main_table_match": False,
        "missing_related_tables": list(case.get("expected_related_tables", [])),
        "missing_expected_joins": list(case.get("expected_joins", [])),
        "generation_correct": False,
    }


def _update_report_item(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    generated_sql = payload.get("sql", "")
    actual_main_table, actual_tables, alias_map = parse_tables(generated_sql)
    actual_joins = parse_actual_joins(generated_sql, alias_map)
    missing_tables = [t for t in record["expected_related_tables"] if t not in actual_tables]
    missing_joins = [j for j in record["expected_joins"] if j not in actual_joins]

    record.update(
        {
            "generated_safe": payload.get("safe"),
            "generated_retry_count": payload.get("retry_count"),
            "generated_error": payload.get("error", ""),
            "generated_execution_result": payload.get("execution_result"),
            "generated_sql": generated_sql,
            "generated_main_table": actual_main_table,
            "generated_tables": actual_tables,
            "generated_joins": actual_joins,
            "main_table_match": actual_main_table == record["expected_main_table"],
            "missing_related_tables": missing_tables,
            "missing_expected_joins": missing_joins,
            "generation_correct": (
                actual_main_table == record["expected_main_table"]
                and not missing_tables
                and not missing_joins
                and bool(payload.get("execution_result", {}).get("success"))
            ),
        }
    )
    return record


def evaluate_cases(
    cases: list[dict[str, Any]],
    base_url: str,
    report_path: Path,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    db_url = settings.execution_database_url.replace("+asyncpg", "")
    report_by_case_id: dict[str, dict[str, Any]] = {}

    with psycopg.connect(db_url) as conn:
        for case in cases:
            report_by_case_id[str(case["case_id"])] = _build_report_item(conn, case)

    report_path.write_text(
        json.dumps(list(report_by_case_id.values()), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(call_api, base_url, case["question"]): str(case["case_id"]) for case in cases}
        for future in concurrent.futures.as_completed(futures):
            case_id = futures[future]
            record = report_by_case_id[case_id]
            payload = future.result()
            _update_report_item(record, payload)
            ordered = [report_by_case_id[str(case["case_id"])] for case in cases]
            report_path.write_text(
                json.dumps(ordered, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "case_id": case_id,
                        "question": record["question"],
                        "generated_sql_ok": bool(payload.get("execution_result", {}).get("success")),
                        "generation_correct": record["generation_correct"],
                        "retry_count": payload.get("retry_count"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    return [report_by_case_id[str(case["case_id"])] for case in cases]
