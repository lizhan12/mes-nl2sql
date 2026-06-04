"""端到端测试脚本：读取 CSV 问题清单，调用 /nl2sql 接口，生成对比文档。"""

import csv
import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

BASE_URL = "http://127.0.0.1:8002"
CSV_PATH = Path(__file__).parent / "mes联表测试问题清单_含完整SQL.csv"
REPORT_JSON_PATH = Path(__file__).parent / "e2e_test_report.json"
REPORT_MD_PATH = Path(__file__).parent / "e2e_test_report.md"
TIMEOUT = 300  # 单个请求超时秒数


def split_cn_list(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[；;]", raw or "") if item.strip()]


def normalize_join(expr: str) -> str:
    match = re.search(
        r"([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)\s*=\s*([a-zA-Z_][\w]*)\.([a-zA-Z_][\w]*)",
        expr,
        re.IGNORECASE,
    )
    if not match:
        return re.sub(r"\s+", " ", expr.strip())
    left_alias, left_col, right_alias, right_col = match.groups()
    ordered = sorted([f"{left_alias}.{left_col}", f"{right_alias}.{right_col}"])
    return f"{ordered[0]} = {ordered[1]}"


def parse_expected_joins(raw: str) -> list[str]:
    result: list[str] = []
    for expr in split_cn_list(raw):
        result.append(normalize_join(expr))
    return result


def parse_tables_from_sql(sql: str) -> tuple[str, list[str], dict[str, str]]:
    alias_map: dict[str, str] = {}
    tables: list[str] = []
    keywords = {
        "WHERE", "GROUP", "ORDER", "LIMIT", "LEFT", "RIGHT", "INNER",
        "FULL", "CROSS", "JOIN", "ON", "SELECT", "FROM", "AS", "AND", "OR",
        "SET", "INTO", "VALUES", "UPDATE", "DELETE", "INSERT", "HAVING",
    }
    pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w]*)\s*(?:AS\s+)?([a-zA-Z_][\w]*)?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(sql):
        table = match.group(1)
        alias = match.group(2) or table
        if alias.upper() in keywords:
            alias = table
        alias_map[alias] = table
        alias_map[table] = table
        if table not in tables:
            tables.append(table)
    return (tables[0] if tables else ""), tables, alias_map


