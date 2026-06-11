"""快速验证 NL2SQL 通道 SSE 工作流"""
import json
import asyncio
import httpx


async def main():
    query = "有没有返工的产品"
    payload = {"query": query, "thread_id": "e2e-nl2sql-quick", "user_id": "e2e_test"}

    print(f"发送: {query}")
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", "http://localhost:8000/chat/stream", json=payload) as resp:
            print(f"HTTP {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                event = json.loads(line.removeprefix("data: "))
                node = event.get("node", "")
                status = event.get("status", "")
                data = event.get("data", {})

                if node == "done":
                    channel = data.get("channel", "")
                    rows = sum(r.get("rows", 0) for r in data.get("execution_results", []) if isinstance(r, dict))
                    error = not data.get("execution_results") or any(
                        r.get("error") for r in data.get("execution_results", []) if isinstance(r, dict)
                    )
                    sql_count = len(data.get("final_sqls", []))
                    print(f"  done: channel={channel}, sql_count={sql_count}, total_rows={rows}, error={error}")
                    if data.get("empty_result"):
                        print(f"  empty_message: {data.get('empty_message')}")
                    print("  PASS" if channel == "nl2sql" else "  FAIL: expected nl2sql")
                    return
                elif data.get("sql"):
                    print(f"  [{node}] sql={data['sql'][:80]}...")
                else:
                    print(f"  [{node}] {status}")


asyncio.run(main())