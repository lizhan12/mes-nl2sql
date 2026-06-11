"""Trace 查询 API。"""

import uuid

from fastapi import APIRouter, HTTPException

from src.trace.repository import get_trace_repository

router = APIRouter(prefix="/api/trace", tags=["Trace 追踪"])


@router.get("/recent")
async def get_recent_traces(limit: int = 50):
    """获取最近的 trace 摘要列表。"""
    try:
        summaries = get_trace_repository().query_recent_traces(limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询 trace 失败: {exc}") from exc
    return {"traces": [s.__dict__ for s in summaries], "count": len(summaries)}


@router.get("/stats")
async def get_trace_stats(node: str = "", days: int = 7):
    """获取 trace 统计信息：各节点 P50/P95/P99 耗时、成功率、token 消耗。"""
    try:
        stats = get_trace_repository().get_trace_stats(node_name=node, days=days)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询 trace 统计失败: {exc}") from exc
    return stats


@router.get("/thread/{thread_id}")
async def get_thread_traces(thread_id: str):
    """获取整个会话的所有 trace spans。"""
    try:
        spans = get_trace_repository().query_by_thread_id(thread_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询 trace 失败: {exc}") from exc
    return {"thread_id": thread_id, "spans": spans, "count": len(spans)}


@router.get("/{trace_id}")
async def get_trace(trace_id: str):
    """获取单次请求的所有 trace spans。"""
    try:
        uuid.UUID(trace_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"无效的 trace_id: {trace_id}") from None

    try:
        spans = get_trace_repository().query_by_trace_id(trace_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询 trace 失败: {exc}") from exc
    if not spans:
        raise HTTPException(status_code=404, detail=f"trace {trace_id} 不存在")
    return {"trace_id": trace_id, "spans": spans, "count": len(spans)}
