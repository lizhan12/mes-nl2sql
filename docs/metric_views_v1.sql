-- ================================================================
-- MES 指标平台 第一期 - PostgreSQL视图定义
-- 前提：所有视图基于只读账号，不影响MES生产系统
-- 口径确认状态：标注[待确认]的视图上线前必须经业务方书面确认
-- ================================================================

-- ----------------------------------------------------------------
-- 生产类指标
-- ----------------------------------------------------------------

-- M001: 工单日产量 [口径：待业务方确认actual_qty字段含义]
CREATE OR REPLACE VIEW v_m001_wo_daily_output AS
SELECT
    pl.pdline_name                          AS 产线名称,
    wo.pdline_code                          AS 产线代码,
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    DATE(wo.update_time)                    AS 统计日期,
    COUNT(wo.id)                            AS 工单总数,
    SUM(CASE WHEN wo.wo_status = '40' THEN 1 ELSE 0 END) AS 完工工单数,
    SUM(wo.plan_qty)                        AS 计划总数量
FROM t_pd_wo wo
LEFT JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
LEFT JOIN t_bd_part   p  ON wo.part_id = p.id
WHERE wo.wo_status != '10'  -- 排除新建未下达
GROUP BY pl.pdline_name, wo.pdline_code, p.part_no, p.part_name, DATE(wo.update_time);

-- M002: 工单计划达成率 [待确认：actual_qty是否存在于wo表]
CREATE OR REPLACE VIEW v_m002_wo_achievement AS
SELECT
    pl.pdline_name                          AS 产线名称,
    wo.pdline_code                          AS 产线代码,
    DATE(wo.update_time)                    AS 统计日期,
    SUM(wo.plan_qty)                        AS 计划总量,
    COUNT(DISTINCT wo.wo_no)                AS 工单数,
    SUM(CASE WHEN wo.wo_status='40' THEN 1 ELSE 0 END) AS 完工数,
    ROUND(
        SUM(CASE WHEN wo.wo_status='40' THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(DISTINCT wo.wo_no), 0) * 100, 2
    )                                       AS 完工率_pct
FROM t_pd_wo wo
LEFT JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
GROUP BY pl.pdline_name, wo.pdline_code, DATE(wo.update_time);

-- M003: 在制工单数（实时）
CREATE OR REPLACE VIEW v_m003_wip_count AS
SELECT
    pl.pdline_name                          AS 产线名称,
    wo.pdline_code                          AS 产线代码,
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    COUNT(wo.id)                            AS 在制工单数,
    SUM(wo.plan_qty)                        AS 在制计划总量
FROM t_pd_wo wo
LEFT JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
LEFT JOIN t_bd_part   p  ON wo.part_id = p.id
WHERE wo.wo_status IN ('20', '30')  -- 已下达+生产中
GROUP BY pl.pdline_name, wo.pdline_code, p.part_no, p.part_name;

-- M004: SN过站良品率 [核心指标，口径已确认：分母去重SN，排除skip工序]
-- 注意：同SN返工后重测，取每个(sn, node_name)组合的最终结果
CREATE OR REPLACE VIEW v_m004_yield_rate AS
WITH latest_result AS (
    SELECT
        sn, pdline_code, node_name,
        pass_flag,
        ROW_NUMBER() OVER (PARTITION BY sn, pdline_code, node_name
                           ORDER BY create_time DESC) AS rn
    FROM t_pd_sn_travel
    WHERE COALESCE(skip_flag, 0) != 1
)
SELECT
    pl.pdline_name                          AS 产线名称,
    lr.pdline_code                          AS 产线代码,
    lr.node_name                            AS 工序名称,
    DATE(st.create_time)                    AS 统计日期,
    COUNT(DISTINCT CASE WHEN lr.pass_flag='Y' THEN lr.sn END) AS 通过数,
    COUNT(DISTINCT lr.sn)                   AS 测试总数,
    ROUND(
        COUNT(DISTINCT CASE WHEN lr.pass_flag='Y' THEN lr.sn END)::numeric
        / NULLIF(COUNT(DISTINCT lr.sn), 0) * 100, 2
    )                                       AS 良品率_pct
