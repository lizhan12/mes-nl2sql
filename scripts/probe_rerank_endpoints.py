"""探测本地 Rerank 服务的实际端点路径。"""

import asyncio
import httpx


BASE_URL = "http://192.168.0.76:8001"
API_KEY = "sk-wlmdnlcicswgoealbouetyyuedswzyousvwfqgazncwqkxgo"
MODEL = "Qwen3-Reranker-8B"

# 常见 vLLM / 其它推理框架 rerank 端点候选
CANDIDATE_PATHS = [
    "/v1/rerank",
    "/v1/ranking",
    "/v1/score",
    "/v1/rerank/score",
    "/v1/embeddings",  # 用于对比：vLLM 也常把 rerank 当作特殊 embeddings 暴露
    "/score",
    "/rerank",
    "/ranking",
]

QUERY = "今天上海天气怎么样"
DOCS = [
    "北京今天晴转多云，最高气温 28 度。",
    "上海今日有雷阵雨，气温 22 到 26 度，出门记得带伞。",
    "广州天气炎热，35 度高温预警。",
]


async def probe():
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        # 1) 列出每个候选路径的 GET 状态
        print("=" * 60)
        print("Step 1: GET 探测各路径")
        print("=" * 60)
        for p in CANDIDATE_PATHS:
            try:
                r = await client.get(f"{BASE_URL}{p}", headers=headers)
                print(f"  GET {p:30s}  -> {r.status_code}  {r.text[:100]!r}")
            except Exception as e:
                print(f"  GET {p:30s}  -> ERROR: {e}")

        # 2) 用 rerank payload POST 探测
        print()
        print("=" * 60)
        print("Step 2: POST 探测各路径 (payload=rerank)")
        print("=" * 60)
        payload_rerank = {
            "model": MODEL,
            "query": QUERY,
            "documents": DOCS,
            "top_n": 3,
        }
        for p in CANDIDATE_PATHS:
            try:
                r = await client.post(
                    f"{BASE_URL}{p}", headers=headers, json=payload_rerank
                )
                snippet = r.text[:150].replace("\n", " ")
                print(f"  POST {p:30s} -> {r.status_code}  {snippet!r}")
            except Exception as e:
                print(f"  POST {p:30s} -> ERROR: {e}")

        # 3) 探测 OpenAI 兼容根路径
        print()
        print("=" * 60)
        print("Step 3: 根路径 /")
        print("=" * 60)
        try:
            r = await client.get(f"{BASE_URL}/", headers=headers)
            print(f"  GET /  -> {r.status_code}")
            print(f"  Body: {r.text[:500]}")
        except Exception as e:
            print(f"  GET /  -> ERROR: {e}")

        # 4) 探测 /openapi.json / /docs
        print()
        print("=" * 60)
        print("Step 4: OpenAPI 文档")
        print("=" * 60)
        for p in ["/openapi.json", "/docs", "/redoc"]:
            try:
                r = await client.get(f"{BASE_URL}{p}", headers=headers)
                print(f"  GET {p:20s} -> {r.status_code}  {r.text[:200]!r}")
            except Exception as e:
                print(f"  GET {p:20s} -> ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(probe())
