"""实体词典与结构化实体提取模块。

从 data/entity_lexicon.json 加载实体词映射和动作类型规则，
提供 extract_structural_entities() 函数用于 FewShot 结构化匹配。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LEXICON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "entity_lexicon.json"

_CACHE: dict[str, Any] | None = None
_CACHE_MTIME: float = 0.0

VALID_DOMAINS = {"production", "quality", "warehouse", "equipment", "master", "barcode"}


def _read_lexicon() -> dict[str, Any]:
    """读取 entity_lexicon.json，文件修改后自动刷新缓存。"""
    global _CACHE, _CACHE_MTIME
    try:
        mtime = _LEXICON_PATH.stat().st_mtime
    except FileNotFoundError:
        logger.warning("实体词典文件不存在: %s", _LEXICON_PATH)
        return {"entity_lexicon": [], "action_patterns": []}

    if _CACHE is not None and mtime == _CACHE_MTIME:
        return _CACHE

    with open(_LEXICON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    _CACHE = data
    _CACHE_MTIME = mtime
    return data


def get_entity_lexicon_data() -> dict[str, Any]:
    """返回原始 JSON 数据（供 API 使用）。"""
    return _read_lexicon()


def save_entity_lexicon_data(data: dict[str, Any]) -> None:
    """保存 JSON 数据到文件（供 API 使用），同时刷新缓存。"""
    global _CACHE, _CACHE_MTIME
    _LEXICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LEXICON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _CACHE = None
    _CACHE_MTIME = 0.0
    logger.info("实体词典配置已保存: %s", _LEXICON_PATH)


def extract_structural_entities(query: str) -> dict[str, str]:
    """从查询文本中提取结构化实体三元组。

    Args:
        query: 用户查询文本

    Returns:
        {"object_entity": str, "action_type": str, "domain": str}
    """
    data = _read_lexicon()
    entity_lexicon = data.get("entity_lexicon", [])
    action_patterns = data.get("action_patterns", [])

    # 1. 提取 object_entity：优先匹配最长的实体词
    best_entity = ""
    best_domain = ""
    for entry in entity_lexicon:
        entity_word = entry.get("entity", "")
        if not entity_word:
            continue
        if entity_word in query and len(entity_word) > len(best_entity):
            best_entity = entity_word
            best_domain = entry.get("domain", "")

    # 2. 提取 action_type：按顺序匹配动作关键词
    best_action = "查询"  # 兜底
    for pattern in action_patterns:
        keywords = pattern.get("keywords", [])
        action = pattern.get("action", "")
        if not action or not keywords:
            continue
        if any(kw in query for kw in keywords):
            best_action = action
            break

    return {
        "object_entity": best_entity,
        "action_type": best_action,
        "domain": best_domain,
    }


def build_archive_key(structural: dict[str, str]) -> str:
    """构建结构化归档主键。

    格式: {domain}|{object_entity}|{action_type}
    例如: equipment|治具|库存查询
    """
    return f"{structural.get('domain', '')}|{structural.get('object_entity', '')}|{structural.get('action_type', '')}"
