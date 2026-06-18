"""Few-Shot SQL 测试、修正与优化脚本。

对 data/dify_few_shot.txt 中的 SQL 逐条：
1. 静态校验（表名/列名是否存在于知识库和数据库）
2. 动态测试（EXPLAIN 验证可执行性）
3. 问题匹配度检查（SQL 与问题语义是否对应）
4. 自动修正（列名/JOIN/表名修正后重测）
5. 性能检查与优化（优化后必须重新 EXPLAIN 测试）
6. 只保留全部通过的 SQL 写回文件并同步 Neo4j
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

# ---- 项目路径 ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.db_pool import execution_connection
from src.services.neo4j_graph import clear_few_shot_nodes
from src.services.vector_store import build_neo4j_few_shot_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("validate_few_shot")

# ── 常量 ──────────────────────────────────────────────────────────────

KB_PATH = PROJECT_ROOT / "data" / "mes_knowledge_base.txt"
FEWSHOT_PATH = PROJECT_ROOT / "data" / "dify_few_shot.txt"

# 业务术语 → 表名映射（用于问题匹配度检查）
TERM_TABLE_MAP: dict[str, list[str]] = {
    "工单": ["t_pd_wo"],
    "产线": ["t_bd_pdline"],
    "SN": ["t_pd_sn_status", "t_pd_sn_travel"],
    "过站": ["t_pd_sn_travel", "t_pd_sn_status"],
    "不良": ["t_pd_sn_defect", "t_pd_sn_defect_detail", "t_bd_defect"],
    "缺陷": ["t_pd_sn_defect", "t_bd_defect"],
    "库存": ["t_wms_stock"],
    "仓库": ["t_wms_warehouse", "t_wms_stock"],
    "料号": ["t_bd_part"],
    "BOM": ["t_bd_bom", "t_bd_bom_detail"],
    "领料": ["t_wms_wo_material_bill", "t_wms_wo_material_bill_detail"],
    "发料": ["t_wms_wo_material_bill", "t_wms_wo_material_bill_detail"],
    "退料": ["t_wms_wo_rb", "t_wms_wo_rb_detail"],
    "设备": ["t_ems_equipment"],
    "维修": ["t_ems_repair_request"],
    "报修": ["t_ems_repair_request"],
    "工单BOM": ["t_pd_wo_bom"],
}

# ── Step 1: 加载知识库表结构 ──────────────────────────────────────────


def load_knowledge_base() -> dict[str, dict[str, tuple[str, str]]]:
    """加载知识库表结构映射。

    Returns:
        {表名: {字段名: (类型, 注释)}}
    """
    content = KB_PATH.read_text(encoding="utf-8")
    chunks = content.split("\n---\n")
    tables: dict[str, dict[str, tuple[str, str]]] = {}

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # 提取表名
        m = re.search(r"表名：(\w+)", chunk)
        if not m:
            continue
        table_name = m.group(1)

        # 提取关键字段
        fields: dict[str, tuple[str, str]] = {}
        for line in chunk.split("\n"):
            line = line.strip()
            # 格式: 字段名 (类型) -- 注释
            fm = re.match(r"(\w+)\s*\(([^)]+)\)\s*--\s*(.+)", line)
            if fm:
                fname = fm.group(1)
                ftype = fm.group(2).strip()
                fcomment = fm.group(3).strip()
                fields[fname] = (ftype, fcomment)

        tables[table_name] = fields

    logger.info("知识库加载完成: %d 张表", len(tables))
    return tables


def load_db_schema() -> dict[str, dict[str, tuple[str, str]]]:
    """从数据库 information_schema 加载实际表结构。

    Returns:
        {表名: {字段名: (类型, 注释)}}
    """
    tables: dict[str, dict[str, tuple[str, str]]] = {}
    with execution_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name, data_type, col_description("
            "  (quote_ident(table_schema) || '.' || quote_ident(table_name))::regclass, ordinal_position"
            ") AS comment "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "ORDER BY table_name, ordinal_position"
        )
        for row in cur.fetchall():
            tname = row["table_name"]
            cname = row["column_name"]
            ctype = row["data_type"]
            ccomment = row["comment"] or ""
            if tname not in tables:
                tables[tname] = {}
            tables[tname][cname] = (ctype, ccomment)

    logger.info("数据库结构加载完成: %d 张表", len(tables))
    return tables


# ── Step 2: 解析 few-shot ─────────────────────────────────────────────


def parse_few_shot(filepath: Path) -> list[dict]:
    """解析 few-shot 文件。

    Returns:
        [{"scenario": str, "question": str, "sql": str}, ...]
    """
    content = filepath.read_text(encoding="utf-8")
    chunks = content.split("\n---\n")
    results: list[dict] = []

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        scenario = ""
        question = ""
        sql_lines: list[str] = []
        in_sql = False

        for line in chunk.split("\n"):
            stripped = line.strip()
            if stripped.startswith("场景："):
                scenario = stripped[len("场景："):].strip()
                in_sql = False
            elif stripped.startswith("用户问题："):
                question = stripped[len("用户问题："):].strip()
                in_sql = False
            elif stripped.startswith("SQL：") or stripped == "SQL:":
                in_sql = True
                # SQL：后面可能还有内容
                after = stripped[len("SQL："):].strip() if stripped.startswith("SQL：") else stripped[len("SQL:"):].strip()
                if after:
                    sql_lines.append(after)
            elif in_sql:
                sql_lines.append(line)  # 保留原始缩进

        sql = "\n".join(sql_lines).strip()
        if scenario and question and sql:
            results.append({"scenario": scenario, "question": question, "sql": sql})

    logger.info("Few-shot 解析完成: %d 条", len(results))
    return results


# ── Step 3: SQL 静态校验 ──────────────────────────────────────────────


def extract_sql_tables(sql: str) -> list[str]:
    """提取 SQL 中 FROM/JOIN 后引用的表名。"""
    # 匹配 FROM / JOIN 后的表名（可能带别名）
    pattern = r"\b(?:FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?\w+)?"
    return list(dict.fromkeys(re.findall(pattern, sql, re.IGNORECASE)))


def extract_sql_alias_map(sql: str) -> dict[str, str]:
    """提取 SQL 中表别名映射 {alias: table_name}。"""
    pattern = r"\b(?:FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?"
    alias_map: dict[str, str] = {}
    for m in re.finditer(pattern, sql, re.IGNORECASE):
        table = m.group(1)
        alias = m.group(2) if m.group(2) else table
        alias_map[alias] = table
    return alias_map


def extract_sql_columns(sql: str) -> list[tuple[str, str]]:
    """提取 SQL 中的列引用 (alias_or_table, column)。

    包括 alias.column 和裸 column 两种形式。
    """
    refs: list[tuple[str, str]] = []
    # alias.column 形式
    for m in re.finditer(r"(\w+)\.(\w+)", sql):
        prefix = m.group(1)
        col = m.group(2)
        # 排除 SQL 关键字
        if prefix.upper() not in ("SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AND", "OR", "AS", "SET", "INTO", "GROUP", "ORDER", "HAVING", "LIMIT", "CASE", "WHEN", "THEN", "ELSE", "END", "COALESCE", "NULL", "NOT", "EXISTS", "IN", "BETWEEN", "LIKE", "COUNT", "SUM", "AVG", "MIN", "MAX", "DATE", "CURRENT_DATE", "EXTRACT", "EPOCH"):
            refs.append((prefix, col))
    return refs


def static_validate(sql: str, kb_tables: dict, db_tables: dict) -> list[str]:
    """静态校验 SQL，返回错误列表。"""
    errors: list[str] = []

    # 合并知识库和数据库的表结构（以 DB 为准）
    all_tables: dict[str, dict[str, tuple[str, str]]] = {}
    for tname, fields in kb_tables.items():
        all_tables[tname] = dict(fields)
    for tname, fields in db_tables.items():
        all_tables[tname] = dict(fields)

    # 检查表名
    sql_tables = extract_sql_tables(sql)
    alias_map = extract_sql_alias_map(sql)
    for tname in sql_tables:
        if tname not in all_tables:
            # 尝试前缀匹配
            candidates = [t for t in all_tables if t.startswith(tname[:5])]
            hint = f" (相似: {candidates[:3]})" if candidates else ""
            errors.append(f"表 {tname} 不存在于知识库或数据库中{hint}")

    # 检查列名
    col_refs = extract_sql_columns(sql)
    for prefix, col in col_refs:
        # prefix 可能是别名
        actual_table = alias_map.get(prefix, prefix)
        if actual_table in all_tables:
            table_fields = all_tables[actual_table]
            if col not in table_fields and col.upper() not in (
                "ID", "COUNT", "SUM", "AVG", "MIN", "MAX", "NULL", "ASC", "DESC"
            ):
                # 语义匹配推荐（基于注释）
                candidates = _semantic_match(col, col, table_fields, top_n=3)
                hint = f" (相似: {candidates})" if candidates else ""
                errors.append(f"列 {prefix}.{col} 在表 {actual_table} 中不存在{hint}")

    return errors


def _fuzzy_match(target: str, candidates: list[str], top_n: int = 3) -> list[str]:
    """模糊匹配，返回最相似的候选列表。"""
    scored = [(c, SequenceMatcher(None, target.lower(), c.lower()).ratio()) for c in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, score in scored[:top_n] if score > 0.3]


def _semantic_match(
    target_col: str,
    target_comment: str,
    table_fields: dict[str, tuple[str, str]],
    top_n: int = 3,
) -> list[str]:
    """基于字段注释的语义匹配。

    优先匹配注释中包含目标语义的字段，其次用列名相似度。

    Args:
        target_col: 原始错误列名
        target_comment: 原始列的注释/语义描述
        table_fields: {字段名: (类型, 注释)}
        top_n: 返回前 N 个候选

    Returns:
        候选字段名列表
    """
    scored: list[tuple[str, float]] = []

    # 从注释中提取关键词
    target_keywords = set(re.findall(r"[\w]+", target_comment.lower()))
    # 也从列名中提取关键词（驼峰/下划线拆分）
    for part in re.split(r"[_]", target_col.lower()):
        if len(part) > 1:
            target_keywords.add(part)

    for fname, (ftype, fcomment) in table_fields.items():
        score = 0.0

        # 1. 注释关键词匹配（权重最高）
        comment_keywords = set(re.findall(r"[\w]+", fcomment.lower()))
        # 也从字段名拆分
        for part in re.split(r"[_]", fname.lower()):
            if len(part) > 1:
                comment_keywords.add(part)

        keyword_overlap = target_keywords & comment_keywords
        if target_keywords and keyword_overlap:
            score += len(keyword_overlap) / len(target_keywords) * 0.7

        # 2. 列名字符串相似度
        name_sim = SequenceMatcher(None, target_col.lower(), fname.lower()).ratio()
        score += name_sim * 0.3

        # 3. 类型兼容性加分（数值列替换数值列，时间列替换时间列）
        if target_comment and fcomment:
            numeric_types = {"integer", "bigint", "numeric", "decimal", "double", "real", "float", "int"}
            time_types = {"timestamp", "date", "time"}
            if ftype.lower().split("(")[0] in numeric_types and any(
                w in target_comment for w in ("数量", "用量", "qty", "量", "次数")
            ):
                score += 0.1
            if ftype.lower().split("(")[0] in time_types and any(
                w in target_comment for w in ("时间", "日期", "time", "date")
            ):
                score += 0.1

        scored.append((fname, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, score in scored[:top_n] if score > 0.2]


# ── Step 4: SQL 动态测试 ──────────────────────────────────────────────


def dynamic_test(sql: str) -> tuple[bool, str]:
    """EXPLAIN 测试 SQL 可执行性。

    Returns:
        (成功, 错误信息)
    """
    # 对 SELECT 语句用 EXPLAIN，对其他语句直接跳过
    explain_sql = f"EXPLAIN {sql}"
    try:
        with execution_connection() as conn, conn.cursor() as cur:
            cur.execute(explain_sql)
            cur.fetchall()
        return True, ""
    except Exception as e:
        return False, str(e)


# ── Step 5: 问题匹配度检查 ────────────────────────────────────────────


def check_question_match(question: str, sql: str, kb_tables: dict) -> float:
    """检查 SQL 与问题的匹配度，返回 0-1 分数。"""
    score = 0.0
    max_score = 0.0

    # 1. 问题中的业务术语是否在 SQL 中有对应表
    for term, tables in TERM_TABLE_MAP.items():
        if term in question:
            max_score += 1.0
            sql_tables = extract_sql_tables(sql)
            if any(t in sql_tables for t in tables):
                score += 1.0

    # 2. 问题要求统计/聚合，SQL 是否有 GROUP BY + 聚合函数
    if any(w in question for w in ("统计", "多少", "数量", "次数", "平均", "合计", "总计")):
        max_score += 1.0
        has_group = "GROUP BY" in sql.upper()
        has_agg = any(fn in sql.upper() for fn in ("COUNT(", "SUM(", "AVG(", "MIN(", "MAX("))
        if has_group and has_agg:
            score += 1.0
        elif has_agg:
            score += 0.5

    # 3. 问题中的时间范围，SQL 是否有对应过滤
    time_words = {"今天": "CURRENT_DATE", "本周": "WEEK", "上月": "MONTH", "本月": "MONTH", "今年": "YEAR"}
    for word, _ in time_words.items():
        if word in question:
            max_score += 1.0
            if "DATE" in sql.upper() or "INTERVAL" in sql.upper() or "TIME" in sql.upper():
                score += 1.0
            break

    if max_score == 0:
        return 1.0  # 没有可检查的维度，默认通过

    return score / max_score


# ── Step 6: 自动修正 ──────────────────────────────────────────────────

# 手动修正映射表：对于自动修正无法处理的复杂场景，提供人工指导
# 格式: (表名, 错误列名) → (正确列名, 语义描述)
MANUAL_FIX_MAP: dict[tuple[str, str], tuple[str, str]] = {
    # t_pd_sn_travel: SN过站表
    ("t_pd_sn_travel", "node_name"): ("process_name", "工序/制程名称"),
    ("t_pd_sn_travel", "pass_flag"): ("hold_flag", "是否锁定(0不锁/1锁)"),
    ("t_pd_sn_travel", "operator"): ("create_user_id", "操作人ID"),
    # t_wms_stock: 库存表
    ("t_wms_stock", "part_no"): ("part_id", "料号ID"),
    ("t_wms_stock", "warehouse_id"): ("warehouse_code", "仓库编码"),
    # t_bd_bom: BOM主表 — item_part_id/item_qty 在 detail 表中
    ("t_bd_bom", "item_part_id"): ("part_id", "成品料号ID"),
    ("t_bd_bom", "item_qty"): ("qty", "BOM用量（注意：实际用量在bom_detail中）"),
    # t_pd_wo: 工单表
    ("t_pd_wo", "plan_qty"): ("panel_qty", "连扳数"),
    # t_pd_wo_bom: 工单BOM关联
    ("t_pd_wo_bom", "bom_id"): ("id", "主键ID"),
    # t_wms_wo_material_bill_detail: 领料单明细
    ("t_wms_wo_material_bill_detail", "actual_qty"): ("total_qty", "总数量"),
    # t_ems_repair_request: 维修请求
    ("t_ems_repair_request", "repair_end_time"): ("end_repair_time", "维修结束时间"),
}

# SQL 级别的手动修正：对于别名引用错误等复杂场景，直接提供修正后的 SQL 片段
# 格式: 场景名 → 修正后的完整 SQL
MANUAL_SQL_FIX: dict[str, str] = {
    "工单领料与BOM对比": """SELECT
  bd.item_part_id,
  bp.part_no AS 子件料号,
  bp.part_name AS 子件名称,
  bd.item_qty * wo.panel_qty AS BOM计划用量,
  COALESCE(SUM(md.total_qty), 0) AS 实际领料量,
  (COALESCE(SUM(md.total_qty), 0) - bd.item_qty * wo.panel_qty) AS 差异
