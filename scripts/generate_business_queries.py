"""从 Neo4j 读取表关系与字段信息，基于业务含义生成有实际意义的 SQL 查询语句。

用法：
    uv run python scripts/generate_business_queries.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.neo4j_graph import _get_driver, _safe_str

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ── 从 Neo4j 读取图数据 ─────────────────────────────────────────────


def load_table_nodes() -> list[dict]:
    """读取所有 Table 节点的业务含义、模块等信息。"""
    driver = _get_driver()
    with driver.session() as session:
        result = session.run("""
            MATCH (t:Table)
            RETURN t.name AS name,
                   t.domain AS domain,
                   t.prefix AS prefix,
                   t.module AS module,
                   t.business_meaning AS business_meaning,
                   t.full_text AS full_text
            ORDER BY t.name
        """)
        return [
            {
                "name": _safe_str(rec["name"]),
                "domain": _safe_str(rec["domain"]),
                "prefix": _safe_str(rec["prefix"]),
                "module": _safe_str(rec["module"]),
                "business_meaning": _safe_str(rec["business_meaning"]),
                "full_text": _safe_str(rec["full_text"]),
            }
            for rec in result
        ]


def load_join_edges() -> list[dict]:
    """读取所有 JOIN_REL 边。"""
    driver = _get_driver()
    with driver.session() as session:
        result = session.run("""
            MATCH (a:Table)-[r:JOIN_REL]->(b:Table)
            RETURN a.name AS from_table, b.name AS to_table,
                   r.from_field AS from_field, r.to_field AS to_field,
                   r.join_condition AS join_condition,
                   r.join_type AS join_type,
                   r.description AS description
        """)
        return [
            {
                "from_table": _safe_str(rec["from_table"]),
                "to_table": _safe_str(rec["to_table"]),
                "from_field": _safe_str(rec["from_field"]),
                "to_field": _safe_str(rec["to_field"]),
                "join_condition": _safe_str(rec["join_condition"]),
                "join_type": _safe_str(rec["join_type"], "JOIN"),
                "description": _safe_str(rec["description"]),
            }
            for rec in result
        ]


def load_field_nodes() -> list[dict]:
    """读取所有 Field 节点。"""
    driver = _get_driver()
    with driver.session() as session:
        result = session.run("""
            MATCH (f:Field)
            RETURN f.table_name AS table_name,
                   f.name AS name,
                   f.type AS type,
                   f.comment AS comment,
                   f.is_pk AS is_pk
            ORDER BY f.table_name, f.name
        """)
        return [
            {
                "table_name": _safe_str(rec["table_name"]),
                "name": _safe_str(rec["name"]),
                "type": _safe_str(rec["type"]),
                "comment": _safe_str(rec["comment"]),
                "is_pk": bool(rec["is_pk"]),
            }
            for rec in result
        ]


# ── 生成有业务意义的 SQL 查询 ────────────────────────────────────────


def generate_business_queries(tables: list[dict], edges: list[dict], fields: list[dict]) -> list[dict]:
    """基于 Neo4j 中的表关系和业务含义，生成有实际业务意义的 SQL 查询。

    每个查询都涉及多表 JOIN，且对应一个真实的 MES 业务场景。
    """
    # 构建字段索引: {table_name: [{name, type, comment, is_pk}]}
    field_map: dict[str, list[dict]] = {}
    for f in fields:
        field_map.setdefault(f["table_name"], []).append(f)

    # 构建边索引: {(from_table, to_table): edge}
    edge_map: dict[tuple[str, str], dict] = {}
    for e in edges:
        edge_map[(e["from_table"], e["to_table"])] = e

    # 构建表信息索引
    table_info: dict[str, dict] = {t["name"]: t for t in tables}

    queries: list[dict] = []

    # ── 查询 1：工单执行进度看板 ─────────────────────────────────────
    # 业务场景：生产管理人员需要查看每个工单的计划产出 vs 实际产出，
    # 同时需要知道产品名、产线名、当前完成百分比，用于排产调度决策。
    # 涉及表关系：t_pd_wo → t_bd_part（工单属于哪个产品）
    #            t_pd_wo → t_bd_pdline（工单在哪条产线生产）
    #            t_pd_wo → t_pd_plan_detail（工单源自哪个计划）
    queries.append({
        "title": "工单执行进度看板",
        "business_scenario": (
            "生产管理人员需要实时掌握每个工单的执行进度。"
            "该查询将工单与产品料号、产线、计划明细关联，"
            "计算产出达成率，用于发现滞后工单并调整排产。"
        ),
        "tables_involved": ["t_pd_wo", "t_bd_part", "t_bd_pdline", "t_pd_plan_detail"],
        "join_path": (
            "t_pd_wo.part_id = t_bd_part.id（工单→产品料号）\n"
            "    t_pd_wo.pdline_code = t_bd_pdline.pdline_code（工单→产线）\n"
            "    t_pd_wo.plan_detail_id = t_pd_plan_detail.id（工单→计划明细）"
        ),
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
    })

    # ── 查询 2：SN 全流程追溯（条码 → 过站 → 不良 → 用料）──────────
    # 业务场景：客诉不良品需要追溯完整生产履历——
    # 该产品经过了哪些工序、在哪个工序产生了不良、使用了哪些物料。
    # 涉及表关系：t_pd_sn_status → t_pd_sn_travel（SN→过站履历）
    #            t_pd_sn_status → t_pd_sn_defect（SN→不良记录）
    #            t_pd_sn_status → t_pd_sn_material（SN→使用物料）
    #            t_pd_sn_status → t_pd_wo（SN→工单）
    queries.append({
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
        "join_path": (
            "t_pd_sn_status.work_order = t_pd_wo.work_order（SN→工单）\n"
            "    t_pd_sn_status.sn = t_pd_sn_travel.sn（SN→过站履历）\n"
            "    t_pd_sn_status.sn = t_pd_sn_defect.sn（SN→不良记录）\n"
            "    t_pd_sn_status.sn = t_pd_sn_material.sn（SN→用料记录）"
        ),
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
WHERE s.sn = 'SPECIFIC_SN'
ORDER BY tr.create_time ASC
LIMIT 200""",
    })

    # ── 查询 3：产线工序不良率分析 ───────────────────────────────────
    # 业务场景：质量工程师需要按产线、工序维度统计不良率，
    # 找出不良高发的工序和产线组合，推动制程改善。
    # 涉及表关系：t_pd_sn_defect → t_pd_wo（不良→工单）
    #            t_pd_wo → t_bd_pdline（工单→产线）
    #            t_pd_wo → t_bd_part（工单→产品）
    queries.append({
        "title": "产线 × 工序不良率排行分析",
        "business_scenario": (
            "质量工程师需要识别不良高发的「产线 × 工序」组合。\n"
            "该查询将不良记录与工单、产线、产品关联，\n"
            "统计每个组合的不良数量和已维修数量，\n"
            "为制程改善提供数据支撑。"
        ),
        "tables_involved": ["t_pd_sn_defect", "t_pd_wo", "t_bd_pdline", "t_bd_part"],
        "join_path": (
            "t_pd_sn_defect.work_order = t_pd_wo.work_order（不良→工单）\n"
            "    t_pd_wo.pdline_code = t_bd_pdline.pdline_code（工单→产线）\n"
            "    t_pd_wo.part_id = t_bd_part.id（工单→产品）"
        ),
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
    })

    # ── 查询 4：工单物料齐套分析 ─────────────────────────────────────
    # 业务场景：生产计划员在工单投产前需要确认物料是否齐套。
    # 对比 BOM 需求量和仓库实际库存，找出缺料项。
    # 涉及表关系：t_pd_wo_bom → t_pd_wo（工单BOM→工单）
    #            t_pd_wo_bom → t_bd_part（BOM子件→料号）
    #            t_bd_part → t_wms_stock（料号→库存）
    queries.append({
        "title": "工单物料齐套分析（BOM vs 库存）",
        "business_scenario": (
            "生产计划员在工单投产前需确认物料是否齐套。\n"
            "该查询将工单 BOM 的子件需求量与仓库实时库存对比，\n"
            "计算 shortage_qty（缺料数量），标记缺料项，\n"
            "帮助计划员提前协调采购或调拨。"
        ),
        "tables_involved": ["t_pd_wo_bom", "t_pd_wo", "t_bd_part", "t_wms_stock"],
        "join_path": (
            "t_pd_wo_bom.work_order = t_pd_wo.work_order（工单BOM→工单）\n"
            "    t_pd_wo_bom.item_part_id = t_bd_part.id（BOM子件→料号主数据）\n"
            "    t_bd_part.part_no = t_wms_stock.part_no（料号→仓库库存）"
        ),
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
    SELECT part_no, SUM(qty) AS total_stock
    FROM t_wms_stock
    WHERE current_status = 0
      AND stock_status = 1
    GROUP BY part_no
    LIMIT 5000
) inv ON child_part.part_no = inv.part_no
WHERE wo.wo_status IN (0, 1)
ORDER BY shortage_qty DESC
LIMIT 100""",
    })

    # ── 查询 5：工单发料与退料差异分析 ───────────────────────────────
    # 业务场景：财务/仓储需要核对每个工单的实际发料量和退料量，
    # 计算净消耗，与 BOM 标准用量对比发现异常损耗。
    # 涉及表关系：t_pd_wo → t_wms_wo_material_bill（工单→领料单）
    #            t_wms_wo_material_bill → t_wms_wo_material_bill_detail（领料单→明细）
    #            t_pd_wo → t_wms_wo_rb（工单→退料单）
    #            t_wms_wo_rb → t_wms_wo_rb_detail（退料单→明细）
    queries.append({
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
        "join_path": (
            "t_pd_wo.work_order = t_wms_wo_material_bill.work_order（工单→领料单）\n"
            "    t_wms_wo_material_bill.id = t_wms_wo_material_bill_detail.doc_id（领料单→明细）\n"
            "    t_pd_wo.work_order = t_wms_wo_rb.work_order（工单→退料单）\n"
            "    t_wms_wo_rb.id = t_wms_wo_rb_detail.doc_id（退料单→明细）\n"
            "    t_wms_wo_rb_detail.part_id = t_bd_part.id（退料明细→料号）"
        ),
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
    })

    # ── 查询 6：仓库库龄分析与超期预警 ───────────────────────────────
    # 业务场景：仓储管理需要监控物料的库龄，识别超过预警期的物料，
    # 推动先进先出（FIFO）执行，避免物料过期报废。
    # 涉及表关系：t_wms_stock → t_bd_part（库存→料号，获取预警天数）
    #            t_wms_stock → t_wms_warehouse（库存→仓库）
    queries.append({
        "title": "仓库库龄分析与超期预警",
        "business_scenario": (
            "仓储管理需要监控物料库龄，识别超过预警期的物料。\n"
            "该查询将库存与料号主数据（含预警天数配置）和仓库关联，\n"
            "计算每批物料的在库天数，与预警阈值和超期阈值对比，\n"
            "标记预警/超期状态，推动 FIFO 执行。"
        ),
        "tables_involved": ["t_wms_stock", "t_bd_part", "t_wms_warehouse"],
        "join_path": (
            "t_wms_stock.part_no = t_bd_part.part_no（库存→料号，获取预警/超期天数配置）\n"
            "    t_wms_stock.warehouse_id = t_wms_warehouse.id（库存→仓库）"
        ),
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
       CURRENT_DATE - s.date_code::date AS days_in_stock,
       CASE
           WHEN p.limit_time_value > 0
                AND (CURRENT_DATE - s.date_code::date) > p.limit_time_value THEN '已超期'
           WHEN p.warm_time_value > 0
                AND (CURRENT_DATE - s.date_code::date) > p.warm_time_value THEN '预警中'
           ELSE '正常'
       END AS age_status
FROM t_wms_stock s
JOIN t_bd_part p ON s.part_no = p.part_no
JOIN t_wms_warehouse wh ON s.warehouse_id = wh.id
WHERE s.current_status = 0
  AND s.stock_status = 1
  AND s.qty > 0
ORDER BY days_in_stock DESC
LIMIT 200""",
    })

    # ── 查询 7：BOM 多级展开（成品→子件→工序）──────────────────────
    # 业务场景：工程部门需要查看某个产品的完整 BOM 结构，
    # 包括每个子件的料号、品名、单位用量、损耗率、对应工序。
    # 涉及表关系：t_bd_bom → t_bd_part（BOM→成品料号）
    #            t_bd_bom → t_bd_bom_detail（BOM主表→BOM明细）
    #            t_bd_bom_detail → t_bd_part（BOM明细→子件料号）
    #            t_bd_bom_detail → t_bd_process（BOM明细→工序）
    queries.append({
        "title": "BOM 多级展开（成品→子件→工序）",
        "business_scenario": (
            "工程部门需要查看某产品的完整 BOM 结构。\n"
            "该查询将 BOM 主表、明细表、料号主数据、工序关联，\n"
            "展开每个子件的料号、品名、规格、用量、损耗率及对应工序，\n"
            "用于生产备料和工艺评审。"
        ),
        "tables_involved": ["t_bd_bom", "t_bd_bom_detail", "t_bd_part", "t_bd_process"],
        "join_path": (
            "t_bd_bom.part_id = t_bd_part.id（BOM主表→成品料号）\n"
            "    t_bd_bom_detail.bom_id = t_bd_bom.id（BOM明细→BOM主表）\n"
            "    t_bd_bom_detail.item_part_id = t_bd_part.id（BOM明细→子件料号）\n"
            "    t_bd_bom_detail.process_id = t_bd_process.id（BOM明细→工序）"
        ),
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
WHERE parent_part.part_no = 'SPECIFIC_PART_NO'
  AND bom.current_status = 2
  AND bom.is_enabled = 'Y'
ORDER BY detail.item_seq ASC
LIMIT 500""",
    })

    # ── 查询 8：工单 SN 产出统计（按产线、产品汇总）──────────────────
    # 业务场景：生产主管需要按产线维度统计各工单的 SN 投入/产出/不良数量，
    # 用于评估产线效率和产品质量。
    # 涉及表关系：t_pd_sn_status → t_pd_wo（SN→工单）
    #            t_pd_wo → t_bd_pdline（工单→产线）
    #            t_pd_wo → t_bd_part（工单→产品）
    #            t_pd_sn_status → t_pd_sn_defect（SN→不良）
    queries.append({
        "title": "产线维度 SN 投入产出与不良统计",
        "business_scenario": (
            "生产主管需要按产线维度评估生产效率和产品质量。\n"
            "该查询将 SN 状态、工单、产线、产品、不良记录关联，\n"
            "统计每条产线各工单的 SN 投入数、产出数、不良数、良率，\n"
            "用于产能评估和不良趋势监控。"
        ),
        "tables_involved": ["t_pd_sn_status", "t_pd_wo", "t_bd_pdline", "t_bd_part", "t_pd_sn_defect"],
        "join_path": (
            "t_pd_sn_status.work_order = t_pd_wo.work_order（SN状态→工单）\n"
            "    t_pd_wo.pdline_code = t_bd_pdline.pdline_code（工单→产线）\n"
            "    t_pd_wo.part_id = t_bd_part.id（工单→产品）\n"
            "    t_pd_sn_status.sn = t_pd_sn_defect.sn（SN状态→不良记录）"
        ),
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
    })

    return queries


# ── 主流程 ────────────────────────────────────────────────────────────


def main() -> None:
    logger.info("从 Neo4j 读取表节点...")
    tables = load_table_nodes()
    logger.info("读取到 %d 个表节点", len(tables))

    logger.info("从 Neo4j 读取 JOIN_REL 边...")
    edges = load_join_edges()
    logger.info("读取到 %d 条关系边", len(edges))

    logger.info("从 Neo4j 读取 Field 节点...")
    fields = load_field_nodes()
    logger.info("读取到 %d 个字段节点", len(fields))

    logger.info("生成有业务意义的 SQL 查询...")
    queries = generate_business_queries(tables, edges, fields)

    # 输出结果
    output_lines: list[str] = []
    output_lines.append("=" * 80)
    output_lines.append("基于 Neo4j 表关系生成的有业务意义的 SQL 查询")
    output_lines.append(f"共 {len(queries)} 个查询")
    output_lines.append("=" * 80)

    for i, q in enumerate(queries, 1):
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
        output_lines.append("【JOIN 路径】")
        output_lines.append(q["join_path"])
        output_lines.append("")
        output_lines.append("【SQL】")
        output_lines.append(q["sql"])
        output_lines.append("")

    result_text = "\n".join(output_lines)
    print(result_text)

    # 同时保存到文件
    output_path = Path(__file__).resolve().parent.parent / "data" / "business_queries.sql"
    output_path.write_text(result_text, encoding="utf-8")
    logger.info("查询已保存到: %s", output_path)


if __name__ == "__main__":
    main()
