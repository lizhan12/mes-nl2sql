"""线上 Harness 服务层。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.config import settings
from src.harness.evolution import (
    build_evolved_few_shot_text,
    build_few_shot_item_from_successful_sql,
    build_llm_labeled_candidate,
    build_observation_candidate_from_failure,
    build_rule_candidate_from_failure_and_recovery,
    build_rule_candidate_from_labeled_failure,
    build_runtime_rule_from_successful_sql,
    merge_runtime_rules,
)
from src.harness.knowledge import normalize_question
from src.harness.llm_labeler import auto_label_failure_case
from src.harness.repository import get_online_harness_repository


def _merge_few_shot_deduped(existing_text: str, new_chunks: list[str]) -> str:
    """合并 few-shot 文本，按「用户问题」去重并限制条数。

    新 chunks 优先：如果新 chunk 与已有 chunk 问题相同，新 chunk 覆盖旧的。
    条数限制：超过 settings.max_evolved_few_shot_items 时截断。
    """
    from src.core.config import settings
    from src.harness.knowledge import _extract_few_shot_question

    # 解析已有 chunks
    existing_chunks = [c.strip() for c in existing_text.split("\n---\n") if c.strip()] if existing_text.strip() else []

    # 合并：新 chunks 放后面，后出现的会覆盖先出现的（同 key）
    all_chunks = existing_chunks + [c.strip() for c in new_chunks if c.strip()]

    seen: dict[str, str] = {}
    for chunk in all_chunks:
        key = _extract_few_shot_question(chunk)
        seen[key or chunk] = chunk

    deduped = list(seen.values())
    if len(deduped) > settings.max_evolved_few_shot_items:
        deduped = deduped[: settings.max_evolved_few_shot_items]

    return "\n---\n".join(deduped)


def evolve_online_service(limit: int = 200, sync_failures: bool = True) -> dict[str, int | str]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    synced_failures = repo.sync_failure_cases() if sync_failures else 0
    candidates = repo.fetch_promotable_requests(limit=limit)

    rules = [build_runtime_rule_from_successful_sql(item) for item in candidates]
    few_shot_text = build_evolved_few_shot_text([build_few_shot_item_from_successful_sql(item) for item in candidates])

    version = f"online-{Path.cwd().name}-{len(candidates)}-{len(rules)}"
    if rules or few_shot_text:
        published = repo.load_published_knowledge()
        merged_few_shot = _merge_few_shot_deduped(published.few_shot_text, few_shot_text.split("\n---\n"))
        repo.publish_runtime_knowledge(
            version=version,
            rules=merge_runtime_rules(published.rules, rules),
            few_shot_text=merged_few_shot,
            source="online_harness_job",
        )
        repo.mark_requests_promoted([str(item["request_id"]) for item in candidates if item.get("request_id")])

    return {
        "synced_failures": synced_failures,
        "promotable_requests": len(candidates),
        "published_rules": len(rules),
        "version": version if rules or few_shot_text else "",
    }


def analyze_failures_online_service(limit: int = 200, sync_failures: bool = True) -> dict[str, int]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    synced_failures = repo.sync_failure_cases() if sync_failures else 0
    failure_cases = repo.fetch_open_failure_cases(limit=limit)
    labeled_cases = repo.fetch_labeled_failure_cases(limit=limit)
    successful_requests = repo.fetch_successful_requests_for_queries(
        sorted({str(item.get("query_text", "")) for item in failure_cases if str(item.get("query_text", "")).strip()})
    )

    successful_by_normalized: dict[str, dict[str, Any]] = {}
    for request in successful_requests:
        normalized = normalize_question(str(request.get("query_text", "")))
        successful_by_normalized.setdefault(normalized, request)

    created = 0
    recovered = 0
    observed = 0
    labeled = 0

    for failure_case in labeled_cases:
        candidate = build_rule_candidate_from_labeled_failure(failure_case)
        candidate["source_request_ids"] = []
        candidate["source_failure_case_ids"] = [int(failure_case.get("id", 0))]
        candidate["status"] = "pending"
        repo.upsert_rule_candidate(candidate)
        created += 1
        labeled += 1

    labeled_ids = {int(item.get("id", 0)) for item in labeled_cases}
    for failure_case in failure_cases:
        if int(failure_case.get("id", 0)) in labeled_ids:
            continue
        normalized = normalize_question(str(failure_case.get("query_text", "")))
        recovered_request = successful_by_normalized.get(normalized)
        if recovered_request:
            candidate = build_rule_candidate_from_failure_and_recovery(failure_case, recovered_request)
            candidate["source_request_ids"] = [str(recovered_request.get("request_id", ""))]
            candidate["source_failure_case_ids"] = [int(failure_case.get("id", 0))]
            candidate["status"] = "pending"
            repo.upsert_rule_candidate(candidate)
            recovered += 1
        else:
            candidate = build_observation_candidate_from_failure(failure_case)
            candidate["source_request_ids"] = []
            candidate["source_failure_case_ids"] = [int(failure_case.get("id", 0))]
            candidate["status"] = "pending"
            repo.upsert_rule_candidate(candidate)
            observed += 1
        created += 1

    return {
        "synced_failures": synced_failures,
        "open_failures": len(failure_cases),
        "labeled_failures": len(labeled_cases),
        "candidates_upserted": created,
        "recovered_candidates": recovered,
        "observation_candidates": observed,
        "labeled_candidates": labeled,
    }


def list_candidates_service(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    return repo.list_rule_candidates(status=status, limit=limit)


def review_candidate_service(candidate_id: int, action: str, note: str = "") -> dict[str, Any]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    repo.review_rule_candidate(candidate_id=candidate_id, action=action, note=note)
    return {"candidate_id": candidate_id, "action": action, "note": note}


def publish_approved_service(version: str | None = None) -> dict[str, int | str]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    approved = repo.fetch_publishable_candidates()
    published = repo.load_published_knowledge()

    new_rules: list[dict[str, Any]] = []
    few_shot_chunks: list[str] = []
    published_candidate_ids: list[int] = []
    promoted_failure_case_ids: list[int] = []

    for item in approved:
        proposed_rule = item.get("proposed_rule_json")
        if isinstance(proposed_rule, str):
            proposed_rule = json.loads(proposed_rule)
        proposed_few_shot = str(item.get("proposed_few_shot_text", "") or "")
        is_publishable = (isinstance(proposed_rule, dict) and bool(proposed_rule)) or bool(proposed_few_shot.strip())
        if not is_publishable:
            continue
        if isinstance(proposed_rule, dict) and proposed_rule:
            new_rules.append(proposed_rule)
        if proposed_few_shot.strip():
            few_shot_chunks.append(proposed_few_shot.strip())

        source_failure_ids = item.get("source_failure_case_ids_json")
        if isinstance(source_failure_ids, str):
            source_failure_ids = json.loads(source_failure_ids)
        if isinstance(source_failure_ids, list):
            promoted_failure_case_ids.extend(int(v) for v in source_failure_ids if str(v).strip())
        published_candidate_ids.append(int(item["id"]))

    merged_rules = merge_runtime_rules(published.rules, new_rules)
    merged_few_shot = _merge_few_shot_deduped(published.few_shot_text, few_shot_chunks)
    final_version = version or f"reviewed-{Path.cwd().name}-{len(published_candidate_ids)}"

    if published_candidate_ids:
        repo.publish_runtime_knowledge(
            version=final_version,
            rules=merged_rules,
            few_shot_text=merged_few_shot,
            source="candidate_publish",
        )
        repo.mark_candidates_published(published_candidate_ids, final_version)
        repo.update_failure_case_statuses(promoted_failure_case_ids, "promoted")

    return {
        "approved_candidates": len(approved),
        "published_candidates": len(published_candidate_ids),
        "published_version": final_version if published_candidate_ids else "",
    }


def list_failure_cases_service(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    return repo.list_failure_cases(status=status, limit=limit)


def label_failure_case_service(
    failure_case_id: int, correct_sql: str, note: str = "", label_type: str = "correct_sql"
) -> dict[str, Any]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    label_id = repo.upsert_failure_label(
        failure_case_id=failure_case_id,
        correct_sql=correct_sql,
        note=note,
        label_type=label_type,
    )
    return {
        "failure_case_id": failure_case_id,
        "label_id": label_id,
        "label_type": label_type,
        "note": note,
    }


def auto_label_failures_online_service(
    limit: int = 50,
    sync_failures: bool = True,
    db_url: str | None = None,
    generate_model: str | None = None,
    eval_model: str | None = None,
) -> dict[str, Any]:
    """使用 LLM 对失败案例自动标注 + 多维度评估。

    - 高置信度 (>=0.70)：自动审批，候选直接为 approved
    - 中置信度 (0.40-0.70)：候选为 pending，带 LLM 生成的 SQL 和评估详情
    - 低置信度 (<0.40)：候选为 pending，需人工编写正确 SQL

    Args:
        limit: 最多处理多少条失败案例
        sync_failures: 是否先同步失败案例
        db_url: 数据库连接串（用于执行验证）
        generate_model: 生成 SQL 用的模型
        eval_model: 评估用的模型
    """
    repo = get_online_harness_repository()
    repo.ensure_tables()
    synced_failures = repo.sync_failure_cases() if sync_failures else 0

    failure_cases = repo.fetch_open_failure_cases(limit=limit)
    execution_db_url = db_url or settings.execution_database_url

    stats: dict[str, Any] = {
        "synced_failures": synced_failures,
        "open_failures": len(failure_cases),
        "auto_approved": 0,
        "medium_confidence": 0,
        "low_confidence": 0,
        "skipped": 0,
        "total_processed": 0,
        "details": [],
    }

    # 收集需要标记为非 open 的案例 ID，防止下次重复标注
    unprocessable_ids: list[int] = []
    low_confidence_ids: list[int] = []

    for case in failure_cases:
        case_id = int(case.get("id", 0))
        query_text = str(case.get("query_text", "")).strip()
        failed_sql = str(case.get("final_sql") or case.get("generated_sql", "")).strip()
        error_text = str(case.get("error_text", "")).strip()

        if not query_text or not failed_sql:
            stats["skipped"] += 1
            unprocessable_ids.append(case_id)
            continue

        # LLM 自动标注
        result = auto_label_failure_case(
            question=query_text,
            failed_sql=failed_sql,
            error_msg=error_text,
            db_url=execution_db_url,
            generate_model=generate_model,
            eval_model=eval_model,
        )

        # 如果没有生成有效 SQL，标记为不可处理
        if not result.corrected_sql.strip():
            stats["skipped"] += 1
            unprocessable_ids.append(case_id)
            continue

        # 构建候选规则
        candidate = build_llm_labeled_candidate(
            query_text=query_text,
            corrected_sql=result.corrected_sql,
            confidence=result.confidence,
            candidate_type=result.candidate_type,
            review_note=result.review_note,
            failure_case_id=case_id,
            dimension_details=result.dimension_scores.details,
        )

        repo.upsert_rule_candidate(candidate)

        # 根据置信度分级处理
        if result.candidate_type == "llm_auto_approved":
            # 高置信度：自动审批 + 保存标准答案，状态变为 labeled
            repo.upsert_failure_label(
                failure_case_id=case_id,
                correct_sql=result.corrected_sql,
                note=f"LLM自动标注，置信度 {result.confidence:.2%}",
                label_type="llm_auto_label",
            )
            stats["auto_approved"] += 1
        elif result.candidate_type == "llm_labeled_failure":
            # 中置信度：保存标注（待确认），状态变为 labeled
            repo.upsert_failure_label(
                failure_case_id=case_id,
                correct_sql=result.corrected_sql,
                note=f"LLM自动标注（待确认），置信度 {result.confidence:.2%}",
                label_type="llm_label_need_review",
            )
            stats["medium_confidence"] += 1
        else:
            # 低置信度：不保存标注，但需标记为已处理防止重复
            stats["low_confidence"] += 1
            low_confidence_ids.append(case_id)

        stats["total_processed"] += 1
        stats["details"].append(
            {
                "case_id": case_id,
                "question": query_text[:80],
                "confidence": result.confidence,
                "level": result.dimension_scores.confidence_level,
                "needs_review": result.needs_human_review,
            }
        )

    # 批量标记：将低置信度和不可处理案例标记为 auto_labeled，防止下次重复标注
    marked_ids = low_confidence_ids + unprocessable_ids
    if marked_ids:
        repo.update_failure_case_statuses(marked_ids, "auto_labeled")
        stats["marked_auto_labeled"] = len(marked_ids)

    return stats
