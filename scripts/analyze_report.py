"""分析端到端回归测试报告。"""
import json
from pathlib import Path

report = json.loads(Path("temp_batch_e2e_report.json").read_text(encoding="utf-8"))
total = len(report)
correct = sum(1 for r in report if r.get("generation_correct"))
exec_ok = sum(1 for r in report if r.get("generated_execution_result", {}).get("success"))
expected_ok = sum(1 for r in report if r["expected_sql_exec"]["success"])

print("=== 端到端测试结果汇总 ===")
print(f"总用例数: {total}")
print(f"生成完全正确: {correct} / {total} ({correct / total * 100:.1f}%)")
print(f"SQL 执行成功: {exec_ok} / {total} ({exec_ok / total * 100:.1f}%)")
print(f"预期SQL执行成功: {expected_ok} / {total}")
print()

# 分类
cats = {
    "correct": [],
    "exec_ok_not_match": [],
    "exec_fail": [],
}
for r in report:
    if r.get("generation_correct"):
        cats["correct"].append(r)
    elif r.get("generated_execution_result", {}).get("success"):
        cats["exec_ok_not_match"].append(r)
    else:
        cats["exec_fail"].append(r)

print(f"--- 分类 ---")
print(f"完全正确: {len(cats['correct'])}")
print(f"SQL可执行但表/Join不匹配: {len(cats['exec_ok_not_match'])}")
print(f"SQL执行失败: {len(cats['exec_fail'])}")
print()

print("--- 执行失败用例详情 ---")
for r in cats["exec_fail"]:
    err = r.get("generated_error", "") or r.get("generated_execution_result", {}).get("error", "unknown")
    main_ok = "Y" if r.get("main_table_match") else "N"
    print(f"  #{r['index']} 主表匹配:{main_ok}")
    print(f"    问题: {r['question'][:80]}")
    print(f"    缺失表: {r.get('missing_related_tables', [])}")
    print(f"    缺失Join: {r.get('missing_expected_joins', [])}")
    print(f"    错误: {err[:200]}")
    print(f"    SQL: {r.get('generated_sql', '')[:200]}")
    print()

print("--- SQL可执行但未完全匹配 ---")
for r in cats["exec_ok_not_match"]:
    main_ok = "Y" if r.get("main_table_match") else "N"
    print(f"  #{r['index']} 主表匹配:{main_ok}")
    print(f"    问题: {r['question'][:80]}")
    print(f"    缺失表: {r.get('missing_related_tables', [])}")
    print(f"    缺失Join: {r.get('missing_expected_joins', [])}")
    print(f"    生成SQL: {r.get('generated_sql', '')[:250]}")
    print()

print("--- 完全正确 ---")
for r in cats["correct"]:
    print(f"  #{r['index']} {r['question'][:60]}")
