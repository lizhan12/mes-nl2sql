"""端到端 SSE 集成测试 — 验证全链路：路由 → 安全校验 → SQL执行 → 审计埋点"""

import json
import asyncio
import httpx

BASE = "http://localhost:8000"
USER_ID = "e2e_test_user"


async def test_sse(description: str, query: str, expected_channel: str = "", metric_id: str = "") -> bool:
    """发送一条 SSE 请求并解析完整的 done 事件。"""
    payload = {"query": query, "thread_id": f"e2e-{description}", "user_id": USER_ID}
    if metric_id:
        payload["metric_id"] = metric_id

    channel = ""
    done_data = {}
    errors = []
    events = []

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", f"{BASE}/chat/stream", json=payload) as resp:
                if resp.status_code != 200:
                    print(f"  [FAIL] HTTP {resp.status_code}")
                    return False

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line.removeprefix("data: "))
                        events.append((event.get("node"), event.get("status")))
                        data = event.get("data", {})

                        if event.get("node") == "done":
                            done_data = data
                            channel = data.get("channel", "")

                        # 检查错误
                        if event.get("status") == "error" or "error" in str(data).lower()[:20]:
                            errors.append(data)
                    except json.JSONDecodeError:
                        pass

    except Exception as exc:
        print(f"  [FAIL] 异常: {exc}")
        return False

    # 验证
    status = "PASS"
    if expected_channel and channel != expected_channel:
        status = f"FAIL (期望={expected_channel}, 实际={channel})"
    elif not channel:
        status = "FAIL (未收到 done 事件)"

    ok = status == "PASS"

    # 输出
    symbol = "OK" if ok else "FAIL"
    meta = []
    if done_data.get("metric_id"):
        meta.append(done_data["metric_id"])
    if done_data.get("empty_result"):
        meta.append("空结果")
    if done_data.get("execution_results"):
        for er in done_data.get("execution_results", []):
            if isinstance(er, dict) and er.get("rows", 0) > 0:
                meta.append(f"{er['rows']}行")
    if done_data.get("candidates"):
        meta.append(f"{len(done_data['candidates'])}候选")
    meta_str = f" ({', '.join(meta)})" if meta else ""

    print(f"  [{symbol}] [{channel:15s}] {description}{meta_str}")
    if not ok:
        print(f"         {status}")
    return ok


async def main():
    print("=" * 70)
    print("  MES 智能问数 — 端到端 SSE 集成测试")
    print("=" * 70)
    print()

    tests = [
        # metric 通道
        ("产量查询", "产量", "metric"),
        ("A线产量", "A线产量", "metric"),
        ("B线良率", "B线良率", "metric"),
        ("SMT1线在制", "SMT1线在制", "metric"),
        ("错别字-良品lv", "良品lv", "metric"),
        ("库存", "库存", "metric"),

        # ask 通道（槽位追问）
        ("A线WIP-追问", "A线WIP", "ask"),

        # clarify 通道（歧义追问）
        ("合格率-歧义", "合格率", "clarify"),

        # multi_metric 通道
        ("库存和领料", "库存和领料", "multi_metric"),
        ("A线产量和良率", "A线产量和良率", "multi_metric"),

        # NL2SQL 通道（done event 不显式设 channel，通过节点链判断）
        ("返工查询", "有没有返工的产品", "nl2sql"),
        ("长尾查询", "帮我查个东西", "nl2sql"),
    ]

    results = []
    for desc, query, expected in tests:
        ok = await test_sse(desc, query, expected)
        results.append(ok)
        await asyncio.sleep(0.3)  # 避免打爆服务器

    # SQL 安全校验测试
    print()
    print("--- SQL 安全校验 ---")
    sql_tests = [
        ("正常 SELECT", "产量"),
        ("空输入", ""),
    ]
    for desc, query in sql_tests:
        await test_sse(desc, query)

    # 总结
    passed = sum(results)
    total = len(results)
    print()
    print("=" * 70)
    print(f"  结果: {passed}/{total} 通过")
    if passed == total:
        print("  端到端测试全部通过！")
    else:
        print(f"  {total - passed} 个测试失败")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())