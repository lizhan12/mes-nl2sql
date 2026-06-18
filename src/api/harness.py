"""Harness 知识进化管理接口：失败案例、候选规则、发布、用户反馈等。"""

import asyncio

from fastapi import APIRouter, HTTPException

from src.core.config import settings
from src.harness.online_service import (
    analyze_failures_online_service,
    auto_label_failures_online_service,
    evolve_online_service,
    label_failure_case_service,
    list_candidates_service,
    list_failure_cases_service,
    publish_approved_service,
    review_candidate_service,
)
from src.harness.repository import get_online_harness_repository
from src.models.schemas import (
    HarnessCandidateReviewRequest,
    HarnessFailureLabelRequest,
    HarnessFeedbackRequest,
    HarnessPublishRequest,
)

router = APIRouter(prefix="/admin/harness")


@router.get("/feedback")
async def list_harness_feedback(limit: int = 100):
    """查看所有用户点赞/点踩反馈记录。"""
    if not settings.enable_online_harness:
        return {"items": [], "error": "线上 Harness 未启用"}
    items = await asyncio.to_thread(
        get_online_harness_repository().list_user_feedback,
        limit,
    )
    return {"items": items}


@router.get("/failure-cases")
async def list_harness_failure_cases(status: str = "", limit: int = 50):
    """查看线上 Harness 失败案例。"""
    if not settings.enable_online_harness:
        return {"items": [], "error": "线上 Harness 未启用"}
    items = await asyncio.to_thread(list_failure_cases_service, status or None, limit)
    return {"items": items}


@router.post("/failure-cases/{failure_case_id}/label")
async def label_harness_failure_case(failure_case_id: int, request: HarnessFailureLabelRequest):
    """给失败案例补充正确 SQL。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(
        label_failure_case_service,
        failure_case_id,
        request.correct_sql,
        request.note,
        request.label_type,
    )
    return result


@router.post("/analyze-failures")
async def analyze_harness_failures(limit: int = 200, sync_failures: bool = True):
    """分析失败案例并生成候选规则。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(analyze_failures_online_service, limit, sync_failures)
    return result


@router.post("/auto-label-failures")
async def auto_label_harness_failures(
    limit: int = 50,
    sync_failures: bool = True,
    generate_model: str = "",
    eval_model: str = "",
):
    """LLM 自动标注 + 多维度评估失败案例。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(
        auto_label_failures_online_service,
        limit,
        sync_failures,
        settings.execution_database_url,
        generate_model or None,
        eval_model or None,
    )
    return result


@router.post("/evolve-online")
async def evolve_harness_online(limit: int = 200, sync_failures: bool = True, include_liked: bool = True):
    """从线上数据库日志生成并发布运行时知识。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(evolve_online_service, limit, sync_failures, include_liked)
    return result


@router.get("/candidates")
async def list_harness_candidates(status: str = "", limit: int = 50):
    """查看候选规则。"""
    if not settings.enable_online_harness:
        return {"items": [], "error": "线上 Harness 未启用"}
    items = await asyncio.to_thread(list_candidates_service, status or None, limit)
    return {"items": items}


@router.post("/candidates/{candidate_id}/review")
async def review_harness_candidate(candidate_id: int, request: HarnessCandidateReviewRequest):
    """审核候选规则。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(review_candidate_service, candidate_id, request.action, request.note)
    return result


@router.post("/pre-publish-check")
async def pre_publish_check_api():
    """发布前去重检查：检查所有 approved 候选是否与已有知识库重复。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    from src.harness.online_service import pre_publish_check_service

    result = await asyncio.to_thread(pre_publish_check_service)
    return result


@router.post("/publish")
async def publish_harness_candidates(request: HarnessPublishRequest):
    """发布已审核通过的候选规则。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(publish_approved_service, request.version or None)
    return result


@router.post("/feedback")
async def submit_harness_feedback(request: HarnessFeedbackRequest):
    """用户点赞/点踩反馈。点踩时自动创建失败案例进入 Harness 闭环。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    rating = 1 if request.rating == "up" else -1
    try:
        result = await asyncio.to_thread(
            get_online_harness_repository().submit_user_feedback,
            request.request_id,
            rating,
            request.reason,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"提交反馈失败: {exc}") from exc
    return result
