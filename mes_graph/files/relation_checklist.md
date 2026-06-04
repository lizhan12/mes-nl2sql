# MES关联关系人工校验清单
## 说明
以下关联是通过字段名推断得出的，置信度为medium，请与业务/开发人员确认后，
将结果（confirmed/rejected）填入最后一列，然后更新代码节点中的GRAPH。

| # | 从表 | 到表 | 关联字段 | 推断依据 | 需确认的问题 | 状态 |
|---|------|------|----------|----------|--------------|------|
| 1 | t_bd_bom_detail | t_bd_process | t_bd_bom_detail.process_id = t_bd_process.id | 字段命名规律 | 需确认process_id是否始终有值 | 待确认 |
| 2 | t_qm_ipqc_doc | t_qm_ipqc_scheme | t_qm_ipqc_doc.scheme_id = t_qm_ipqc_scheme.id | 字段命名规律 | scheme可能被删除，注意LEFT JOIN | 待确认 |
| 3 | t_ems_equipment | t_ems_model | t_ems_equipment.model_id = t_ems_model.id | 字段命名规律 | 需确认model_id是否必填 | 待确认 |
| 4 | t_ems_equipment | t_bd_terminal | t_ems_equipment.terminal_id = t_bd_terminal.id | 字段命名规律 | terminal_id可能为空，用LEFT JOIN | 待确认 |
| 5 | t_ems_maintain_wo | t_ems_maintain_plan_detail | t_ems_maintain_wo.plan_detail_id = t_ems_maintain_plan_detail.id | 字段命名规律 | 需确认plan_detail_id是否有历史数据 | 待确认 |
| 6 | t_wms_upn_record | t_bd_part | t_wms_upn_record.part_no = t_bd_part.part_no | 字段命名规律 | part_no格式需一致 | 待确认 |
| 7 | t_bd_terminal | t_bd_process | t_bd_terminal.process_id = t_bd_process.id | 字段命名规律 | process_id可能为空 | 待确认 |

## 可能遗漏的关联（请业务方补充）
以下场景在当前关系图中不连通，如果业务上有关联请补充：
- 设备(t_ems_equipment) ↔ 产线产量(t_pd_sn_status)：通过 terminal_id → pdline_code 可能间接关联
- IPQC巡检(t_qm_ipqc_doc) ↔ 工单(t_pd_wo)：是否有直接工单号关联？
- 检验单(t_qm_inspect_info) ↔ SN(t_pd_sn_status)：IQC检验是否关联到具体SN？
- 工单工艺路线(t_pd_wo_route) ↔ 工作站(t_bd_terminal)：是否记录了每道工序在哪个工作站执行？