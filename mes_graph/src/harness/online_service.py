"""线上 Harness 服务层。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.harness.evolution import (
    build_evolved_few_shot_text,
    build_few_shot_item_from_successful_sql,
    build_observation_candidate_from_failure,
    build_rule_candidate_from_failure_and_recovery,
    build_rule_candidate_from_labeled_failure,
    build_runtime_rule_from_successful_sql,
    merge_runtime_rules,
)
from src.harness.knowledge import normalize_question
from src.harness.repository import get_online_harness_repository


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
        repo.publish_runtime_knowledge(
            version=version,
            rules=merge_runtime_rules(published.rules, rules),
            few_shot_text=few_shot_text or published.few_shot_text,
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
    merged_few_shot = "\n---\n".join(chunk for chunk in [published.few_shot_text.strip(), *few_shot_chunks] if chunk)
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
