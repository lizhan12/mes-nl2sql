"""知识库管理服务，从 Neo4j 读写表知识库。

职责：
  - 从 Neo4j 加载所有表摘要 / 单表详情
  - 更新表定义：同步 Neo4j Table 节点 + 同步本地文件 + 重建关键词索引
  - 从原始文本中通过 LLM 抽取表结构定义
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from src.core.config import settings
from src.services.vector_store import (
    _build_keyword_index,
    _build_schema_embed_text,
    _get_embeddings,
    _parse_schema_chunk,
)

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_KB_FILE = _DATA_DIR / "mes_knowledge_base.txt"

# 字段行正则：  col_name (type) -- comment
_FIELD_LINE_RE = re.compile(r"^(\s*)(\w+)\s*\((.+?)\)\s*--\s*(.*)")
# 无注释的字段行
_FIELD_LINE_NO_COMMENT_RE = re.compile(r"^(\s*)(\w+)\s*\((.+?)\)\s*$")


async def load_all_tables() -> list[dict]:
    """从 Neo4j 加载所有表的摘要信息。"""
    try:
        from src.services.neo4j_graph import _get_driver

        driver = await _get_driver()
        async with driver.session() as session:
            result = await session.run("""
                MATCH (t:Table)
                RETURN t.name AS name, t.module AS module,
                       t.business_meaning AS bm, t.full_text AS full_text
                ORDER BY t.name
            """)
            tables = []
            async for rec in result:
                full_text = rec["full_text"] or ""
                field_count = _count_fields_from_full_text(full_text)
                tables.append(
                    {
                        "table_name": rec["name"] or "",
                        "module": rec["module"] or "",
                        "business_meaning": rec["bm"] or "",
                        "field_count": field_count,
                    }
                )
            return tables
    except Exception as exc:
        logger.error("从 Neo4j 加载表列表失败: %s", exc)
        return []


async def get_table(name: str) -> dict | None:
    """从 Neo4j 获取单张表的完整详情。

    同时从关系图中补充关联关系信息。
    """
    try:
        from src.services.neo4j_graph import _get_driver

        driver = await _get_driver()
        async with driver.session() as session:
            result = await session.run(
                """
                MATCH (t:Table {name: $name})
                RETURN t.name AS name, t.module AS module,
                       t.business_meaning AS bm, t.full_text AS full_text
                """,
                {"name": name},
            )
            rec = await result.single()
            if not rec:
                return None

            full_text = rec["full_text"] or ""
            fields = _parse_fields(full_text) if full_text else []
            meta = _parse_schema_chunk(full_text) if full_text else {}

            # 从关系图补充关联关系（比 full_text 中的更完整）
            relations = await _load_relations_from_graph(session, name)
            # 如果关系图中没有数据，降级用 full_text 中的
            if not relations:
                relations = meta.get("relations", [])

            return {
                "table_name": rec["name"] or "",
                "module": rec["module"] or "",
                "business_meaning": rec["bm"] or "",
                "fields": fields,
                "relations": relations,
                "scenarios": meta.get("scenarios", []),
            }
    except Exception as exc:
        logger.error("从 Neo4j 加载表详情失败: %s", exc)
        return None


async def update_table(name: str, data: dict) -> bool:
    """更新一张表的定义：同步 Neo4j + 同步本地文件 + 重建关键词索引。"""
    new_table_name = data.get("table_name", name)
    full_text = _build_chunk_text(data)

    # 1. 同步本地文件
    _sync_to_local_file(name, new_table_name, full_text)

    # 2. 如果表名变更，先重命名 Neo4j 节点以保留所有关联边
    if new_table_name != name:
        await _rename_neo4j_node(name, new_table_name)

    # 3. 同步 Neo4j（MERGE + 更新 embedding）
    await _sync_to_neo4j(new_table_name, full_text, data.get("module", ""), data.get("business_meaning", ""), data)

    # 4. 重建关键词索引
    await _rebuild_keyword_index()

    return True


# ── 内部辅助 ────────────────────────────────────────────────────────


async def _load_relations_from_graph(session, table_name: str) -> list[str]:
    """从 Neo4j 关系图中加载指定表的关联关系描述。"""
    result = await session.run(
        """
        MATCH (a:Table {name: $name})-[r:JOIN_REL]-(b:Table)
        RETURN b.name AS related_table, r.description AS desc,
               r.from_field AS from_field, r.to_field AS to_field
        """,
        {"name": table_name},
    )
    relations = []
    async for rec in result:
        desc = rec["desc"] or ""
        related = rec["related_table"] or ""
        if desc:
            relations.append(f"{related}({desc})")
        else:
            ff = rec["from_field"] or ""
            tf = rec["to_field"] or ""
            if ff and tf:
                relations.append(f"{related}({ff}={tf})")
            else:
                relations.append(related)
    return relations


def _count_fields_from_full_text(full_text: str) -> int:
    """从 full_text 中统计关键字段数量。"""
    count = 0
    in_fields = False
    for line in full_text.split("\n"):
        stripped = line.strip()
        if stripped == "关键字段：":
            in_fields = True
            continue
        if in_fields:
            if stripped.startswith("关联关系：") or stripped.startswith("适用场景："):
                break
            if stripped and (stripped[0].isalpha() or stripped[0] == "_"):
                count += 1
    return count


def _parse_fields(chunk: str) -> list[dict]:
    """从 chunk 文本中解析字段列表，拆分为 name / type / comment。"""
    fields: list[dict] = []
    in_fields = False
    for line in chunk.split("\n"):
        stripped = line.strip()
        if stripped == "关键字段：":
            in_fields = True
            continue
        if in_fields:
            if stripped.startswith("关联关系：") or stripped.startswith("适用场景：") or stripped == "":
                if stripped and not stripped.startswith("关联关系：") and not stripped.startswith("适用场景："):
                    continue
                break
            m = _FIELD_LINE_RE.match(line)
            if m:
                fields.append(
                    {"name": m.group(2), "type": m.group(3).strip(), "comment": m.group(4).strip().rstrip(")")}
                )
                continue
            m2 = _FIELD_LINE_NO_COMMENT_RE.match(line)
            if m2:
                fields.append({"name": m2.group(2), "type": m2.group(3).strip(), "comment": ""})
                continue
            if stripped:
                fields.append({"name": stripped, "type": "", "comment": ""})
    return fields


def _build_chunk_text(data: dict, original_chunk: str = "") -> str:
    """根据 update 数据构建知识库 chunk 文本。

    注意：不再包含"关联关系"段。JOIN 关系统一由 Neo4j (:JOIN_REL 边) 管理，
    在运行时通过 BFS 节点动态注入 prompt，避免数据双写不一致。
    """
    lines: list[str] = []
    table_name = data.get("table_name", "")
    lines.append(f"表名：{table_name}")
    lines.append(f"模块：{data.get('module', '')}")
    lines.append(f"业务含义：{data.get('business_meaning', '')}")

    lines.append("关键字段：")
    for f in data.get("fields", []):
        name = f.get("name", "")
        ftype = f.get("type", "")
        comment = f.get("comment", "")
        if comment:
            lines.append(f"  {name} ({ftype}) -- {comment}")
        else:
            lines.append(f"  {name} ({ftype})")

    scenarios = data.get("scenarios", [])
    if scenarios:
        lines.append("适用场景：")
        for s in scenarios:
            lines.append(s)

    return "\n".join(lines)


def _sync_to_local_file(original_name: str, new_name: str, new_full_text: str) -> None:
    """将更新后的表定义写回 mes_knowledge_base.txt 本地文件。"""
    try:
        if not _KB_FILE.exists():
            logger.warning("本地知识库文件不存在: %s", _KB_FILE)
            return

        content = _KB_FILE.read_text(encoding="utf-8")
        chunks = content.split("\n---\n")
        new_chunks: list[str] = []
        found = False

        for chunk in chunks:
            chunk_stripped = chunk.strip()
            if not chunk_stripped:
                continue
            meta = _parse_schema_chunk(chunk_stripped)
            if meta.get("table_name") == original_name:
                if not found:
                    # 首次匹配：替换
                    new_chunks.append(new_full_text)
                    found = True
                # 后续同名 chunk 跳过（去重）
            else:
                new_chunks.append(chunk_stripped)

        if not found:
            # 新表，追加到末尾
            new_chunks.append(new_full_text)

        clean = [c for c in new_chunks if c]
        new_content = "\n---\n".join(clean) + "\n"
        _KB_FILE.write_text(new_content, encoding="utf-8")
        logger.info("已同步本地文件: %s", _KB_FILE)
    except Exception as exc:
        logger.warning("同步本地文件失败（非致命）: %s", exc)


async def _sync_to_neo4j(table_name: str, full_text: str, module: str, business_meaning: str, data: dict) -> None:
    """对更新后的表重新生成 embedding 并同步到 Neo4j Table 节点。

    使用 MERGE 支持新建和更新两种场景。
    """
    try:
        from src.services.neo4j_graph import _derive_domain, _derive_prefix, _get_driver

        embeddings = _get_embeddings()

        # 用完整元数据构建 embedding 文本（包含字段、关联、场景）
        meta = _parse_schema_chunk(full_text)
        embed_text = _build_schema_embed_text(meta)
        if not embed_text.strip():
            embed_text = full_text
        vector = embeddings.embed_query(embed_text)

        domain = _derive_domain(table_name)
        prefix = _derive_prefix(table_name)

        driver = await _get_driver()
        async with driver.session() as session:
            await session.run(
                """
                MERGE (t:Table {name: $name})
                SET t.schema_embedding = $embedding,
                    t.full_text = $full_text,
                    t.module = $module,
                    t.business_meaning = $business_meaning,
                    t.domain = $domain,
                    t.prefix = $prefix
                """,
                {
                    "name": table_name,
                    "embedding": vector,
                    "full_text": full_text,
                    "module": module,
                    "business_meaning": business_meaning,
                    "domain": domain,
                    "prefix": prefix,
                },
            )
        logger.info("已同步 Neo4j Table 节点: %s (embedding 已重新生成)", table_name)
    except Exception as exc:
        logger.warning("同步 Neo4j 失败（非致命）: %s", exc)


async def _rename_neo4j_node(old_name: str, new_name: str) -> None:
    """重命名 Neo4j Table 节点名称，保留所有关联边和属性。"""
    try:
        from src.services.neo4j_graph import _get_driver

        driver = await _get_driver()
        async with driver.session() as session:
            result = await session.run(
                """
                MATCH (t:Table {name: $old_name})
                SET t.name = $new_name
                RETURN count(t) AS updated
                """,
                {"old_name": old_name, "new_name": new_name},
            )
            rec = await result.single()
            updated = rec["updated"] if rec else 0
            if updated:
                logger.info("已将 Neo4j Table 节点重命名: %s -> %s", old_name, new_name)
            else:
                logger.warning("Neo4j 中未找到要重命名的 Table 节点: %s", old_name)
    except Exception as exc:
        logger.warning("重命名 Neo4j 节点失败（非致命）: %s", exc)


async def _rebuild_keyword_index() -> None:
    """从 Neo4j 重建全局关键词倒排索引。"""
    import src.services.vector_store as vs

    try:
        from src.services.neo4j_graph import _get_driver

        driver = await _get_driver()
        async with driver.session() as session:
            result = await session.run("""
                MATCH (t:Table)
                WHERE t.full_text IS NOT NULL AND t.full_text <> ''
                RETURN t.full_text AS full_text
            """)
            chunks = []
            async for rec in result:
                full_text = rec["full_text"]
                meta = _parse_schema_chunk(full_text)
                embed_text = _build_schema_embed_text(meta)
                chunks.append(
                    {
                        "full_text": full_text,
                        "embed_text": embed_text,
                        "metadata": meta,
                    }
                )
        vs._keyword_index = _build_keyword_index(chunks)
        logger.info("关键词索引重建完成（从 Neo4j），共 %d 个词条", len(vs._keyword_index))
    except Exception as exc:
        logger.warning("从 Neo4j 重建关键词索引失败: %s", exc)


# ── 删除表 ───────────────────────────────────────────────────────────


async def delete_table(table_name: str) -> bool:
    """删除知识库中的表定义：从本地文件移除 chunk、从 Neo4j 删除 Table 节点和关联边。"""
    # 1. 从本地文件移除
    _remove_from_local_file(table_name)
    # 2. 从 Neo4j 删除 Table 节点（DETACH DELETE 会级联删除关联 JOIN_REL 边）
    await _delete_from_neo4j(table_name)
    # 3. 重建关键词索引
    await _rebuild_keyword_index()
    return True


def _remove_from_local_file(table_name: str) -> None:
    """从 mes_knowledge_base.txt 中移除指定表的 chunk。"""
    try:
        if not _KB_FILE.exists():
            logger.warning("本地知识库文件不存在: %s", _KB_FILE)
            return

        content = _KB_FILE.read_text(encoding="utf-8")
        chunks = content.split("\n---\n")
        new_chunks: list[str] = []

        for chunk in chunks:
            chunk_stripped = chunk.strip()
            if not chunk_stripped:
                continue
            meta = _parse_schema_chunk(chunk_stripped)
            if meta.get("table_name") == table_name:
                continue
            new_chunks.append(chunk_stripped)

        clean = [c for c in new_chunks if c]
        new_content = "\n---\n".join(clean) + "\n"
        _KB_FILE.write_text(new_content, encoding="utf-8")
        logger.info("已从本地文件移除表: %s", table_name)
    except Exception as exc:
        logger.warning("从本地文件移除表失败（非致命）: %s", exc)


async def _delete_from_neo4j(table_name: str) -> None:
    """从 Neo4j 删除 Table 节点，DETACH DELETE 级联删除关联 JOIN_REL 边。"""
    try:
        from src.services.neo4j_graph import _get_driver

        driver = await _get_driver()
        async with driver.session() as session:
            result = await session.run(
                "MATCH (t:Table {name: $name}) DETACH DELETE t RETURN count(t) AS deleted",
                {"name": table_name},
            )
            rec = await result.single()
            deleted = rec["deleted"] if rec else 0
            if deleted:
                logger.info("已从 Neo4j 删除 Table 节点: %s（关联边已级联删除）", table_name)
            else:
                logger.warning("Neo4j 中未找到 Table 节点: %s", table_name)
    except Exception as exc:
        logger.warning("从 Neo4j 删除表失败（非致命）: %s", exc)


# ── FewShot CRUD ─────────────────────────────────────────────────────


async def list_few_shots() -> list[dict]:
    """从 Neo4j 加载所有 FewShot 示例。"""
    try:
        from src.services.neo4j_graph import _get_driver

        driver = await _get_driver()
        async with driver.session() as session:
            result = await session.run("""
                MATCH (f:FewShot)
                RETURN f.id AS id, f.type AS type, f.scenario AS scenario,
                       f.question AS question, f.full_text AS full_text,
                       COALESCE(f.enabled, true) AS enabled
                ORDER BY f.id
            """)
            return [
                {
                    "id": rec["id"] or "",
                    "type": rec["type"] or "manual",
                    "scenario": rec["scenario"] or "",
                    "question": rec["question"] or "",
                    "full_text": rec["full_text"] or "",
                    "enabled": rec["enabled"] if rec["enabled"] is not None else True,
                }
                async for rec in result
            ]
    except Exception as exc:
        logger.error("从 Neo4j 加载 FewShot 列表失败: %s", exc)
        return []


# ── 去重检查 ────────────────────────────────────────────────────────


async def check_few_shot_dedup(question: str) -> dict:
    """检查 FewShot 是否已存在（精确匹配 + 向量相似度）。

    Returns:
        {
            "has_duplicate": bool,
            "exact_match": bool,
            "similar_items": [{"key": ..., "question": ..., "score": ..., "match_type": ...}]
        }
    """
    from src.services.neo4j_graph import _get_driver
    from src.services.vector_store import _build_few_shot_embed_text, _get_embeddings

    similar_items = []

    # 1. 精确匹配检查
    driver = await _get_driver()
    async with driver.session() as session:
        # 检查 FewShot 节点精确匹配
        result = await session.run(
            "MATCH (f:FewShot) WHERE f.question = $question RETURN f.id AS id, f.question AS question, f.scenario AS scenario, f.full_text AS full_text",
            {"question": question},
        )
        records = [rec async for rec in result]
        for rec in records:
            similar_items.append(
                {
                    "key": str(rec["id"] or ""),
                    "question": str(rec["question"] or ""),
                    "score": 1.0,
                    "match_type": "exact",
                    "existing_item": {
                        "id": str(rec["id"] or ""),
                        "scenario": str(rec["scenario"] or ""),
                        "question": str(rec["question"] or ""),
                        "full_text": str(rec["full_text"] or ""),
                    },
                }
            )

    has_exact = any(item["match_type"] == "exact" for item in similar_items)
    if has_exact:
        return {"has_duplicate": True, "exact_match": True, "similar_items": similar_items}

    # 2. 向量相似度检查
    try:
        embeddings = _get_embeddings()
        embed_text = _build_few_shot_embed_text({"scenario": "", "question": question})
        query_vec = embeddings.embed_query(embed_text)
        threshold = settings.dedup_similarity_threshold

        async with driver.session() as session:
            # 在 FewShot 节点上做向量相似度搜索
            result = await session.run(
                """
                MATCH (f:FewShot)
                WHERE f.question_embedding IS NOT NULL
                WITH f, vector.similarity.cosine(f.question_embedding, $query_vec) AS score
                WHERE score >= $threshold
                RETURN f.id AS id, f.question AS question, f.scenario AS scenario, f.full_text AS full_text, score
                ORDER BY score DESC
                LIMIT 3
                """,
                {"query_vec": query_vec, "threshold": threshold},
            )
            async for rec in result:
                similar_items.append(
                    {
                        "key": str(rec["id"] or ""),
                        "question": str(rec["question"] or ""),
                        "score": float(rec["score"]),
                        "match_type": "vector",
                        "existing_item": {
                            "id": str(rec["id"] or ""),
                            "scenario": str(rec["scenario"] or ""),
                            "question": str(rec["question"] or ""),
                            "full_text": str(rec["full_text"] or ""),
                        },
                    }
                )

    except Exception as exc:
        logger.warning("FewShot 向量去重检查失败: %s", exc)

    return {
        "has_duplicate": len(similar_items) > 0,
        "exact_match": False,
        "similar_items": similar_items,
    }


async def check_runtime_rule_dedup(normalized_question: str) -> dict:
    """检查 RuntimeRule 是否已存在（精确匹配 + 向量相似度）。

    Returns:
        {
            "has_duplicate": bool,
            "exact_match": bool,
            "similar_items": [{"key": ..., "question": ..., "score": ..., "match_type": ...}]
        }
    """
    from src.services.neo4j_graph import _get_driver
    from src.services.vector_store import _get_embeddings

    similar_items = []

    driver = await _get_driver()

    # 1. 精确匹配检查
    async with driver.session() as session:
        result = await session.run(
            "MATCH (r:RuntimeRule) WHERE r.normalized_question = $nq "
            "RETURN r.normalized_question AS normalized_question, r.question AS question, "
            "r.preferred_main_table AS preferred_main_table, r.required_tables AS required_tables, "
            "r.required_joins AS required_joins, r.source AS source",
            {"nq": normalized_question},
        )
        records = [rec async for rec in result]
        for rec in records:
            similar_items.append(
                {
                    "key": str(rec["normalized_question"] or ""),
                    "question": str(rec["question"] or ""),
                    "score": 1.0,
                    "match_type": "exact",
                    "existing_item": {
                        "normalized_question": str(rec["normalized_question"] or ""),
                        "question": str(rec["question"] or ""),
                        "preferred_main_table": str(rec["preferred_main_table"] or ""),
                        "source": str(rec["source"] or ""),
                    },
                }
            )

    has_exact = any(item["match_type"] == "exact" for item in similar_items)
    if has_exact:
        return {"has_duplicate": True, "exact_match": True, "similar_items": similar_items}

    # 2. 向量相似度检查
    try:
        embeddings = _get_embeddings()
        query_vec = embeddings.embed_query(normalized_question[:500])
        threshold = settings.dedup_similarity_threshold

        async with driver.session() as session:
            result = await session.run(
                """
                MATCH (r:RuntimeRule)
                WHERE r.question_embedding IS NOT NULL
                WITH r, vector.similarity.cosine(r.question_embedding, $query_vec) AS score
                WHERE score >= $threshold
                RETURN r.normalized_question AS normalized_question, r.question AS question,
                       r.preferred_main_table AS preferred_main_table, r.source AS source, score
                ORDER BY score DESC
                LIMIT 3
                """,
                {"query_vec": query_vec, "threshold": threshold},
            )
            async for rec in result:
                similar_items.append(
                    {
                        "key": str(rec["normalized_question"] or ""),
                        "question": str(rec["question"] or ""),
                        "score": float(rec["score"]),
                        "match_type": "vector",
                        "existing_item": {
                            "normalized_question": str(rec["normalized_question"] or ""),
                            "question": str(rec["question"] or ""),
                            "preferred_main_table": str(rec["preferred_main_table"] or ""),
                            "source": str(rec["source"] or ""),
                        },
                    }
                )
    except Exception as exc:
        logger.warning("RuntimeRule 向量去重检查失败: %s", exc)

    return {
        "has_duplicate": len(similar_items) > 0,
        "exact_match": False,
        "similar_items": similar_items,
    }


async def create_few_shot(scenario: str, question: str, sql: str, few_shot_type: str = "manual") -> dict:
    """创建或覆盖 FewShot 示例（若同 question 已存在则覆盖）。"""
    import uuid

    from src.services.neo4j_graph import _get_driver
    from src.services.vector_store import _build_few_shot_embed_text, _get_embeddings

    # 构建 full_text
    full_text = f"场景：{scenario}\n用户问题：{question}\nSQL：\n{sql}"

    # 生成 embedding
    embeddings = _get_embeddings()
    embed_text = _build_few_shot_embed_text({"scenario": scenario, "question": question})
    embedding = embeddings.embed_query(embed_text)

    # 写入 Neo4j：先查找同 question 的已有节点，存在则复用 ID 覆盖，否则新建
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:FewShot {question: $question}) RETURN f.id AS id LIMIT 1",
            {"question": question},
        )
        rec = await result.single()
        few_shot_id = str(rec["id"]) if rec else f"few_{uuid.uuid4().hex[:8]}"

        await session.run(
            """
            MERGE (f:FewShot {id: $id})
            SET f.type = $type,
                f.scenario = $scenario,
                f.question = $question,
                f.full_text = $full_text,
                f.question_embedding = $embedding,
                f.enabled = true
            """,
            {
                "id": few_shot_id,
                "type": few_shot_type,
                "scenario": scenario,
                "question": question,
                "full_text": full_text,
                "embedding": embedding,
            },
        )

    logger.info("已创建/覆盖 FewShot: %s (type=%s)", few_shot_id, few_shot_type)
    return {"id": few_shot_id, "type": few_shot_type, "scenario": scenario, "question": question, "full_text": full_text}


async def update_few_shot(few_shot_id: str, scenario: str, question: str, sql: str) -> bool:
    """更新 FewShot 示例。"""
    from src.services.neo4j_graph import _get_driver
    from src.services.vector_store import _build_few_shot_embed_text, _get_embeddings

    # 构建 full_text
    full_text = f"场景：{scenario}\n用户问题：{question}\nSQL：\n{sql}"

    # 重新生成 embedding
    embeddings = _get_embeddings()
    embed_text = _build_few_shot_embed_text({"scenario": scenario, "question": question})
    embedding = embeddings.embed_query(embed_text)

    # 更新 Neo4j
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:FewShot {id: $id})
            SET f.scenario = $scenario,
                f.question = $question,
                f.full_text = $full_text,
                f.question_embedding = $embedding
            RETURN count(f) AS updated
            """,
            {
                "id": few_shot_id,
                "scenario": scenario,
                "question": question,
                "full_text": full_text,
                "embedding": embedding,
            },
        )
        rec = await result.single()
        updated = rec["updated"] if rec else 0

    if updated:
        logger.info("已更新 FewShot: %s", few_shot_id)
    return bool(updated)


