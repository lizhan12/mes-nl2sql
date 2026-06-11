"""SQL 安全校验 — 所有业务 SQL 执行前必须通过此校验。

不依赖 sqlglot 等第三方解析库，仅做最小化安全检查：
1. 只允许 SELECT（拒绝 DROP/INSERT/UPDATE/DELETE/TRUNCATE/ALTER/CREATE/EXEC）
2. 拒绝多语句注入（分号分割）
3. 强制行数上限（无 LIMIT 时自动追加，上限值从配置读取）

用法：
    from src.security.sql_guard import validate_sql

    try:
        safe_sql = validate_sql(raw_sql)
    except SecurityError as e:
        raise HTTPException(400, str(e))
"""

from __future__ import annotations

import logging
import re

from src.core.config import settings

logger = logging.getLogger(__name__)

# 危险关键字（大小写不敏感匹配）
_DANGEROUS_KEYWORDS = (
    "DROP",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "ALTER",
    "CREATE",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "REVOKE",
)


class SecurityError(ValueError):
    """SQL 安全校验失败。"""


def validate_sql(sql: str) -> str:
    """校验并净化 SQL。

    Returns:
        净化后的安全 SQL（可能被追加了 LIMIT）。

    Raises:
        SecurityError: SQL 不安全时抛出。
    """
    if not sql or not sql.strip():
        raise SecurityError("SQL 为空")

    sql = sql.strip()

    # 1. 拒绝多语句注入
    if _has_multiple_statements(sql):
        raise SecurityError("禁止多语句查询")

    # 2. 检查危险关键字（在 SELECT 检查之前，避免 DROP TABLE 等直接命中"只允许 SELECT"）
    sql_upper = sql.upper()
    for keyword in _DANGEROUS_KEYWORDS:
        if _keyword_present(sql_upper, keyword):
            raise SecurityError(f"SQL 包含禁止关键字: {keyword}")

    # 3. 检查是否为 SELECT / WITH 开头
    sql_upper_stripped = sql_upper.lstrip()
    if sql_upper_stripped.startswith("WITH"):
        pass  # CTE 安全
    elif not sql_upper_stripped.startswith("SELECT"):
        raise SecurityError("只允许 SELECT 查询")

    # 4. 强制行数上限
    if "LIMIT" not in sql_upper:
        sql = sql.rstrip(";") + f" LIMIT {settings.sql_max_rows}"
        logger.debug("SQL 自动追加 LIMIT %s", settings.sql_max_rows)

    return sql


def _remove_string_literals(sql: str) -> str:
    """移除 SQL 中的所有字符串字面量（用空格替代）。

    处理三种 PostgreSQL 字符串形式：
    1. 单引号字符串（含转义单引号 '' 的处理）
    2. 美元引号字符串 $$...$$ 和 $tag$...$tag$
    3. SQL 注释（行注释 -- 和块注释 /* */）
    """
    # 移除美元引号字符串（$tag$...$tag$ 或 $$...$$）
    cleaned = re.sub(r"\$[a-zA-Z_]*\$.*?\$[a-zA-Z_]*\$", " ", sql, flags=re.DOTALL)
    # 移除单引号字符串（处理两个连续单引号作为转义）
    cleaned = re.sub(r"'(?:[^']|'')*'", " ", cleaned)
    # 移除双引号标识符
    cleaned = re.sub(r'"(?:[^"]|"")*"', " ", cleaned)
    # 移除 SQL 注释
    cleaned = re.sub(r"--[^\n]*", " ", cleaned)  # 行注释
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)  # 块注释
    return cleaned


def _has_multiple_statements(sql: str) -> bool:
    """检查是否包含多语句（分号分割）。

    通过移除字符串字面量和注释后检查剩余部分是否包含 ; 来避免误判。
    容错尾部可选分号。
    """
    cleaned = _remove_string_literals(sql).rstrip(";").strip()
    return ";" in cleaned


def _keyword_present(sql_upper: str, keyword: str) -> bool:
    """检查 SQL 中是否包含完整的关键字（独立单词，非子串匹配）。

    例如: "DROP" 不匹配 "DROPPED"，但匹配 "DROP TABLE"。
    """
    cleaned = _remove_string_literals(sql_upper)
    return bool(re.search(rf"\b{keyword}\b", cleaned))
