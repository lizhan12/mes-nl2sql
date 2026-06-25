"""看真实 schema 召回结果的 full_text 长度和样本。"""

import asyncio
import json

import httpx


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "http://localhost:8000/api/knowledge/search",
            json={
                "query": "查询包装规则为69b254c9a059eeeb74c433aa明细",
                "search_types": ["schema"],
                "top_k": 5,
                "similarity_threshold": 0.0,
                "use_rerank": False,
            },
        )
    data = r.json()
    for i, it in enumerate(data.get("schema_results", []), 1):
        bm = it.get("business_meaning", "")
        ft = it.get("full_text", "")
        print(f"--- schema_result #{i}: {it.get('table_name')} ---")
        print(f"  business_meaning ({len(bm)} chars):")
        print(f"    {bm!r}")
        print(f"  full_text ({len(ft)} chars):")
        print(f"    {ft[:600]!r}")
        if len(ft) > 600:
            print(f"    ... (省略中间 {len(ft) - 1200} 字) ...")
            print(f"    {ft[-300:]!r}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
