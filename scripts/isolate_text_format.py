"""隔离实验：固定 10 条 schema 候选，固定 query，只改 candidate 文本格式。"""

import asyncio

import httpx


QUERY = "查询包装规则为69b254c9a059eeeb74c433aa明细"

# 固定 10 条 business_meaning
BMS = [
    "包装规则配置表，用于定义产品或订单的包装规范，关联包装层级和容器信息",
    "包装规则明细表，定义各包装层级的容器、容量、检查类型（不管控/同料号/同工单/同批次等）、是否称重等详细规范",
    "UPN单据关联表，记录仓库单据与物料唯一编号(UPN)的关联关系，实现物料精确追溯",
    "生产领料单明细表，记录领料单中具体物料的领用数量、已出数量、交接数量等行项目",
    "包装容器定义表，记录容器的名称、容量、类型、标签来源（自产/外部）等属性，是包装规则的基础数据",
    "编码规则定义，配置条码/序列号的生成规则，包括前缀、流水号、日期格式等编码模板",
    "标签解析规则组，定义从产线设备获取的标签数据的解析规则",
    "编码规则组，将多个编码规则组合为规则组，供物料料号引用以确定其条码编码方式",
    "SN缺陷明细",
    "生产领料单主表",
]

NAMES = [
    "t_packing_rule", "t_packing_rule_detail", "t_wms_doc_upn",
    "t_wms_wo_material_bill_detail", "t_packing_container", "t_bc_encode_rule",
    "t_lb_label_parse_rule_group", "t_bc_encode_rule_group",
    "t_pd_sn_defect_detail", "t_wms_wo_material_bill",
]

# 5 种文本格式
VARIANTS = {
    "F1: 只 business_meaning": BMS,
    "F2: bm + 表名": [f"{bm}\n表名：{n}" for bm, n in zip(BMS, NAMES)],
    "F3: bm + 表名 + 模块": [
        f"{bm}\n表名：{n}\n模块：包装管理" if i < 2 else
        f"{bm}\n表名：{n}\n模块：仓库管理" if i in (2, 3, 9) else
        f"{bm}\n表名：{n}\n模块：标签/条码/生产"
        for i, (bm, n) in enumerate(zip(BMS, NAMES))
    ],
    "F4: bm + 表名 + 适用场景": [
        f"{BMS[i]}\n表名：{NAMES[i]}\n适用场景：{scen}"
        for i, scen in enumerate([
            "packingrule查询", "packingrule明细数据查询", "wmsdoc数据查询",
            "wmswo明细数据查询", "packingcontainer数据查询", "barcode编码生成",
            "label解析", "编码组合", "SN缺陷查询", "wmswo查询",
        ])
    ],
    "F5: bm + 完整 full_text (旧实现)": [
        bm + "\n表名：" + n + "\n关键字段：id, create_time, update_time\n适用场景：xxx"
        for bm, n in zip(BMS, NAMES)
    ],
}


async def score(client, items):
    r = await client.post(
        "http://192.168.0.76:8001/generative_scoring",
        headers={"Authorization": "Bearer sk-wlmdnlcicswgoealbouetyyuedswzyousvwfqgazncwqkxgo",
                 "Content-Type": "application/json"},
        json={
            "model": "qwen3-reranker-8b",
            "query": QUERY,
            "items": items,
            "label_token_ids": [9454, 2162],
        },
    )
    return r.json()["data"]


async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        for label, items in VARIANTS.items():
            data = await score(client, items)
            ranked = sorted(data, key=lambda x: -x["score"])
            print(f"\n=== {label} ===")
            for d in ranked[:5]:
                idx = d["index"]
                print(f"  score={d['score']:.4f}  {NAMES[idx]:30s}  {BMS[idx][:30]}")


if __name__ == "__main__":
    asyncio.run(main())