FROM latest_result lr
JOIN t_pd_sn_travel st ON lr.sn = st.sn
    AND lr.node_name = st.node_name
    AND lr.rn = 1
LEFT JOIN t_bd_pdline pl ON lr.pdline_code = pl.pdline_code
GROUP BY pl.pdline_name, lr.pdline_code, lr.node_name, DATE(st.create_time);

-- M005: 首次通过率FPY [口径：第一次测试即Y的SN / 全部测试SN]
CREATE OR REPLACE VIEW v_m005_fpy AS
WITH first_result AS (
    SELECT
        sn, pdline_code, node_name, pass_flag,
        ROW_NUMBER() OVER (PARTITION BY sn, pdline_code, node_name
                           ORDER BY create_time ASC) AS rn
    FROM t_pd_sn_travel
    WHERE COALESCE(skip_flag, 0) != 1
)
SELECT
    pl.pdline_name                          AS 产线名称,
    fr.pdline_code                          AS 产线代码,
    fr.node_name                            AS 工序名称,
    DATE(st.create_time)                    AS 统计日期,
    COUNT(DISTINCT CASE WHEN fr.pass_flag='Y' THEN fr.sn END) AS 首次通过数,
    COUNT(DISTINCT fr.sn)                   AS 总测试SN数,
    ROUND(
        COUNT(DISTINCT CASE WHEN fr.pass_flag='Y' THEN fr.sn END)::numeric
        / NULLIF(COUNT(DISTINCT fr.sn), 0) * 100, 2
    )                                       AS FPY_pct
FROM first_result fr
JOIN t_pd_sn_travel st ON fr.sn = st.sn AND fr.node_name = st.node_name AND fr.rn = 1
LEFT JOIN t_bd_pdline pl ON fr.pdline_code = pl.pdline_code
GROUP BY pl.pdline_name, fr.pdline_code, fr.node_name, DATE(st.create_time);

-- M006: 工单平均周期时间（从下达到完工）[待确认：完工时间字段名]
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
WHERE wo.wo_status = '40'
GROUP BY pl.pdline_name, wo.pdline_code, DATE_TRUNC('week', wo.update_time);

-- ----------------------------------------------------------------
-- 质量类指标
-- ----------------------------------------------------------------

-- M007: IQC来料合格率 [按供应商+料号]
CREATE OR REPLACE VIEW v_m007_iqc_rate AS
SELECT
    s.supplier_name                         AS 供应商名称,
    qi.supplier_id                          AS 供应商ID,
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    DATE_TRUNC('month', qi.create_time)     AS 统计月,
    COUNT(qi.id)                            AS 检验批次,
    SUM(CASE WHEN qi.inspect_result='Y' THEN 1 ELSE 0 END) AS 合格批次,
    ROUND(
        SUM(CASE WHEN qi.inspect_result='Y' THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(qi.id), 0) * 100, 2
    )                                       AS IQC合格率_pct
FROM t_qm_inspect_info qi
LEFT JOIN t_bd_part p ON qi.part_id = p.id
LEFT JOIN t_bd_supplier s ON qi.supplier_id = s.id
WHERE qi.inspect_type = 'IQC'
GROUP BY s.supplier_name, qi.supplier_id, p.part_no, p.part_name,
         DATE_TRUNC('month', qi.create_time);

-- M008: IPQC巡检合格率
CREATE OR REPLACE VIEW v_m008_ipqc_rate AS
SELECT
    pl.pdline_name                          AS 产线名称,
    qi.pdline_code                          AS 产线代码,
    DATE(qi.create_time)                    AS 统计日期,
    COUNT(qi.id)                            AS 检验次数,
    SUM(CASE WHEN qi.inspect_result='Y' THEN 1 ELSE 0 END) AS 合格次数,
    ROUND(
        SUM(CASE WHEN qi.inspect_result='Y' THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(qi.id), 0) * 100, 2
    )                                       AS IPQC合格率_pct
FROM t_qm_inspect_info qi
LEFT JOIN t_bd_pdline pl ON qi.pdline_code = pl.pdline_code
WHERE qi.inspect_type = 'IPQC'
GROUP BY pl.pdline_name, qi.pdline_code, DATE(qi.create_time);

