"""RuntimeRule 运行时规则管理接口。"""

import json

from fastapi import APIRouter, HTTPException, Query

from src.models.schemas import (
    RuntimeRuleCreateRequest,
    RuntimeRuleItem,
    RuntimeRuleUpdateRequest,
    ToggleEnabledRequest,
)

router = APIRouter(prefix="/api/knowledge")


@router.get("/runtime-rules", response_model=list[RuntimeRuleItem])
async def list_runtime_rules_api():
    """List all RuntimeRule entries."""
    from src.services.knowledge_service import list_runtime_rules

    items = await list_runtime_rules()
    return [RuntimeRuleItem(**item) for item in items]


@router.post("/runtime-rules", response_model=RuntimeRuleItem)
async def create_runtime_rule_api(
    request: RuntimeRuleCreateRequest, force: bool = Query(False, description="强制创建（跳过重复检查）")
):
    """Create a new RuntimeRule."""
    from src.services.knowledge_service import check_runtime_rule_dedup, create_runtime_rule

    if not force:
        dedup = await check_runtime_rule_dedup(request.normalized_question)
        if dedup["has_duplicate"]:
            if dedup["exact_match"]:
                raise HTTPException(
                    status_code=409,
                    detail="已存在完全相同的 RuntimeRule 规则",
                )
            raise HTTPException(
                status_code=409,
                detail=json.dumps({"duplicate_items": dedup["similar_items"]}, ensure_ascii=False),
            )

    try:
        result = await create_runtime_rule(
            request.question,
            request.normalized_question,
            request.preferred_main_table,
            request.required_tables,
            request.required_joins,
            request.source,
        )
        return RuntimeRuleItem(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create RuntimeRule: {exc}") from exc


@router.put("/runtime-rules/{normalized_question:path}")
async def update_runtime_rule_api(normalized_question: str, request: RuntimeRuleUpdateRequest):
    """Update a RuntimeRule."""
    from src.services.knowledge_service import update_runtime_rule

    ok = await update_runtime_rule(
        normalized_question,
        request.question,
        request.preferred_main_table,
        request.required_tables,
        request.required_joins,
        request.source,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"RuntimeRule {normalized_question} 不存在")
    return {"message": f"RuntimeRule {normalized_question} 已更新"}


@router.delete("/runtime-rules/{normalized_question:path}")
async def delete_runtime_rule_api(normalized_question: str):
    """Delete a RuntimeRule."""
    from src.services.knowledge_service import delete_runtime_rule

    ok = await delete_runtime_rule(normalized_question)
    if not ok:
        raise HTTPException(status_code=404, detail=f"RuntimeRule {normalized_question} 不存在")
    return {"message": f"RuntimeRule {normalized_question} 已删除", "normalized_question": normalized_question}


@router.patch("/runtime-rules/{normalized_question:path}/enabled")
async def toggle_runtime_rule_api(normalized_question: str, request: ToggleEnabledRequest):
    """切换 RuntimeRule 启用/禁用状态。"""
    from src.services.knowledge_service import toggle_runtime_rule

    ok = await toggle_runtime_rule(normalized_question, request.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail=f"RuntimeRule {normalized_question} 不存在")
    return {"message": f"RuntimeRule {normalized_question} 已{'启用' if request.enabled else '禁用'}", "enabled": request.enabled}
