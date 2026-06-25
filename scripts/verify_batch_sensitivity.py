"""验证：vLLM generative_scoring 的分数是 batch 内 softmax 归一化的相对概率。"""

import asyncio

import httpx


API_KEY = "sk-wlmdnlcicswgoealbouetyyuedswzyousvwfqgazncwqkxgo"
BASE_URL = "http://192.168.0.76:8001"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# 固定 5 个"无关"占位 doc + 1 个目标 doc，对比不同 batch 大小下目标 doc 的分数
TARGET = "包装规则明细表，定义各包装层级的容器、容量、检查类型"
DISTRACTOR = "不相关的随机文本" * 5


async def score_one(client, target, distractors, label):
    items = [target] + distractors
    r = await client.post(
        f"{BASE_URL}/generative_scoring",
        headers=HEADERS,
        json={
            "model": "qwen3-reranker-8b",
            "query": "查询包装规则为69b254c9a059eeeb74c433aa明细",
            "items": items,
            "label_token_ids": [9454, 2162],
        },
    )
    data = r.json()["data"]
    target_score = data[0]["score"]
    other_scores = [d["score"] for d in data[1:]]
    print(f"  [{label}] batch_size={len(items):2d}  target(score[0])={target_score:.4f}  "
          f"min={min(other_scores):.4f}  max={max(other_scores):.4f}")


async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("对比：固定 target 文本 + 不同数量 distractors（noise）")
        print("=" * 70)
        for n in [1, 5, 10, 20, 30, 50, 64, 100]:
            distractors = [f"{DISTRACTOR} #{i}" for i in range(n)]
            await score_one(client, TARGET, distractors, f"n_distract={n}")


if __name__ == "__main__":
    asyncio.run(main())