async def delete_few_shot(few_shot_id: str) -> bool:
    """删除 FewShot 示例。"""
    from src.services.neo4j_graph import _get_driver

    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:FewShot {id: $id}) DETACH DELETE f RETURN count(f) AS deleted",
            {"id": few_shot_id},
        )
        rec = await result.single()
        deleted = rec["deleted"] if rec else 0

    if deleted:
        logger.info("已删除 FewShot: %s", few_shot_id)
    return bool(deleted)


async def toggle_few_shot(few_shot_id: str, enabled: bool) -> bool:
    """切换 FewShot 启用/禁用状态。"""
    from src.services.neo4j_graph import _get_driver

    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:FewShot {id: $id}) SET f.enabled = $enabled RETURN count(f) AS updated",
            {"id": few_shot_id, "enabled": enabled},
        )
        rec = await result.single()
        updated = rec["updated"] if rec else 0

    if updated:
        logger.info("已%s FewShot: %s", "启用" if enabled else "禁用", few_shot_id)
    return bool(updated)


# ── RuntimeRule CRUD ─────────────────────────────────────────────────


async def list_runtime_rules() -> list[dict]:
    """从 Neo4j 加载所有 RuntimeRule 规则。"""
    import json

    def _parse_json_list(value) -> list[str]:
        """将 Neo4j 中的值解析为字符串列表（兼容 JSON 字符串、原生列表、双重编码）。"""
        if not value:
            return []
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
                # 双重编码：解析后仍是字符串，再解一层
                if isinstance(parsed, str):
                    try:
                        parsed2 = json.loads(parsed)
                        if isinstance(parsed2, list):
                            return [str(v) for v in parsed2]
                    except (json.JSONDecodeError, TypeError):
                        pass
                logger.warning(
                    "_parse_json_list: JSON 解析结果不是列表，原值=%s，解析结果=%s", value[:200], type(parsed).__name__
                )
                return []
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("_parse_json_list: JSON 解析失败，原值=%s，错误=%s", value[:200], exc)
                return []
        logger.warning("_parse_json_list: 未知类型 %s，原值=%s", type(value).__name__, str(value)[:200])
        return []

    try:
        from src.services.neo4j_graph import _get_driver

        driver = await _get_driver()
        async with driver.session() as session:
            result = await session.run("""
                MATCH (r:RuntimeRule)
                RETURN r.normalized_question AS normalized_question,
                       r.question AS question,
                       r.preferred_main_table AS preferred_main_table,
                       r.required_tables AS required_tables,
                       r.required_joins AS required_joins,
                       r.source AS source,
                       COALESCE(r.enabled, true) AS enabled
                ORDER BY r.normalized_question
            """)
            return [
                {
                    "normalized_question": rec["normalized_question"] or "",
                    "question": rec["question"] or "",
                    "preferred_main_table": rec["preferred_main_table"] or "",
                    "required_tables": _parse_json_list(rec["required_tables"]),
                    "required_joins": _parse_json_list(rec["required_joins"]),
                    "source": rec["source"] or "",
                    "enabled": rec["enabled"] if rec["enabled"] is not None else True,
                }
                async for rec in result
            ]
    except Exception as exc:
        logger.error("从 Neo4j 加载 RuntimeRule 列表失败: %s", exc)
        return []


