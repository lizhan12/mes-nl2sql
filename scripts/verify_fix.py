"""快速验证：测试 S1-R1 查询是否不再使用不存在的 defect_id 列。"""

import json

import requests

URL = "http://localhost:8000/chat/stream"
Q = '帮我查一下工单 "WO-2024-001" 的不良情况，包括不良总数、不良SN数、不良代码分布。'

r = requests.post(URL, json={"query": Q, "thread_id": "verify-fix-v2", "user_id": "test"}, stream=True, timeout=180)
for line in r.iter_lines(decode_unicode=True):
    if not line or not line.startswith("data: "):
        continue
    d = json.loads(line[6:])
    node = d.get("node", "")
    if node == "sql_gen":
        sqls = d["data"].get("generated_sqls", [])
        for s in sqls:
            print("GENERATED:", s[:600])
    if node == "done":
        data = d["data"]
        sqls = data.get("final_sqls", [])
        for s in sqls:
            print("FINAL:", s[:600])
        er = data.get("execution_results", [])
        if er:
            r0 = er[0] if isinstance(er, list) else er
            print("EXEC_SUCCESS:", r0.get("success"))
            err = r0.get("error", "")
            print("EXEC_ERROR:", err[:300] if err else "NONE")
            if not r0.get("success"):
                print(">>> STILL FAILING!")
            else:
                print(">>> FIX VERIFIED!")
