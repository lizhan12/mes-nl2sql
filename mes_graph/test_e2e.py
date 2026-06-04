import json, time, requests

BASE = "http://127.0.0.1:8002"

tests = [
    "查询最近一周入库数量最多的前10个物料",
    "今天各产线完成了多少工单",
    "查询库存数量低于100的物料",
]

for q in tests:
    print(f"\n{'='*60}")
    print(f"Q: {q}")
    start = time.time()
    r = requests.post(f"{BASE}/nl2sql", json={"query": q}, timeout=180)
    elapsed = time.time() - start
    data = r.json()
    print(f"Status: {r.status_code} | Time: {elapsed:.1f}s | Safe: {data['safe']}")
    print(f"SQL: {data['sql'][:200]}...")
    print(f"Retry: {data.get('retry_count', 0)}")
    exec_result = data.get("execution_result")
    if exec_result:
        print(f"Exec: success={exec_result.get('success')}, rows={exec_result.get('rows')}")
        if exec_result.get("preview"):
            print(f"Preview: {json.dumps(exec_result['preview'][:2], ensure_ascii=False)}")
        if exec_result.get("error"):
            print(f"Error: {exec_result['error'][:200]}")
    if data.get("error"):
        print(f"App Error: {data['error'][:200]}")