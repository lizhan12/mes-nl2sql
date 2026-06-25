"""探测 /generative_scoring 端点接受的请求格式。"""

import asyncio
import json

import httpx


API_KEY = "sk-wlmdnlcicswgoealbouetyyuedswzyousvwfqgazncwqkxgo"
MODEL = "Qwen3-Reranker-8B"
BASE_URL = "http://192.168.0.76:8001"

QUERY = "今天上海天气怎么样"
DOCS = [
    "北京今天晴转多云，最高气温 28 度。",
    "上海今日有雷阵雨，气温 22 到 26 度，出门记得带伞。",
    "广州天气炎热，35 度高温预警。",
]

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


async def try_post(client: httpx.AsyncClient, path: str, payload: dict, label: str):
    print("=" * 60)
    print(f"[{label}] POST {path}")
    print(f"Payload: {json.dumps(payload, ensure_ascii=False)[:400]}")
    print("=" * 60)
    try:
        r = await client.post(f"{BASE_URL}{path}", headers=HEADERS, json=payload)
        print(f"Status: {r.status_code}")
        print(f"Body: {r.text[:1000]}")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
    print()


async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1) 极简 payload：model + query + documents
        await try_post(
            client,
            "/generative_scoring",
            {"model": MODEL, "query": QUERY, "documents": DOCS},
            "A: model+query+documents",
        )

        # 2) 加 input_text / input_texts
        await try_post(
            client,
            "/generative_scoring",
            {
                "model": MODEL,
                "input": {"query": QUERY, "documents": DOCS},
            },
            "B: input={query,documents}",
        )

        # 3) 加 prompts 字段
        await try_post(
            client,
            "/generative_scoring",
            {
                "model": MODEL,
                "prompts": [f"Query: {QUERY}\nDocument: {d}\nRelevant:" for d in DOCS],
            },
            "C: prompts=[...]",
        )

        # 4) 加 task 字段
        await try_post(
            client,
            "/generative_scoring",
            {
                "model": MODEL,
                "task": "rerank",
                "query": QUERY,
                "documents": DOCS,
            },
            "D: task=rerank",
        )

        # 5) 用 OpenAI 风格 chat completions（Qwen3-Reranker 通常用 chat template + yes/no 输出）
        # Qwen3-Reranker prompt 格式:
        # <|im_start|>system\n...<|im_end|>\n<|im_start|>user\n<Instruct>: ...
        # <|im_start|>assistant\n
        sys_prompt = (
            'You are a helpful assistant that ranks documents based on relevance to a query. '
            'Output only "yes" or "no" for each document.'
        )
        user_prompt = f"<Instruct>: Given a query, determine if the following document is relevant.\n<Query>: {QUERY}\n"
        for i, d in enumerate(DOCS):
            user_prompt += f"<Document {i+1}>: {d}\n"
        await try_post(
            client,
            "/v1/chat/completions",
            {
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 256,
                "temperature": 0.0,
            },
            "E: /v1/chat/completions with yes/no prompt",
        )


if __name__ == "__main__":
    asyncio.run(main())
