"""对比 use_rerank=true/false 的搜索结果。"""

import asyncio
import json

import httpx


URL = "http://localhost:8000/api/knowledge/search"
QUERY = "查询包装规则为69b254c9a059eeeb74c433aa明细"
PAYLOAD_BASE = {
    "query": QUERY,
    "search_types": ["few_shot", "fields", "schema", "runtime_rule"],
    "top_k": 10,
    "similarity_threshold": 0.55,
    "rerank_top_n": None,
}


async def call(client: httpx.AsyncClient, use_rerank: bool):
    payload = {**PAYLOAD_BASE, "use_rerank": use_rerank}
    r = await client.post(URL, json=payload, timeout=60.0)
    r.raise_for_status()
    return r.json()


def summarize(data: dict, label: str):
    print()
    print("=" * 80)
    print(f"[{label}]  use_rerank = 分数对比")
    print("=" * 80)
    for section in ("schema_results", "few_shot_results", "field_results", "runtime_rule_results"):
        items = data.get(section) or []
        if not items:
            continue
        print()
        print(f"--- {section} ({len(items)} 条) ---")
        for i, it in enumerate(items, 1):
            score = it.get("score", 0.0)
            mt = it.get("match_type", "")
            if section == "schema_results":
                txt = f"{it.get('table_name','')} :: {it.get('business_meaning','')[:50]}"
            elif section == "few_shot_results":
                txt = f"{it.get('question','')[:50]}  (match={mt})"
            elif section == "field_results":
                txt = f"{it.get('table_name','')}.{it.get('field_name','')}  ::  {it.get('comment','')[:30]}"
            elif section == "runtime_rule_results":
                txt = f"{it.get('question','')[:50]}"
            else:
                txt = ""
            print(f"  {i:2d}. score={score:.4f}  {txt}")


async def main():
    async with httpx.AsyncClient() as client:
        no_rerank = await call(client, use_rerank=False)
        yes_rerank = await call(client, use_rerank=True)

    summarize(no_rerank, "未 rerank（原始向量分数）")
    summarize(yes_rerank, "rerank 后")

    # 直接对比 schema_results 排序与分数变化
    print()
    print("=" * 80)
    print("schema_results 顺序对比（rerank 前后）")
    print("=" * 80)
    before = no_rerank.get("schema_results") or []
    after = yes_rerank.get("schema_results") or []
    for i in range(max(len(before), len(after))):
        b = before[i] if i < len(before) else None
        a = after[i] if i < len(after) else None
        if b:
            print(f"  前[{i+1}]  score={b['score']:.4f}  {b['table_name']}  {b['business_meaning'][:30]}")
        if a:
            print(f"  后[{i+1}]  score={a['score']:.4f}  {a['table_name']}  {a['business_meaning'][:30]}")
        if b or a:
            print()


if __name__ == "__main__":
    asyncio.run(main())
