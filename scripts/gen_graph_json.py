"""根据业务SQL中的JOIN关系生成 mes_relation_graph.json。

每条关系生成正向和反向两条边，确保图的双向可达性。
"""
import json
from pathlib import Path

# 所有业务SQL中提取的JOIN关系
# (from_table, to_table, from_field, to_field, join_condition, join_type, desc)
RELATIONSHIPS = [
    # t_bd_part_process_component
    ("t_bd_part_process_component", "t_bd_part", "item_part_id", "id", "t_bd_part_process_component.item_part_id = t_bd_part.id", "LEFT JOIN", "组装清单→组件料号"),
    ("t_bd_part_process_component", "t_bd_part", "part_id", "id", "t_bd_part_process_component.part_id = t_bd_part.id", "LEFT JOIN", "组装清单→主料号"),
    ("t_bd_part_process_component", "t_basic_user", "create_user_id", "id", "t_bd_part_process_component.create_user_id = t_basic_user.id", "LEFT JOIN", "组装清单→创建人"),
    # t_bd_part
    ("t_bd_part", "t_bc_encode_rule_group", "encode_rule_group_id", "id", "t_bd_part.encode_rule_group_id = t_bc_encode_rule_group.id", "LEFT JOIN", "料号→编码规则组"),
    ("t_bd_part", "t_lb_label_parse_rule_group", "parse_rule_group_id", "id", "t_bd_part.parse_rule_group_id = t_lb_label_parse_rule_group.id", "LEFT JOIN", "料号→解析规则组"),
    # t_packing_rule_detail
    ("t_packing_rule_detail", "t_packing_container", "container_name", "container_name", "t_packing_rule_detail.container_name = t_packing_container.container_name", "LEFT JOIN", "包装规则明细→包装容器"),
    # t_packing_container
    ("t_packing_container", "t_bc_encode_rule", "chk_no_rule_id", "id", "t_packing_container.chk_no_rule_id = t_bc_encode_rule.id", "LEFT JOIN", "包装容器→编码规则"),
    ("t_packing_container", "t_basic_user", "create_user_id", "id", "t_packing_container.create_user_id = t_basic_user.id", "LEFT JOIN", "包装容器→创建人"),
    ("t_packing_container", "t_basic_user", "update_user_id", "id", "t_packing_container.update_user_id = t_basic_user.id", "LEFT JOIN", "包装容器→更新人"),
    # t_bd_substitute
    ("t_bd_substitute", "t_bd_part", "sub_part_id", "id", "t_bd_substitute.sub_part_id = t_bd_part.id", "LEFT JOIN", "替代料→替代料号"),
    ("t_bd_substitute", "t_bd_part", "part_id", "id", "t_bd_substitute.part_id = t_bd_part.id", "LEFT JOIN", "替代料→主料号"),
    ("t_bd_substitute", "t_bd_part", "item_part_id", "id", "t_bd_substitute.item_part_id = t_bd_part.id", "LEFT JOIN", "替代料→子件料号"),
    ("t_bd_substitute", "t_basic_user", "create_user_id", "id", "t_bd_substitute.create_user_id = t_basic_user.id", "LEFT JOIN", "替代料→创建人"),
    ("t_bd_substitute", "t_basic_user", "update_user_id", "id", "t_bd_substitute.update_user_id = t_basic_user.id", "LEFT JOIN", "替代料→更新人"),
    ("t_bd_substitute", "t_bd_bom", "part_id+bom_version", "part_id+bom_version", "t_bd_substitute.part_id = t_bd_bom.part_id AND t_bd_substitute.bom_version = t_bd_bom.bom_version", "LEFT JOIN", "替代料→BOM"),
    # t_pd_sn_defect
    ("t_pd_sn_defect", "t_bd_part", "part_no", "part_no", "t_pd_sn_defect.part_no = t_bd_part.part_no", "LEFT JOIN", "SN不良→料号"),
    ("t_pd_sn_defect", "t_basic_user", "create_user_id", "id", "t_pd_sn_defect.create_user_id = t_basic_user.id", "LEFT JOIN", "SN不良→创建人"),
    # t_pd_wo
    ("t_pd_wo", "t_bd_part", "part_id", "id", "t_pd_wo.part_id = t_bd_part.id", "LEFT JOIN", "工单→料号"),
    # t_pd_wo_bom
    ("t_pd_wo_bom", "t_bd_part", "item_part_id", "id", "t_pd_wo_bom.item_part_id = t_bd_part.id", "LEFT JOIN", "工单BOM→料号"),
    ("t_pd_wo_bom", "t_pd_wo", "work_order", "work_order", "t_pd_wo_bom.work_order = t_pd_wo.work_order", "LEFT JOIN", "工单BOM→工单"),
    ("t_pd_wo_bom", "t_wms_stock", "item_part_id", "part_id", "t_pd_wo_bom.item_part_id = t_wms_stock.part_id", "LEFT JOIN", "工单BOM→库存"),
    # t_pd_sn_travel
    ("t_pd_sn_travel", "t_basic_user", "create_user_id", "id", "t_pd_sn_travel.create_user_id = t_basic_user.id", "LEFT JOIN", "SN履历→创建人"),
    ("t_pd_sn_travel", "t_basic_user", "update_user_id", "id", "t_pd_sn_travel.update_user_id = t_basic_user.id", "LEFT JOIN", "SN履历→更新人"),
    # t_ht_pd_wo_issue_material
    ("t_ht_pd_wo_issue_material", "t_pd_wo", "work_order", "work_order", "t_ht_pd_wo_issue_material.work_order = t_pd_wo.work_order", "LEFT JOIN", "历史备料→工单"),
    ("t_ht_pd_wo_issue_material", "t_basic_user", "create_user_id", "id", "t_ht_pd_wo_issue_material.create_user_id = t_basic_user.id", "LEFT JOIN", "历史备料→创建人"),
    ("t_ht_pd_wo_issue_material", "t_basic_user", "update_user_id", "id", "t_ht_pd_wo_issue_material.update_user_id = t_basic_user.id", "LEFT JOIN", "历史备料→更新人"),
    # t_pd_wo_issue_material
    ("t_pd_wo_issue_material", "t_pd_wo", "work_order", "work_order", "t_pd_wo_issue_material.work_order = t_pd_wo.work_order", "LEFT JOIN", "发料→工单"),
    ("t_pd_wo_issue_material", "t_basic_user", "create_user_id", "id", "t_pd_wo_issue_material.create_user_id = t_basic_user.id", "LEFT JOIN", "发料→创建人"),
    ("t_pd_wo_issue_material", "t_basic_user", "update_user_id", "id", "t_pd_wo_issue_material.update_user_id = t_basic_user.id", "LEFT JOIN", "发料→更新人"),
    # t_pd_plan_need_material
    ("t_pd_plan_need_material", "t_bd_part", "part_id", "id", "t_pd_plan_need_material.part_id = t_bd_part.id", "LEFT JOIN", "用料需求→料号"),
    ("t_pd_plan_need_material", "t_basic_user", "create_user_id", "id", "t_pd_plan_need_material.create_user_id = t_basic_user.id", "LEFT JOIN", "用料需求→创建人"),
    ("t_pd_plan_need_material", "t_basic_user", "update_user_id", "id", "t_pd_plan_need_material.update_user_id = t_basic_user.id", "LEFT JOIN", "用料需求→更新人"),
    # t_pd_wo_msl
    ("t_pd_wo_msl", "t_bd_pdline", "pdline_code", "pdline_code", "t_pd_wo_msl.pdline_code = t_bd_pdline.pdline_code", "LEFT JOIN", "工单MSL→产线"),
    ("t_pd_wo_msl", "t_pd_wo_msl_detail", "id", "msl_id", "t_pd_wo_msl.id = t_pd_wo_msl_detail.msl_id", "LEFT JOIN", "工单MSL→MSL明细"),
    ("t_pd_wo_msl", "t_pd_wo_load_material", "work_order", "work_order", "t_pd_wo_msl.work_order = t_pd_wo_load_material.work_order", "LEFT JOIN", "工单MSL→上料(含多字段关联)"),
    # t_qm_inspect_info
    ("t_qm_inspect_info", "t_qm_inspect_item_info", "doc_no", "doc_no", "t_qm_inspect_info.doc_no = t_qm_inspect_item_info.doc_no", "LEFT JOIN", "检验单→检验项目"),
    ("t_qm_inspect_info", "t_bd_part", "part_id", "id", "t_qm_inspect_info.part_id = t_bd_part.id", "LEFT JOIN", "检验单→料号"),
    ("t_qm_inspect_info", "t_qm_sample_config", "config_id", "id", "t_qm_inspect_info.config_id = t_qm_sample_config.id", "LEFT JOIN", "检验单→抽样配置"),
    ("t_qm_inspect_info", "t_qm_sample_type_setting", "type_setting_id", "id", "t_qm_inspect_info.type_setting_id = t_qm_sample_type_setting.id", "LEFT JOIN", "检验单→抽样类型设置"),
    ("t_qm_inspect_info", "t_basic_user", "create_user_id", "id", "t_qm_inspect_info.create_user_id = t_basic_user.id", "LEFT JOIN", "检验单→创建人"),
    ("t_qm_inspect_info", "t_basic_user", "update_user_id", "id", "t_qm_inspect_info.update_user_id = t_basic_user.id", "LEFT JOIN", "检验单→更新人"),
    ("t_qm_inspect_info", "t_bd_customer", "cust_code", "id", "t_qm_inspect_info.cust_code = t_bd_customer.id", "LEFT JOIN", "检验单→客户"),
    ("t_qm_inspect_info", "t_bd_supplier", "supplier_code", "id", "t_qm_inspect_info.supplier_code = t_bd_supplier.id", "LEFT JOIN", "检验单→供应商"),
    ("t_qm_inspect_info", "t_basic_user", "send_user", "id", "t_qm_inspect_info.send_user = t_basic_user.id", "LEFT JOIN", "检验单→送检人"),
    ("t_qm_inspect_info", "t_basic_user", "test_user", "id", "t_qm_inspect_info.test_user = t_basic_user.id", "LEFT JOIN", "检验单→检验人"),
    ("t_qm_inspect_info", "t_basic_user", "audit_user", "id", "t_qm_inspect_info.audit_user = t_basic_user.id", "LEFT JOIN", "检验单→审核人"),
    ("t_qm_inspect_info", "t_qm_inspect_parent_info", "doc_no", "doc_no", "t_qm_inspect_info.doc_no = t_qm_inspect_parent_info.doc_no", "LEFT JOIN", "检验单→检验父单"),
    # t_tool_maintenance_info
    ("t_tool_maintenance_info", "t_basic_user", "report_user", "id", "t_tool_maintenance_info.report_user = t_basic_user.id", "LEFT JOIN", "治具维修→报修人"),
    ("t_tool_maintenance_info", "t_basic_user", "repair_user", "id", "t_tool_maintenance_info.repair_user = t_basic_user.id", "LEFT JOIN", "治具维修→维修人"),
    ("t_tool_maintenance_info", "t_bd_file", "id", "service_id", "t_tool_maintenance_info.id = t_bd_file.service_id", "LEFT JOIN", "治具维修→文件"),
    # t_tool_no_attr_travel
    ("t_tool_no_attr_travel", "t_basic_user", "create_user_id", "id", "t_tool_no_attr_travel.create_user_id = t_basic_user.id", "LEFT JOIN", "治具保养→创建人"),
    ("t_tool_no_attr_travel", "t_basic_user", "update_user_id", "id", "t_tool_no_attr_travel.update_user_id = t_basic_user.id", "LEFT JOIN", "治具保养→更新人"),
    ("t_tool_no_attr_travel", "t_tool_no", "tool_no", "tool_no", "t_tool_no_attr_travel.tool_no = t_tool_no.tool_no", "LEFT JOIN", "治具保养→治具"),
    # t_tool_no
    ("t_tool_no", "t_tool_model", "model_id", "id", "t_tool_no.model_id = t_tool_model.id", "LEFT JOIN", "治具→型号"),
    ("t_tool_no", "t_basic_user", "instock_emp", "id", "t_tool_no.instock_emp = t_basic_user.id", "LEFT JOIN", "治具→入库人"),
    ("t_tool_no", "t_basic_user", "use_empid", "id", "t_tool_no.use_empid = t_basic_user.id", "LEFT JOIN", "治具→使用人"),
    ("t_tool_no", "t_basic_user", "return_emp_id", "id", "t_tool_no.return_emp_id = t_basic_user.id", "LEFT JOIN", "治具→退回人"),
    ("t_tool_no", "t_basic_user", "test_user", "id", "t_tool_no.test_user = t_basic_user.id", "LEFT JOIN", "治具→测试人"),
    # t_tool_model
    ("t_tool_model", "t_tool_type", "tool_type_id", "id", "t_tool_model.tool_type_id = t_tool_type.id", "LEFT JOIN", "治具型号→类型"),
    ("t_tool_model", "t_bd_route", "route_id", "id", "t_tool_model.route_id = t_bd_route.id", "LEFT JOIN", "治具型号→工艺路线"),
    ("t_tool_model", "t_basic_user", "create_user_id", "id", "t_tool_model.create_user_id = t_basic_user.id", "LEFT JOIN", "治具型号→创建人"),
    ("t_tool_model", "t_basic_user", "update_user_id", "id", "t_tool_model.update_user_id = t_basic_user.id", "LEFT JOIN", "治具型号→更新人"),
    # t_wms_stock
    ("t_wms_stock", "t_bd_supplier", "supplier_id", "id", "t_wms_stock.supplier_id = t_bd_supplier.id", "LEFT JOIN", "库存→供应商"),
    ("t_wms_stock", "t_bd_customer", "customer_id", "id", "t_wms_stock.customer_id = t_bd_customer.id", "LEFT JOIN", "库存→客户"),
    ("t_wms_stock", "t_wms_warehouse", "warehouse_code", "warehouse_code", "t_wms_stock.warehouse_code = t_wms_warehouse.warehouse_code", "LEFT JOIN", "库存→仓库"),
    ("t_wms_stock", "t_wms_location", "location_no", "location_no", "t_wms_stock.location_no = t_wms_location.location_no", "LEFT JOIN", "库存→储位"),
    ("t_wms_stock", "t_bd_part", "part_id", "id", "t_wms_stock.part_id = t_bd_part.id", "LEFT JOIN", "库存→料号"),
    # t_wms_location
    ("t_wms_location", "t_wms_warehouse", "warehouse_id", "id", "t_wms_location.warehouse_id = t_wms_warehouse.id", "LEFT JOIN", "储位→仓库"),
    ("t_wms_location", "t_wms_shelf", "shelf_id", "id", "t_wms_location.shelf_id = t_wms_shelf.id", "LEFT JOIN", "储位→货架"),
    # t_wms_wo_material_bill
    ("t_wms_wo_material_bill", "t_wms_doc_upn", "id", "doc_id", "t_wms_wo_material_bill.id = t_wms_doc_upn.doc_id", "LEFT JOIN", "领料单→UPN"),
    ("t_wms_wo_material_bill", "t_wms_wo_rb", "work_order", "work_order", "t_wms_wo_material_bill.work_order = t_wms_wo_rb.work_order", "LEFT JOIN", "领料单→退料单"),
    ("t_wms_wo_material_bill", "t_wms_wo_material_bill_detail", "id", "doc_id", "t_wms_wo_material_bill.id = t_wms_wo_material_bill_detail.doc_id", "LEFT JOIN", "领料单→领料明细"),
    ("t_wms_wo_material_bill", "t_pd_wo", "work_order", "work_order", "t_wms_wo_material_bill.work_order = t_pd_wo.work_order", "LEFT JOIN", "领料单→工单"),
    # t_wms_wo_rb
    ("t_wms_wo_rb", "t_wms_wo_rb_detail", "id", "doc_id", "t_wms_wo_rb.id = t_wms_wo_rb_detail.doc_id", "LEFT JOIN", "退料单→退料明细"),
    ("t_wms_wo_rb", "t_pd_wo", "work_order", "work_order", "t_wms_wo_rb.work_order = t_pd_wo.work_order", "LEFT JOIN", "退料单→工单"),
    # t_wms_wo_rb_detail
    ("t_wms_wo_rb_detail", "t_bd_part", "part_id", "id", "t_wms_wo_rb_detail.part_id = t_bd_part.id", "LEFT JOIN", "退料明细→料号"),
    # t_wms_doc_upn
    ("t_wms_doc_upn", "t_bd_part", "part_no", "part_no", "t_wms_doc_upn.part_no = t_bd_part.part_no", "LEFT JOIN", "UPN→料号"),
]