def parse_actual_joins(sql: str, alias_map: dict[str, str]) -> list[str]:
    joins: list[str] = []
    pattern = re.compile(
        r"\bJOIN\s+[a-zA-Z_][\w]*\s*(?:AS\s+)?(?:[a-zA-Z_][\w]*)?\s+ON\s+(.+?)"
        r"(?=\b(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|;|$)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(sql):
        for piece in re.split(r"\bAND\b", match.group(1), flags=re.IGNORECASE):
            piece = piece.strip().strip("()")
            if piece:
                joins.append(normalize_join(piece))
    return joins


def call_nl2sql(question: str) -> dict:
    url = f"{BASE_URL}/nl2sql"
    payload = json.dumps({"query": question}).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except Exception as exc:
        return {
            "query": question,
            "safe": False,
            "retry_count": -1,
            "sql": "",
            "error": f"HTTP request failed: {exc}",
            "execution_result": {"success": False, "rows": 0, "error": str(exc)},
            "tables_used": [],
            "join_hints": "",
        }


def compare_results(expected: dict, generated: dict) -> dict:
    expected_main = expected["expected_main_table"]
    expected_tables = expected["expected_related_tables"]
    expected_joins = expected["expected_joins"]

    gen_sql = generated.get("sql", "")
    gen_main, gen_tables, alias_map = parse_tables_from_sql(gen_sql)
    gen_joins = parse_actual_joins(gen_sql, alias_map)

    main_match = gen_main == expected_main
    missing_tables = [t for t in expected_tables if t not in gen_tables]
    extra_tables = [t for t in gen_tables if t not in expected_tables and t != expected_main]
    missing_joins = [j for j in expected_joins if j not in gen_joins]
    extra_joins = [j for j in gen_joins if j not in expected_joins]

    exec_result = generated.get("execution_result") or {}
    exec_success = exec_result.get("success", False) if isinstance(exec_result, dict) else False

    all_correct = (
        main_match
        and not missing_tables
        and not missing_joins
        and exec_success
    )

    return {
        "main_table_match": main_match,
        "missing_tables": missing_tables,
        "extra_tables": extra_tables,
        "missing_joins": missing_joins,
        "extra_joins": extra_joins,
        "exec_success": exec_success,
        "all_correct": all_correct,
        "gen_main_table": gen_main,
        "gen_tables": gen_tables,
        "gen_joins": gen_joins,
    }


def generate_markdown_report(results: list[dict]) -> str:
    lines = []
    lines.append("# MES NL2SQL 端到端测试报告")
    lines.append("")
    lines.append(f"- 测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 测试用例数: {len(results)}")

    total = len(results)
    correct = sum(1 for r in results if r["comparison"]["all_correct"])
    main_match = sum(1 for r in results if r["comparison"]["main_table_match"])
    exec_ok = sum(1 for r in results if r["comparison"]["exec_success"])

    lines.append(f"- 全部正确: {correct}/{total} ({correct/total*100:.1f}%)")
    lines.append(f"- 主表匹配: {main_match}/{total} ({main_match/total*100:.1f}%)")
    lines.append(f"- SQL执行成功: {exec_ok}/{total} ({exec_ok/total*100:.1f}%)")
    lines.append("")
    lines.append("---")
    lines.append("")

    for r in results:
        idx = r["index"]
        q = r["question"]
        comp = r["comparison"]
        status = "PASS" if comp["all_correct"] else "FAIL"

        lines.append(f"## {idx}. {q}")
        lines.append("")
        lines.append(f"**结果: {status}**")
        lines.append("")
        lines.append("| 项目 | 值 |")
        lines.append("|------|------|")
        lines.append(f"| 预期主表 | `{r['expected_main_table']}` |")
        lines.append(f"| 生成主表 | `{comp['gen_main_table']}` |")
        lines.append(f"| 主表匹配 | {'是' if comp['main_table_match'] else '否'} |")
        lines.append(f"| SQL执行成功 | {'是' if comp['exec_success'] else '否'} |")
        lines.append(f"| 重试次数 | {r['generated'].get('retry_count', 'N/A')} |")

        if r["generated"].get("error"):
            lines.append(f"| 错误信息 | {r['generated']['error'][:200]} |")

        if comp["missing_tables"]:
            lines.append(f"| 缺失关联表 | {', '.join(f'`{t}`' for t in comp['missing_tables'])} |")
        if comp["extra_tables"]:
            lines.append(f"| 多余关联表 | {', '.join(f'`{t}`' for t in comp['extra_tables'])} |")
        if comp["missing_joins"]:
            lines.append(f"| 缺失JOIN条件 | {', '.join(f'`{j}`' for j in comp['missing_joins'])} |")
        if comp["extra_joins"]:
            lines.append(f"| 多余JOIN条件 | {', '.join(f'`{j}`' for j in comp['extra_joins'])} |")

        lines.append("")
        lines.append("### 预期 SQL")
        lines.append("```sql")
        lines.append(r["expected_sql"])
        lines.append("```")
        lines.append("")
        lines.append("### 生成 SQL")
        lines.append("```sql")
        lines.append(r["generated"].get("sql", ""))
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig", newline="")))
    results: list[dict] = []

    total = len(rows)
    for index, row in enumerate(rows, start=1):
        question = row["问题"].strip()
        expected_main_table = row["预期主表"].strip()
        expected_related_tables = split_cn_list(row["预期关联表"])
        expected_joins = parse_expected_joins(row["预期 join"])
        expected_sql = row["完整SQL"].strip()

        print(f"[{index}/{total}] 测试: {question[:50]}...", flush=True)
        start_time = time.time()

        generated = call_nl2sql(question)

        elapsed = time.time() - start_time
        print(f"  耗时: {elapsed:.1f}s | SQL执行: {generated.get('execution_result', {}).get('success', False)}", flush=True)

        expected_info = {
            "expected_main_table": expected_main_table,
            "expected_related_tables": expected_related_tables,
            "expected_joins": expected_joins,
        }

        comparison = compare_results(expected_info, generated)

        result = {
            "index": index,
            "question": question,
            "expected_main_table": expected_main_table,
            "expected_related_tables": expected_related_tables,
            "expected_joins": expected_joins,
            "expected_sql": expected_sql,
            "generated": generated,
            "comparison": comparison,
            "elapsed_seconds": round(elapsed, 1),
        }
        results.append(result)

        # 实时写入 JSON 报告
        REPORT_JSON_PATH.write_text(
            json.dumps(results, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    # 生成 Markdown 报告
    md_content = generate_markdown_report(results)
    REPORT_MD_PATH.write_text(md_content, encoding="utf-8")

    print(f"\n测试完成！")
    print(f"JSON 报告: {REPORT_JSON_PATH}")
    print(f"Markdown 报告: {REPORT_MD_PATH}")


if __name__ == "__main__":
    main()
