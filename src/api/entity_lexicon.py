"""实体词典配置管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.graph.entity_lexicon import (
    VALID_DOMAINS,
    extract_structural_entities,
    get_entity_lexicon_data,
    save_entity_lexicon_data,
)

router = APIRouter(prefix="/api/knowledge/entity-lexicon", tags=["实体词典"])


@router.get("")
async def get_entity_lexicon():
    """获取实体词典配置。"""
    return get_entity_lexicon_data()


@router.put("")
async def update_entity_lexicon(data: dict):
    """更新实体词典配置。"""
    # 验证 entity_lexicon
    entity_lexicon = data.get("entity_lexicon", [])
    for i, entry in enumerate(entity_lexicon):
        if not entry.get("entity"):
            raise HTTPException(400, f"entity_lexicon[{i}].entity 不能为空")
        if entry.get("domain") not in VALID_DOMAINS:
            raise HTTPException(400, f"entity_lexicon[{i}].domain 必须是 {VALID_DOMAINS} 之一")

    # 验证 action_patterns
    action_patterns = data.get("action_patterns", [])
    for i, pattern in enumerate(action_patterns):
        if not pattern.get("action"):
            raise HTTPException(400, f"action_patterns[{i}].action 不能为空")
        if not pattern.get("keywords"):
            raise HTTPException(400, f"action_patterns[{i}].keywords 不能为空列表")

    save_entity_lexicon_data(data)
    return {"status": "ok"}


@router.post("/preview")
async def preview_extract(query: str):
    """预览结构化实体提取结果。"""
    structural = extract_structural_entities(query)
    from src.graph.entity_lexicon import build_archive_key

    archive_key = build_archive_key(structural)
    return {"query": query, "structural": structural, "archive_key": archive_key}
