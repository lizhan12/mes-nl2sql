"""执行生成的业务 SQL 查询，验证语法和可执行性。

用法：
    uv run python scripts/execute_business_queries.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.db_pool import execution_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── SQL 查询定义 ─────────────────────────────────────────────────────

QUERIES = [
    {
        "title": "工单执行进度看板",
        "business_scenario": (
            "生产管理人员需要实时掌握每个工单的执行进度。"
            "该查询将工单与产品料号、产线、计划明细关联，"
            "计算产出达成率，用于发现滞后工单并调整排产。"
        ),
        "tables_involved": ["t_pd_wo", "t_bd_part", "t_bd_pdline", "t_pd_plan_detail"],
        "sql": """\
SELECT wo.work_order,
       wo.wo_status,
       p.part_no,
       p.part_name,
       pl.pdline_name,
       wo.target_qty,
       wo.output_qty,
       ROUND(wo.output_qty::numeric / NULLIF(wo.target_qty, 0) * 100, 1) AS achievement_pct,
       pd.schedule_start_date,
       pd.schedule_end_date,
       wo.start_date,
       wo.end_date
FROM t_pd_wo wo
JOIN t_bd_part p ON wo.part_id = p.id
JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
JOIN t_pd_plan_detail pd ON wo.plan_detail_id = pd.id
WHERE wo.wo_status NOT IN (-1, 3)
  AND wo.create_time >= '2026-01-01'
  AND wo.create_time < '2026-07-01'
ORDER BY achievement_pct ASC
LIMIT 100""",
    },
    {
        "title": "SN 全流程追溯（客诉不良品回溯）",
        "business_scenario": (
            "客户投诉某个产品不良时，需要通过条码 SN 追溯完整生产履历：\n"
            "  1) 该产品经过了哪些工序、各工序的检验结果\n"
            "  2) 在哪个工序产生了不良、不良详情\n"
            "  3) 生产过程中使用了哪些物料（批号、供应商）\n"
            "用于定位不良根因是来料问题还是制程问题。"
        ),
        "tables_involved": [
            "t_pd_sn_status", "t_pd_sn_travel", "t_pd_sn_defect",
            "t_pd_sn_material", "t_pd_wo",
        ],
        "sql": """\
SELECT s.sn,
       s.work_order,
       s.current_phase,
       s.process_name AS current_process,
       tr.process_name AS travel_process,
       tr.current_status AS station_result,
       tr.qc_result,
       tr.create_time AS station_time,
       tr.terminal_name AS station_name,
       d.process_name AS defect_process,
       d.repair_flag,
       m.item_part_no AS material_part_no,
       m.upn AS material_upn,
       m.supplier_code,
       m.lot_no,
       m.real_qty
FROM t_pd_sn_status s
JOIN t_pd_wo wo ON s.work_order = wo.work_order
LEFT JOIN t_pd_sn_travel tr ON s.sn = tr.sn
LEFT JOIN t_pd_sn_defect d ON s.sn = d.sn
LEFT JOIN t_pd_sn_material m ON s.sn = m.sn
WHERE s.sn = 'TEST_SN_001'
ORDER BY tr.create_time ASC
LIMIT 200""",
    },
    {
        "title": "产线 × 工序不良率排行分析",
        "business_scenario": (
            "质量工程师需要识别不良高发的「产线 × 工序」组合。\n"
            "该查询将不良记录与工单、产线、产品关联，\n"
            "统计每个组合的不良数量和已维修数量，\n"
            "为制程改善提供数据支撑。"
        ),
        "tables_involved": ["t_pd_sn_defect", "t_pd_wo", "t_bd_pdline", "t_bd_part"],
        "sql": """\
SELECT pl.pdline_name,
       d.process_name,
       p.part_no,
       p.part_name,
       COUNT(d.sn) AS defect_count,
       SUM(CASE WHEN d.repair_flag = 'Y' THEN 1 ELSE 0 END) AS repaired_count,
       ROUND(
           SUM(CASE WHEN d.repair_flag = 'N' THEN 1 ELSE 0 END)::numeric
           / NULLIF(COUNT(d.sn), 0) * 100, 1
       ) AS unrepaired_pct
FROM t_pd_sn_defect d
JOIN t_pd_wo wo ON d.work_order = wo.work_order
JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
JOIN t_bd_part p ON wo.part_id = p.id
WHERE d.create_time >= '2026-01-01'
  AND d.create_time < '2026-07-01'
