"""SQL 安全校验。"""

import re

_DANGEROUS_KEYWORDS = [
    "DELETE",
    "UPDATE",
    "DROP",
    "TRUNCATE",
    "INSERT",
    "ALTER",
    "CREATE",
    "GRANT",
    "REVOKE",
]


def validate_sql(sql: str, default_limit: int = 500) -> dict:
    """校验生成的 SQL：过滤危险操作，清理 markdown 格式，自动补 LIMIT。

    Returns:
        {"safe": bool, "final_sql": str, "error": str}
    """
    sql_upper = sql.upper().strip()

    for kw in _DANGEROUS_KEYWORDS:
        if re.search(r"\b" + kw + r"\b", sql_upper):
            return {"safe": False, "final_sql": "", "error": f"包含禁止操作: {kw}"}

    cleaned = re.sub(r"```sql|```", "", sql).strip().rstrip(";")

    # 始终使用配置的默认 LIMIT，替换或追加
    cleaned = re.sub(r"\bLIMIT\s+\d+", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = f"{cleaned}\nLIMIT {default_limit}"

    return {"safe": True, "final_sql": f"{cleaned};", "error": ""}


# ---- 语义检查 ----

_AGG_FUNCS = {"SUM", "AVG", "COUNT", "MIN", "MAX", "STDDEV", "VARIANCE"}

_SELECT_COL_PATTERN = re.compile(r"SELECT\s+(.+?)\s+FROM", re.IGNORECASE | re.DOTALL)
_GROUP_BY_PATTERN = re.compile(r"\bGROUP\s+BY\s+(.+?)(?=\bHAVING\b|\bORDER\b|\bLIMIT\b|;|$)", re.IGNORECASE | re.DOTALL)
_AGG_FUNC_PATTERN = re.compile(r"\b(SUM|AVG|COUNT|MIN|MAX|STDDEV|VARIANCE)\s*\(", re.IGNORECASE)
_JOIN_TABLE_PATTERN = re.compile(r"\bJOIN\s+([a-zA-Z_][\w\.]*)", re.IGNORECASE)


def semantic_sanity_check(sql: str) -> list[str]:
    """对 EXPLAIN 通过的 SQL 做轻量语义检查，拦截高频静默错误。

    纯代码逻辑，不调用 LLM。返回警告列表（空列表表示无问题）。
    不阻断执行，仅标记为需要人工核实。
    """
    issues: list[str] = []

    # 检查1：GROUP BY 完整性
    issues.extend(_check_group_by_completeness(sql))

    # 检查2：多对多 JOIN 风险（同一表被 JOIN 多次）
    issues.extend(_check_duplicate_join(sql))

    # 检查3：聚合函数 NULL 处理
    issues.extend(_check_agg_null_handling(sql))

    return issues


def _check_group_by_completeness(sql: str) -> list[str]:
    """检查 SELECT 中的非聚合列是否都在 GROUP BY 中。"""
    issues: list[str] = []

    select_match = _SELECT_COL_PATTERN.search(sql)
    if not select_match:
        return issues

    select_clause = select_match.group(1).strip()

    # 如果没有聚合函数，不需要 GROUP BY 检查
    if not _AGG_FUNC_PATTERN.search(select_clause):
        return issues

    # 提取 GROUP BY 列
    group_by_match = _GROUP_BY_PATTERN.search(sql)
    if not group_by_match:
        # 有聚合函数但没有 GROUP BY，检查是否是全表聚合（只有聚合列）
        # 如果 SELECT 中有非聚合列，说明缺少 GROUP BY
        non_agg_cols = _extract_non_agg_select_cols(select_clause)
        if non_agg_cols:
            issues.append(
                f"SQL 包含聚合函数但缺少 GROUP BY，SELECT 中的非聚合列 {non_agg_cols} 会被压缩为一行，可能不是预期行为"
            )
        return issues

    group_by_cols = {col.strip().lower().split(".")[-1] for col in group_by_match.group(1).split(",")}
    non_agg_cols = _extract_non_agg_select_cols(select_clause)

    missing = [col for col in non_agg_cols if col.lower().split(".")[-1] not in group_by_cols]
    if missing:
        issues.append(
            f"SELECT 中的非聚合列 {missing} 不在 GROUP BY 中，可能导致结果错误（PostgreSQL 严格模式下会报错）"
        )

    return issues


def _extract_non_agg_select_cols(select_clause: str) -> list[str]:
    """从 SELECT 子句中提取非聚合列名。"""
    cols: list[str] = []
    # 按逗号分割，但要注意函数内的逗号
    depth = 0
    current = ""
    for char in select_clause:
        if char == "(":
            depth += 1
            current += char
        elif char == ")":
            depth -= 1
            current += char
        elif char == "," and depth == 0:
            cols.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        cols.append(current.strip())

    # 过滤掉聚合函数表达式和常量，只保留裸列名
    result: list[str] = []
    for col in cols:
        col = col.strip()
        # 跳过聚合函数
        if _AGG_FUNC_PATTERN.search(col):
            continue
        # 跳过常量
        if re.match(r"^['\d]", col) or col.upper() in ("NULL", "TRUE", "FALSE"):
            continue
        # 跳过 AS 别名，提取列名
        col = re.sub(r"\s+AS\s+\w+", "", col, flags=re.IGNORECASE).strip()
        # 提取列名（去掉表名前缀）
        if "." in col:
            col = col.split(".")[-1]
        # 去掉引号
        col = col.strip('"`[]')
        if col and col.isidentifier():
            result.append(col)

    return result


def _check_duplicate_join(sql: str) -> list[str]:
    """检测同一张表被 JOIN 多次的情况（多对多风险）。"""
    issues: list[str] = []

    join_tables = _JOIN_TABLE_PATTERN.findall(sql)
    if not join_tables:
        return issues

    # 统计每张表出现的次数（去掉 schema 前缀）
    table_counts: dict[str, int] = {}
    for t in join_tables:
        tname = t.split(".")[-1].lower()
        table_counts[tname] = table_counts.get(tname, 0) + 1

    for tname, count in table_counts.items():
        if count >= 2:
            issues.append(
                f"表 `{tname}` 被 JOIN 了 {count} 次，可能产生行数膨胀（多对多关系），请确认 JOIN 条件是否正确"
            )

    return issues


def _check_agg_null_handling(sql: str) -> list[str]:
    """检测聚合函数目标字段是否有 NULL 处理。"""
    issues: list[str] = []

    # 查找 AVG/SUM 等聚合函数，检查是否有 COALESCE 或 IS NOT NULL
    agg_pattern = re.compile(r"\b(AVG|SUM)\s*\(\s*(\w+(?:\.\w+)?)\s*\)", re.IGNORECASE)
    for match in agg_pattern.finditer(sql):
        func_name = match.group(1).upper()
        col_name = match.group(2)

        # 检查 SQL 中是否有针对该列的 NULL 处理
        col_base = col_name.split(".")[-1].lower()
        has_null_handling = bool(
            re.search(rf"COALESCE\s*\([^)]*{re.escape(col_base)}", sql, re.IGNORECASE)
            or re.search(rf"{re.escape(col_base)}\s+IS\s+NOT\s+NULL", sql, re.IGNORECASE)
        )

        if not has_null_handling:
            issues.append(f"{func_name}({col_name}) 未做 NULL 处理，NULL 值会被静默忽略，可能导致聚合结果偏低")

    return issues
