"""FewShot 与 EvolvedFewShot 示例管理接口。"""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query

from src.models.schemas import (
    EvolvedFewShotCreateRequest,
    EvolvedFewShotItem,
    EvolvedFewShotUpdateRequest,
    FewShotCreateRequest,
    FewShotItem,
    FewShotUpdateRequest,
)

router = APIRouter(prefix="/api/knowledge")


# ── FewShot 管理 ──────────────────────────────────────────────────


@router.get("/few-shots", response_model=list[FewShotItem])
async def list_few_shots_api():
    """列出所有 FewShot 示例。"""
    from src.services.knowledge_service import list_few_shots

    items = list_few_shots()
    return [FewShotItem(**item) for item in items]


@router.post("/few-shots", response_model=FewShotItem)
async def create_few_shot_api(
    request: FewShotCreateRequest, force: bool = Query(False, description="强制创建（跳过重复检查）")
):
    """创建新的 FewShot 示例。"""
    from src.services.knowledge_service import check_few_shot_dedup, create_few_shot

    if not force:
        dedup = await asyncio.to_thread(check_few_shot_dedup, request.question)
        if dedup["has_duplicate"]:
            if dedup["exact_match"]:
                raise HTTPException(
                    status_code=409,
                    detail="已存在完全相同的 FewShot 示例",
                )
            raise HTTPException(
                status_code=409,
                detail=json.dumps({"duplicate_items": dedup["similar_items"]}, ensure_ascii=False),
            )

    try:
        result = await asyncio.to_thread(create_few_shot, request.scenario, request.question, request.sql)
        return FewShotItem(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建 FewShot 失败: {exc}") from exc


@router.put("/few-shots/{few_shot_id}")
async def update_few_shot_api(few_shot_id: str, request: FewShotUpdateRequest):
    """更新 FewShot 示例。"""
    from src.services.knowledge_service import update_few_shot

    ok = await asyncio.to_thread(update_few_shot, few_shot_id, request.scenario, request.question, request.sql)
    if not ok:
        raise HTTPException(status_code=404, detail=f"FewShot {few_shot_id} 不存在")
    return {"message": f"FewShot {few_shot_id} 更新成功", "id": few_shot_id}


@router.delete("/few-shots/{few_shot_id}")
async def delete_few_shot_api(few_shot_id: str):
    """删除 FewShot 示例。"""
    from src.services.knowledge_service import delete_few_shot

    ok = await asyncio.to_thread(delete_few_shot, few_shot_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"FewShot {few_shot_id} 不存在")
    return {"message": f"FewShot {few_shot_id} 已删除", "id": few_shot_id}


# ── EvolvedFewShot 管理 ───────────────────────────────────────────


@router.get("/evolved-few-shots", response_model=list[EvolvedFewShotItem])
async def list_evolved_few_shots_api():
    """列出所有 EvolvedFewShot 示例。"""
    from src.services.knowledge_service import list_evolved_few_shots

    items = list_evolved_few_shots()
    return [EvolvedFewShotItem(**item) for item in items]


@router.post("/evolved-few-shots", response_model=EvolvedFewShotItem)
async def create_evolved_few_shot_api(request: EvolvedFewShotCreateRequest):
    """创建新的 EvolvedFewShot 示例。"""
    from src.services.knowledge_service import create_evolved_few_shot

    try:
        result = await asyncio.to_thread(create_evolved_few_shot, request.scenario, request.question, request.sql)
        return EvolvedFewShotItem(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建 EvolvedFewShot 失败: {exc}") from exc


@router.put("/evolved-few-shots/{evolved_id}")
async def update_evolved_few_shot_api(evolved_id: str, request: EvolvedFewShotUpdateRequest):
    """更新 EvolvedFewShot 示例。"""
    from src.services.knowledge_service import update_evolved_few_shot

    ok = await asyncio.to_thread(update_evolved_few_shot, evolved_id, request.scenario, request.question, request.sql)
    if not ok:
        raise HTTPException(status_code=404, detail=f"EvolvedFewShot {evolved_id} 不存在")
    return {"message": f"EvolvedFewShot {evolved_id} 更新成功", "id": evolved_id}


@router.delete("/evolved-few-shots/{evolved_id}")
async def delete_evolved_few_shot_api(evolved_id: str):
    """删除 EvolvedFewShot 示例。"""
    from src.services.knowledge_service import delete_evolved_few_shot

    ok = await asyncio.to_thread(delete_evolved_few_shot, evolved_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"EvolvedFewShot {evolved_id} 不存在")
    return {"message": f"EvolvedFewShot {evolved_id} 已删除", "id": evolved_id}
