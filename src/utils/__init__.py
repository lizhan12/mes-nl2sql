"""SQL 安全校验。"""

import re

from src.core.config import settings

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


def validate_sql(sql: str, default_limit: int | None = None) -> dict:
    """校验生成的 SQL，过滤危险操作，自动补 LIMIT。

    Returns:
        {"safe": bool, "final_sql": str, "error": str}
    """
    if default_limit is None:
        default_limit = settings.default_limit
    sql_upper = sql.upper().strip()

    # 1. 危险操作黑名单
    for kw in _DANGEROUS_KEYWORDS:
        if re.search(r"\b" + kw + r"\b", sql_upper):
            return {"safe": False, "final_sql": "", "error": f"包含禁止操作: {kw}"}

    # 2. 清理 markdown 代码块格式
    cleaned = re.sub(r"```sql|```", "", sql).strip().rstrip(";")

    # 3. 强制加 LIMIT
    if "LIMIT" not in cleaned.upper():
        cleaned = f"{cleaned}\nLIMIT {default_limit}"

    return {"safe": True, "final_sql": f"{cleaned};", "error": ""}