async def create_runtime_rule(
    question: str,
    normalized_question: str,
    preferred_main_table: str = "",
    required_tables: list[str] | None = None,
    required_joins: list[str] | None = None,
    source: str = "manual",
) -> dict:
    """创建或覆盖 RuntimeRule 规则（若同 normalized_question 已存在则覆盖）。"""
    import json

    from src.services.neo4j_graph import _get_driver
    from src.services.vector_store import _get_embeddings

    if required_tables is None:
        required_tables = []
    if required_joins is None:
        required_joins = []

    # 生成 embedding
    embeddings = _get_embeddings()
    embedding = embeddings.embed_query(normalized_question[:500])

    # 写入 Neo4j（MERGE by normalized_question，存在则覆盖）
    driver = await _get_driver()
    async with driver.session() as session:
        await session.run(
            """
            MERGE (r:RuntimeRule {normalized_question: $normalized_question})
            SET r.question = $question,
                r.preferred_main_table = $preferred_main_table,
                r.required_tables = $required_tables,
                r.required_joins = $required_joins,
                r.source = $source,
                r.question_embedding = $embedding,
                r.enabled = true
            """,
            {
                "normalized_question": normalized_question,
                "question": question,
                "preferred_main_table": preferred_main_table,
                "required_tables": json.dumps(required_tables, ensure_ascii=False),
                "required_joins": json.dumps(required_joins, ensure_ascii=False),
                "source": source,
                "embedding": embedding,
            },
        )

    logger.info("已创建/覆盖 RuntimeRule: %s", normalized_question)
    return {
        "normalized_question": normalized_question,
        "question": question,
        "preferred_main_table": preferred_main_table,
        "required_tables": required_tables,
        "required_joins": required_joins,
        "source": source,
    }


