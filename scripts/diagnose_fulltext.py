"""用真实 full_text 调 rerank，看为什么分数这么低。"""

import asyncio

import httpx


API_KEY = "sk-wlmdnlcicswgoealbouetyyuedswzyousvwfqgazncwqkxgo"
BASE_URL = "http://192.168.0.76:8001"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

QUERY = "查询包装规则为69b254c9a059eeeb74c433aa明细"

# 真实 5 条 schema 结果的 business_meaning + full_text
# （从 inspect_schema_text.py 复制）
REAL_TEXTS = [
    # 1. t_packing_rule
    "包装规则配置表，用于定义产品或订单的包装规范，关联包装层级和容器信息\n"
    "表名：t_packing_rule\n模块：包装管理\n业务含义：包装规则配置表，用于定义产品或订单的包装规范，关联包装层级和容器信息\n关键字段：\n  id (varchar(40))\n  rule_name (varchar(40))\n  rule_desc (varchar(40))\n  is_enabled (varchar(1))\n  create_user_id (varchar(40))\n  create_time (timestamp(6))\n  update_user_id (varchar(40))\n  update_time (timestamp(6))\n关联关系：\n  （无关联关系）\n适用场景 ：packingrule查询",
    # 2. t_packing_rule_detail
    "包装规则明细表，定义各包装层级的容器、容量、检查类型（不管控/同料号/同工单/同批次等）、是否称重等详细规范\n"
    "表名：t_packing_rule_detail\n模块：包装管理\n业务含义：包装规则明细表，定义各包装层级的容器、容量、检查类型（不管控/同料号/同工单/同批次等）、是否称重等详细规范\n关键字段：\n  id (varchar(40))\n  rule_id (varchar(40))\n  container_name (varchar(40))\n  container_level (int4)\n  container_capacity (numeric(16)\n  count_type (int4)\n  check_type (varchar(40))\n  weight_flag (varchar(1))\n  create_user_id (varchar(40))\n  create_time (timestamp(6))\n  update_user_id (varchar(40))\n  update_time (timestamp(6))\n关联关系：\n  JOIN t_packing_container ON t_packing_rule_detail.container_name = t_packing_container.container_name  --  包装规则明细→包装容器\n适用场景：packingrule明细数据查询",
    # 3. t_wms_doc_upn
    "UPN单据关联表，记录仓库单据与物料唯一编号(UPN)的关联关系，实现物料精确追溯\n"
    "表名：t_wms_doc_upn\n模块：仓库管理\n业务含义：UPN单据关联表，记录仓库单据与物料唯一编号(UPN)的关联关系，实现物料精确追溯\n关键字段：\n  id (character varying)\n  doc_id (character varying) -- 细项ID\n  item_id (character varying) -- 细项ID\n  upn (character varying) -- 唯一码\n  part_no (character varying) -- 物料编码\n  part_name (character varying) -- 物料名称\n  part_spec (character varying) -- 物料描述\n  qty (integer) -- 数量\n  lot_no (character varying) -- 批次\n  date_code (character varying) -- 生产日期\n  bin_code (character varying) -- bin值代码\n  supplier_code (character varying) -- 供应商代码\n  supplier_name (character varying) -- 供应商名称\n  customer_code (character varying) -- 客户编码\n  carton_no (character varying) -- 外箱\n  pallet_no (character varying) -- 栈板\n  container_no (character varying) -- 集装箱\n  update_user_id (character varying)\n  update_time (timestamp without time zone)\n  doc_no (character varying) -- 单据号\n  doc_category_code (character varying) -- 单据类别\n适用场景 ：\nwmsdoc数据查询",
    # 4. t_wms_wo_material_bill_detail
    "生产领料单明细表，记录领料单中具体物料的领用数量、已出数量、交接数量等行项目\n"
    "表名：t_wms_wo_material_bill_detail\n模块：仓库管理\n业务含义：生产领料单明细表，记录领料单中具体物料的领用数量、已出数量、交接数量等行项目\n关键字段：\n  id (character varying)\n  doc_id (character varying) -- 单据ID\n  item_seq (integer) -- 序号\n  part_id (character varying) -- 物料编码\n  unit_id (character varying) -- 单位\n  current_status (integer) -- 当前状态(0,创建;1,开始;2,完结)\n  warehouse_id (character varying) -- 出仓编码\n  need_fid (character varying) -- 用料清单ID\n  need_frowid (character varying) -- 用料清单行ID\n  lot_no (character varying) -- 批次\n  supplier_id (character varying) -- 供应商\n  bin_code (character varying) -- BIN值\n  upload_time (timestamp without time zone) -- 上传时间\n  create_time (timestamp without time zone)\n  update_user_id (character varying)\n  update_time (timestamp without time zone)\n  total_qty (numeric) -- 总数\n  out_qty (numeric) -- 已出数量\n  handover_qty (numeric) -- 交接数量\n  upload_qty (numeric) -- 上传数量\n  work_order (character varying) -- 工单\n适用场景：\nwmswo明细数据查询",
    # 5. t_packing_container
    "包装容器定义表，记录容器的名称、容量、类型、标签来源（自产/外部）等属性，是包装规则的基础数据\n"
    "表名：t_packing_container\n模块：包装管理\n业务含义：包装容器定义表，记录容器的名称、容量、类型、标签来源（自产/外部）等属性，是包装规则的基础数据\n关键字段：\n  id (character varying)\n  container_name (character varying) -- 容器名称\n  container_desc (character varying) -- 描述\n  container_capacity (numeric) -- 容量\n  container_type_code (character varying) -- 容器类型\n  chk_no_rule_id (character varying) -- 编号检查规则\n  label_from (integer) -- 标签来源(0,自己;1,外部)\n  label_file (character varying) -- 标签文件名称\n  is_enabled (character varying)\n  create_user_id (character varying)\n  create_time (timestamp without time zone)\n  update_user_id (character varying)\n  update_time (timestamp without time zone)\n  count_type (integer) -- 容量计算方式(0,计算子容器;1,计算SN)\n适用场景：\npackingcontainer数据查询",
]


async def score(client, items, label):
    r = await client.post(
        f"{BASE_URL}/generative_scoring",
        headers=HEADERS,
        json={
            "model": "qwen3-reranker-8b",
            "query": QUERY,
            "items": items,
            "label_token_ids": [9454, 2162],
        },
    )
    data = r.json()["data"]
    print(f"--- {label} ---")
    for item in data:
        idx = item["index"]
        score = item["score"]
        first_line = REAL_TEXTS[idx].split("\n")[0][:60]
        print(f"  score={score:.4f}  {first_line}")


async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1) 真实文本（业务意义 + full_text）
        await score(client, REAL_TEXTS, "真实文本 (business_meaning + full_text)")

        # 2) 只用 business_meaning（短文本）
        short = [t.split("\n")[0] for t in REAL_TEXTS]
        await score(client, short, "只用 business_meaning（短文本）")

        # 3) 截断到 200 字（去掉字段噪音）
        truncated_200 = [t[:200] for t in REAL_TEXTS]
        await score(client, truncated_200, "截断到 200 字")

        # 4) 截断到 100 字
        truncated_100 = [t[:100] for t in REAL_TEXTS]
        await score(client, truncated_100, "截断到 100 字")

        # 5) 只保留前 3 行（表名/模块/业务含义）
        first3 = ["\n".join(t.split("\n")[:3]) for t in REAL_TEXTS]
        await score(client, first3, "只保留前 3 行（表名/模块/业务含义）")


if __name__ == "__main__":
    asyncio.run(main())