GROUP BY pl.pdline_name, d.process_name, p.part_no, p.part_name
HAVING COUNT(d.sn) >= 5
ORDER BY defect_count DESC
LIMIT 50""",
    },
    {
        "title": "工单物料齐套分析（BOM vs 库存）",
        "business_scenario": (
            "生产计划员在工单投产前需确认物料是否齐套。\n"
            "该查询将工单 BOM 的子件需求量与仓库实时库存对比，\n"
            "计算 shortage_qty（缺料数量），标记缺料项，\n"
            "帮助计划员提前协调采购或调拨。"
        ),
        "tables_involved": ["t_pd_wo_bom", "t_pd_wo", "t_bd_part", "t_wms_stock"],
        "sql": """\
SELECT wo.work_order,
       wo.wo_status,
       bom.item_part_id,
       child_part.part_no AS item_part_no,
       child_part.part_name AS item_part_name,
       bom.item_qty AS bom_qty_per_unit,
       bom.item_qty * wo.target_qty AS total_need_qty,
       COALESCE(inv.total_stock, 0) AS current_stock,
       GREATEST(bom.item_qty * wo.target_qty - COALESCE(inv.total_stock, 0), 0) AS shortage_qty,
       CASE
           WHEN COALESCE(inv.total_stock, 0) >= bom.item_qty * wo.target_qty THEN '齐套'
           WHEN COALESCE(inv.total_stock, 0) > 0 THEN '部分缺料'
           ELSE '完全缺料'
       END AS kit_status
FROM t_pd_wo_bom bom
JOIN t_pd_wo wo ON bom.work_order = wo.work_order
JOIN t_bd_part child_part ON bom.item_part_id = child_part.id
LEFT JOIN (
    SELECT part_id, SUM(qty) AS total_stock
    FROM t_wms_stock
    WHERE current_status = 0
      AND stock_status = 1
    GROUP BY part_id
    LIMIT 5000
) inv ON child_part.id = inv.part_id
WHERE wo.wo_status IN (0, 1)
ORDER BY shortage_qty DESC
LIMIT 100""",
    },
    {
        "title": "工单发料 vs 退料 vs BOM 标准用量差异分析",
        "business_scenario": (
            "财务和仓储部门需要核对工单的物料消耗是否合理。\n"
            "该查询汇总每个工单的领料总量、退料总量，\n"
            "计算净消耗并与 BOM 标准用量对比，\n"
            "找出损耗率异常的工单，用于成本管控。"
        ),
        "tables_involved": [
            "t_pd_wo", "t_wms_wo_material_bill", "t_wms_wo_material_bill_detail",
            "t_wms_wo_rb", "t_wms_wo_rb_detail", "t_bd_part",
        ],
        "sql": """\
SELECT wo.work_order,
       p.part_no AS product_part_no,
       wo.target_qty,
       wo.output_qty,
       COALESCE(issue.total_issue_qty, 0) AS total_issue_qty,
       COALESCE(rb.total_return_qty, 0) AS total_return_qty,
       COALESCE(issue.total_issue_qty, 0) - COALESCE(rb.total_return_qty, 0) AS net_consumed_qty
FROM t_pd_wo wo
JOIN t_bd_part p ON wo.part_id = p.id
LEFT JOIN (
    SELECT mb.work_order, SUM(mbd.current_status) AS total_issue_qty
    FROM t_wms_wo_material_bill mb
    JOIN t_wms_wo_material_bill_detail mbd ON mb.id = mbd.doc_id
    WHERE mb.current_status = 2
    GROUP BY mb.work_order
    LIMIT 5000
) issue ON wo.work_order = issue.work_order
LEFT JOIN (
    SELECT rb.work_order, SUM(rbd.total_qty) AS total_return_qty
    FROM t_wms_wo_rb rb
    JOIN t_wms_wo_rb_detail rbd ON rb.id = rbd.doc_id
    WHERE rb.current_status = 2
    GROUP BY rb.work_order
    LIMIT 5000
) rb ON wo.work_order = rb.work_order
WHERE wo.wo_status = 5
  AND wo.create_time >= '2026-01-01'
  AND wo.create_time < '2026-07-01'
ORDER BY net_consumed_qty DESC
LIMIT 100""",
    },
    {
        "title": "仓库库龄分析与超期预警",
        "business_scenario": (
            "仓储管理需要监控物料库龄，识别超过预警期的物料。\n"
            "该查询将库存与料号主数据（含预警天数配置）和仓库关联，\n"
            "计算每批物料的在库天数，与预警阈值和超期阈值对比，\n"
            "标记预警/超期状态，推动 FIFO 执行。"
        ),
        "tables_involved": ["t_wms_stock", "t_bd_part", "t_wms_warehouse"],
        "sql": """\