# 所有44个表
ALL_TABLES = [
    "t_basic_user", "t_bc_encode_rule", "t_bc_encode_rule_group",
    "t_lb_label_parse_rule_group", "t_bd_bom", "t_bd_customer",
    "t_bd_file", "t_bd_part", "t_bd_part_process_component",
    "t_bd_pdline", "t_bd_route", "t_bd_substitute", "t_bd_supplier",
    "t_packing_container", "t_packing_rule_detail",
    "t_ht_pd_wo_issue_material", "t_pd_plan_need_material",
    "t_pd_sn_defect", "t_pd_sn_travel", "t_pd_wo", "t_pd_wo_bom",
    "t_pd_wo_issue_material", "t_pd_wo_load_material",
    "t_pd_wo_msl", "t_pd_wo_msl_detail",
    "t_qm_inspect_info", "t_qm_inspect_item_info",
    "t_qm_inspect_parent_info", "t_qm_sample_config",
    "t_qm_sample_type_setting",
    "t_tool_maintenance_info", "t_tool_model", "t_tool_no",
    "t_tool_no_attr_travel", "t_tool_type",
    "t_wms_doc_upn", "t_wms_location", "t_wms_shelf",
    "t_wms_stock", "t_wms_warehouse",
    "t_wms_wo_material_bill", "t_wms_wo_material_bill_detail",
    "t_wms_wo_rb", "t_wms_wo_rb_detail",
]


def build_graph() -> dict[str, list[dict]]:
    """构建双向邻接表。"""
    graph: dict[str, list[dict]] = {t: [] for t in ALL_TABLES}

    for from_t, to_t, from_f, to_f, join, jtype, desc in RELATIONSHIPS:
        # 正向边
        graph[from_t].append({
            "to": to_t,
            "from_field": from_f,
            "to_field": to_f,
            "join": join,
            "join_type": jtype,
            "desc": desc,
            "confidence": "high",
            "note": "",
        })
        # 反向边
        graph[to_t].append({
            "to": from_t,
            "from_field": to_f,
            "to_field": from_f,
            "join": join,
            "join_type": jtype,
            "desc": desc + "(反向)",
            "confidence": "high",
            "note": "",
        })

    return graph


def main() -> None:
    graph = build_graph()
    output_path = Path(__file__).parent.parent / "data" / "mes_relation_graph.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    total_edges = sum(len(v) for v in graph.values())
    print(f"已生成 {output_path}")
    print(f"表数: {len(graph)}, 总边数: {total_edges}")


if __name__ == "__main__":
    main()
