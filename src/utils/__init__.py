"""SQL 安全校验 & 工具函数。"""

import re

_THINK_COMPLETE_PATTERN = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_THINK_PARTIAL_PATTERN = re.compile(r"<think>.*$", re.DOTALL)
# Qwen3 某些部署输出的 thinking 只有 </think> 闭标签，无 <think> 开标签，
# 开头以 "Here's a thinking process:" 或直接是分析内容
_THINK_TAIL_PATTERN = re.compile(r"^.*?</think>\s*", re.DOTALL)


def strip_thinking(text: str) -> str:
    """移除 Qwen3 模型的思考内容，只保留最终响应。

    支持三种格式：
    1. <think>...</think> — 标准标签（如 vLLM 部署）
    2. <think>... — 未闭合标签（token 截断）
    3. ...</think> — 只有闭标签，开头为纯文本思考内容（如 LM Studio/ollama 部署）
    """
    text = _THINK_COMPLETE_PATTERN.sub("", text)
    if "<think>" in text:
        text = _THINK_PARTIAL_PATTERN.sub("", text)
    elif "</think>" in text:
        text = _THINK_TAIL_PATTERN.sub("", text, count=1)
    return text.strip()


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
    """校验生成的 SQL，过滤危险操作，自动补 LIMIT。

    Returns:
        {"safe": bool, "final_sql": str, "error": str}
    """
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
