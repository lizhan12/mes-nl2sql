"""回放联表 CSV，用于验证标准 SQL 和 NL2SQL 生成效果。"""

import concurrent.futures
import csv
import json
import re
from pathlib import Path

import psycopg
import requests

from src.core.config import settings

BASE_URL = "http://127.0.0.1:8000"
CSV_PATH = Path("mes联表测试问题清单_含完整SQL.csv")
REPORT_PATH = Path("temp_batch_e2e_report.json")
MAX_WORKERS = 1
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


def split_cn_list(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[；;]", raw or "") if item.strip()]


def normalize_join_expr(expr: str, alias_map: dict[str, str]) -> str:
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


def parse_expected_joins(raw: str) -> list[str]:
    result: list[str] = []
    for expr in split_cn_list(raw):
        alias_map = {name: name for name in re.findall(r"[a-zA-Z_][\w]*", expr)}
        result.append(normalize_join_expr(expr, alias_map))
    return result


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


def execute_sql(conn: psycopg.Connection, sql: str) -> dict:
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


def call_api(index: int, question: str) -> tuple[int, dict]:
    session = requests.Session()
    try:
        response = session.post(BASE_URL + "/nl2sql", json={"query": question}, timeout=300)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        payload = {
            "query": question,
            "safe": False,
            "retry_count": -1,
            "sql": "",
            "error": f"HTTP request failed: {exc}",
            "execution_result": {"success": False, "rows": 0, "error": str(exc)},
        }
    return index, payload


def main() -> None:
    db_url = settings.execution_database_url.replace("+asyncpg", "")
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig", newline="")))
    report_by_index: dict[int, dict] = {}

    with psycopg.connect(db_url) as conn:
        for index, row in enumerate(rows, start=1):
            expected_main_table = row["预期主表"].strip()
            expected_related_tables = split_cn_list(row["预期关联表"])
            expected_joins = parse_expected_joins(row["预期 join"])
            report_by_index[index] = {
                "index": index,
                "question": row["问题"],
                "expected_sql_exec": execute_sql(conn, row["完整SQL"]),
                "expected_main_table": expected_main_table,
                "expected_related_tables": expected_related_tables,
                "expected_joins": expected_joins,
                "generated_safe": None,
                "generated_retry_count": None,
                "generated_error": "",
                "generated_execution_result": None,
                "generated_sql": "",
                "generated_main_table": "",
                "generated_tables": [],
                "generated_joins": [],
                "main_table_match": False,
                "missing_related_tables": expected_related_tables,
                "missing_expected_joins": expected_joins,
                "generation_correct": False,
            }

    REPORT_PATH.write_text(
        json.dumps([report_by_index[i] for i in sorted(report_by_index)], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(call_api, index, report_by_index[index]["question"]) for index in sorted(report_by_index)
        ]
        for future in concurrent.futures.as_completed(futures):
            index, payload = future.result()
            record = report_by_index[index]
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

            ordered_report = [report_by_index[i] for i in sorted(report_by_index)]
            REPORT_PATH.write_text(
                json.dumps(ordered_report, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "index": index,
                        "question": record["question"],
                        "expected_sql_ok": record["expected_sql_exec"]["success"],
                        "generated_sql_ok": bool(payload.get("execution_result", {}).get("success")),
                        "generation_correct": record["generation_correct"],
                        "retry_count": payload.get("retry_count"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    print(f"REPORT={REPORT_PATH.resolve()}", flush=True)


if __name__ == "__main__":
    main()