-- M009: FQC成品合格率
CREATE OR REPLACE VIEW v_m009_fqc_rate AS
SELECT
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    DATE_TRUNC('week', qi.create_time)      AS 统计周,
    COUNT(qi.id)                            AS 检验批次,
    SUM(CASE WHEN qi.inspect_result='Y' THEN 1 ELSE 0 END) AS 合格批次,
    SUM(qi.inspect_qty)                     AS 检验总数量,
    SUM(CASE WHEN qi.inspect_result='Y' THEN qi.inspect_qty ELSE 0 END) AS 合格数量,
    ROUND(
        SUM(CASE WHEN qi.inspect_result='Y' THEN qi.inspect_qty ELSE 0 END)::numeric
        / NULLIF(SUM(qi.inspect_qty), 0) * 100, 2
    )                                       AS FQC合格率_pct
FROM t_qm_inspect_info qi
LEFT JOIN t_bd_part p ON qi.part_id = p.id
WHERE qi.inspect_type = 'FQC'
GROUP BY p.part_no, p.part_name, DATE_TRUNC('week', qi.create_time);

-- M010: TOP N 不良类型统计
CREATE OR REPLACE VIEW v_m010_top_defects AS
SELECT
    pl.pdline_name                          AS 产线名称,
    st.pdline_code                          AS 产线代码,
    d.defect_name                           AS 不良名称,
    d.defect_code                           AS 不良代码,
    DATE_TRUNC('week', sd.create_time)      AS 统计周,
    COUNT(sd.id)                            AS 不良数量,
    RANK() OVER (
        PARTITION BY st.pdline_code, DATE_TRUNC('week', sd.create_time)
        ORDER BY COUNT(sd.id) DESC
    )                                       AS 不良排名
FROM t_pd_sn_defect sd
LEFT JOIN t_pd_sn_status st ON sd.sn = st.sn
LEFT JOIN t_bd_defect d ON sd.defect_id = d.id
LEFT JOIN t_bd_pdline pl ON st.pdline_code = pl.pdline_code
GROUP BY pl.pdline_name, st.pdline_code, d.defect_name, d.defect_code,
         DATE_TRUNC('week', sd.create_time);

-- ----------------------------------------------------------------
-- 库存类指标
-- ----------------------------------------------------------------

-- M011: 实时库存快照
CREATE OR REPLACE VIEW v_m011_stock AS
SELECT
    wh.warehouse_name                       AS 仓库名称,
    s.warehouse_id                          AS 仓库ID,
    p.part_no                               AS 料号,
    p.part_name                             AS 料号名称,
    p.part_type                             AS 料号类型,
    SUM(CASE WHEN s.stock_type='0' THEN s.qty ELSE 0 END) AS 正常库存,
    SUM(CASE WHEN s.stock_type='1' THEN s.qty ELSE 0 END) AS 冻结库存,
    SUM(CASE WHEN s.stock_type='2' THEN s.qty ELSE 0 END) AS 不良品库存,
    SUM(s.qty)                              AS 总库存
FROM t_wms_stock s
LEFT JOIN t_bd_part p ON s.part_no = p.part_no
LEFT JOIN t_wms_warehouse wh ON s.warehouse_id = wh.id
GROUP BY wh.warehouse_name, s.warehouse_id, p.part_no, p.part_name, p.part_type;

-- M012: 当日领料量
CREATE OR REPLACE VIEW v_m012_daily_issue AS
SELECT
    wo.pdline_code                          AS 产线代码,
    pl.pdline_name                          AS 产线名称,
    p.part_no                               AS 物料料号,
    p.part_name                             AS 物料名称,
    DATE(mb.create_time)                    AS 领料日期,
    SUM(mbd.actual_qty)                     AS 实际领料量,
    SUM(mbd.plan_qty)                       AS 计划领料量
