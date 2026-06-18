"""线上 Harness 服务层。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.core.config import settings
from src.harness.evolution import (
    build_evolved_few_shot_text,
    build_few_shot_item_from_successful_sql,
    build_llm_labeled_candidate,
    build_llm_verified_candidate,
    build_observation_candidate_from_failure,
    build_rule_candidate_from_failure_and_recovery,
    build_rule_candidate_from_labeled_failure,
    build_runtime_rules_from_successful_sql,
    merge_runtime_rules,
)
from src.harness.knowledge import normalize_question
from src.harness.llm_labeler import auto_label_failure_case
from src.harness.repository import get_online_harness_repository

logger = logging.getLogger(__name__)


def _merge_few_shot_deduped(existing_text: str, new_chunks: list[str]) -> str:
    """合并 few-shot 文本，按「用户问题」去重并限制条数。

    新 chunks 优先：如果新 chunk 与已有 chunk 问题相同，新 chunk 覆盖旧的。
    条数限制：超过 settings.max_evolved_few_shot_items 时截断。
    """
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


async def evolve_online_service(
    limit: int = 200, sync_failures: bool = True, include_liked: bool = True
) -> dict[str, int | str]:
    """线上进化：从线上成功请求生成 few-shot 和运行时规则，直接发布到运行时知识库。

    默认仅从用户点赞的成功请求生成。重试成功的请求不在此处理（仅说明 SQL
    无语法错误，不代表符合需求），由 LLM 自动标注服务进行验证后再决定是否采纳。

    Args:
        limit: 最多处理的请求数
        sync_failures: 是否先同步失败案例
        include_liked: 是否包含用户点赞的请求
    """
    repo = get_online_harness_repository()
    repo.ensure_tables()
    synced_failures = repo.sync_failure_cases() if sync_failures else 0

    liked_requests: list[dict[str, Any]] = []
    if include_liked:
        liked_requests = repo.fetch_liked_requests(limit=limit)

    # 使用多 SQL 规则抽取，展平结果
    rules: list[dict[str, Any]] = []
    for item in liked_requests:
        rules.extend(build_runtime_rules_from_successful_sql(item))
    few_shot_text = build_evolved_few_shot_text(
        [build_few_shot_item_from_successful_sql(item) for item in liked_requests],
        source="user_liked",
    )

    all_promoted_ids = [str(item["request_id"]) for item in liked_requests if item.get("request_id")]
    version = f"online-{Path.cwd().name}-{len(liked_requests)}-{len(rules)}"
    if rules or few_shot_text:
        from src.services.neo4j_graph import (
            load_published_few_shot_text,
            load_published_rules,
            publish_harness_knowledge,
        )

        existing_rules = await load_published_rules()
        existing_few_shot = await load_published_few_shot_text()
        merged_few_shot = _merge_few_shot_deduped(existing_few_shot, few_shot_text.split("\n---\n"))
        await publish_harness_knowledge(
            version=version,
            rules=merge_runtime_rules(existing_rules, rules),
            few_shot_text=merged_few_shot,
            source="online_harness_job",
        )
        repo.mark_requests_promoted(all_promoted_ids)

    return {
        "synced_failures": synced_failures,
        "liked_requests": len(liked_requests),
        "published_rules": len(rules),
        "version": version if rules or few_shot_text else "",
    }


def analyze_failures_online_service(limit: int = 200, sync_failures: bool = True) -> dict[str, int]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    synced_failures = repo.sync_failure_cases() if sync_failures else 0
    labeled = 0
    labeled_skipped = 0

    # ── 第一部分：人工标注案例直接生成候选（confidence=0.99） ──────
    labeled_cases = repo.fetch_labeled_failure_cases(limit=limit)
    for lc in labeled_cases:
        normalized = normalize_question(str(lc.get("query_text", "")))
        candidate_key = f"labeled::{normalized}"
        if repo.candidate_exists_by_key(candidate_key):
            labeled_skipped += 1
            continue
        correct_sql = str(lc.get("correct_sql", "")).strip()
        if not correct_sql:
            labeled_skipped += 1
            continue
        candidate = build_rule_candidate_from_labeled_failure(lc)
        candidate["status"] = "approved"
        candidate["source_failure_case_ids"] = [int(lc.get("id", 0))]
        repo.upsert_rule_candidate(candidate)
        labeled += 1
    if labeled_cases:
        labeled_ids = [int(lc.get("id", 0)) for lc in labeled_cases if lc.get("id")]
        repo.update_failure_case_statuses(labeled_ids, "labeled")

    # ── 第二部分：未标注案例的 recover / observe 分析 ───────────────
    failure_cases = repo.fetch_open_failure_cases(limit=limit)
    successful_requests = repo.fetch_successful_requests_for_queries(
        sorted({str(item.get("query_text", "")) for item in failure_cases if str(item.get("query_text", "")).strip()})
    )

    successful_by_normalized: dict[str, dict[str, Any]] = {}
    for request in successful_requests:
        normalized = normalize_question(str(request.get("query_text", "")))
        successful_by_normalized.setdefault(normalized, request)

    created = 0
    skipped = 0
    recovered = 0
    observed = 0

    for failure_case in failure_cases:
        normalized = normalize_question(str(failure_case.get("query_text", "")))
        recovered_request = successful_by_normalized.get(normalized)
        if recovered_request:
            candidate_key = f"recovered::{normalized}"
            if repo.candidate_exists_by_key(candidate_key):
                skipped += 1
                continue
            candidate = build_rule_candidate_from_failure_and_recovery(failure_case, recovered_request)
            candidate["source_request_ids"] = [str(recovered_request.get("request_id", ""))]
            candidate["source_failure_case_ids"] = [int(failure_case.get("id", 0))]
            candidate["status"] = "pending"
            repo.upsert_rule_candidate(candidate)
            recovered += 1
        else:
            candidate_key = f"observe::{normalized}"
            if repo.candidate_exists_by_key(candidate_key):
                skipped += 1
                continue
            candidate = build_observation_candidate_from_failure(failure_case)
            candidate["source_request_ids"] = []
            candidate["source_failure_case_ids"] = [int(failure_case.get("id", 0))]
            candidate["status"] = "pending"
            repo.upsert_rule_candidate(candidate)
            observed += 1
        created += 1

    # ── 第二部分：用户点赞的成功请求抽取为候选规则 ──────────────────
    # 用户点赞的成功请求是经过人工验证的正确 SQL，抽取为候选规则（表推荐、JOIN 提示）。
    # few-shot 示例由「线上进化」统一生成并发布，此处不重复生成。
    liked_requests = repo.fetch_liked_requests(limit=limit)
    liked_created = 0
    liked_skipped = 0
    liked_promoted_ids: list[str] = []
    for req in liked_requests:
        query_text = str(req.get("query_text", "")).strip()
        sql = str(req.get("final_sql", "")).strip()
        if not query_text or not sql:
            continue
        normalized = normalize_question(query_text)
        # 使用多 SQL 规则抽取，为每条 SQL 单独生成候选
        runtime_rules = build_runtime_rules_from_successful_sql(req)
        for idx, runtime_rule in enumerate(runtime_rules, 1):
            candidate_key = (
                f"user_liked::{normalized}" if len(runtime_rules) == 1 else f"user_liked::{normalized}::part{idx}"
            )
            if repo.candidate_exists_by_key(candidate_key):
                liked_skipped += 1
                continue
            candidate = {
                "candidate_key": candidate_key,
                "candidate_type": "user_liked_successful_rule",
                "pattern_type": "normalized_query",
                "pattern_key": normalized,
                "question_example": query_text,
                "proposed_rule_json": runtime_rule,
                "proposed_few_shot_text": "",
                "confidence": 0.95,
                "evidence_json": {
                    "request_id": str(req.get("request_id", "")),
                    "source": "user_liked",
                    "retry_count": int(req.get("retry_count", 0)),
                    "sql_index": idx if len(runtime_rules) > 1 else None,
                    "total_sqls": len(runtime_rules),
                },
                "status": "approved",
                "source_request_ids": [str(req.get("request_id", ""))],
                "source_failure_case_ids": [],
                "review_note": "用户点赞的正确 SQL，置信度 0.95",
            }
            repo.upsert_rule_candidate(candidate)
        liked_promoted_ids.append(str(req.get("request_id", "")))
        liked_created += 1
    if liked_promoted_ids:
        repo.mark_requests_promoted(liked_promoted_ids)

    # 批处理完成，标记所有已处理的案例为 analyzed，防止后续 LLM 自动标注重复抽取
    processed_ids = [int(case.get("id", 0)) for case in failure_cases if case.get("id")]
    if processed_ids:
        repo.update_failure_case_statuses(processed_ids, "analyzed")

    return {
        "synced_failures": synced_failures,
        "labeled_candidates": labeled,
        "labeled_skipped": labeled_skipped,
        "open_failures": len(failure_cases),
        "candidates_upserted": created,
        "candidates_skipped": skipped,
        "recovered_candidates": recovered,
        "observation_candidates": observed,
        "liked_requests": len(liked_requests),
        "liked_candidates": liked_created,
        "liked_skipped": liked_skipped,
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


def delete_candidate_service(candidate_id: int) -> dict[str, Any]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    deleted = repo.delete_rule_candidate(candidate_id)
    return {"candidate_id": candidate_id, "deleted": deleted}


def delete_failure_case_service(failure_case_id: int) -> dict[str, Any]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    deleted = repo.delete_failure_case(failure_case_id)
    return {"failure_case_id": failure_case_id, "deleted": deleted}


async def pre_publish_check_service() -> dict:
    """发布前去重检查：检查所有 approved 候选是否与已有知识库重复。

    Returns:
        {
            "total_candidates": int,
            "duplicate_items": [...],
            "clean_count": int,
        }
    """
    import json

    from src.core.config import settings
    from src.services.neo4j_graph import _get_driver
    from src.services.vector_store import _build_few_shot_embed_text, _get_embeddings

    repo = get_online_harness_repository()
    repo.ensure_tables()
    approved = repo.fetch_publishable_candidates()

    if not approved:
        return {"total_candidates": 0, "duplicate_items": [], "clean_count": 0}

    duplicate_items = []
    threshold = settings.dedup_similarity_threshold
    driver = await _get_driver()
    embeddings = _get_embeddings()

    # 为每个候选做去重检查
    for item in approved:
        candidate_id = int(item["id"])
        proposed_rule = item.get("proposed_rule_json")
        proposed_few_shot = str(item.get("proposed_few_shot_text", "") or "")

        if isinstance(proposed_rule, str):
            try:
                proposed_rule = json.loads(proposed_rule)
            except (json.JSONDecodeError, TypeError):
                proposed_rule = None

        # 检查 RuntimeRule 重复
        if isinstance(proposed_rule, dict) and proposed_rule:
            normalized_q = str(proposed_rule.get("normalized_question") or "")
            question = str(proposed_rule.get("question") or "")

            # 精确匹配
            async with driver.session() as session:
                result = await session.run(
                    "MATCH (r:RuntimeRule) WHERE r.normalized_question = $nq "
                    "RETURN r.normalized_question AS nq, r.question AS q, r.source AS source",
                    {"nq": normalized_q},
                )
                records = await result.data()
                for rec in records:
                    duplicate_items.append(
                        {
                            "key": str(rec["nq"] or ""),
                            "question": str(rec["q"] or ""),
                            "score": 1.0,
                            "match_type": "exact",
                            "existing_item": {
                                "normalized_question": str(rec["nq"] or ""),
                                "question": str(rec["q"] or ""),
                                "source": str(rec["source"] or ""),
                            },
                            "candidate_id": candidate_id,
                        }
                    )

            if not duplicate_items:
                # 向量相似度检查
                try:
                    query_vec = embeddings.embed_query(question[:500])
                    async with driver.session() as session:
                        result = await session.run(
                            """
                            MATCH (r:RuntimeRule)
                            WHERE r.question_embedding IS NOT NULL
                            WITH r, vector.similarity.cosine(r.question_embedding, $query_vec) AS score
                            WHERE score >= $threshold
                            RETURN r.normalized_question AS nq, r.question AS q, r.source AS source, score
                            ORDER BY score DESC
                            LIMIT 3
                            """,
                            {"query_vec": query_vec, "threshold": threshold},
                        )
                        records = await result.data()
                        for rec in records:
                            duplicate_items.append(
                                {
                                    "key": str(rec["nq"] or ""),
                                    "question": str(rec["q"] or ""),
                                    "score": float(rec["score"]),
                                    "match_type": "vector",
                                    "existing_item": {
                                        "normalized_question": str(rec["nq"] or ""),
                                        "question": str(rec["q"] or ""),
                                        "source": str(rec["source"] or ""),
                                    },
                                    "candidate_id": candidate_id,
                                }
                            )
                except Exception as exc:
                    logger.warning("Harness 预发布 RuntimeRule 去重检查失败: %s", exc)

        # 检查 FewShot 重复
        if proposed_few_shot.strip():
            # 提取问题文本
            question_in_few_shot = ""
            for line in proposed_few_shot.split("\n"):
                line = line.strip()
                if line.startswith("用户问题："):
                    question_in_few_shot = line[len("用户问题：") :].strip()
                    break

            if question_in_few_shot:
                # 精确匹配
                async with driver.session() as session:
                    result = await session.run(
                        "MATCH (f:FewShot) WHERE f.question = $question RETURN f.id AS id, f.question AS question",
                        {"question": question_in_few_shot},
                    )
                    records = await result.data()
                    for rec in records:
                        duplicate_items.append(
                            {
                                "key": str(rec["id"] or ""),
                                "question": str(rec["question"] or ""),
                                "score": 1.0,
                                "match_type": "exact",
                                "existing_item": {
                                    "id": str(rec["id"] or ""),
                                    "question": str(rec["question"] or ""),
                                },
                                "candidate_id": candidate_id,
                            }
                        )

                # 向量相似度检查
                if not any(d.get("candidate_id") == candidate_id for d in duplicate_items):
                    try:
                        embed_text = _build_few_shot_embed_text({"scenario": "", "question": question_in_few_shot})
                        query_vec = embeddings.embed_query(embed_text)
                        async with driver.session() as session:
                            result = await session.run(
                                """
                                MATCH (f:FewShot)
                                WHERE f.question_embedding IS NOT NULL
                                WITH f, vector.similarity.cosine(f.question_embedding, $query_vec) AS score
                                WHERE score >= $threshold
                                RETURN f.id AS id, f.question AS question, score
                                ORDER BY score DESC
                                LIMIT 3
                                """,
                                {"query_vec": query_vec, "threshold": threshold},
                            )
                            records = await result.data()
                            for rec in records:
                                duplicate_items.append(
                                    {
                                        "key": str(rec["id"] or ""),
                                        "question": str(rec["question"] or ""),
                                        "score": float(rec["score"]),
                                        "match_type": "vector",
                                        "existing_item": {
                                            "id": str(rec["id"] or ""),
                                            "question": str(rec["question"] or ""),
                                        },
                                        "candidate_id": candidate_id,
                                    }
                                )
                    except Exception as exc:
                        logger.warning("Harness 预发布 FewShot 去重检查失败: %s", exc)

    return {
        "total_candidates": len(approved),
        "duplicate_items": duplicate_items,
        "clean_count": len(approved) - len({d["candidate_id"] for d in duplicate_items}),
    }


async def publish_approved_service(version: str | None = None, candidate_ids: list[int] | None = None) -> dict[str, int | str]:
    repo = get_online_harness_repository()
    repo.ensure_tables()
    if candidate_ids is not None:
        approved = repo.fetch_candidates_by_ids(candidate_ids)
    else:
        approved = repo.fetch_publishable_candidates()

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

    final_version = version or f"reviewed-{Path.cwd().name}-{len(published_candidate_ids)}"

    if published_candidate_ids:
        from src.services.neo4j_graph import (
            load_published_few_shot_text,
            load_published_rules,
            publish_harness_knowledge,
        )

        existing_rules = await load_published_rules()
        existing_few_shot = await load_published_few_shot_text()
        merged_rules = merge_runtime_rules(existing_rules, new_rules)
        merged_few_shot = _merge_few_shot_deduped(existing_few_shot, few_shot_chunks)
        await publish_harness_knowledge(
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
    """LLM 自动标注：对失败/点踩 SQL 进行修复 + 多维度打分，对重试成功 SQL 进行提取 + 多维度打分。

    第一部分 — 失败/点踩 SQL 修复：
        数据源：nl2sql_failure_case 中 failure_type 为 execution_error / unsafe_sql / user_reported
        处理：LLM 生成修正 SQL + 多维度评估，按置信度分级处理。

    第二部分 — 重试成功 SQL 提取：
        数据源：nl2sql_failure_case 中 failure_type 为 retry_success
        处理：提取重试后成功的 final_sql，多维度评估（不重新生成），按置信度分级处理。

    Args:
        limit: 最多处理多少条案例
        sync_failures: 是否先同步失败案例
        db_url: 数据库连接串（用于执行验证）
        generate_model: 生成 SQL 用的模型
        eval_model: 评估用的模型
    """
    from src.harness.llm_labeler import evaluate_sql_multi_dimension

    repo = get_online_harness_repository()
    repo.ensure_tables()
    synced_failures = repo.sync_failure_cases() if sync_failures else 0

    labeled = 0
    labeled_skipped = 0

    # ── 第一部分：人工标注案例直接生成候选（confidence=0.99），不用 LLM ──
    labeled_cases = repo.fetch_labeled_failure_cases(limit=limit)
    for lc in labeled_cases:
        normalized = normalize_question(str(lc.get("query_text", "")))
        candidate_key = f"labeled::{normalized}"
        if repo.candidate_exists_by_key(candidate_key):
            labeled_skipped += 1
            continue
        correct_sql = str(lc.get("correct_sql", "")).strip()
        if not correct_sql:
            labeled_skipped += 1
            continue
        candidate = build_rule_candidate_from_labeled_failure(lc)
        candidate["status"] = "approved"
        candidate["source_failure_case_ids"] = [int(lc.get("id", 0))]
        # 重新标注：删除旧候选再新增
        repo.delete_candidates_by_failure_case_ids([int(lc.get("id", 0))])
        repo.delete_candidate_by_key(candidate["candidate_key"])
        repo.upsert_rule_candidate(candidate)
        labeled += 1
    if labeled_cases:
        labeled_ids = [int(lc.get("id", 0)) for lc in labeled_cases if lc.get("id")]
        repo.update_failure_case_statuses(labeled_ids, "labeled")

    # 第二部分：失败/点踩案例（不含 retry_success）— LLM 自动标注
    failure_cases = repo.fetch_unlabeled_failure_cases_by_type(
        failure_types=["execution_error", "unsafe_sql", "user_reported"], limit=limit
    )
    # 第二部分：重试成功案例
    retry_success_cases = repo.fetch_unlabeled_failure_cases_by_type(failure_types=["retry_success"], limit=limit)

    stats: dict[str, Any] = {
        "synced_failures": synced_failures,
        "labeled_candidates": labeled,
        "labeled_skipped": labeled_skipped,
        "failure_cases": len(failure_cases),
        "retry_success_cases": len(retry_success_cases),
        # 失败/点踩修复统计
        "auto_approved": 0,
        "medium_confidence": 0,
        "low_confidence": 0,
        "skipped": 0,
        "total_processed": 0,
        "details": [],
        # 重试成功提取统计
        "promotable_requests": len(retry_success_cases),
        "promotable_auto_approved": 0,
        "promotable_medium_confidence": 0,
        "promotable_low_confidence": 0,
        "promotable_skipped": 0,
        "promotable_processed": 0,
        "promotable_details": [],
    }

    # ── 第一部分：失败/点踩 SQL 修复 + 多维度打分 ────────────────────

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

        # LLM 自动标注：生成修正 SQL + 多维度评估
        result = auto_label_failure_case(
            question=query_text,
            failed_sql=failed_sql,
            error_msg=error_text,
            db_url=None,
            generate_model=generate_model,
            eval_model=eval_model,
        )

        if not result.corrected_sql.strip():
            stats["skipped"] += 1
            unprocessable_ids.append(case_id)
            continue

        candidate = build_llm_labeled_candidate(
            query_text=query_text,
            corrected_sql=result.corrected_sql,
            confidence=result.confidence,
            candidate_type=result.candidate_type,
            review_note=result.review_note,
            failure_case_id=case_id,
            dimension_details=result.dimension_scores.details,
        )
        # 重新标注：删除旧候选（按 failure_case_id + candidate_key）再新增
        repo.delete_candidates_by_failure_case_ids([case_id])
        repo.delete_candidate_by_key(candidate["candidate_key"])
        repo.upsert_rule_candidate(candidate)

        if result.candidate_type == "llm_auto_approved":
            repo.upsert_failure_label(
                failure_case_id=case_id,
                correct_sql=result.corrected_sql,
                note=f"LLM自动标注，置信度 {result.confidence:.2%}",
                label_type="llm_auto_label",
            )
            repo.update_failure_case_statuses([case_id], "labeled")
            stats["auto_approved"] += 1
        elif result.candidate_type == "llm_labeled_failure":
            repo.upsert_failure_label(
                failure_case_id=case_id,
                correct_sql=result.corrected_sql,
                note=f"LLM自动标注（待确认），置信度 {result.confidence:.2%}",
                label_type="llm_label_need_review",
            )
            repo.update_failure_case_statuses([case_id], "labeled")
            stats["medium_confidence"] += 1
        else:
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

    marked_ids = low_confidence_ids + unprocessable_ids
    if marked_ids:
        repo.update_failure_case_statuses(marked_ids, "auto_labeled")
        stats["marked_auto_labeled"] = len(marked_ids)

    # ── 第二部分：重试成功 SQL 提取 + 多维度打分 ─────────────────────
    # 重试成功的 SQL 已通过执行验证，提取 final_sql 做多维度评估（不重新生成）。

    verified_case_ids: list[int] = []

    for case in retry_success_cases:
        case_id = int(case.get("id", 0))
        query_text = str(case.get("query_text", "")).strip()
        sql = str(case.get("final_sql", "")).strip()

        if not query_text or not sql:
            stats["promotable_skipped"] += 1
            verified_case_ids.append(case_id)
            continue

        from src.harness.runner import parse_tables

        _, tables, _ = parse_tables(sql)
        scores = evaluate_sql_multi_dimension(
            question=query_text,
            sql=sql,
            failed_sql="",
            error_msg="",
            table_names=tables,
            db_url=db_url,
            model=eval_model,
        )

        confidence = scores.overall_confidence

        if confidence >= 0.70:
            candidate_type = "llm_auto_approved"
            review_note = f"重试成功 SQL 提取，置信度 {confidence:.2%}，各维度均通过。建议自动审批。"
        elif confidence >= 0.40:
            candidate_type = "llm_labeled_failure"
            review_note = f"重试成功 SQL 提取，置信度 {confidence:.2%}（中等），建议人工快速确认。"
        else:
            candidate_type = "llm_low_confidence_failure"
            review_note = f"重试成功 SQL 提取，置信度 {confidence:.2%}（低），不建议采纳。"

        request_item = {
            "query_text": query_text,
            "final_sql": sql,
            "request_id": str(case.get("request_log_id", "")),
            "retry_count": int(case.get("retry_count", 0)),
            "execution_error": "",
        }
        candidate = build_llm_verified_candidate(
            request_item=request_item,
            confidence=confidence,
            candidate_type=candidate_type,
            review_note=review_note,
            dimension_details=scores.details,
        )
        candidate["source_failure_case_ids"] = [case_id]
        # 重新标注：删除旧候选（按 failure_case_id + candidate_key）再新增
        repo.delete_candidates_by_failure_case_ids([case_id])
        repo.delete_candidate_by_key(candidate["candidate_key"])
        repo.upsert_rule_candidate(candidate)

        if candidate_type == "llm_auto_approved":
            stats["promotable_auto_approved"] += 1
        elif candidate_type == "llm_labeled_failure":
            stats["promotable_medium_confidence"] += 1
        else:
            stats["promotable_low_confidence"] += 1

        stats["promotable_processed"] += 1
        verified_case_ids.append(case_id)
        stats["promotable_details"].append(
            {
                "case_id": case_id,
                "question": query_text[:80],
                "confidence": confidence,
                "level": scores.confidence_level,
                "candidate_type": candidate_type,
            }
        )

    # 标记已处理的重试成功案例，防止重复消费
    if verified_case_ids:
        repo.update_failure_case_statuses(verified_case_ids, "auto_labeled")

    return stats
