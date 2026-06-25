"""验证：vLLM /generative_scoring 内部用的 prompt 模板是否正确。

Qwen3-Reranker 官方要求 prompt 格式：
<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n
<|im_start|>user
<Instruct>: {instruct}
<Query>: {query}
<Document>: {document}<|im_end|>\n
<|im_start|>assistant\n<think>\n\n</think>\n\n
"""

import asyncio

import httpx


# 标准 vLLM 端点调用
async def call_vllm_score(client, query, doc):
    r = await client.post(
        "http://192.168.0.76:8001/generative_scoring",
        headers={"Authorization": "Bearer sk-wlmdnlcicswgoealbouetyyuedswzyousvwfqgazncwqkxgo",
                 "Content-Type": "application/json"},
        json={
            "model": "qwen3-reranker-8b",
            "query": query,
            "items": [doc],
            "label_token_ids": [9454, 2162],
        },
    )
    return r.json()["data"][0]["score"]


# vLLM chat completions 手工拼 prompt
QWEN3_RERANKER_PROMPT = (
    "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n"
    "<|im_start|>user\n"
    "<Instruct>: Given a web search query, retrieve relevant passages that answer the query\n"
    "<Query>: {query}\n"
    "<Document>: {doc}<|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n\n"
)


async def call_vllm_chat(client, query, doc):
    prompt = QWEN3_RERANKER_PROMPT.format(query=query, doc=doc)
    r = await client.post(
        "http://192.168.0.76:8001/v1/completions",
        headers={"Authorization": "Bearer sk-wlmdnlcicswgoealbouetyyuedswzyousvwfqgazncwqkxgo",
                 "Content-Type": "application/json"},
        json={
            "model": "qwen3-reranker-8b",
            "prompt": prompt,
            "max_tokens": 1,
            "temperature": 0.0,
            "logprobs": 5,
        },
    )
    print(f"  /v1/completions status={r.status_code}  body={r.text[:500]}")


async def main():
    query = "查询包装规则为69b254c9a059eeeb74c433aa明细"
    docs = [
        ("t_packing_rule", "包装规则配置表，用于定义产品或订单的包装规范，关联包装层级和容器信息"),
        ("t_packing_rule_detail", "包装规则明细表，定义各包装层级的容器、容量、检查类型"),
        ("t_tool_maintenance_info", "工装治具维保记录表"),
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, doc in docs:
            print(f"--- {name} ---")
            print(f"  doc = {doc!r}")
            # 1) 直接调 /generative_scoring
            score1 = await call_vllm_score(client, query, doc)
            print(f"  /generative_scoring score = {score1:.4f}")
            # 2) 手工拼 Qwen3-Reranker 官方 prompt，调 /v1/completions
            await call_vllm_chat(client, query, doc)
            print()


if __name__ == "__main__":
    asyncio.run(main())
