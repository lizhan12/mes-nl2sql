"""基于实际表结构创建所有指标视图（统一版本）。

所有视图使用 CREATE OR REPLACE VIEW + DROP IF EXISTS CASCADE，
确保幂等性和依赖处理。
"""

import re

import psycopg

from src.core.config import settings

url = settings.execution_database_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
conn = psycopg.connect(url)
conn.autocommit = True
cur = conn.cursor()

views_sql = [
    # ── 原子视图（被 M004/M005 依赖） ──
    # v_atom_sn_travel_result: SN过站记录，含首次/末次排序
    """DROP VIEW IF EXISTS v_m004_yield_rate CASCADE;
DROP VIEW IF EXISTS v_m005_fpy CASCADE;
DROP VIEW IF EXISTS v_atom_sn_travel_result CASCADE;
CREATE OR REPLACE VIEW v_atom_sn_travel_result AS
SELECT
    sn,
    pdline_code,
    process_name,
    qc_result,
    create_time,
    ROW_NUMBER() OVER (
        PARTITION BY sn, pdline_code, process_name
        ORDER BY create_time ASC
    ) AS rn_asc,
    ROW_NUMBER() OVER (
        PARTITION BY sn, pdline_code, process_name
        ORDER BY create_time DESC
    ) AS rn_desc
FROM t_pd_sn_travel""",

    # M001: 工单日产量
    # wo_status: 10=已取消, 20=新建, 30=生产中, 40=完工
    """DROP VIEW IF EXISTS v_m001_wo_daily_output CASCADE;
CREATE OR REPLACE VIEW v_m001_wo_daily_output AS
SELECT
    pl.pdline_name                          AS 产线名称,
    wo.pdline_code                          AS 产线代码,
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    DATE(wo.update_time)                    AS 统计日期,
    COUNT(wo.id)                            AS 工单总数,
    SUM(CASE WHEN wo.wo_status = 40 THEN 1 ELSE 0 END) AS 完工工单数,
    SUM(wo.target_qty)                      AS 计划总数量
FROM t_pd_wo wo
LEFT JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
LEFT JOIN t_bd_part   p  ON wo.part_id = p.id
WHERE wo.wo_status != 10
GROUP BY pl.pdline_name, wo.pdline_code, p.part_no, p.part_name, DATE(wo.update_time)""",

    # M002: 工单计划达成率
    """DROP VIEW IF EXISTS v_m002_wo_achievement CASCADE;
CREATE OR REPLACE VIEW v_m002_wo_achievement AS
SELECT
    pl.pdline_name                          AS 产线名称,
    wo.pdline_code                          AS 产线代码,
    DATE(wo.update_time)                    AS 统计日期,
    SUM(wo.target_qty)                      AS 计划总量,
    COUNT(DISTINCT wo.work_order)           AS 工单数,
    SUM(CASE WHEN wo.wo_status=40 THEN 1 ELSE 0 END) AS 完工数,
    ROUND(
        SUM(CASE WHEN wo.wo_status=40 THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(DISTINCT wo.work_order), 0) * 100, 2
    )                                       AS 完工率_pct
FROM t_pd_wo wo
LEFT JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
GROUP BY pl.pdline_name, wo.pdline_code, DATE(wo.update_time)""",

    # M003: 在制工单数
    """DROP VIEW IF EXISTS v_m003_wip_count CASCADE;
CREATE OR REPLACE VIEW v_m003_wip_count AS
SELECT
    pl.pdline_name                          AS 产线名称,
    wo.pdline_code                          AS 产线代码,
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    COUNT(wo.id)                            AS 在制工单数,
    SUM(wo.target_qty)                      AS 在制计划总量
FROM t_pd_wo wo
LEFT JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
LEFT JOIN t_bd_part   p  ON wo.part_id = p.id
WHERE wo.wo_status IN (20, 30)
GROUP BY pl.pdline_name, wo.pdline_code, p.part_no, p.part_name""",

    # M007: IQC来料合格率
    """DROP VIEW IF EXISTS v_m007_iqc_rate CASCADE;
CREATE OR REPLACE VIEW v_m007_iqc_rate AS
SELECT
    s.supplier_name                         AS 供应商名称,
    qi.supplier_code                        AS 供应商编码,
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    DATE_TRUNC('month', qi.create_time)     AS 统计月,
    COUNT(qi.id)                            AS 检验批次,
    SUM(CASE WHEN qi.test_result = 0 THEN 1 ELSE 0 END) AS 合格批次,
    ROUND(
        SUM(CASE WHEN qi.test_result = 0 THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(qi.id), 0) * 100, 2
    )                                       AS IQC合格率_pct
FROM t_qm_inspect_info qi
LEFT JOIN t_bd_part p ON qi.part_id = p.id
LEFT JOIN t_bd_supplier s ON qi.supplier_code = s.supplier_code
WHERE qi.doc_type = 'IQC'
GROUP BY s.supplier_name, qi.supplier_code, p.part_no, p.part_name,
         DATE_TRUNC('month', qi.create_time)""",

    # M008: IPQC巡检合格率（pdline_code 不在 qi 表中，按 doc_type 和日期统计）
    """DROP VIEW IF EXISTS v_m008_ipqc_rate CASCADE;
CREATE OR REPLACE VIEW v_m008_ipqc_rate AS
SELECT
    qi.doc_type                             AS 检验类型,
    DATE(qi.create_time)                    AS 统计日期,
    COUNT(qi.id)                            AS 检验次数,
    SUM(CASE WHEN qi.test_result = 0 THEN 1 ELSE 0 END) AS 合格次数,
    ROUND(
        SUM(CASE WHEN qi.test_result = 0 THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(qi.id), 0) * 100, 2
    )                                       AS IPQC合格率_pct
FROM t_qm_inspect_info qi
WHERE qi.doc_type = 'IPQC'
GROUP BY qi.doc_type, DATE(qi.create_time)""",

    # M009: FQC成品合格率
    """DROP VIEW IF EXISTS v_m009_fqc_rate CASCADE;
CREATE OR REPLACE VIEW v_m009_fqc_rate AS
SELECT
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    DATE_TRUNC('week', qi.create_time)      AS 统计周,
    COUNT(qi.id)                            AS 检验批次,
    SUM(CASE WHEN qi.test_result = 0 THEN 1 ELSE 0 END) AS 合格批次,
    SUM(qi.real_qty)                        AS 检验总数量,
    SUM(CASE WHEN qi.test_result = 0 THEN qi.real_qty ELSE 0 END) AS 合格数量,
    ROUND(
        SUM(CASE WHEN qi.test_result = 0 THEN qi.real_qty ELSE 0 END)::numeric
        / NULLIF(SUM(qi.real_qty), 0) * 100, 2
    )                                       AS FQC合格率_pct
FROM t_qm_inspect_info qi
LEFT JOIN t_bd_part p ON qi.part_id = p.id
WHERE qi.doc_type = 'FQC'
GROUP BY p.part_no, p.part_name, DATE_TRUNC('week', qi.create_time)""",

    # M010: TOP N 不良类型（t_pd_sn_defect 用 terminal_name 作为不良类型名）
    """DROP VIEW IF EXISTS v_m010_top_defects CASCADE;
CREATE OR REPLACE VIEW v_m010_top_defects AS
SELECT
    pl.pdline_name                          AS 产线名称,
    sd.pdline_code                          AS 产线代码,
    sd.terminal_name                        AS 不良名称,
    sd.process_name                         AS 工序名称,
    DATE_TRUNC('week', sd.create_time)      AS 统计周,
    COUNT(sd.id)                            AS 不良数量,
    RANK() OVER (
        PARTITION BY sd.pdline_code, DATE_TRUNC('week', sd.create_time)
        ORDER BY COUNT(sd.id) DESC
    )                                       AS 不良排名
FROM t_pd_sn_defect sd
LEFT JOIN t_bd_pdline pl ON sd.pdline_code = pl.pdline_code
GROUP BY pl.pdline_name, sd.pdline_code, sd.terminal_name, sd.process_name,
         DATE_TRUNC('week', sd.create_time)""",

    # M011: 实时库存快照
    """DROP VIEW IF EXISTS v_m011_stock CASCADE;
CREATE OR REPLACE VIEW v_m011_stock AS
SELECT
    wh.warehouse_name                       AS 仓库名称,
    s.warehouse_code                        AS 仓库编码,
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    SUM(CASE WHEN s.stock_status = 0 THEN s.qty ELSE 0 END) AS 正常库存,
    SUM(CASE WHEN s.stock_status = 1 THEN s.qty ELSE 0 END) AS 冻结库存,
    SUM(CASE WHEN s.stock_status = 2 THEN s.qty ELSE 0 END) AS 不良品库存,
    SUM(s.qty)                              AS 总库存
FROM t_wms_stock s
LEFT JOIN t_bd_part p ON s.part_id = p.id
LEFT JOIN t_wms_warehouse wh ON s.warehouse_code = wh.warehouse_code
GROUP BY wh.warehouse_name, s.warehouse_code, p.part_no, p.part_name""",

    # M012: 当日领料量
    """DROP VIEW IF EXISTS v_m012_daily_issue CASCADE;
CREATE OR REPLACE VIEW v_m012_daily_issue AS
SELECT
    wo.pdline_code                          AS 产线代码,
    pl.pdline_name                          AS 产线名称,
    p.part_no                               AS 物料料号,
    p.part_name                             AS 物料名称,
    DATE(mb.create_time)                    AS 领料日期,
    SUM(mbd.total_qty)                      AS 实际领料量,
    SUM(mbd.out_qty)                        AS 已出库量
FROM t_wms_wo_material_bill mb
LEFT JOIN t_wms_wo_material_bill_detail mbd ON mb.id = mbd.doc_id
LEFT JOIN t_pd_wo wo ON mb.work_order = wo.work_order
LEFT JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
LEFT JOIN t_bd_part p ON mbd.part_id = p.id
GROUP BY wo.pdline_code, pl.pdline_name, p.part_no, p.part_name, DATE(mb.create_time)""",

    # M016: 平均维修时长MTTR
    """DROP VIEW IF EXISTS v_m016_mttr CASCADE;
CREATE OR REPLACE VIEW v_m016_mttr AS
SELECT
    r.equipment_code                        AS 设备编号,
    r.equipment_name                        AS 设备名称,
    DATE_TRUNC('month', r.create_time)      AS 统计月,
    COUNT(r.id)                             AS 维修次数,
    ROUND(AVG(
        EXTRACT(EPOCH FROM (r.end_repair_time - r.start_repair_time)) / 3600
    ), 2)                                   AS 平均维修时长_小时
FROM t_ems_repair_request r
WHERE r.current_status = 30
  AND r.start_repair_time IS NOT NULL
  AND r.end_repair_time IS NOT NULL
GROUP BY r.equipment_code, r.equipment_name, DATE_TRUNC('month', r.create_time)""",

    # M017: 设备点检完成率
    """DROP VIEW IF EXISTS v_m017_inspection_rate CASCADE;
CREATE OR REPLACE VIEW v_m017_inspection_rate AS
SELECT
    e.equipment_code                        AS 设备编号,
    e.equipment_name                        AS 设备名称,
    DATE_TRUNC('month', cd.create_time)     AS 统计月,
    COUNT(cd.id)                            AS 应点检次数,
    SUM(CASE WHEN cd.check_result = 0 THEN 1 ELSE 0 END) AS 已完成次数,
    ROUND(
        SUM(CASE WHEN cd.check_result = 0 THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(cd.id), 0) * 100, 2
    )                                       AS 点检完成率_pct
FROM t_ems_chk_doc cd
LEFT JOIN t_ems_equipment e ON cd.equipment_id = e.id
GROUP BY e.equipment_code, e.equipment_name, DATE_TRUNC('month', cd.create_time)""",

    # M004: SN过站良品率（依赖 v_atom_sn_travel_result）
    """DROP VIEW IF EXISTS v_m004_yield_rate CASCADE;
CREATE OR REPLACE VIEW v_m004_yield_rate AS
SELECT
    pl.pdline_name                          AS 产线名称,
    lr.pdline_code                          AS 产线代码,
    lr.process_name                         AS 工序名称,
    DATE(lr.create_time)                    AS 统计日期,
    COUNT(DISTINCT CASE WHEN lr.qc_result = 0 THEN lr.sn END) AS 通过数,
    COUNT(DISTINCT lr.sn)                   AS 测试总数,
    ROUND(
        COUNT(DISTINCT CASE WHEN lr.qc_result = 0 THEN lr.sn END)::numeric
        / NULLIF(COUNT(DISTINCT lr.sn), 0) * 100, 2
    )                                       AS 良品率_pct
FROM v_atom_sn_travel_result lr
LEFT JOIN t_bd_pdline pl ON lr.pdline_code = pl.pdline_code
WHERE lr.rn_desc = 1
GROUP BY pl.pdline_name, lr.pdline_code, lr.process_name, DATE(lr.create_time)""",

    # M005: 首次通过率FPY（依赖 v_atom_sn_travel_result）
    """DROP VIEW IF EXISTS v_m005_fpy CASCADE;
CREATE OR REPLACE VIEW v_m005_fpy AS
SELECT
    pl.pdline_name                          AS 产线名称,
    fr.pdline_code                          AS 产线代码,
    fr.process_name                         AS 工序名称,
    DATE(fr.create_time)                    AS 统计日期,
    COUNT(DISTINCT CASE WHEN fr.qc_result = 0 THEN fr.sn END) AS 首次通过数,
    COUNT(DISTINCT fr.sn)                   AS 总测试数,
    ROUND(
        COUNT(DISTINCT CASE WHEN fr.qc_result = 0 THEN fr.sn END)::numeric
        / NULLIF(COUNT(DISTINCT fr.sn), 0) * 100, 2
    )                                       AS FPY_pct
FROM v_atom_sn_travel_result fr
LEFT JOIN t_bd_pdline pl ON fr.pdline_code = pl.pdline_code
WHERE fr.rn_asc = 1
GROUP BY pl.pdline_name, fr.pdline_code, fr.process_name, DATE(fr.create_time)""",

    # M006: 工单平均周期时间（从下达到完工）
    """DROP VIEW IF EXISTS v_m006_wo_cycle_time CASCADE;
CREATE OR REPLACE VIEW v_m006_wo_cycle_time AS
SELECT
    pl.pdline_name                          AS 产线名称,
    wo.pdline_code                          AS 产线代码,
    DATE_TRUNC('week', wo.update_time)      AS 统计周,
    COUNT(wo.id)                            AS 完工工单数,
    ROUND(AVG(
        EXTRACT(EPOCH FROM (wo.update_time - wo.create_time)) / 3600
    ), 2)                                   AS 平均周期_小时,
    ROUND(MIN(
        EXTRACT(EPOCH FROM (wo.update_time - wo.create_time)) / 3600
    ), 2)                                   AS 最短周期_小时,
    ROUND(MAX(
        EXTRACT(EPOCH FROM (wo.update_time - wo.create_time)) / 3600
    ), 2)                                   AS 最长周期_小时
FROM t_pd_wo wo
LEFT JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
WHERE wo.wo_status = 40
GROUP BY pl.pdline_name, wo.pdline_code, DATE_TRUNC('week', wo.update_time)""",

    # M014: 采购到货准时率
    """DROP VIEW IF EXISTS v_m014_po_ontime CASCADE;
CREATE OR REPLACE VIEW v_m014_po_ontime AS
SELECT
    s.supplier_name                         AS 供应商名称,
    DATE_TRUNC('month', b.create_time)      AS 统计月,
    COUNT(b.id)                             AS 到货批次
FROM t_wms_po_in_bill b
LEFT JOIN t_bd_supplier s ON b.supplier_id = s.id
GROUP BY s.supplier_name, DATE_TRUNC('month', b.create_time)""",

    # M015: 设备月故障次数
    """DROP VIEW IF EXISTS v_m015_equipment_failure CASCADE;
CREATE OR REPLACE VIEW v_m015_equipment_failure AS
SELECT
    e.equipment_code                        AS 设备编号,
    e.equipment_name                        AS 设备名称,
    DATE_TRUNC('month', r.create_time)      AS 统计月,
    COUNT(r.id)                             AS 报修次数
FROM t_ems_repair_request r
LEFT JOIN t_ems_equipment e ON r.equipment_code = e.equipment_code
GROUP BY e.equipment_code, e.equipment_name, DATE_TRUNC('month', r.create_time)""",
]

success = 0
fail = 0
for sql in views_sql:
    # 提取视图名
    match = re.search(r'CREATE OR REPLACE VIEW (\S+)', sql)
    view_name = match.group(1) if match else "unknown"
    try:
        # 支持多语句（如 DROP + CREATE），用 ; 分割逐条执行
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            cur.execute(stmt)
        success += 1
        print(f"  OK   {view_name}")
    except Exception as exc:
        fail += 1
        print(f"  FAIL {view_name}: {exc}")

print(f"\n结果: 成功={success}, 失败={fail}")

conn.close()