async def update_runtime_rule(
    normalized_question: str,
    question: str,
    preferred_main_table: str = "",
    required_tables: list[str] | None = None,
    required_joins: list[str] | None = None,
    source: str = "",
) -> bool:
    """更新 RuntimeRule 规则。"""
    import json

    from src.services.neo4j_graph import _get_driver
    from src.services.vector_store import _get_embeddings

    if required_tables is None:
        required_tables = []
    if required_joins is None:
        required_joins = []

    # 重新生成 embedding
    embeddings = _get_embeddings()
    embedding = embeddings.embed_query(normalized_question[:500])

    # 更新 Neo4j
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (r:RuntimeRule {normalized_question: $normalized_question})
            SET r.question = $question,
                r.preferred_main_table = $preferred_main_table,
                r.required_tables = $required_tables,
                r.required_joins = $required_joins,
                r.source = $source,
                r.question_embedding = $embedding
            RETURN count(r) AS updated
            """,
            {
                "normalized_question": normalized_question,
                "question": question,
                "preferred_main_table": preferred_main_table,
                "required_tables": json.dumps(required_tables, ensure_ascii=False),
                "required_joins": json.dumps(required_joins, ensure_ascii=False),
                "source": source,
                "embedding": embedding,
            },
        )
        rec = await result.single()
        updated = rec["updated"] if rec else 0

    if updated:
        logger.info("已更新 RuntimeRule: %s", normalized_question)
    return bool(updated)


async def delete_runtime_rule(normalized_question: str) -> bool:
    """删除 RuntimeRule 规则。"""
    from src.services.neo4j_graph import _get_driver

    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (r:RuntimeRule {normalized_question: $normalized_question}) DETACH DELETE r RETURN count(r) AS deleted",
            {"normalized_question": normalized_question},
        )
        rec = await result.single()
        deleted = rec["deleted"] if rec else 0

    if deleted:
        logger.info("已删除 RuntimeRule: %s", normalized_question)
    return bool(deleted)


async def toggle_runtime_rule(normalized_question: str, enabled: bool) -> bool:
    """切换 RuntimeRule 启用/禁用状态。"""
    from src.services.neo4j_graph import _get_driver

    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (r:RuntimeRule {normalized_question: $normalized_question}) SET r.enabled = $enabled RETURN count(r) AS updated",
            {"normalized_question": normalized_question, "enabled": enabled},
        )
        rec = await result.single()
        updated = rec["updated"] if rec else 0

    if updated:
        logger.info("已%s RuntimeRule: %s", "启用" if enabled else "禁用", normalized_question)
    return bool(updated)


# ── 线上 → 本地全量同步 ────────────────────────────────────────────

_FEW_SHOT_FILE = _DATA_DIR / "dify_few_shot.txt"
_RELATION_FILE = _DATA_DIR / "mes_relation_graph.json"


async def sync_from_neo4j() -> dict:
    """将 Neo4j 中的表结构、SQL 示例、关系图数据全量同步回本地文件。

    直接覆盖写入：
      - data/mes_knowledge_base.txt（所有 Table 节点的 full_text）
      - data/dify_few_shot.txt（所有 FewShot 节点的 full_text）
      - data/mes_relation_graph.json（所有 :JOIN_REL 边）

    返回写入记录数统计。
    """
    from src.services.neo4j_graph import _get_driver

    driver = await _get_driver()
    table_count = 0
    few_shot_count = 0
    relation_count = 0

    async with driver.session() as session:
        # 1. 同步表结构
        result = await session.run(
            "MATCH (t:Table) WHERE t.full_text IS NOT NULL RETURN t.full_text AS full_text ORDER BY t.name"
        )
        chunks = [rec["full_text"] async for rec in result if rec["full_text"]]
        if chunks:
            _KB_FILE.write_text("\n---\n".join(chunks) + "\n", encoding="utf-8")
        table_count = len(chunks)
        logger.info("已同步 %d 张表结构到 %s", table_count, _KB_FILE)

        # 2. 同步 SQL 示例
        result = await session.run(
            "MATCH (f:FewShot) WHERE f.full_text IS NOT NULL RETURN f.full_text AS full_text ORDER BY f.id"
        )
        chunks = [rec["full_text"] async for rec in result if rec["full_text"]]
        if chunks:
            _FEW_SHOT_FILE.write_text("\n---\n".join(chunks) + "\n", encoding="utf-8")
        few_shot_count = len(chunks)
        logger.info("已同步 %d 条 SQL 示例到 %s", few_shot_count, _FEW_SHOT_FILE)

        # 3. 同步关系图数据
        result = await session.run("""
            MATCH (a:Table)-[r:JOIN_REL]->(b:Table)
            RETURN a.name AS from_table, b.name AS to_table,
                   r.from_field AS from_field, r.to_field AS to_field,
                   r.join_condition AS join_condition, r.join_type AS join_type,
                   r.description AS description, r.confidence AS confidence, r.note AS note
            ORDER BY a.name, b.name
        """)
        graph: dict[str, list[dict]] = {}
        async for rec in result:
            ft = rec["from_table"]
            if ft not in graph:
                graph[ft] = []
            graph[ft].append(
                {
                    "to": rec["to_table"],
                    "from_field": rec.get("from_field") or "",
                    "to_field": rec.get("to_field") or "",
                    "join": rec.get("join_condition") or "",
                    "join_type": rec.get("join_type") or "",
                    "desc": rec.get("description") or "",
                    "confidence": rec.get("confidence") or "",
                    "note": rec.get("note") or "",
                }
            )
        with open(_RELATION_FILE, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)
        relation_count = sum(len(v) for v in graph.values())
        logger.info("已同步 %d 条关系边到 %s", relation_count, _RELATION_FILE)

    # 4. 重建关键词索引
    await _rebuild_keyword_index()

    return {
        "table_count": table_count,
        "few_shot_count": few_shot_count,
        "relation_count": relation_count,
        "message": f"同步完成：{table_count} 张表, {few_shot_count} 条SQL示例, {relation_count} 条关系边",
        "synced_files": [
            "data/mes_knowledge_base.txt",
            "data/dify_few_shot.txt",
            "data/mes_relation_graph.json",
        ],
    }


# ── LLM 抽取表结构 ──────────────────────────────────────────────────

_EXTRACT_PROMPT = """\
你是一个数据库表结构分析专家。请从以下文本中抽取所有数据库表的定义信息。

