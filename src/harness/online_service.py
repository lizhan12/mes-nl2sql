"""线上 Harness 服务层。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.core.config import settings
from src.harness.evolution import (
    build_few_shot_chunk,
    build_llm_labeled_candidate,
    build_llm_verified_candidate,
    build_rule_candidate_from_failure_and_recovery,
    build_rule_candidate_from_labeled_failure,
    build_runtime_rules_from_successful_sql,
    merge_runtime_rules,
)
from src.harness.knowledge import normalize_question
from src.harness.llm_labeler import auto_label_failure_case, evaluate_sql_multi_dimension
from src.harness.repository import get_online_harness_repository

logger = logging.getLogger(__name__)


def _safe_int(value: Any) -> int:
    """将任意值安全转换为 int，转换失败返回 0。"""
    try:
        return int(value) if value is not None else 0
    except (ValueError, TypeError):
        return 0


def _merge_few_shot_deduped(existing_text: str, new_chunks: list[str]) -> str:
    """合并 few-shot 文本，按「用户问题」去重并限制条数。

    新 chunks 优先：如果新 chunk 与已有 chunk 问题相同，新 chunk 覆盖旧的。
    条数限制：超过 settings.max_evolved_few_shot_items 时截断，截断时优先保留新 chunk。
    """
    from src.harness.knowledge import _extract_few_shot_question

    existing_chunks = [c.strip() for c in existing_text.split("\n---\n") if c.strip()] if existing_text.strip() else []
    stripped_new = [c.strip() for c in new_chunks if c.strip()]

    # 构建去重字典：现有 chunks 先入，新 chunks 后入（同 key 时新覆盖旧）
    seen: dict[str, str] = {}
    for chunk in existing_chunks:
        key = _extract_few_shot_question(chunk)
        seen[key or chunk] = chunk
    new_keys: set[str] = set()
    for chunk in stripped_new:
        key = _extract_few_shot_question(chunk)
        actual_key = key or chunk
        seen[actual_key] = chunk
        new_keys.add(actual_key)

    deduped = list(seen.values())
    if len(deduped) > settings.max_evolved_few_shot_items:
        # 截断时优先保留新 chunk
        new_items = [v for k, v in seen.items() if k in new_keys]
        old_items = [v for k, v in seen.items() if k not in new_keys]
        deduped = new_items + old_items
        deduped = deduped[: settings.max_evolved_few_shot_items]

    return "\n---\n".join(deduped)



def analyze_failures_online_service(
    limit: int = 200,
    sync_failures: bool = True,
    db_url: str | None = None,
    generate_model: str | None = None,
    eval_model: str | None = None,
) -> dict[str, Any]:
    """分析失败案例并生成候选规则。

    流程：
    1. 人工标注案例 → labeled_failure_rule (approved, 0.99)
    2. 失败案例匹配历史成功 SQL → recovered_failure_rule (pending)
       无匹配则回退 LLM 自动标注 → llm_auto_approved / llm_labeled_failure
    3. 用户点赞请求 → user_liked_successful_rule (approved)
    4. 重试成功案例 LLM 评估 → llm_auto_approved / llm_labeled_failure
    """
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

    # ── 第二部分：未标注案例的 recover / LLM 回退分析 ───────────────
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
    llm_generated = 0
    llm_failed = 0
    llm_auto_approved_count = 0
    llm_medium_count = 0

    for failure_case in failure_cases:
        case_id = int(failure_case.get("id", 0))
        normalized = normalize_question(str(failure_case.get("query_text", "")))
        recovered_request = successful_by_normalized.get(normalized)
        if recovered_request:
            candidate_key = f"recovered::{normalized}"
            if repo.candidate_exists_by_key(candidate_key):
                skipped += 1
                continue
            candidate = build_rule_candidate_from_failure_and_recovery(failure_case, recovered_request)
            candidate["source_request_ids"] = [str(recovered_request.get("request_id", ""))]
            candidate["source_failure_case_ids"] = [case_id]
            candidate["status"] = "pending"
            repo.upsert_rule_candidate(candidate)
            recovered += 1
        else:
            # 无匹配恢复 SQL，回退 LLM 自动标注
            query_text = str(failure_case.get("query_text", "")).strip()
            failed_sql = str(failure_case.get("final_sql") or failure_case.get("generated_sql", "")).strip()
            error_text = str(failure_case.get("error_text", "")).strip()
            user_rating = _safe_int(failure_case.get("user_rating"))
            user_feedback = str(failure_case.get("user_feedback", "")).strip()

            if not query_text or not failed_sql:
                skipped += 1
                continue

            result = auto_label_failure_case(
                question=query_text,
                failed_sql=failed_sql,
                error_msg=error_text,
                db_url=db_url,
                user_feedback=user_feedback,
                user_rating=user_rating,
                generate_model=generate_model,
                eval_model=eval_model,
            )

            if not result.corrected_sql.strip():
                llm_failed += 1
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
            repo.delete_candidates_by_failure_case_ids([case_id])
            repo.delete_candidate_by_key(candidate["candidate_key"])
            repo.upsert_rule_candidate(candidate)

            if result.candidate_type == "llm_auto_approved":
                repo.upsert_failure_label(
                    failure_case_id=case_id,
                    correct_sql=result.corrected_sql,
                    note=f"LLM自动标注（分析回退），置信度 {result.confidence:.2%}",
                    label_type="llm_auto_label",
                )
                repo.update_failure_case_statuses([case_id], "labeled")
                llm_auto_approved_count += 1
            elif result.candidate_type == "llm_labeled_failure":
                repo.upsert_failure_label(
                    failure_case_id=case_id,
                    correct_sql=result.corrected_sql,
                    note=f"LLM自动标注（分析回退，待确认），置信度 {result.confidence:.2%}",
                    label_type="llm_label_need_review",
                )
                repo.update_failure_case_statuses([case_id], "labeled")
                llm_medium_count += 1
            elif result.candidate_type == "llm_low_confidence_failure":
                repo.update_failure_case_statuses([case_id], "auto_labeled")
            llm_generated += 1
        created += 1

    # recovered 路径的案例标记为 analyzed
    recovered_ids = [
        int(case.get("id", 0))
        for case in failure_cases
        if case.get("id") and normalize_question(str(case.get("query_text", ""))) in successful_by_normalized
    ]
    if recovered_ids:
        repo.update_failure_case_statuses(recovered_ids, "analyzed")

    # ── 第三部分：用户点赞的成功请求抽取为候选规则 ──────────────────
    # 用户点赞的成功请求是经过人工验证的正确 SQL，同时生成运行时规则和 few-shot 示例。
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
            # 生成 few-shot：每条 SQL 对应一个 few-shot 示例
            rule_sql = runtime_rule.get("sql_part", sql)
            few_shot_item = {
                "question": query_text,
                "expected_main_table": runtime_rule.get("preferred_main_table", ""),
                "expected_related_tables": runtime_rule.get("required_tables", []),
                "expected_sql": rule_sql,
            }
            candidate = {
                "candidate_key": candidate_key,
                "candidate_type": "user_liked_successful_rule",
                "pattern_type": "normalized_query",
                "pattern_key": normalized,
                "question_example": query_text,
                "proposed_rule_json": runtime_rule,
                "proposed_few_shot_text": build_few_shot_chunk(few_shot_item, source="user_liked"),
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

    # ── 第四部分：重试成功案例 LLM 多维度评估 ──────────────────────
    # 跳过已被点赞路径处理的请求，避免重复生成候选
    liked_request_ids: set[str] = {str(req.get("request_id", "")) for req in liked_requests if req.get("request_id")}
    retry_success_cases = repo.fetch_unlabeled_failure_cases_by_type(failure_types=["retry_success"], limit=limit)
    retry_auto_approved = 0
    retry_medium = 0
    retry_low = 0
    retry_skipped = 0

    for case in retry_success_cases:
        case_id = int(case.get("id", 0))
        # 该案例对应的请求已被点赞路径处理（用户已验证），跳过
        if str(case.get("request_log_id", "")) in liked_request_ids:
            retry_skipped += 1
            continue
        query_text = str(case.get("query_text", "")).strip()
        sql = str(case.get("final_sql", "")).strip()

        if not query_text or not sql:
            retry_skipped += 1
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
            review_note = f"重试成功 SQL 评估，置信度 {confidence:.2%}"
        elif confidence >= 0.40:
            candidate_type = "llm_labeled_failure"
            review_note = f"重试成功 SQL 评估（待确认），置信度 {confidence:.2%}"
        else:
            candidate_type = "llm_low_confidence_failure"
            review_note = f"重试成功 SQL 评估（低），置信度 {confidence:.2%}"

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
        repo.delete_candidates_by_failure_case_ids([case_id])
        repo.delete_candidate_by_key(candidate["candidate_key"])
        repo.upsert_rule_candidate(candidate)

        if candidate_type == "llm_auto_approved":
            repo.upsert_failure_label(
                failure_case_id=case_id,
                correct_sql=sql,
                note=f"LLM评估（重试成功），置信度 {confidence:.2%}",
                label_type="llm_auto_label",
            )
            repo.update_failure_case_statuses([case_id], "labeled")
            retry_auto_approved += 1
        elif candidate_type == "llm_labeled_failure":
            repo.upsert_failure_label(
                failure_case_id=case_id,
                correct_sql=sql,
                note=f"LLM评估（重试成功，待确认），置信度 {confidence:.2%}",
                label_type="llm_label_need_review",
            )
            repo.update_failure_case_statuses([case_id], "labeled")
            retry_medium += 1
        else:
            repo.update_failure_case_statuses([case_id], "auto_labeled")
            retry_low += 1

    return {
        "synced_failures": synced_failures,
        "labeled_candidates": labeled,
        "labeled_skipped": labeled_skipped,
        "open_failures": len(failure_cases),
        "candidates_upserted": created,
        "candidates_skipped": skipped,
        "recovered_candidates": recovered,
        "llm_generated_candidates": llm_generated,
        "llm_auto_approved": llm_auto_approved_count,
        "llm_medium_confidence": llm_medium_count,
        "llm_failed": llm_failed,
        "liked_requests": len(liked_requests),
        "liked_candidates": liked_created,
        "liked_skipped": liked_skipped,
        "retry_success_cases": len(retry_success_cases),
        "retry_auto_approved": retry_auto_approved,
        "retry_medium_confidence": retry_medium,
        "retry_low_confidence": retry_low,
        "retry_skipped": retry_skipped,
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
    import logging
    _log = logging.getLogger(__name__)

    repo = get_online_harness_repository()
    repo.ensure_tables()
    if candidate_ids is not None:
        approved = repo.fetch_candidates_by_ids(candidate_ids)
    else:
        approved = repo.fetch_publishable_candidates()

    _log.info("publish_approved_service: 获取到 %d 个候选规则", len(approved))

    new_rules: list[dict[str, Any]] = []
    few_shot_chunks: list[str] = []
    published_candidate_ids: list[int] = []
    promoted_failure_case_ids: list[int] = []

    for item in approved:
        candidate_id = int(item["id"])
        proposed_rule = item.get("proposed_rule_json")
        if isinstance(proposed_rule, str):
            proposed_rule = json.loads(proposed_rule)
        proposed_few_shot_raw = item.get("proposed_few_shot_text")
        proposed_few_shot = str(proposed_few_shot_raw or "")
        _log.info(
            "  候选#%d: has_rule=%s, has_few_shot=%s (type=%s, len=%d, stripped=%s)",
            candidate_id,
            bool(isinstance(proposed_rule, dict) and proposed_rule),
            bool(proposed_few_shot.strip()),
            type(proposed_few_shot_raw).__name__,
            len(proposed_few_shot),
            bool(proposed_few_shot.strip()),
        )
        is_publishable = (isinstance(proposed_rule, dict) and bool(proposed_rule)) or bool(proposed_few_shot.strip())
        if not is_publishable:
            _log.info("  候选#%d 跳过: 无可发布内容", candidate_id)
            continue
        if isinstance(proposed_rule, dict) and proposed_rule:
            new_rules.append(proposed_rule)
        if proposed_few_shot.strip():
            few_shot_chunks.append(proposed_few_shot.strip())
            _log.info("  候选#%d few-shot 已加入合并列表", candidate_id)

        source_failure_ids = item.get("source_failure_case_ids_json")
        if isinstance(source_failure_ids, str):
            source_failure_ids = json.loads(source_failure_ids)
        if isinstance(source_failure_ids, list):
            promoted_failure_case_ids.extend(int(v) for v in source_failure_ids if str(v).strip())
        published_candidate_ids.append(candidate_id)

    _log.info("汇总: new_rules=%d, few_shot_chunks=%d, published_ids=%s", len(new_rules), len(few_shot_chunks), published_candidate_ids)

    final_version = version or f"reviewed-{Path.cwd().name}-{len(published_candidate_ids)}"

    if published_candidate_ids:
        from src.services.neo4j_graph import (
            load_published_few_shot_text,
            load_published_rules,
            publish_harness_knowledge,
        )

        existing_rules = await load_published_rules()
        existing_few_shot = await load_published_few_shot_text()
        _log.info("现有 few_shot 文本长度: %d", len(existing_few_shot))
        merged_rules = merge_runtime_rules(existing_rules, new_rules)
        merged_few_shot = _merge_few_shot_deduped(existing_few_shot, few_shot_chunks)
        _log.info("合并后 few_shot 文本长度: %d", len(merged_few_shot))
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



