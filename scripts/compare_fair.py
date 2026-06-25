"""公平对比：use_rerank=True/False 都用 recall_k=30，再各自取 top 8。"""

import asyncio

import httpx


URL = "http://localhost:8000/api/knowledge/search"
QUERY = "查询包装规则为69b254c9a059eeeb74c433aa明细"
BASE = {
    "query": QUERY,
    "search_types": ["schema"],
    "top_k": 30,  # 用 recall_k 作为 top_k，让两路召回集一致
    "similarity_threshold": 0.55,
    "rerank_top_n": None,
}


async def call(client, use_rerank):
    payload = {**BASE, "use_rerank": use_rerank}
    r = await client.post(URL, json=payload, timeout=60.0)
    r.raise_for_status()
    return r.json()


def show(data, label):
    print()
    print(f"--- {label} ---")
    items = data.get("schema_results", [])
    for i, it in enumerate(items[:10], 1):
        print(f"  {i:2d}. score={it['score']:.4f}  {it['table_name']:35s}  {it['business_meaning'][:30]}")


async def main():
    async with httpx.AsyncClient() as client:
        no_rerank = await call(client, use_rerank=False)
        yes_rerank = await call(client, use_rerank=True)
    show(no_rerank, "未 rerank (top 30 召回按向量分)")
    show(yes_rerank, "rerank 后 (top 30 召回 rerank 取前 N)")


if __name__ == "__main__":
    asyncio.run(main())
