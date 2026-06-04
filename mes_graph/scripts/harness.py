"""Harness CLI：评测、进化、引导运行时学习。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.harness.evolution import (
    build_evolved_few_shot_text,
    build_runtime_rule,
    merge_runtime_rules,
    should_promote_report_item,
)
from src.harness.knowledge import (
    get_cases_path,
    get_evolved_few_shot_path,
    get_runtime_rules_path,
    load_cases,
    load_json_file,
    load_runtime_rules,
    normalize_question,
    save_cases,
    save_evolved_few_shot_text,
    save_runtime_rules,
)
from src.harness.online_service import (
    analyze_failures_online_service,
    evolve_online_service,
    list_candidates_service,
    list_failure_cases_service,
    label_failure_case_service,
    publish_approved_service,
    review_candidate_service,
)
from src.harness.runner import evaluate_cases, load_cases_from_csv


DEFAULT_CSV_PATH = Path("mes联表测试问题清单_含完整SQL.csv")
DEFAULT_REPORT_PATH = Path("temp_batch_e2e_report.json")


def bootstrap_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    cases = load_cases_from_csv(csv_path)
    save_cases(cases)
    return cases


def evolve_from_report(report_path: Path, include_correct_with_retry: bool = True) -> dict[str, int]:
    report = load_json_file(report_path, [])
    if not isinstance(report, list):
        raise ValueError(f"报告格式错误: {report_path}")

    cases = load_cases()
    case_by_id = {str(case.get("case_id")): case for case in cases}
    case_by_question = {str(case.get("question")): case for case in cases}
    candidates: list[dict[str, Any]] = []
    for item in report:
        if not isinstance(item, dict):
            continue
        case = case_by_id.get(str(item.get("case_id"))) or case_by_question.get(str(item.get("question")))
        if case:
            item.setdefault("expected_sql", case.get("expected_sql", ""))
        if should_promote_report_item(item):
            candidates.append(item)
            continue
        retry_count = int(item.get("generated_retry_count") or 0)
        if include_correct_with_retry and retry_count > 0:
            candidates.append(item)

    new_rules = [build_runtime_rule(item) for item in candidates]
    merged_rules = merge_runtime_rules(load_runtime_rules(), new_rules)
    save_runtime_rules(merged_rules)
    save_evolved_few_shot_text(build_evolved_few_shot_text(candidates))

    summary = {
        "promoted_cases": len(candidates),
        "runtime_rules_total": len(merged_rules),
        "runtime_rules_path": str(get_runtime_rules_path()),
        "few_shot_path": str(get_evolved_few_shot_path()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def run_harness(base_url: str, report_path: Path, max_workers: int, evolve: bool) -> None:
    cases = load_cases()
    if not cases:
        cases = bootstrap_from_csv(DEFAULT_CSV_PATH)

    report = evaluate_cases(
        cases=cases,
        base_url=base_url,
        report_path=report_path,
        max_workers=max_workers,
    )
    summary = {
        "total": len(report),
        "generated_exec_ok": sum(
            1 for item in report if (item.get("generated_execution_result") or {}).get("success")
        ),
        "generation_correct": sum(1 for item in report if item.get("generation_correct")),
        "report_path": str(report_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if evolve:
        evolve_from_report(report_path)


def evolve_online(limit: int = 200, sync_failures: bool = True) -> dict[str, int | str]:
    summary = evolve_online_service(limit=limit, sync_failures=sync_failures)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def analyze_failures_online(limit: int = 200, sync_failures: bool = True) -> dict[str, int]:
    summary = analyze_failures_online_service(limit=limit, sync_failures=sync_failures)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def list_candidates(status: str | None, limit: int) -> list[dict[str, Any]]:
    items = list_candidates_service(status=status, limit=limit)
    print(json.dumps(items, ensure_ascii=False, indent=2, default=str))
    return items


def review_candidate(candidate_id: int, action: str, note: str = "") -> None:
    print(json.dumps(review_candidate_service(candidate_id=candidate_id, action=action, note=note), ensure_ascii=False, indent=2))


def publish_approved(version: str | None = None) -> dict[str, int | str]:
    summary = publish_approved_service(version=version)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def list_failure_cases(status: str | None, limit: int) -> list[dict[str, Any]]:
    items = list_failure_cases_service(status=status, limit=limit)
    print(json.dumps(items, ensure_ascii=False, indent=2, default=str))
    return items


def label_failure_case(failure_case_id: int, correct_sql: str, note: str = "", label_type: str = "correct_sql") -> dict[str, Any]:
    summary = label_failure_case_service(
        failure_case_id=failure_case_id,
        correct_sql=correct_sql,
        note=note,
        label_type=label_type,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MES NL2SQL Harness CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap-csv", help="从 CSV 初始化 harness 用例集")
    bootstrap_parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH), help="CSV 文件路径")

    run_parser = subparsers.add_parser("run", help="执行 harness 评测")
    run_parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="服务地址")
    run_parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH), help="报告输出路径")
    run_parser.add_argument("--max-workers", type=int, default=4, help="并发数")
    run_parser.add_argument("--evolve", action="store_true", help="评测后自动进化")

    evolve_parser = subparsers.add_parser("evolve", help="根据报告生成运行时规则和 few-shot")
    evolve_parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH), help="报告路径")

    evolve_online_parser = subparsers.add_parser("evolve-online", help="从线上数据库日志生成并发布运行时知识")
    evolve_online_parser.add_argument("--limit", type=int, default=200, help="最多提炼多少条高成本成功案例")
    evolve_online_parser.add_argument("--skip-sync-failures", action="store_true", help="跳过失败案例同步")

    analyze_parser = subparsers.add_parser("analyze-failures", help="从线上失败案例生成候选规则")
    analyze_parser.add_argument("--limit", type=int, default=200, help="最多分析多少条失败案例")
    analyze_parser.add_argument("--skip-sync-failures", action="store_true", help="跳过失败案例同步")

    list_failure_parser = subparsers.add_parser("list-failures", help="查看失败案例")
    list_failure_parser.add_argument("--status", default="", help="按状态过滤，如 open/labeled/promoted")
    list_failure_parser.add_argument("--limit", type=int, default=50, help="返回条数")

    label_failure_parser = subparsers.add_parser("label-failure", help="给失败案例补充正确 SQL")
    label_failure_parser.add_argument("--failure-case-id", type=int, required=True, help="失败案例 ID")
    label_failure_parser.add_argument("--correct-sql", required=True, help="人工确认的正确 SQL")
    label_failure_parser.add_argument("--note", default="", help="标注备注")
    label_failure_parser.add_argument("--label-type", default="correct_sql", help="标注类型")

    list_candidates_parser = subparsers.add_parser("list-candidates", help="查看候选规则")
    list_candidates_parser.add_argument("--status", default="", help="按状态过滤，如 pending/approved/rejected/published")
    list_candidates_parser.add_argument("--limit", type=int, default=50, help="返回条数")

    review_parser = subparsers.add_parser("review-candidate", help="审核候选规则")
    review_parser.add_argument("--candidate-id", type=int, required=True, help="候选规则 ID")
    review_parser.add_argument("--action", choices=["approve", "reject"], required=True, help="审核动作")
    review_parser.add_argument("--note", default="", help="审核备注")

    publish_parser = subparsers.add_parser("publish-approved", help="发布已审核通过的候选规则")
    publish_parser.add_argument("--version", default="", help="发布版本号，可选")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "bootstrap-csv":
        cases = bootstrap_from_csv(Path(args.csv))
        print(json.dumps({
            "cases": len(cases),
            "cases_path": str(get_cases_path()),
        }, ensure_ascii=False, indent=2))
        return

    if args.command == "run":
        run_harness(
            base_url=args.base_url,
            report_path=Path(args.report),
            max_workers=args.max_workers,
            evolve=args.evolve,
        )
        return

    if args.command == "evolve":
        evolve_from_report(Path(args.report))
        return

    if args.command == "evolve-online":
        evolve_online(limit=args.limit, sync_failures=not args.skip_sync_failures)
        return

    if args.command == "analyze-failures":
        analyze_failures_online(limit=args.limit, sync_failures=not args.skip_sync_failures)
        return

    if args.command == "list-failures":
        list_failure_cases(status=args.status or None, limit=args.limit)
        return

    if args.command == "label-failure":
        label_failure_case(
            failure_case_id=args.failure_case_id,
            correct_sql=args.correct_sql,
            note=args.note,
            label_type=args.label_type,
        )
        return

    if args.command == "list-candidates":
        list_candidates(status=args.status or None, limit=args.limit)
        return

    if args.command == "review-candidate":
        review_candidate(candidate_id=args.candidate_id, action=args.action, note=args.note)
        return

    if args.command == "publish-approved":
        publish_approved(version=args.version or None)
        return

    raise ValueError(f"未知命令: {args.command}")


if __name__ == "__main__":
    main()
