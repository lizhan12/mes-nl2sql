"""动态 DDL 渲染器。

将知识库 chunk 文本渲染为不同的格式输出，适配不同 LLM 模型对 DDL 的偏好。

支持的格式：
  - compact: 当前默认的紧凑文本格式
  - sql_ddl: 标准 SQL CREATE TABLE DDL 格式
  - markdown_table: Markdown 表格格式

配置入口：环境变量 DDL_FORMAT，默认 "compact"
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

_DDL_FORMAT = os.getenv("DDL_FORMAT", "compact")


def render_ddl(schema_context: str, fmt: str = "") -> str:
    """将 schema_context 渲染为指定格式。

    Args:
        schema_context: "\n\n" 分隔的多个 chunk 文本
        fmt: 输出格式，为空时使用 DDL_FORMAT 环境变量

    Returns:
        渲染后的 schema 文本
    """
    if not fmt:
        fmt = _DDL_FORMAT

    renderer = _ddl_renderers.get(fmt)
    if not renderer:
        renderer = _render_compact  # 未知格式回退 compact
        logger.warning("未知 DDL 格式 '%s'，回退到 compact", fmt)

    chunks = schema_context.split("\n\n") if schema_context else []
    rendered = [renderer(chunk) for chunk in chunks]
    return "\n\n".join(rendered)


# ── 格式渲染器 ──


def _parse_field_line(line: str) -> tuple[str, str, str]:
    """解析字段行，支持嵌套括号类型如 varchar(40)。

    格式：  name (type) -- comment  或  name (type)

    Returns:
        (name, type, comment) — 无法解析时返回 ("", "", "")
    """
    line = line.strip()
    # 按 ' -- ' 分割注释部分
    field_part = line
    comment = ""
    if " -- " in line:
        idx = line.index(" -- ")
        field_part = line[:idx].strip()
        comment = line[idx + len(" -- ") :].strip()

    # 解析 name (type) — 从右找最后一个 )，向前匹配第一个 (
    idx_r = field_part.rfind(")")
    if idx_r == -1:
        m = re.match(r"(\w+)\s*$", field_part)
        return (m.group(1), "", "") if m else ("", "", "")
    idx_l = field_part.find("(")
    if idx_l == -1:
        m = re.match(r"(\w+)\s*$", field_part)
        return (m.group(1), "", "") if m else ("", "", "")

    name = field_part[:idx_l].strip()
    ftype = field_part[idx_l + 1 : idx_r].strip()
    return name, ftype, comment


def _render_compact(chunk: str) -> str:
    """紧凑文本格式（当前默认格式）。

    示例：
        表名：t_pd_wo
        模块：生产执行
        业务含义：工单表
        关键字段：
          work_order (varchar(40)) -- 工单号
    """
    return chunk


def _render_sql_ddl(chunk: str) -> str:
    """标准 SQL DDL 格式。

    示例：
        -- 生产执行：工单表
        CREATE TABLE t_pd_wo (
          work_order VARCHAR(40)  PRIMARY KEY COMMENT '工单号',
          part_id    VARCHAR(40)             COMMENT '料号'
        );
    """
    table_name = ""
    module = ""
    meaning = ""
    fields: list[tuple[str, str, str, bool]] = []  # (name, type, comment, is_pk)

    in_fields = False
    for line in chunk.split("\n"):
        if line.startswith("表名："):
            table_name = line[len("表名：") :].strip()
        elif line.startswith("模块："):
            module = line[len("模块：") :].strip()
        elif line.startswith("业务含义："):
            meaning = line[len("业务含义：") :].strip()
        elif line.startswith("关键字段："):
            in_fields = True
        elif in_fields and line.startswith("  "):
            # 格式：  name (type) -- comment  或  name (type)
            name, ftype, comment = _parse_field_line(line)
            if name:
                is_pk = name.endswith("_id") or name == "id" or "主键" in comment
                fields.append((name, ftype, comment, is_pk))

    if not table_name or not fields:
        return chunk  # 无法解析则回退原格式

    header = f"-- {module}: {meaning}" if module or meaning else f"-- 表 {table_name}"
    lines = [header, f"CREATE TABLE {table_name} ("]

    for i, (name, ftype, comment, is_pk) in enumerate(fields):
        pk_str = " PRIMARY KEY" if is_pk else ""
        comment_str = f" COMMENT '{comment}'" if comment else ""
        comma = "," if i < len(fields) - 1 else ""
        lines.append(f"  {name} {ftype}{pk_str}{comment_str}{comma}")

    lines.append(");")
    return "\n".join(lines)


def _render_md_table(chunk: str) -> str:
    """Markdown 表格格式。

    示例：
        **表 t_pd_wo** — 生产执行：工单表

        | 字段 | 类型 | 主键 | 说明 |
        |------|------|------|------|
        | work_order | VARCHAR(40) | PK | 工单号 |
        | part_id | VARCHAR(40) | | 料号 |
    """
    table_name = ""
    module = ""
    meaning = ""
    fields: list[tuple[str, str, str, bool]] = []

    in_fields = False
    for line in chunk.split("\n"):
        if line.startswith("表名："):
            table_name = line[len("表名：") :].strip()
        elif line.startswith("模块："):
            module = line[len("模块：") :].strip()
        elif line.startswith("业务含义："):
            meaning = line[len("业务含义：") :].strip()
        elif line.startswith("关键字段："):
            in_fields = True
        elif in_fields and line.startswith("  "):
            name, ftype, comment = _parse_field_line(line)
            if name:
                is_pk = name.endswith("_id") or name == "id" or "主键" in comment
                fields.append((name, ftype, comment, is_pk))

    if not table_name or not fields:
        return chunk

    desc = f"{module}: {meaning}" if module or meaning else ""
    lines = [f"**表 {table_name}** — {desc}", "", "| 字段 | 类型 | 主键 | 说明 |", "|------|------|------|------|"]
    for name, ftype, comment, is_pk in fields:
        pk_col = "PK" if is_pk else ""
        lines.append(f"| {name} | {ftype} | {pk_col} | {comment} |")
    return "\n".join(lines)


_ddl_renderers: dict[str, object] = {
    "compact": _render_compact,
    "sql_ddl": _render_sql_ddl,
    "markdown_table": _render_md_table,
}
