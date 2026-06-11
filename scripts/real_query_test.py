"""真实用户查询测试 v2 — 区分路由错误与视图执行错误。

修改点（对比 v1）：
  - 移除"纯产线名→M001"（改为 NL2SQL）
  - 移除"合格不→clarify"（改为 NL2SQL）
  - 区分"路由正确"vs"视图不存在"vs"路由错误"三类失败
"""

import asyncio
import json

import httpx

BASE_URL = "http://localhost:8000"

# ════════════════════════════════════════════════════════════════════
# 查询用例（修正预期）
# ════════════════════════════════════════════════════════════════════

QUERIES = [
    # ── 超短查询 ──
    ("超短", "产量", "metric", "M001"),
    ("超短", "良率", "metric", "M004"),
    ("超短", "在制", "metric", "M003"),
    ("超短", "库存", "metric", "M011"),
    ("超短", "故障", "metric", "M015"),
    ("超短", "FPY", "metric", "M005"),
    ("超短", "WIP", "metric", "M003"),
    ("超短", "MTTR", "metric", "M016"),
    ("超短", "IQC", "metric", "M007"),
    ("超短", "IPQC", "metric", "M008"),
    ("超短", "FQC", "metric", "M009"),
    ("超短", "完工", "metric", "M002"),
    ("超短", "产出", "metric", "M001"),
    ("超短", "日产", "metric", "M001"),
    ("超短", "领料", "metric", "M012"),
    ("超短", "到货", "metric", "M014"),
    ("超短", "点检", "metric", "M017"),
    ("超短", "维修", "metric", "M016"),
    ("超短", "不良", "metric", "M010"),
    ("超短", "缺陷", "metric", "M010"),
    ("超短", "停机", "metric", "M015"),
    ("超短", "坏了", "metric", "M015"),
    ("超短", "来料", "metric", "M007"),
    ("超短", "巡检", "metric", "M008"),
    ("超短", "成品", "metric", "M009"),

    # ── 口语化表达 ──
    ("口语", "今天产了多少", "metric", "M001"),
    ("口语", "做了多少个", "metric", "M001"),
    ("口语", "干了多少", "metric", "M001"),
    ("口语", "良率咋样", "metric", "M004"),
    ("口语", "今天干得怎么样", "metric", "M001"),
    ("口语", "这月干得咋样", "metric", "M001"),
    ("口语", "昨天过了多少", "metric", "M001"),
    ("口语", "搞了多少", "metric", "M001"),  # 需补充别名
    ("口语", "最近产出咋样", "metric", "M001"),
    ("口语", "今天做了多少", "metric", "M001"),
    ("口语", "A线产量多少", "metric", "M001"),
    ("口语", "SMT1线今天干得咋样", "metric", "M001"),
    ("口语", "A线良率多少", "metric", "M004"),
    ("口语", "B线通过率", "metric", "M004"),
    ("口语", "库存还有多少", "metric", "M011"),
    ("口语", "领了多少料", "metric", "M012"),
    ("口语", "设备最近怎么样", "metric", "M015"),  # 需修复时间词兜底
    ("口语", "到货了没", "metric", "M014"),
    ("口语", "不良多不多", "metric", "M010"),
    ("口语", "最近生产情况", "metric", "M001"),
    ("口语", "产出情况怎么样", "metric", "M001"),

    # ── 带产线的超短查询（修正：裸产线名→NL2SQL） ──
    ("产线", "A线", "nl2sql", ""),          # 裸产线名，不知道查什么
    ("产线", "B线", "nl2sql", ""),
    ("产线", "SMT1线", "nl2sql", ""),
    ("产线", "SMT1", "nl2sql", ""),
    ("产线", "A线产量", "metric", "M001"),
    ("产线", "B线良率", "metric", "M004"),
    ("产线", "SMT1线在制", "metric", "M003"),
    ("产线", "A线FPY", "metric", "M005"),
    ("产线", "SMT1线不良", "metric", "M010"),
    ("产线", "A线WIP", "metric", "M003"),
    ("产线", "B线yield", "metric", "M004"),  # 需补充 yield 别名
    ("产线", "A线今天", "metric", "M001"),
    ("产线", "SMT1线昨天", "metric", "M001"),

    # ── 中英混合 ──
    ("中英混", "SMT1线yield", "metric", "M004"),  # 需 yield 别名
    ("中英混", "A line良品率", "metric", "M004"),
    ("中英混", "line A良率", "metric", "M004"),
    ("中英混", "今天WIP多少", "metric", "M003"),
    ("中英混", "A线FPY咋样", "metric", "M005"),
    ("中英混", "SMT1 line yield", "metric", "M004"),  # 需 yield 别名

    # ── 带错别字/拼音 ──
    ("错别字", "良品lv", "metric", "M004"),    # 需模糊匹配
    ("错别字", "lian品率", "metric", "M004"),  # 需模糊匹配
    ("错别字", "在治工单", "metric", "M003"),   # 需别名
    ("错别字", "良平率", "metric", "M004"),     # 需别名
    ("错别字", "来料合格lv", "metric", "M007"),
    ("错别字", "产两", "metric", "M001"),       # 需别名
    ("错别字", "两率", "metric", "M004"),       # 需别名
    ("错别字", "再制", "metric", "M003"),       # 需别名
    ("错别字", "故章", "metric", "M015"),       # 需别名
    ("错别字", "点捡", "metric", "M017"),       # 需别名

    # ── 模糊指代 ──
    ("模糊", "最近咋样", "metric", "M001"),
    ("模糊", "今天情况", "metric", "M001"),
    ("模糊", "这周怎么样", "metric", "M001"),
    ("模糊", "最近的产出", "metric", "M001"),
    ("模糊", "库存情况", "metric", "M011"),
    ("模糊", "设备状态", "metric", "M015"),
    ("模糊", "质量那块", "metric", "M004"),     # 需补充别名，非 clarify

    # ── 仅时间词 ──
    ("时间", "昨天", "metric", "M001"),
    ("时间", "今天", "metric", "M001"),
    ("时间", "这周", "metric", "M001"),
    ("时间", "本周", "metric", "M001"),
    ("时间", "上个月", "metric", "M001"),
    ("时间", "去年", "metric", "M001"),
    ("时间", "最近一周", "metric", "M001"),
    ("时间", "近7天", "metric", "M001"),
    ("时间", "今天产量", "metric", "M001"),
    ("时间", "昨天良率", "metric", "M004"),
    ("时间", "本月在制", "metric", "M003"),

    # ── 歧义术语（修正："合格不"→NL2SQL） ──
    ("歧义", "合格率", "clarify", ""),
    ("歧义", "合格不", "nl2sql", ""),       # 是非判断，走 NL2SQL
    ("歧义", "不良率", "clarify", ""),
    ("歧义", "质量", "clarify", ""),
    ("歧义", "那个合格的", "nl2sql", ""),    # 是非判断

    # ── 多指标混合查询 ──
    ("多指标", "A线产量和良率", "multi_metric", "M001,M004"),
    ("多指标", "今天产量和良品率", "multi_metric", "M001,M004"),
    ("多指标", "SMT1线在制和FPY", "multi_metric", "M003,M005"),
    ("多指标", "库存和领料", "multi_metric", "M011,M012"),
    ("多指标", "A线良品率和FPY", "multi_metric", "M004,M005"),
    ("多指标", "故障和维修", "multi_metric", "M015,M016"),

    # ── NL2SQL 长尾查询 ──
    ("长尾", "帮我查个东西", "nl2sql", ""),
    ("长尾", "看看", "nl2sql", ""),
    ("长尾", "查一下", "nl2sql", ""),
    ("长尾", "那个SN的过站记录", "nl2sql", ""),
    ("长尾", "看看有没有返工的", "nl2sql", ""),
    ("长尾", "最近哪个产线最差", "nl2sql", ""),
    ("长尾", "这个月汇总一下", "nl2sql", ""),
    ("长尾", "还有多少没做完", "nl2sql", ""),
    ("长尾", "线体稼动率", "nl2sql", ""),
    ("长尾", "WO20240001工单进度", "nl2sql", ""),
    ("长尾", "SN ABC123过站详情", "nl2sql", ""),
    ("长尾", "上周哪个班次产量最高", "nl2sql", ""),
    ("长尾", "帮我对比一下A线和B线", "nl2sql", ""),
    ("长尾", "有没有异常", "nl2sql", ""),
    ("长尾", "行不行", "nl2sql", ""),
    ("长尾", "看一下", "nl2sql", ""),
    ("长尾", "查", "nl2sql", ""),
    ("长尾", "多少", "nl2sql", ""),
    ("长尾", "啥情况", "nl2sql", ""),
    ("长尾", "怎么样", "nl2sql", ""),

    # ── 极端输入 ──
    ("极端", "1", "nl2sql", ""),
    ("极端", "。。。", "nl2sql", ""),
    ("极端", "help", "nl2sql", ""),
    ("极端", "?", "nl2sql", ""),
    ("极端", "", "nl2sql", ""),
    ("极端", "   ", "nl2sql", ""),
]


