"""SQL 组装器。

根据指标 ID 和提取的参数，使用参数化查询拼接安全的可执行 SQL。
只修改 WHERE 子句，不修改视图本身的 SELECT 逻辑。
"""

from __future__ import annotations

import logging
import re

from src.core.config import settings
from src.services.metric_registry import get_metric

logger = logging.getLogger(__name__)

# 视图名和列名的合法格式：字母/数字/下划线/中文（中文列别名）
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\u4e00-\u9fff]+$")


class AssembleError(ValueError):
    """SQL 组装错误。"""


def _validate_identifier(name: str, label: str) -> None:
    """校验标识符（表名/列名）是否为安全格式。"""
    if not name or not _SAFE_NAME_RE.match(name):
        raise AssembleError(f"{label}包含非法字符: {name!r}")


def assemble_sql(metric_id: str, params: dict[str, str], limit: int | None = None) -> tuple[str, list]:
    """根据指标 ID 和参数组装参数化 SQL。

    Args:
        metric_id: 指标 ID（如 M004）
        params: 提取的参数 {param_name: value}
        limit: 返回行数限制，默认从配置文件的 default_limit 读取

    Returns:
        (参数化 SQL 字符串, 参数列表)  — 使用 %s 占位符
    """
    if limit is None:
        limit = settings.default_limit
    metric = get_metric(metric_id)
    if not metric:
        raise AssembleError(f"未知指标: {metric_id}")

    view_name = metric.view_name
    _validate_identifier(view_name, "视图名")

    where_clauses: list[str] = []
    param_values: list = []

    for pdef in metric.params:
        value = params.get(pdef.name)
        if not value:
            continue
        clause, clause_params = _build_where_clause(pdef, value)
        if clause:
            where_clauses.append(clause)
            param_values.extend(clause_params)

    sql = f"SELECT * FROM {view_name}"
    if where_clauses:
        sql += "\nWHERE " + "\n  AND ".join(where_clauses)
    sql += f"\nLIMIT {int(limit)}"

    return sql, param_values


def _build_where_clause(pdef, value: str) -> tuple[str, list]:
    """根据参数定义和值构建参数化 WHERE 条件。

    Returns:
        (参数化子句, 参数值列表)
    """
    col = pdef.column
    _validate_identifier(col, "列名")

    if pdef.type == "time":
        if " TO " in value:
            parts = value.split(" TO ")
            return f"{col} >= %s AND {col} <= %s", [parts[0].strip(), parts[1].strip()]
        return f"{col} >= %s", [value.strip()]

    if pdef.match == "ILIKE":
        # 转义 LIKE 通配符，防止用户输入 % 或 _ 被当作通配符
        escaped_like = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"{col} ILIKE %s", [f"%{escaped_like}%"]

    # 默认 =，转义反斜杠
    escaped = value.replace("\\", "\\\\")
    return f"{col} = %s", [escaped]


def build_explain(metric_id: str, params: dict[str, str]) -> str:
    """生成可读的查询说明文本。"""
    metric = get_metric(metric_id)
    if not metric:
        return f"查询指标 {metric_id}"

    parts = [f"指标: {metric.name} ({metric_id})"]
    if params:
        parts.append(f"条件: {', '.join(f'{k}={v}' for k, v in params.items())}")
    if metric.note:
        parts.append(f"\u26a0\ufe0f 注意: {metric.note}")
    return "\n".join(parts)
