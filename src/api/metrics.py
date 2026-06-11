"""指标路由 API。"""

from fastapi import APIRouter

from src.models.schemas import MetricClarifyRequest, MetricRouteRequest, MetricSlotAnswerRequest

router = APIRouter(prefix="/api/metrics", tags=["指标路由"])


@router.get("")
async def list_metrics(category: str = ""):
    """列出所有可用指标及其元数据。"""
    from src.services.metric_registry import list_metrics as list_m

    metrics = list_m(category)
    return {
        "metrics": [
            {
                "metric_id": m.metric_id,
                "view_name": m.view_name,
                "name": m.name,
                "category": m.category,
                "description": m.description,
                "aliases": m.aliases,
                "params": [
                    {"name": p.name, "type": p.type, "column": p.column, "required": p.required} for p in m.params
                ],
                "status": m.status,
                "note": m.note,
            }
            for m in metrics
        ],
        "total": len(metrics),
    }


@router.post("/route")
async def route_metric(request: MetricRouteRequest):
    """输入查询文本，返回路由决策结果。"""
    from src.services.metric_router import route as metric_route

    result = await metric_route(request.query)
    return {
        "channel": result.channel,
        "query": result.query,
        "metric_id": result.metric_id,
        "metric_name": result.metric_name,
        "sql": result.sql,
        "explain": result.explain,
        "params": result.params,
        "matched_term": result.matched_term,
        "clarification_prompt": result.clarification_prompt,
        "candidates": result.candidates,
        "multi_metric_ids": result.multi_metric_ids,
        "multi_sqls": result.multi_sqls,
    }


@router.post("/clarify")
async def clarify_metric(request: MetricClarifyRequest):
    """用户选择歧义指标后，返回组装好的 SQL。"""
    from src.services.metric_router import route_clarification

    result = await route_clarification(request.query, request.metric_id)
    return {
        "channel": result.channel,
        "metric_id": result.metric_id,
        "metric_name": result.metric_name,
        "sql": result.sql,
        "explain": result.explain,
        "params": result.params,
    }


@router.post("/slot-answer")
async def slot_answer(request: MetricSlotAnswerRequest):
    """用户确认槽位追问后，跳过置信度检查直接组装 SQL。"""
    from src.services.metric_router import route_slot_answer

    result = await route_slot_answer(request.query, request.metric_id)
    return {
        "channel": result.channel,
        "metric_id": result.metric_id,
        "metric_name": result.metric_name,
        "sql": result.sql,
        "explain": result.explain,
        "params": result.params,
    }
