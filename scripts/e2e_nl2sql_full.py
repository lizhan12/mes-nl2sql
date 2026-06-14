"""NL2SQL 通道 E2E 测试"""
import asyncio
import json

import httpx


async def test_one(query: str):
    payload = {"query": query, "thread_id": f"e2e-nl2sql-{query[:6]}", "user_id": "e2e_test"}
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", "http://localhost:8000/chat/stream", json=payload) as resp:
                channel = ""
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        e = json.loads(line[6:])
                        if e.get("node") == "done":
                            channel = e.get("data", {}).get("channel", "")
                ok = channel == "nl2sql"
                print(f"  [{'OK' if ok else 'FAIL'}] [{channel:15s}] {query}")
    except Exception as ex:
        print(f"  [FAIL] {query}: {ex}")

async def main():
    print("NL2SQL E2E 测试")
    print("-" * 30)
    await test_one("有没有返工的产品")
    await test_one("帮我查个东西")
    print("完成")

asyncio.run(main())