FROM t_wms_wo_material_bill mb
LEFT JOIN t_wms_wo_material_bill_detail mbd ON mb.id = mbd.doc_id
LEFT JOIN t_pd_wo wo ON mb.wo_no = wo.wo_no
LEFT JOIN t_bd_pdline pl ON wo.pdline_code = pl.pdline_code
LEFT JOIN t_bd_part p ON mbd.part_id = p.id
GROUP BY wo.pdline_code, pl.pdline_name, p.part_no, p.part_name, DATE(mb.create_time);

-- M014: 采购到货准时率 [待确认：期望到货时间字段]
CREATE OR REPLACE VIEW v_m014_po_ontime AS
SELECT
    s.supplier_name                         AS 供应商名称,
    DATE_TRUNC('month', b.create_time)      AS 统计月,
    COUNT(b.id)                             AS 到货批次,
    COUNT(b.id)                             AS 总批次
    -- 注意：此视图需要业务确认 expected_date 字段是否存在，暂只统计批次
FROM t_wms_po_in_bill b
LEFT JOIN t_bd_supplier s ON b.supplier_id = s.id
GROUP BY s.supplier_name, DATE_TRUNC('month', b.create_time);

-- ----------------------------------------------------------------
-- 设备类指标
-- ----------------------------------------------------------------

-- M015: 设备月故障次数
CREATE OR REPLACE VIEW v_m015_equipment_failure AS
SELECT
    e.equipment_code                        AS 设备编号,
    e.equipment_name                        AS 设备名称,
    DATE_TRUNC('month', r.create_time)      AS 统计月,
    COUNT(r.id)                             AS 报修次数,
    COUNT(DISTINCT rf.id)                   AS 故障记录数
FROM t_ems_repair_request r
LEFT JOIN t_ems_equipment e ON r.equipment_code = e.equipment_code
LEFT JOIN t_ems_repair_request_fault rf ON r.id = rf.request_id
GROUP BY e.equipment_code, e.equipment_name, DATE_TRUNC('month', r.create_time);

-- M016: 平均维修时长MTTR [待确认：repair_end_time字段是否存在]
CREATE OR REPLACE VIEW v_m016_mttr AS
SELECT
    e.equipment_code                        AS 设备编号,
    e.equipment_name                        AS 设备名称,
    DATE_TRUNC('month', r.create_time)      AS 统计月,
    COUNT(r.id)                             AS 维修次数,
    ROUND(AVG(
        EXTRACT(EPOCH FROM (r.update_time - r.create_time)) / 3600
    ), 2)                                   AS 平均维修时长_小时
FROM t_ems_repair_request r
LEFT JOIN t_ems_equipment e ON r.equipment_code = e.equipment_code
WHERE r.status = '30'  -- 维修完成
GROUP BY e.equipment_code, e.equipment_name, DATE_TRUNC('month', r.create_time);

-- M017: 设备点检完成率
CREATE OR REPLACE VIEW v_m017_inspection_rate AS
SELECT
    e.equipment_code                        AS 设备编号,
    e.equipment_name                        AS 设备名称,
    DATE_TRUNC('month', cd.create_time)     AS 统计月,
    COUNT(cd.id)                            AS 应点检次数,
    SUM(CASE WHEN cd.check_status='done' THEN 1 ELSE 0 END) AS 已完成次数,
    ROUND(
        SUM(CASE WHEN cd.check_status='done' THEN 1 ELSE 0 END)::numeric
        / NULLIF(COUNT(cd.id), 0) * 100, 2
    )                                       AS 点检完成率_pct
FROM t_ems_chk_doc cd
LEFT JOIN t_ems_equipment e ON cd.equipment_id = e.id
GROUP BY e.equipment_code, e.equipment_name, DATE_TRUNC('month', cd.create_time);

-- ================================================================
-- 使用示例
-- ================================================================
-- 今天A线的良品率：
-- SELECT * FROM v_m004_yield_rate WHERE 统计日期=CURRENT_DATE AND 产线名称='A线';

-- 本月各供应商IQC合格率排名：
-- SELECT * FROM v_m007_iqc_rate
-- WHERE 统计月=DATE_TRUNC('month',CURRENT_DATE)
-- ORDER BY IQC合格率_pct ASC;

-- 当前在制工单数：
-- SELECT * FROM v_m003_wip_count ORDER BY 在制工单数 DESC;
