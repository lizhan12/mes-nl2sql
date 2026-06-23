"""FewShot 示例管理接口。"""

from fastapi import APIRouter, HTTPException, Query

from src.models.schemas import (
    FewShotCreateRequest,
    FewShotItem,
    FewShotUpdateRequest,
    ToggleEnabledRequest,
)

router = APIRouter(prefix="/api/knowledge")


# ── FewShot 管理 ──────────────────────────────────────────────────


@router.get("/few-shots", response_model=list[FewShotItem])
async def list_few_shots_api():
    """列出所有 FewShot 示例。"""
    from src.services.knowledge_service import list_few_shots

    items = await list_few_shots()
    return [FewShotItem(**item) for item in items]


@router.post("/few-shots", response_model=FewShotItem)
async def create_few_shot_api(
    request: FewShotCreateRequest, force: bool = Query(True, description="已废弃，始终覆盖已存在的同 question 示例")
):
    """创建或覆盖 FewShot 示例（若同 question 已存在则直接覆盖）。"""
    from src.services.knowledge_service import create_few_shot

    try:
        result = await create_few_shot(request.scenario, request.question, request.sql, request.type)
        return FewShotItem(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建 FewShot 失败: {exc}") from exc


@router.put("/few-shots/{few_shot_id}")
async def update_few_shot_api(few_shot_id: str, request: FewShotUpdateRequest):
    """更新 FewShot 示例。"""
    from src.services.knowledge_service import update_few_shot

    ok = await update_few_shot(few_shot_id, request.scenario, request.question, request.sql)
    if not ok:
        raise HTTPException(status_code=404, detail=f"FewShot {few_shot_id} 不存在")
    return {"message": f"FewShot {few_shot_id} 更新成功", "id": few_shot_id}


@router.delete("/few-shots/{few_shot_id}")
async def delete_few_shot_api(few_shot_id: str):
    """删除 FewShot 示例。"""
    from src.services.knowledge_service import delete_few_shot

    ok = await delete_few_shot(few_shot_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"FewShot {few_shot_id} 不存在")
    return {"message": f"FewShot {few_shot_id} 已删除", "id": few_shot_id}


# ── 启用/禁用 ───────────────────────────────────────────────────────


@router.patch("/few-shots/{few_shot_id}/enabled")
async def toggle_few_shot_api(few_shot_id: str, request: ToggleEnabledRequest):
    """切换 FewShot 启用/禁用状态。"""
    from src.services.knowledge_service import toggle_few_shot

    ok = await toggle_few_shot(few_shot_id, request.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail=f"FewShot {few_shot_id} 不存在")
    return {"message": f"FewShot {few_shot_id} 已{'启用' if request.enabled else '禁用'}", "enabled": request.enabled}