SELECT wh.warehouse_name,
       p.part_no,
       p.part_name,
       s.upn,
       s.lot_no,
       s.qty AS current_qty,
       s.date_code,
       s.receive_qty,
       s.stock_status,
       wh.fifo_flag,
       p.warm_time_value,
       p.limit_time_value,
       CURRENT_DATE - s.create_time::date AS days_in_stock,
       CASE
           WHEN p.limit_time_value > 0
                AND (CURRENT_DATE - s.create_time::date) > p.limit_time_value THEN '已超期'
           WHEN p.warm_time_value > 0
                AND (CURRENT_DATE - s.create_time::date) > p.warm_time_value THEN '预警中'
           ELSE '正常'
       END AS age_status
FROM t_wms_stock s
JOIN t_bd_part p ON s.part_id = p.id
JOIN t_wms_warehouse wh ON s.warehouse_code = wh.warehouse_code
WHERE s.current_status = 0
  AND s.stock_status = 1
  AND s.qty > 0
ORDER BY days_in_stock DESC
LIMIT 200""",
    },
    {
        "title": "BOM 多级展开（成品→子件→工序）",
        "business_scenario": (
            "工程部门需要查看某产品的完整 BOM 结构。\n"
            "该查询将 BOM 主表、明细表、料号主数据、工序关联，\n"
            "展开每个子件的料号、品名、规格、用量、损耗率及对应工序，\n"
            "用于生产备料和工艺评审。"
        ),
        "tables_involved": ["t_bd_bom", "t_bd_bom_detail", "t_bd_part", "t_bd_process"],
        "sql": """\
SELECT parent_part.part_no AS product_part_no,
       parent_part.part_name AS product_name,
       bom.bom_version,
       bom.current_status AS bom_status,
       detail.item_seq,
       child_part.part_no AS item_part_no,
       child_part.part_name AS item_part_name,
       child_part.part_spec AS item_spec,
       detail.attrition_rate,
       detail.points,
       detail.pcb_side,
       detail.stage_code,
       proc.process_name AS bindprocess
FROM t_bd_bom bom
JOIN t_bd_part parent_part ON bom.part_id = parent_part.id
JOIN t_bd_bom_detail detail ON bom.id = detail.bom_id
JOIN t_bd_part child_part ON detail.item_part_id = child_part.id
LEFT JOIN t_bd_process proc ON detail.process_id = proc.id
WHERE parent_part.part_no = 'TEST_PART_001'
  AND bom.current_status = 2
  AND bom.is_enabled = 'Y'
ORDER BY detail.item_seq ASC
LIMIT 500""",
    },
    {
        "title": "产线维度 SN 投入产出与不良统计",
        "business_scenario": (
            "生产主管需要按产线维度评估生产效率和产品质量。\n"
            "该查询将 SN 状态、工单、产线、产品、不良记录关联，\n"
            "统计每条产线各工单的 SN 投入数、产出数、不良数、良率，\n"
            "用于产能评估和不良趋势监控。"
        ),
        "tables_involved": ["t_pd_sn_status", "t_pd_wo", "t_bd_pdline", "t_bd_part", "t_pd_sn_defect"],
        "sql": """\
SELECT pl.pdline_name,
       wo.work_order,
       p.part_no,
       p.part_name,
       wo.wo_status,
       COUNT(DISTINCT s.sn) AS total_sn_count,
       COUNT(DISTINCT CASE WHEN s.current_phase = 2 THEN s.sn END) AS output_sn_count,
       COUNT(DISTINCT d.sn) AS defect_sn_count,
       ROUND(
           COUNT(DISTINCT CASE WHEN s.current_phase = 2 THEN s.sn END)::numeric
           / NULLIF(COUNT(DISTINCT s.sn), 0) * 100, 1
       ) AS yield_pct
FROM t_pd_sn_status s
JOIN t_pd_wo wo ON s.work_order = wo.work_order
JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
JOIN t_bd_part p ON wo.part_id = p.id
LEFT JOIN t_pd_sn_defect d ON s.sn = d.sn
WHERE wo.create_time >= '2026-01-01'
  AND wo.create_time < '2026-07-01'
