"""端到端测试：指标路由层全场景覆盖。"""

import asyncio
import json

import httpx

BASE_URL = "http://localhost:8000"


async def test(name: str, query: str, expected: dict) -> None:
    """测试单个指标路由场景。"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE_URL}/api/metrics/route", json={"query": query})
        data = r.json()

        channel = data.get("channel", "")
        checks = []

        if "channel" in expected:
            ok = expected["channel"] == channel
            checks.append(f"channel={'PASS' if ok else 'FALSE'}({channel})")
            if not ok:
                print(f"  FAIL {name}: 期望 channel={expected['channel']}, 实际={channel}")
                return

        if "metric_id" in expected and channel == "metric":
            ok = expected["metric_id"] == data.get("metric_id")
            checks.append(f"metric_id={'PASS' if ok else 'FALSE'}({data.get('metric_id')})")

        if "multi_metric_ids" in expected and channel == "multi_metric":
            actual_ids = set(data.get("multi_metric_ids", []))
            expected_ids = set(expected["multi_metric_ids"])
            ok = actual_ids == expected_ids
            checks.append(f"multi_ids={'PASS' if ok else 'FALSE'}({actual_ids})")

        if "candidates_count" in expected and channel == "clarify":
            actual_count = len(data.get("candidates", []))
            ok = expected["candidates_count"] == actual_count
            checks.append(f"candidates={'PASS' if ok else 'FALSE'}({actual_count})")

        if "sql" in expected and channel == "metric":
            sql = data.get("sql", "")
            ok = expected["sql"] in sql
            checks.append(f"sql={'PASS' if ok else 'FALSE'}")

        if "params" in expected and channel == "metric":
            actual_params = data.get("params", {})
            for k, v in expected["params"].items():
                ok = actual_params.get(k) == v
                checks.append(f"param.{k}={'PASS' if ok else 'FALSE'}({actual_params.get(k)})")

        status = "PASS" if all("PASS" in c for c in checks) else "FAIL"
        print(f"  {status} {name} | {' | '.join(checks)}")


async def test_sse(name: str, query: str, expected_nodes: list[str]) -> None:
    """测试 SSE 流式聊天。"""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{BASE_URL}/chat/stream",
            json={"query": query, "thread_id": f"e2e-{name}"},
        )
        nodes = []
        trace_id = None
        for line in r.text.split("\n"):
            if line.startswith("data: "):
                try:
                    event = json.loads(line[6:])
                    nodes.append(event.get("node", ""))
                    if event.get("node") == "done":
                        trace_id = event.get("trace_id")
                except json.JSONDecodeError:
                    pass

        matched = [n for n in expected_nodes if n in nodes]
        ok = len(matched) == len(expected_nodes)
        status = "PASS" if ok else "FAIL"
        trace_info = f"trace_id={trace_id[:8] if trace_id else 'N/A'}..." if trace_id else ""

        # 验证 trace 可查询
        trace_ok = False
        if trace_id:
            tr = await client.get(f"{BASE_URL}/api/trace/{trace_id}")
            trace_ok = tr.status_code == 200

        print(f"  {status} SSE: {name} | nodes={nodes} | {trace_info} | trace_query={'OK' if trace_ok else 'FAIL'}")


async def main():
    print("=" * 70)
    print("端到端测试：指标路由层")
    print("=" * 70)

    # ── 1. 单指标匹配 ──
    print("\n── 单指标匹配 ──")
    await test("良品率（基础）", "良品率是多少", {"channel": "metric", "metric_id": "M004", "sql": "v_m004_yield_rate"})
    await test("良品率+产线", "SMT1线的良品率", {"channel": "metric", "metric_id": "M004"})
    await test("FPY", "FPY是多少", {"channel": "metric", "metric_id": "M005", "sql": "v_m005_fpy"})
    await test("工单日产量", "今天的日产量", {"channel": "metric", "metric_id": "M001"})
    await test("在制工单", "在制工单数", {"channel": "metric", "metric_id": "M003"})
    await test("设备故障", "设备故障", {"channel": "metric", "metric_id": "M015"})
    await test("IQC来料合格率", "IQC合格率", {"channel": "metric", "metric_id": "M007"})
    await test("IPQC巡检合格率", "IPQC合格率", {"channel": "metric", "metric_id": "M008"})
    await test("实时库存", "实时库存", {"channel": "metric", "metric_id": "M011"})
    await test("FPY简称", "FPY", {"channel": "metric", "metric_id": "M005", "sql": "v_m005_fpy"})
    await test("通过率", "通过率", {"channel": "metric", "metric_id": "M004"})

    # ── 2. 多指标匹配 ──
    print("\n── 多指标匹配 ──")
    await test("良品率+FPY", "良品率和FPY", {"channel": "multi_metric", "multi_metric_ids": {"M004", "M005"}})
    await test("良品率+日产量", "日产量和良品率", {"channel": "multi_metric", "multi_metric_ids": {"M001", "M004"}})
    await test("在制+FPY", "在制和FPY", {"channel": "multi_metric", "multi_metric_ids": {"M003", "M005"}})

    # ── 3. 歧义术语 ──
    print("\n── 歧义术语 ──")
    await test("合格率（歧义）", "合格率是多少", {"channel": "clarify", "candidates_count": 4})
    await test("不良率（歧义）", "不良率", {"channel": "clarify", "candidates_count": 2})
    await test("质量相关（歧义）", "质量", {"channel": "clarify", "candidates_count": 6})

    # ── 4. 未匹配 → NL2SQL ──
    print("\n── 未匹配 → NL2SQL ──")
    await test("SN追溯", "SN ABC123的过站记录", {"channel": "nl2sql"})
    await test("天气查询", "今天天气怎么样", {"channel": "nl2sql"})
    await test("闲聊", "你好", {"channel": "nl2sql"})

    # ── 5. SSE 流式聊天 ──
    print("\n── SSE 流式聊天 ──")
    await test_sse("良品率查询", "SMT1线的良品率", ["metric", "done"])
    await test_sse("FPY查询", "A线的FPY", ["metric", "done"])
    await test_sse("多指标查询", "良品率和FPY", ["metric", "done"])
    await test_sse("歧义追问", "合格率", ["clarify", "done"])
    await test_sse("在制工单", "在制工单数", ["metric", "done"])

    # ── 6. 边界情况 ──
    print("\n── 边界情况 ──")
    await test("纯数字", "12345", {"channel": "nl2sql"})
    await test("只有标点", "！@#￥%", {"channel": "nl2sql"})

    print("\n" + "=" * 70)
    print("端到端测试完成")
    print("=" * 70)


asyncio.run(main())
