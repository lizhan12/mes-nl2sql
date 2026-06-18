"""SQL 专项检测器。

对生成的 SQL 进行静态分析，检测常见错误模式。
用于 CI 门禁和运行时校验，防止静默错误。

三类检测：
  1. 禁止模式（FORBIDDEN）：绝对不允许的 SQL 写法
  2. 警告模式（WARNING）：高风险写法，需人工确认
  3. 语义校验（SEMANTIC）：聚合一致性、JOIN 完整性等业务逻辑检查
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    FORBIDDEN = "forbidden"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ReviewFinding:
    """单条检测结果。"""

    severity: Severity
    rule: str
    message: str
    detail: str = ""


@dataclass
class ReviewResult:
    """SQL 检测结果。"""

    sql: str
    findings: list[ReviewFinding] = field(default_factory=list)

    @property
    def has_forbidden(self) -> bool:
        return any(f.severity == Severity.FORBIDDEN for f in self.findings)

    @property
    def has_warning(self) -> bool:
        return any(f.severity == Severity.WARNING for f in self.findings)

    @property
    def passed(self) -> bool:
        return not self.has_forbidden

    def summary(self) -> str:
        lines = [f"SQL Review: {'FAIL' if self.has_forbidden else 'PASS'} ({len(self.findings)} findings)"]
        for f in self.findings:
            icon = {"forbidden": "X", "warning": "!", "info": "i"}[f.severity.value]
            lines.append(f"  [{icon}] {f.rule}: {f.message}")
            if f.detail:
                lines.append(f"      {f.detail}")
        return "\n".join(lines)


# ---- 禁止模式 ----

FORBIDDEN_PATTERNS: list[tuple[str, str, str]] = [
    (r"SELECT\s+\*", "禁止 SELECT *", "必须显式列出字段，防止字段变更导致静默错误"),
    (r"WHERE\s+1\s*=\s*1", "无效 WHERE 条件", "WHERE 1=1 是占位符，说明条件可能遗漏"),
    (r"\bDROP\b", "禁止 DROP 操作", "查询 SQL 不允许 DDL 操作"),
    (r"\bTRUNCATE\b", "禁止 TRUNCATE 操作", "查询 SQL 不允许 DDL 操作"),
    (r"\bDELETE\s+FROM\b", "禁止 DELETE 操作", "查询 SQL 不允许 DML 写操作"),
    (r"\bUPDATE\b\s+\w+\s+SET\b", "禁止 UPDATE 操作", "查询 SQL 不允许 DML 写操作"),
    (r"\bINSERT\s+INTO\b", "禁止 INSERT 操作", "查询 SQL 不允许 DML 写操作"),
    (r"\bALTER\b", "禁止 ALTER 操作", "查询 SQL 不允许 DDL 操作"),
    (r"\bGRANT\b|\bREVOKE\b", "禁止权限操作", "查询 SQL 不允许权限变更"),
    (
        r'f["\'].*SELECT|f["\'].*INSERT|f["\'].*UPDATE|f["\'].*DELETE',
        "禁止 f-string 拼接 SQL",
        "使用参数化查询防止 SQL 注入",
    ),
    (
        r"\.format\(.*SELECT|\.format\(.*INSERT|\.format\(.*UPDATE",
        "禁止 format() 拼接 SQL",
        "使用参数化查询防止 SQL 注入",
    ),
]

# ---- 警告模式 ----

WARNING_PATTERNS: list[tuple[str, str, str]] = [
    (r"\bCROSS\s+JOIN\b", "CROSS JOIN 笛卡尔积", "检查是否遗漏了 JOIN 条件"),
    (r",\s*\w+\s*\.\s*\w+.*\bFROM\b", "旧式逗号 JOIN", "使用显式 JOIN ... ON 语法，更清晰"),
    (r"\bHAVING\b.*\bWHERE\b", "HAVING 和 WHERE 混用", "WHERE 过滤行，HAVING 过滤组，确认逻辑正确"),
    (r"\bUNION\b(?!.*\bALL\b)", "UNION 去重可能影响性能", "如无需去重，使用 UNION ALL 更高效"),
    (r"\bOR\b(?=.*\bOR\b)", "多 OR 条件", "考虑用 IN 替代，或确认索引覆盖"),
]


def _extract_select_columns(sql: str) -> list[str]:
    """提取 SELECT 和 GROUP BY 之间的列表达式。"""
    match = re.search(r"\bSELECT\b\s+(.*?)\bFROM\b", sql, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    columns_part = match.group(1)
    # 简单分割，不处理嵌套括号内的逗号
    return [col.strip() for col in columns_part.split(",") if col.strip()]


def _extract_group_by_columns(sql: str) -> list[str]:
    """提取 GROUP BY 子句中的列。"""
    match = re.search(r"\bGROUP\s+BY\b\s+(.*?)(?:\bHAVING\b|\bORDER\b|\bLIMIT\b|;|$)", sql, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    return [col.strip() for col in match.group(1).split(",") if col.strip()]


def _has_aggregate(sql: str) -> bool:
    """检查 SQL 是否包含聚合函数。"""
    return bool(re.search(r"\b(SUM|COUNT|AVG|MAX|MIN)\s*\(", sql, re.IGNORECASE))


def _extract_join_conditions(sql: str) -> list[tuple[str, str]]:
    """提取 JOIN 表和 ON 条件。返回 [(表名, ON条件)]。"""
    results: list[tuple[str, str]] = []
    pattern = re.compile(
        r"\b(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\s+(\w+)\s*(?:AS\s+\w+)?\s+ON\s+(.+?)(?=\b(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|;|$)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(sql):
        table = match.group(1)
        on_clause = match.group(2).strip()
        results.append((table, on_clause))
    return results


def check_forbidden_patterns(sql: str) -> list[ReviewFinding]:
    """检测禁止模式。"""
    findings: list[ReviewFinding] = []
    for pattern, rule, detail in FORBIDDEN_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE):
            findings.append(ReviewFinding(Severity.FORBIDDEN, rule, f"匹配模式: {pattern}", detail))
    return findings


def check_warning_patterns(sql: str) -> list[ReviewFinding]:
    """检测警告模式。"""
    findings: list[ReviewFinding] = []
    for pattern, rule, detail in WARNING_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE):
            findings.append(ReviewFinding(Severity.WARNING, rule, f"匹配模式: {pattern}", detail))
    return findings


def check_aggregation_consistency(sql: str) -> list[ReviewFinding]:
    """检查 SELECT 字段和 GROUP BY 字段是否一致。

    规则：如果使用了聚合函数，SELECT 中的非聚合列必须出现在 GROUP BY 中。
    这是防止静默错误的核心检查——聚合不一致会导致结果行数或值错误。
    """
    findings: list[ReviewFinding] = []
    if not _has_aggregate(sql):
        return findings

    select_cols = _extract_select_columns(sql)
    group_by_cols = _extract_group_by_columns(sql)

    if not group_by_cols:
        findings.append(
            ReviewFinding(
                Severity.FORBIDDEN,
                "聚合查询缺少 GROUP BY",
                "使用了聚合函数但未声明 GROUP BY",
                "PostgreSQL 严格模式下会报错，宽松模式下会返回随机分组结果",
            )
        )
        return findings

    # 提取 SELECT 中的非聚合列（简单实现：不含 SUM/COUNT/AVG/MAX/MIN 的列）
    agg_pattern = re.compile(r"\b(SUM|COUNT|AVG|MAX|MIN)\s*\(", re.IGNORECASE)
    non_agg_select_cols: list[str] = []
    for col in select_cols:
        if not agg_pattern.search(col):
            # 提取列名（去除别名）
            col_name = re.sub(r"\s+AS\s+\w+\s*$", "", col, flags=re.IGNORECASE).strip()
            non_agg_select_cols.append(col_name)

    # 标准化 GROUP BY 列名用于比较
    group_by_normalized = {col.lower().strip() for col in group_by_cols}

    for col in non_agg_select_cols:
        col_lower = col.lower().strip()
        # 检查是否在 GROUP BY 中（简单匹配，不处理复杂表达式）
        if col_lower not in group_by_normalized and not any(col_lower.endswith(g) for g in group_by_normalized):
            findings.append(
                ReviewFinding(
                    Severity.WARNING,
                    "聚合不一致",
                    f"SELECT 列 '{col}' 未出现在 GROUP BY 中",
                    "非聚合列必须在 GROUP BY 中声明，否则结果不确定",
                )
            )

    return findings


def check_join_conditions(sql: str) -> list[ReviewFinding]:
    """检查 JOIN 是否有明确 ON 条件。"""
    findings: list[ReviewFinding] = []

    # 检测 JOIN 存在但缺少 ON 的情况
    # 匹配 [LEFT|RIGHT|INNER|FULL] JOIN table [alias] 后面不跟 ON 的模式
    # 排除 CROSS JOIN（CROSS JOIN 本身无 ON 条件，由 warning pattern 检测）
    join_without_on = re.compile(
        r"\b(LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\s+(\w+)\s+(?:AS\s+)?(\w+)?\s*"
        r"(?!\s*ON\s)"
        r"(?=\b(?:LEFT|RIGHT|INNER|FULL|CROSS)?\s*JOIN\b|\bWHERE\b|\bGROUP\b|\bORDER\b|\bLIMIT\b|\bHAVING\b|;|$)",
        re.IGNORECASE,
    )
    for match in join_without_on.finditer(sql):
        join_type = (match.group(1) or "").upper()
        table = match.group(2)
        if join_type == "CROSS":
            continue
        if table.upper() in ("ON", "AND", "WHERE", "LEFT", "RIGHT", "INNER", "FULL", "CROSS"):
            continue
        findings.append(
            ReviewFinding(
                Severity.FORBIDDEN,
                "JOIN 缺少 ON 条件",
                f"表 {table} 的 JOIN 没有 ON 条件",
                "缺少 ON 条件会产生笛卡尔积",
            )
        )

    # 检测有 ON 条件的 JOIN，验证等值比较
    joins = _extract_join_conditions(sql)
    for table, on_clause in joins:
        if "=" not in on_clause:
            findings.append(
                ReviewFinding(
                    Severity.WARNING,
                    "JOIN ON 条件无等值比较",
                    f"表 {table} 的 ON 条件 '{on_clause[:50]}' 无等值比较",
                    "非等值 JOIN 通常性能差且语义不明确",
                )
            )

    return findings


def check_time_range(sql: str) -> list[ReviewFinding]:
    """检查时间范围查询是否有上下界。"""
    findings: list[ReviewFinding] = []

    # 检测时间列上的开放区间
    time_patterns = [
        r"(\w+\.)?(create_time|created_at|update_time|updated_at|date|time|datetime)\s*(>|>=|<|<=)\s*['\"]",
        r"(\w+\.)?(create_time|created_at|update_time|updated_at|date|time|datetime)\s+IS\s+NOT\s+NULL",
    ]

    has_time_filter = any(re.search(p, sql, re.IGNORECASE) for p in time_patterns)
    if not has_time_filter:
        return findings

    # 检查是否有上下界（BETWEEN 或两个比较）
    has_between = bool(re.search(r"\bBETWEEN\b", sql, re.IGNORECASE))
    time_col_refs = re.findall(
        r"(\w+\.)?(create_time|created_at|update_time|updated_at|date|time|datetime)", sql, re.IGNORECASE
    )

    if not has_between and len(time_col_refs) < 2:
        findings.append(
            ReviewFinding(
                Severity.WARNING,
                "时间范围缺少上下界",
                "时间列只有单边条件，缺少上界或下界",
                "开放区间可能导致全表扫描或返回意外的大量数据",
            )
        )

    return findings


def check_limit(sql: str) -> list[ReviewFinding]:
    """检查是否有 LIMIT 约束。"""
    findings: list[ReviewFinding] = []
    if not re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE):
        findings.append(
            ReviewFinding(
                Severity.WARNING,
                "缺少 LIMIT",
                "查询没有 LIMIT 约束",
                "无 LIMIT 可能返回大量数据，影响性能和内存",
            )
        )
    return findings


def review_sql(sql: str, strict: bool = False) -> ReviewResult:
    """对 SQL 执行全套检测。

    Args:
        sql: 待检测的 SQL 语句
        strict: 严格模式下 WARNING 也视为不通过

    Returns:
        ReviewResult 包含所有检测结果
    """
    result = ReviewResult(sql=sql)

    # 1. 禁止模式
    result.findings.extend(check_forbidden_patterns(sql))

    # 2. 警告模式
    result.findings.extend(check_warning_patterns(sql))

    # 3. 聚合一致性
    result.findings.extend(check_aggregation_consistency(sql))

    # 4. JOIN 条件
    result.findings.extend(check_join_conditions(sql))

    # 5. 时间范围
    result.findings.extend(check_time_range(sql))

    # 6. LIMIT
    result.findings.extend(check_limit(sql))

    if strict:
        return ReviewResult(
            sql=sql,
            findings=result.findings,
        )

    return result
