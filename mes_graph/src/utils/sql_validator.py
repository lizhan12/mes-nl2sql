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

    if "LIMIT" not in cleaned.upper():
        cleaned = f"{cleaned}\nLIMIT {default_limit}"

    return {"safe": True, "final_sql": f"{cleaned};", "error": ""}