要求：
1. 识别文本中所有表，包括表名、所属模块、业务含义
2. 抽取每个表的所有字段，包括字段名、类型、注释说明
3. 如果文本中包含表之间的关联关系（如外键、JOIN 关系），也要提取
4. 如果能推断出适用场景，也请提取

输出格式为 JSON，严格遵循以下结构：
```json
{{
  "tables": [
    {{
      "table_name": "表名",
      "module": "所属模块（如：基础数据、生产执行、质量管理、仓储管理、设备管理、条码管理）",
      "business_meaning": "业务含义描述",
      "fields": [
        {{"name": "字段名", "type": "字段类型", "comment": "字段注释"}}
      ],
      "scenarios": ["适用场景1", "适用场景2"]
    }}
  ],
  "relations": [
    {{
      "from_table": "源表名",
      "to_table": "目标表名",
      "from_field": "源字段",
      "to_field": "目标字段",
      "join_condition": "JOIN条件，如 a.id = b.aid",
      "join_type": "LEFT",
      "description": "关系描述",
      "confidence": "high",
      "note": ""
    }}
  ]
}}
```

注意事项：
- table_name 必须是数据库中的实际表名（如 t_bd_part）
- module 根据表名前缀推断：t_bd_=基础数据, t_pd_=生产执行, t_qm_=质量管理, t_wms_=仓储管理, t_ems_=设备管理, t_bc_=条码管理
- join_type 只能是 LEFT、INNER、RIGHT 之一
- confidence 只能是 high、medium、low 之一
- 如果无法确定某个字段，留空字符串
- 只输出 JSON，不要输出其他内容