GROUP BY pl.pdline_name, wo.work_order, p.part_no, p.part_name, wo.wo_status
ORDER BY pl.pdline_name, yield_pct ASC
LIMIT 100""",
    },
]


# ── 执行与验证 ────────────────────────────────────────────────────────


def explain_sql(sql: str) -> dict:
    """使用 EXPLAIN 验证 SQL 语法和语义正确性，不实际执行查询。"""
    try:
        with execution_connection() as conn, conn.cursor() as cur:
            cur.execute(f"EXPLAIN (FORMAT JSON) {sql}")
            plan = list(cur.fetchone().values())[0]
            return {
                "success": True,
                "explain_plan": plan,
                "error": "",
            }
    except Exception as e:
        return {
            "success": False,
            "explain_plan": {},
            "error": str(e),
        }


def execute_sql_preview(sql: str, limit: int = 5) -> dict:
    """实际执行 SQL 并返回预览数据。"""
    try:
        with execution_connection() as conn, conn.cursor() as cur:
            # 包装为子查询并限制行数
            wrapped_sql = f"SELECT * FROM ({sql.rstrip(';')}) AS preview_q LIMIT {limit}"
            cur.execute(wrapped_sql)
            if cur.description:
                columns = [d.name for d in cur.description]
                rows = cur.fetchall()
                preview = [dict(zip(columns, row, strict=True)) for row in rows]
                return {
                    "success": True,
                    "rows": len(rows),
                    "columns": columns,
                    "preview": preview,
                    "error": "",
                }
            else:
                return {
                    "success": True,
                    "rows": 0,
                    "columns": [],
                    "preview": [],
                    "error": "",
                }
    except Exception as e:
        return {
            "success": False,
            "rows": 0,
            "columns": [],
            "preview": [],
            "error": str(e),
        }


def main() -> None:
    output_lines: list[str] = []
    output_lines.append("=" * 80)
    output_lines.append("执行生成的业务 SQL 查询验证报告")
    output_lines.append(f"共 {len(QUERIES)} 个查询")
    output_lines.append("=" * 80)

    success_count = 0
    fail_count = 0

    for i, q in enumerate(QUERIES, 1):
        output_lines.append("")
        output_lines.append(f"{'─' * 80}")
        output_lines.append(f"查询 {i}：{q['title']}")
        output_lines.append(f"{'─' * 80}")
        output_lines.append("")
        output_lines.append("【业务场景】")
        output_lines.append(q["business_scenario"])
        output_lines.append("")
        output_lines.append(f"【涉及表】{', '.join(q['tables_involved'])}")
        output_lines.append("")

        # 1. EXPLAIN 验证
        output_lines.append("【EXPLAIN 验证】")
        explain_result = explain_sql(q["sql"])
        if explain_result["success"]:
            output_lines.append("  [OK] SQL 语法和语义正确")
            plan_info = explain_result["explain_plan"][0].get("Plan", {}) if explain_result["explain_plan"] else {}
            output_lines.append(f"  执行计划摘要: {plan_info.get('Node Type', 'N/A')}")
        else:
            output_lines.append("  [FAIL] SQL 验证失败")
            output_lines.append(f"  错误信息: {explain_result['error']}")
            fail_count += 1
            output_lines.append("")
            output_lines.append("【SQL】")
            output_lines.append(q["sql"])
            output_lines.append("")
            continue

        # 2. 实际执行预览
        output_lines.append("")
        output_lines.append("【实际执行预览（前 5 行）】")
        exec_result = execute_sql_preview(q["sql"], limit=5)
        if exec_result["success"]:
            output_lines.append(f"  [OK] 执行成功，返回 {exec_result['rows']} 行")
            output_lines.append(f"  列名: {', '.join(exec_result['columns'])}")
            if exec_result["preview"]:
                output_lines.append("  数据预览:")
                for row in exec_result["preview"]:
                    output_lines.append(f"    {row}")
            else:
                output_lines.append("  （无数据返回，可能是占位符参数不匹配）")
            success_count += 1
        else:
            output_lines.append(f"  [FAIL] 执行失败: {exec_result['error']}")
            fail_count += 1

        output_lines.append("")
        output_lines.append("【SQL】")
        output_lines.append(q["sql"])
        output_lines.append("")

    # 汇总
    output_lines.append("")
    output_lines.append("=" * 80)
    output_lines.append("验证汇总")
    output_lines.append("=" * 80)
    output_lines.append(f"  成功: {success_count}/{len(QUERIES)}")
    output_lines.append(f"  失败: {fail_count}/{len(QUERIES)}")
    output_lines.append("")

    result_text = "\n".join(output_lines)
    print(result_text)

    # 保存到文件
    output_path = Path(__file__).resolve().parent.parent / "data" / "query_execution_report.txt"
    output_path.write_text(result_text, encoding="utf-8")
    logger.info("验证报告已保存到: %s", output_path)


if __name__ == "__main__":
    main()