async def test_route(query: str) -> dict:
    """调用路由 API。"""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(f"{BASE_URL}/api/metrics/route", json={"query": query})
            data = r.json()
            return {
                "channel": data.get("channel", "nl2sql"),
                "metric_id": data.get("metric_id", ""),
                "metric_name": data.get("metric_name", ""),
                "matched_term": data.get("matched_term", ""),
                "sql": data.get("sql", ""),
                "multi_metric_ids": data.get("multi_metric_ids", []),
            }
        except Exception as exc:
            return {"channel": "error", "error": str(exc)}


async def test_execute(query: str) -> dict:
    """通过 SSE 流实际执行查询。"""
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            async with client.stream("POST", f"{BASE_URL}/chat/stream", json={"query": query}) as response:
                result = {"channel": "unknown", "executed": False, "rows": 0, "error": ""}
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            node = data.get("node", "")
                            node_data = data.get("data", {})
                            if node == "done":
                                result["channel"] = node_data.get("channel", "nl2sql")
                                er = node_data.get("execution_results", [])
                                if er and isinstance(er, list) and len(er) > 0:
                                    first = er[0]
                                    result["executed"] = first.get("success", False)
                                    result["rows"] = first.get("rows", 0)
                                    result["error"] = first.get("error", "")
                        except json.JSONDecodeError:
                            pass
                return result
        except Exception as exc:
            return {"channel": "error", "executed": False, "error": str(exc)}