待分析文本：
{raw_text}
"""


def extract_tables_from_text(raw_text: str) -> dict:
    """使用 LLM 从原始文本中抽取表结构定义。

    Args:
        raw_text: 原始文本（DDL/CREATE TABLE/自然语言描述等）

    Returns:
        {"tables": [...], "relations": [...]}
    """
    from src.services.llm import get_intent_llm

    llm = get_intent_llm(temperature=0.0, streaming=False)
    prompt = _EXTRACT_PROMPT.replace("{raw_text}", raw_text)

    response = llm.invoke(prompt)
    content = response.content.strip()

    # 提取 JSON 内容（兼容 markdown 代码块包裹）
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if json_match:
        content = json_match.group(1).strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("LLM 返回的 JSON 解析失败: %s\n原始内容: %s", exc, content[:500])
        return {"tables": [], "relations": []}

    # 校验并规范化
    tables = result.get("tables", [])
    relations = result.get("relations", [])

    validated_tables = []
    for t in tables:
        if not t.get("table_name"):
            continue
        validated_tables.append(
            {
                "table_name": t.get("table_name", ""),
                "module": t.get("module", ""),
                "business_meaning": t.get("business_meaning", ""),
                "fields": [
                    {"name": f.get("name", ""), "type": f.get("type", ""), "comment": f.get("comment", "")}
                    for f in t.get("fields", [])
                ],
                "relations": [],
                "scenarios": t.get("scenarios", []),
            }
        )

    validated_relations = []
    for r in relations:
        if not r.get("from_table") or not r.get("to_table"):
            continue
        validated_relations.append(
            {
                "from_table": r.get("from_table", ""),
                "to_table": r.get("to_table", ""),
                "from_field": r.get("from_field", ""),
                "to_field": r.get("to_field", ""),
                "join_condition": r.get("join_condition", ""),
                "join_type": r.get("join_type", "LEFT"),
                "description": r.get("description", ""),
                "confidence": r.get("confidence", "high"),
                "note": r.get("note", ""),
            }
        )

    logger.info("LLM 抽取完成: %d 张表, %d 条关系", len(validated_tables), len(validated_relations))
    return {"tables": validated_tables, "relations": validated_relations}


# ── 通用知识库服务 ──────────────────────────────────────────────────

from src.core.config import settings
from src.models.schemas import GenericKnowledgeFieldDef, GenericKBSummary, GenericKnowledgeItem
from src.services import neo4j_graph

_EMBED_MAX_CHARS = settings.embedding_max_chars


def _build_generic_embed_text(fields: list[GenericKnowledgeFieldDef]) -> tuple[str, list[str]]:
    """构建通用知识库的 embedding 文本。

    策略：先拼接所有选中字段名作为语义锚点，再拼接字段值，超出 EMBED_MAX_CHARS 时截断。

    Returns:
        (embed_text, embed_field_names)
    """
    embed_fields = [f for f in fields if f.embed]
    if not embed_fields:
        return "", []
    # 语义锚点：字段名
    anchor = " ".join(f.name for f in embed_fields)
    # 字段值
    values = " ".join(f.value for f in embed_fields if f.value)
    text = f"{anchor} {values}".strip()
    if len(text) > _EMBED_MAX_CHARS:
        text = text[:_EMBED_MAX_CHARS]
    return text, [f.name for f in embed_fields]


def _build_generic_full_text(label: str, fields: list[GenericKnowledgeFieldDef]) -> str:
    """构建通用知识库条目的完整展示文本。"""
    parts = [f"{f.name}:{f.value}" for f in fields if f.name]
    prefix = f"[{label}] " if label else ""
    return prefix + " ".join(parts)


async def list_generic_kbs() -> list[GenericKBSummary]:
    """列出所有通用知识库。"""
    raw_kbs = await neo4j_graph.list_generic_knowledge_kbs()
    result = []
    for kb in raw_kbs:
        field_names = await neo4j_graph.get_generic_kb_field_names(kb["kb_name"])
        result.append(
            GenericKBSummary(
                kb_name=kb["kb_name"],
                label=kb["label"],
                item_count=kb["item_count"],
                field_names=field_names,
            )
        )
    return result


async def list_generic_items(kb_name: str) -> list[GenericKnowledgeItem]:
    """列出某个知识库下所有条目。"""
    raw_items = await neo4j_graph.list_generic_knowledge_by_kb(kb_name)
    result = []
    for item in raw_items:
        fields = [
            GenericKnowledgeFieldDef(
                name=f.get("name", ""),
                value=f.get("value", ""),
                embed=f.get("name") in (item.get("embed_fields") or []),
            )
            for f in item["fields"]
            if isinstance(f, dict)
        ]
        result.append(
            GenericKnowledgeItem(
                item_id=item["item_id"],
                label=item["label"],
                fields=fields,
                created_at=item.get("created_at", ""),
            )
        )
    return result


async def create_generic_item(kb_name: str, item: GenericKnowledgeItem) -> GenericKnowledgeItem:
    """创建通用知识库条目。"""
    # 生成 item_id
    if not item.item_id:
        import uuid

        item.item_id = f"{kb_name}_{uuid.uuid4().hex[:8]}"

    # 构建 embedding 文本
    embed_text, embed_field_names = _build_generic_embed_text(item.fields)
    embedding: list[float] = []
    if embed_text:
        embeddings = _get_embeddings()
        embedding = embeddings.embed_query(embed_text)

    # 构建 full_text
    full_text = _build_generic_full_text(item.label, item.fields)

    # 序列化
    fields_json = json.dumps(
        [{"name": f.name, "value": f.value, "embed": f.embed} for f in item.fields],
        ensure_ascii=False,
    )
    embed_fields_json = json.dumps(embed_field_names, ensure_ascii=False)

    await neo4j_graph.create_generic_knowledge(
        kb_name=kb_name,
        item_id=item.item_id,
        label=item.label,
        fields_json=fields_json,
        embed_fields_json=embed_fields_json,
        embed_text=embed_text,
        embedding=embedding,
        full_text=full_text,
    )
    return item


async def update_generic_item(kb_name: str, item_id: str, label: str, fields: list[GenericKnowledgeFieldDef]) -> bool:
    """更新通用知识库条目。"""
    embed_text, embed_field_names = _build_generic_embed_text(fields)
    embedding: list[float] = []
    if embed_text:
        embeddings = _get_embeddings()
        embedding = embeddings.embed_query(embed_text)

    full_text = _build_generic_full_text(label, fields)

    fields_json = json.dumps(
        [{"name": f.name, "value": f.value, "embed": f.embed} for f in fields],
        ensure_ascii=False,
    )
    embed_fields_json = json.dumps(embed_field_names, ensure_ascii=False)

    return await neo4j_graph.update_generic_knowledge(
        kb_name=kb_name,
        item_id=item_id,
        label=label,
        fields_json=fields_json,
        embed_fields_json=embed_fields_json,
        embed_text=embed_text,
        embedding=embedding,
        full_text=full_text,
    )


async def delete_generic_item(kb_name: str, item_id: str) -> bool:
    """删除通用知识库条目。"""
    return await neo4j_graph.delete_generic_knowledge(kb_name, item_id)


async def delete_generic_kb(kb_name: str) -> int:
    """删除整个通用知识库（含其下所有条目）。返回删除的条目数。"""
    return await neo4j_graph.delete_generic_kb(kb_name)
