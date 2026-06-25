"""诊断：直接把 query 和 schema_results 的 rerank 文本喂给 vLLM，看真实打分。"""

import asyncio
import json

import httpx


QUERY = "查询包装规则为69b254c9a059eeeb74c433aa明细"
BASE_URL = "http://192.168.0.76:8001"
API_KEY = "sk-wlmdnlcicswgoealbouetyyuedswzyousvwfqgazncwqkxgo"
MODEL = "qwen3-reranker-8b"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# 从刚才的 rerank 前的 schema_results 抽出 business_meaning + full_text
# 我用最相关的 5 条
SCHEMA_TEXTS = [
    # 1. t_packing_rule
    "包装规则配置表，用于定义产品或订单的包装规范，关联包装层级和容器信息\n"
    "表名: t_packing_rule\n模块: 包装管理\n业务含义: ...(full_text 摘要)",
    # 2. t_packing_rule_detail
    "包装规则明细表，定义各包装层级的容器、容量、检查类型...\n"
    "表名: t_packing_rule_detail\n模块: 包装管理\n业务含义: ...",
    # 3. t_wms_doc_upn
    "UPN单据关联表，记录仓库单据与物料唯一编号(UPN)的关联关系，实现物料精确追溯\n"
    "表名: t_wms_doc_upn\n模块: WMS\n业务含义: ...",
    # 4. t_packing_container
    "包装容器定义表，记录容器的名称、容量、类型、标签来源（自产/外部）等属性\n"
    "表名: t_packing_container\n模块: 包装管理\n业务含义: ...",
    # 5. t_pd_sn_defect_detail
    "SN缺陷明细\n表名: t_pd_sn_defect_detail\n模块: 生产",
]


async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1) 用 query 直接调 vLLM rerank
        payload = {
            "model": MODEL,
            "query": QUERY,
            "items": SCHEMA_TEXTS,
            "label_token_ids": [9454, 2162],
        }
        r = await client.post(
            f"{BASE_URL}/generative_scoring", headers=HEADERS, json=payload
        )
        data = r.json()
        print("=" * 80)
        print(f"Query: {QUERY}")
        print("=" * 80)
        for item in data["data"]:
            idx = item["index"]
            score = item["score"]
            print(f"  index={idx}  score={score:.4f}")
            print(f"    text={SCHEMA_TEXTS[idx][:120]}...")

        # 2) 同样的内容，但 candidate 文本加上表名
        print()
        print("=" * 80)
        print("对比：在文本前面加 '表名: t_packing_rule' 等")
        print("=" * 80)
        enriched = [
            "t_packing_rule\n" + t for t in SCHEMA_TEXTS
        ]
        payload2 = {
            "model": MODEL,
            "query": QUERY,
            "items": enriched,
            "label_token_ids": [9454, 2162],
        }
        r = await client.post(
            f"{BASE_URL}/generative_scoring", headers=HEADERS, json=payload2
        )
        data2 = r.json()
        for item in data2["data"]:
            idx = item["index"]
            score = item["score"]
            print(f"  index={idx}  score={score:.4f}")
            print(f"    text={enriched[idx][:120]}...")

        # 3) 对比：只给表名（极短文本）
        print()
        print("=" * 80)
        print("对比：只给 business_meaning 单行（短文本）")
        print("=" * 80)
        short = [
            "包装规则配置表，用于定义产品或订单的包装规范，关联包装层级和容器信息",
            "包装规则明细表，定义各包装层级的容器、容量、检查类型",
            "UPN单据关联表，记录仓库单据与物料唯一编号的关联关系",
            "包装容器定义表，记录容器的名称、容量、类型、标签来源",
            "SN缺陷明细",
        ]
        payload3 = {
            "model": MODEL,
            "query": QUERY,
            "items": short,
            "label_token_ids": [9454, 2162],
        }
        r = await client.post(
            f"{BASE_URL}/generative_scoring", headers=HEADERS, json=payload3
        )
        data3 = r.json()
        for item in data3["data"]:
            idx = item["index"]
            score = item["score"]
            print(f"  index={idx}  score={score:.4f}  text={short[idx]!r}")


if __name__ == "__main__":
    asyncio.run(main())
