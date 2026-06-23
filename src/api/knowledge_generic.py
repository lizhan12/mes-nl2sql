"""通用知识库 API 路由。"""

from fastapi import APIRouter, HTTPException, status

from src.models.schemas import (
    GenericKBCreateRequest,
    GenericKBSummary,
    GenericKnowledgeItem,
    GenericKnowledgeItemCreate,
    GenericKnowledgeItemUpdate,
)
from src.services import knowledge_service

router = APIRouter(prefix="/api/knowledge/generic", tags=["通用知识库"])


@router.get("/kbs", response_model=list[GenericKBSummary])
async def list_kbs():
    """列出所有通用知识库。"""
    return await knowledge_service.list_generic_kbs()


@router.post("/kbs", response_model=GenericKBSummary, status_code=status.HTTP_201_CREATED)
async def create_kb(req: GenericKBCreateRequest):
    """创建知识库（实际是创建一个占位条目来注册知识库名称）。"""
    label = req.label or req.kb_name
    # 创建一个空条目来注册知识库
    item = GenericKnowledgeItem(label=label, fields=[])
    created = await knowledge_service.create_generic_item(req.kb_name, item)
    # 返回知识库摘要
    kbs = await knowledge_service.list_generic_kbs()
    for kb in kbs:
        if kb.kb_name == req.kb_name:
            return kb
    return GenericKBSummary(kb_name=req.kb_name, label=label, item_count=1, field_names=[])


@router.delete("/kbs/{kb_name}")
async def delete_kb(kb_name: str):
    """删除整个知识库（含其下所有条目）。"""
    deleted = await knowledge_service.delete_generic_kb(kb_name)
    return {"message": f"已删除知识库 {kb_name}，共 {deleted} 条条目", "deleted": deleted}


@router.get("/kbs/{kb_name}/items", response_model=list[GenericKnowledgeItem])
async def list_items(kb_name: str):
    """列出某知识库下所有条目。"""
    return await knowledge_service.list_generic_items(kb_name)


@router.post("/kbs/{kb_name}/items", response_model=GenericKnowledgeItem, status_code=status.HTTP_201_CREATED)
async def create_item(kb_name: str, req: GenericKnowledgeItemCreate):
    """创建通用知识库条目。"""
    if req.kb_name != kb_name:
        raise HTTPException(status_code=400, detail="URL 中的 kb_name 与请求体不一致")
    return await knowledge_service.create_generic_item(kb_name, req.item)


@router.put("/kbs/{kb_name}/items/{item_id}", response_model=GenericKnowledgeItem)
async def update_item(kb_name: str, item_id: str, req: GenericKnowledgeItemUpdate):
    """更新通用知识库条目。"""
    ok = await knowledge_service.update_generic_item(kb_name, item_id, req.label, req.fields)
    if not ok:
        raise HTTPException(status_code=404, detail=f"条目 {kb_name}/{item_id} 不存在")
    items = await knowledge_service.list_generic_items(kb_name)
    for item in items:
        if item.item_id == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"条目 {kb_name}/{item_id} 不存在")


@router.delete("/kbs/{kb_name}/items/{item_id}")
async def delete_item(kb_name: str, item_id: str):
    """删除通用知识库条目。"""
    ok = await knowledge_service.delete_generic_item(kb_name, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"条目 {kb_name}/{item_id} 不存在")
    return {"message": "删除成功"}