async def main():
    print("=" * 90)
    print("  MES 智能问数 — 真实用户查询路由测试 v2")
    print("  区分：路由错误 / 视图不存在 / 执行成功")
    print("=" * 90)

    total = len(QUERIES)
    route_stats = {"metric": 0, "multi_metric": 0, "clarify": 0, "nl2sql": 0, "error": 0}
    exec_stats = {"success": 0, "view_missing": 0, "exec_error": 0, "not_tested": 0}
    details = []

    print(f"\n共 {total} 条查询用例，开始测试...\n")

    for i, (category, query, expected_channel, expected_id) in enumerate(QUERIES):
        route_result = await test_route(query)
        channel = route_result["channel"]
        mid = route_result.get("metric_id", "")
        multi_ids = route_result.get("multi_metric_ids", [])

        route_stats[channel] = route_stats.get(channel, 0) + 1

        # 判断路由准确性
        match_status = "OK"
        if channel == expected_channel:
            if channel == "metric" and expected_id:
                if mid != expected_id:
                    match_status = f"WRONG_ID(exp={expected_id},got={mid})"
            elif channel == "multi_metric" and expected_id:
                exp_ids = set(expected_id.split(","))
                got_ids = set(multi_ids)
                if exp_ids != got_ids:
                    match_status = f"WRONG_IDS(exp={expected_id},got={','.join(sorted(got_ids))})"
        elif channel == "error":
            match_status = "ERROR"
        elif expected_channel == "nl2sql" and channel in ("metric", "multi_metric", "clarify"):
            match_status = "OVERMATCH"
        elif expected_channel in ("metric", "multi_metric", "clarify") and channel == "nl2sql":
            match_status = "MISSED"
        elif expected_channel == "clarify" and channel == "metric":
            match_status = "NO_CLARIFY"
        elif expected_channel == "metric" and channel == "clarify":
            match_status = "FALSE_CLARIFY"

        status = "PASS" if match_status == "OK" else f"FAIL({match_status})"

        detail = {
            "no": i + 1, "category": category, "query": query,
            "channel": channel, "metric_id": mid, "status": status,
            "expected_channel": expected_channel, "expected_id": expected_id,
            "exec_status": "",  # 待填充
        }

        line = f"  [{i+1:3d}/{total}] [{status:30s}] [{category:6s}] {query:28s}"
        if channel == "metric":
            line += f" -> metric  {mid}"
        elif channel == "multi_metric":
            line += f" -> multi   {','.join(multi_ids)}"
        elif channel == "clarify":
            line += " -> clarify"
        elif channel == "nl2sql":
            line += " -> NL2SQL"
        else:
            line += f" -> {channel}"
        print(line)
        details.append(detail)

    # ── 对命中视图的查询抽样执行 SQL ──
    print(f"\n{'='*90}")
    print("  SQL 执行测试（抽样命中视图的查询）")
    print(f"{'='*90}")

    metric_samples = [d for d in details if d["channel"] == "metric"][:15]
    for d in metric_samples:
        exec_result = await test_execute(d["query"])
        if exec_result["executed"]:
            d["exec_status"] = "OK"
            exec_stats["success"] += 1
        elif "does not exist" in exec_result.get("error", ""):
            d["exec_status"] = "VIEW_MISSING"
            exec_stats["view_missing"] += 1
        elif exec_result.get("error"):
            d["exec_status"] = f"ERR: {exec_result['error'][:50]}"
            exec_stats["exec_error"] += 1
        else:
            d["exec_status"] = "NO_RESULT"
            exec_stats["exec_error"] += 1

        rows = exec_result.get("rows", 0)
        print(f"  [{d['exec_status']:20s}] {d['query']:28s}  rows={rows}")

    exec_stats["not_tested"] = route_stats["metric"] + route_stats["multi_metric"] - len(metric_samples)

    # ════════════════════════════════════════════════════════════════
    # 汇总
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print("  路由统计")
    print("=" * 90)

    view_hit = route_stats["metric"] + route_stats["multi_metric"] + route_stats["clarify"]
    pass_count = sum(1 for d in details if "PASS" in d["status"])
    fail_count = sum(1 for d in details if "FAIL" in d["status"])

    print("\n  ┌─────────────────────────────────────────────────────┐")
    print(f"  │  指标视图直接查询 (metric):      {route_stats['metric']:>4}                  │")
    print(f"  │  多指标视图查询 (multi_metric):  {route_stats['multi_metric']:>4}                  │")
    print(f"  │  歧义追问 (clarify):             {route_stats['clarify']:>4}                  │")
    print(f"  │  NL2SQL 生成 SQL:                {route_stats['nl2sql']:>4}                  │")
    print(f"  │  错误:                           {route_stats['error']:>4}                  │")
    print("  ├─────────────────────────────────────────────────────┤")
    print(f"  │  总计:                           {total:>4}                  │")
    print(f"  │  视图命中率: {view_hit}/{total} = {view_hit/total*100:.1f}%{'':>20} │")
    print(f"  │  NL2SQL 占比: {route_stats['nl2sql']}/{total} = {route_stats['nl2sql']/total*100:.1f}%{'':>20} │")
    print(f"  │  路由准确率: {pass_count}/{total} = {pass_count/total*100:.1f}%{'':>20} │")
    print("  └─────────────────────────────────────────────────────┘")

    print(f"\n  SQL 执行统计（抽样 {len(metric_samples)} 条命中视图的查询）:")
    print(f"    执行成功:     {exec_stats['success']}")
    print(f"    视图不存在:   {exec_stats['view_missing']}")
    print(f"    其他执行错误: {exec_stats['exec_error']}")
    print(f"    未测试:       {exec_stats['not_tested']}")

    # 失败分类
    if fail_count > 0:
        print(f"\n  === 路由失败详情 ({fail_count} 条) ===")
        for d in details:
            if "FAIL" in d["status"]:
                print(f"    [{d['no']:3d}] [{d['category']:6s}] {d['query']:28s}  "
                      f"exp={d['expected_channel']} got={d['channel']}  {d['status']}")

    # 按类别
    print("\n  按场景分类:")
    print(f"  {'场景':<10s} {'总数':>5s} {'视图命中':>8s} {'命中率':>8s}")
    print(f"  {'-'*35}")
    by_cat = {}
    for d in details:
        cat = d["category"]
        by_cat.setdefault(cat, {"total": 0, "hit": 0})
        by_cat[cat]["total"] += 1
        if d["channel"] in ("metric", "multi_metric", "clarify"):
            by_cat[cat]["hit"] += 1
    for cat in sorted(by_cat):
        s = by_cat[cat]
        pct = s["hit"] / s["total"] * 100 if s["total"] else 0
        print(f"  {cat:<10s} {s['total']:>5d} {s['hit']:>8d} {pct:>7.1f}%")

    print(f"\n{'='*90}")
    print("  测试完成")
    print(f"{'='*90}")


asyncio.run(main())