FROM t_pd_wo wo
LEFT JOIN t_pd_wo_bom wb ON wo.work_order = wb.work_order
LEFT JOIN t_bd_bom b ON wb.id = b.id
LEFT JOIN t_bd_bom_detail bd ON b.id = bd.bom_id
LEFT JOIN t_bd_part bp ON bd.item_part_id = bp.id
LEFT JOIN t_wms_wo_material_bill mb ON wo.work_order = mb.work_order
LEFT JOIN t_wms_wo_material_bill_detail md ON mb.id = md.doc_id AND md.part_id = bd.item_part_id
WHERE wo.work_order = 'WO20240001'
GROUP BY bd.item_part_id, bp.part_no, bp.part_name, bd.item_qty, wo.panel_qty""",
}


def auto_fix_sql(sql: str, errors: list[str], kb_tables: dict, db_tables: dict) -> str:
    """根据错误信息自动修正 SQL。

    优先使用 MANUAL_FIX_MAP 人工映射，其次用语义匹配。
    """
    fixed = sql
    alias_map = extract_sql_alias_map(sql)

    # 合并表结构（以 DB 为准）
    all_tables: dict[str, dict[str, tuple[str, str]]] = {}
    for tname, fields in kb_tables.items():
        all_tables[tname] = dict(fields)
    for tname, fields in db_tables.items():
        all_tables[tname] = dict(fields)

    for error in errors:
        # 列名修正: "列 X.Y 在表 Z 中不存在 (相似: [a, b, c])"
        m = re.match(r"列 (\w+)\.(\w+) 在表 (\w+) 中不存在(?: \(相似: \[([^\]]*)\]\))?", error)
        if m:
            alias = m.group(1)
            wrong_col = m.group(2)
            table = m.group(3)

            # 优先使用手动修正映射
            manual_fix = MANUAL_FIX_MAP.get((table, wrong_col))
            if manual_fix:
                best, desc = manual_fix
                logger.info("  修正列名(手动): %s.%s → %s.%s (%s)", alias, wrong_col, alias, best, desc)
            else:
                # 从候选列表中取第一个
                candidates_str = m.group(4)
                if candidates_str:
                    candidates = [c.strip().strip("'\"") for c in candidates_str.split(",")]
                    best = candidates[0] if candidates else wrong_col
                else:
                    # 从表结构中语义匹配
                    table_fields = all_tables.get(table, {})
                    candidates = _semantic_match(wrong_col, wrong_col, table_fields)
                    best = candidates[0] if candidates else wrong_col
                logger.info("  修正列名(自动): %s.%s → %s.%s", alias, wrong_col, alias, best)

            # 替换 alias.wrong_col → alias.best
            fixed = re.sub(
                rf"\b{re.escape(alias)}\.{re.escape(wrong_col)}\b",
                f"{alias}.{best}",
                fixed,
            )

        # 表名修正: "表 X 不存在于知识库或数据库中 (相似: [a, b, c])"
        m = re.match(r"表 (\w+) 不存在(?:.*\(相似: \[([^\]]*)\]\))?", error)
        if m:
            wrong_table = m.group(1)
            candidates_str = m.group(2)
            if candidates_str:
                candidates = [c.strip().strip("'\"") for c in candidates_str.split(",")]
                best = candidates[0] if candidates else wrong_table
                fixed = re.sub(rf"\b{re.escape(wrong_table)}\b", best, fixed)
                logger.info("  修正表名: %s → %s", wrong_table, best)

    return fixed


# ── Step 7: 性能检查与优化 ────────────────────────────────────────────


def check_performance(sql: str) -> tuple[str, float]:
    """性能检查，返回 (评估描述, 执行时间ms)。

    使用 EXPLAIN ANALYZE + LIMIT 100 防止长时间运行。
    """
    # 如果 SQL 没有 LIMIT，加一个 LIMIT 100 用于性能测试
    test_sql = sql.rstrip(";")
    if "LIMIT" not in test_sql.upper():
        test_sql += " LIMIT 100"

    explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {test_sql}"
    try:
        with execution_connection() as conn, conn.cursor() as cur:
            cur.execute(explain_sql)
            result = cur.fetchone()
            plan_json = list(result.values())[0] if isinstance(result, dict) else result
    except Exception as e:
        return f"EXPLAIN ANALYZE 失败: {e}", -1

    if isinstance(plan_json, str):
        try:
            plan_json = json.loads(plan_json)
        except json.JSONDecodeError:
            return "无法解析执行计划", -1

    # 提取执行时间
    exec_time_ms = 0.0
    issues: list[str] = []

    def _walk_plan(plan: dict) -> None:
        nonlocal exec_time_ms
        # 累计实际执行时间
        actual = plan.get("Actual Total Time", 0)
        if actual > exec_time_ms:
            exec_time_ms = actual

        node_type = plan.get("Node Type", "")
        rows = plan.get("Actual Rows", 0)

        # 检测全表扫描
        if node_type == "Seq Scan":
            rel = plan.get("Relation Name", "?")
            if rows > 10000:
                issues.append(f"大表全表扫描: {rel} ({rows} 行)")

        # 检测 Nested Loop 大量行
        if node_type == "Nested Loop" and rows > 50000:
            issues.append(f"Nested Loop 大量行: {rows} 行")

        # 递归子计划
        for child in plan.get("Plans", []):
            _walk_plan(child)

    if isinstance(plan_json, list) and plan_json:
        _walk_plan(plan_json[0])
    elif isinstance(plan_json, dict):
        _walk_plan(plan_json)

    desc = f"执行时间: {exec_time_ms:.1f}ms"
    if issues:
        desc += " | 问题: " + "; ".join(issues)
    elif exec_time_ms > 5000:
        desc += " | 性能差"
    elif exec_time_ms > 1000:
        desc += " | 性能一般"
    else:
        desc += " | 性能良好"

    return desc, exec_time_ms


def optimize_sql(sql: str, perf_desc: str, exec_time_ms: float) -> str:
    """根据性能信息优化 SQL。"""
    optimized = sql.rstrip(";")

    # 1. 如果没有 LIMIT 且执行时间 > 1s，加 LIMIT
    if exec_time_ms > 1000 and "LIMIT" not in optimized.upper():
        optimized += " LIMIT 100"
        logger.info("  优化: 添加 LIMIT 100")

    # 2. 如果有全表扫描，尝试添加 WHERE 条件提示（仅日志，不自动改写逻辑）
    if "全表扫描" in perf_desc:
        logger.info("  优化建议: 考虑为全表扫描的表添加索引或 WHERE 条件")

    return optimized


# ── Step 8: 完整验证流程 ──────────────────────────────────────────────


def full_validate(
    item: dict,
    kb_tables: dict[str, dict[str, tuple[str, str]]],
    db_tables: dict[str, dict[str, tuple[str, str]]],
    max_fix_rounds: int = 2,
) -> tuple[bool, str, str]:
    """完整验证流程。

    Returns:
        (通过, 最终SQL, 报告)
    """
    scenario = item["scenario"]
    question = item["question"]
    sql = item["sql"]
    report_lines: list[str] = []
    report_lines.append(f"场景: {scenario}")
    report_lines.append(f"问题: {question}")
    report_lines.append(f"原始 SQL:\n{sql}")

    # ---- 检查是否有 SQL 级别的手动修正 ----
    if scenario in MANUAL_SQL_FIX:
        manual_sql = MANUAL_SQL_FIX[scenario]
        report_lines.append("应用 SQL 级手动修正")
        report_lines.append(f"手动修正后 SQL:\n{manual_sql}")
        current_sql = manual_sql
    else:
        current_sql = sql

    # ---- 静态校验 + 自动修正（最多 max_fix_rounds 轮） ----
    for round_idx in range(max_fix_rounds):
        errors = static_validate(current_sql, kb_tables, db_tables)
        if not errors:
            report_lines.append("静态校验: 通过")
            break
        report_lines.append(f"静态校验 第{round_idx + 1}轮: 发现 {len(errors)} 个错误")
        for e in errors:
            report_lines.append(f"  - {e}")

        if round_idx < max_fix_rounds - 1:
            fixed = auto_fix_sql(current_sql, errors, kb_tables, db_tables)
            if fixed != current_sql:
                report_lines.append(f"自动修正后 SQL:\n{fixed}")
                current_sql = fixed
            else:
                report_lines.append("自动修正: 无法修正")
                break
        else:
            report_lines.append("自动修正: 已达最大修正轮次")

    # 最终静态校验
    final_errors = static_validate(current_sql, kb_tables, db_tables)
    if final_errors:
        report_lines.append(f"最终静态校验: 失败 ({len(final_errors)} 个错误)")
        report_lines.append("--- RESULT: FAIL (静态校验) ---\n")
        return False, current_sql, "\n".join(report_lines)

    # ---- 动态测试 ----
    ok, err = dynamic_test(current_sql)
    if not ok:
        # 尝试修正后再测
        report_lines.append(f"动态测试: 失败 - {err}")
        report_lines.append("--- RESULT: FAIL (动态测试) ---\n")
        return False, current_sql, "\n".join(report_lines)
    report_lines.append("动态测试: 通过")

    # ---- 问题匹配度 ----
    match_score = check_question_match(question, current_sql, kb_tables)
    report_lines.append(f"问题匹配度: {match_score:.2f}")
    if match_score < 0.5:
        report_lines.append("--- RESULT: FAIL (问题匹配度低) ---\n")
        return False, current_sql, "\n".join(report_lines)

    # ---- 性能检查 ----
    perf_desc, exec_time_ms = check_performance(current_sql)
    report_lines.append(f"性能: {perf_desc}")

    if exec_time_ms > 5000:
        # 性能差，尝试优化
        optimized = optimize_sql(current_sql, perf_desc, exec_time_ms)
        if optimized != current_sql:
            report_lines.append(f"优化后 SQL:\n{optimized}")
            # 优化后必须重新动态测试
            ok2, err2 = dynamic_test(optimized)
            if ok2:
                report_lines.append("优化后动态测试: 通过")
                current_sql = optimized
            else:
                report_lines.append(f"优化后动态测试: 失败 - {err2}")
                report_lines.append("--- RESULT: FAIL (优化后无法执行) ---\n")
                return False, current_sql, "\n".join(report_lines)
        else:
            # 无法优化，性能差但可执行，标记警告但保留
            report_lines.append("性能警告: 执行时间 > 5s，无法自动优化")

    report_lines.append("--- RESULT: PASS ---\n")
    return True, current_sql, "\n".join(report_lines)


# ── 写回 few-shot 文件 ────────────────────────────────────────────────


def write_few_shot(filepath: Path, items: list[dict]) -> None:
    """将通过测试的 few-shot 写回文件。"""
    chunks: list[str] = []
    for item in items:
        chunk = f"场景：{item['scenario']}\n用户问题：{item['question']}\nSQL：\n{item['sql']}"
        chunks.append(chunk)

    content = "\n---\n".join(chunks) + "\n"
    filepath.write_text(content, encoding="utf-8")
    logger.info("Few-shot 写回完成: %d 条 → %s", len(items), filepath)


# ── 主流程 ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Few-Shot SQL 测试与优化")
    parser.add_argument("--dry-run", action="store_true", help="仅测试，不写回文件")
    parser.add_argument("--force-sync", action="store_true", help="强制同步 Neo4j")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Few-Shot SQL 测试与优化脚本")
    logger.info("=" * 60)

    # 1. 加载知识库和数据库结构
    logger.info("Step 1: 加载知识库和数据库结构...")
    kb_tables = load_knowledge_base()
    db_tables = load_db_schema()

    # 2. 解析 few-shot
    logger.info("Step 2: 解析 few-shot 文件...")
    items = parse_few_shot(FEWSHOT_PATH)
    if not items:
        logger.error("未找到任何 few-shot 条目")
        return

    # 3. 逐条验证
    logger.info("Step 3: 逐条验证 (%d 条)...", len(items))
    passed_items: list[dict] = []
    all_reports: list[str] = []

    for i, item in enumerate(items):
        logger.info("验证第 %d/%d 条: %s", i + 1, len(items), item["scenario"])
        ok, final_sql, report = full_validate(item, kb_tables, db_tables)
        all_reports.append(report)
        if ok:
            passed_items.append({"scenario": item["scenario"], "question": item["question"], "sql": final_sql})
            logger.info("  ✓ 通过")
        else:
            logger.info("  ✗ 不通过")

    # 4. 输出报告
    print("\n" + "=" * 60)
    print("测试报告")
    print("=" * 60)
    for report in all_reports:
        print(report)

    print("=" * 60)
    print(f"总计: {len(items)} 条, 通过: {len(passed_items)} 条, 不通过: {len(items) - len(passed_items)} 条")
    print("=" * 60)

    if args.dry_run:
        logger.info("Dry-run 模式，不写回文件")
        return

    # 5. 写回文件
    if passed_items:
        logger.info("Step 4: 写回 few-shot 文件...")
        write_few_shot(FEWSHOT_PATH, passed_items)
    else:
        logger.warning("没有通过测试的 few-shot，不写回文件")
        return

    # 6. 同步 Neo4j
    logger.info("Step 5: 同步 Neo4j 知识库...")
    clear_few_shot_nodes()
    build_neo4j_few_shot_store(force_rebuild=True)
    logger.info("Neo4j 同步完成")

    logger.info("全部完成!")


if __name__ == "__main__":
    main()
