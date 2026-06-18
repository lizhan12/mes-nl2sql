"""单独重建 Neo4j Field 节点脚本。

从 data/mes_knowledge_base.txt 提取所有字段信息（name/type/comment），
重新生成 embedding 并全量替换 Neo4j 中的 Field 节点。

用法:
    uv run python scripts/rebuild_field_nodes.py          # 全量重建
    uv run python scripts/rebuild_field_nodes.py --dry-run # 预览不写入
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("rebuild_field_nodes")


async def rebuild_fields(dry_run: bool = False) -> None:
    from src.services.neo4j_graph import (
        _get_driver,
        batch_set_field_embeddings,
        ensure_field_indexes,
    )
    from src.services.vector_store import _get_embeddings, _load_chunks_with_metadata, _parse_schema_chunk

    # 1. 加载知识库 chunks
    chunks = _load_chunks_with_metadata("mes_knowledge_base.txt", _parse_schema_chunk)
    logger.info("从 mes_knowledge_base.txt 加载 %d 个表 chunk", len(chunks))

    # 2. 从 JOIN_REL 推断 PK/FK 字段
    pk_fk_fields: dict[str, set[str]] = {}
    try:
        driver = await _get_driver()
        async with driver.session() as session:
            result = await session.run("""
                MATCH (a:Table)-[r:JOIN_REL]->(b:Table)
                RETURN a.name AS from_table, r.from_field AS from_field,
                       b.name AS to_table, r.to_field AS to_field
            """)
            async for rec in result:
                ft = rec["from_table"]
                tt = rec["to_table"]
                ff = rec["from_field"] or ""
                tf = rec["to_field"] or ""
                if ff:
                    pk_fk_fields.setdefault(ft, set()).add(ff)
                if tf:
                    pk_fk_fields.setdefault(tt, set()).add(tf)
        logger.info("从 JOIN_REL 推断 PK/FK 字段: %d 个表", len(pk_fk_fields))
    except Exception as e:
        logger.warning("从 JOIN_REL 推断 PK/FK 失败: %s", e)

    # 3. 从 full_text 解析字段（保留 type 信息）
    # 原始格式: "  col_name (type) -- comment"，type 可能含嵌套括号如 varchar(40)
    field_items: list[dict] = []
    for c in chunks:
        meta = c["metadata"]
        table_name = meta.get("table_name", "")
        pk_fk_set = pk_fk_fields.get(table_name, set())
        in_columns = False
        for line in c["full_text"].split("\n"):
            stripped = line.strip()
            if stripped == "关键字段：":
                in_columns = True
                continue
            if stripped in ("关联关系：", "适用场景：") or stripped.startswith("表名："):
                in_columns = False
                continue
            if not in_columns or not stripped:
                continue
            # 用 " -- " 分割，右边是 comment；左边提取 field_name 和 type
            if " -- " not in stripped:
                continue
            left, comment = stripped.rsplit(" -- ", 1)
            comment = comment.strip()
            # left 格式: "col_name (type)"，提取 field_name 和 type
            paren_idx = left.find("(")
            if paren_idx < 0 or not left.endswith(")"):
                continue
            field_name = left[:paren_idx].strip()
            ftype = left[paren_idx + 1 : -1].strip()
            if not field_name or not ftype:
                continue
            embed_text = f"{table_name}.{field_name} {ftype} {comment}".strip()
            if len(embed_text) > 400:
                embed_text = embed_text[:400]
            field_items.append(
                {
                    "table_name": table_name,
                    "name": field_name,
                    "type": ftype,
                    "comment": comment,
                    "embed_text": embed_text,
                    "is_pk": field_name in pk_fk_set,
                }
            )

    logger.info("解析出 %d 个字段", len(field_items))

    if not field_items:
        logger.warning("未解析到任何字段，终止")
        return

    if dry_run:
        logger.info("--dry-run 模式，预览前 20 个字段:")
        for f in field_items[:20]:
            logger.info("  %s.%s (%s) -- %s [pk=%s]", f["table_name"], f["name"], f["type"], f["comment"], f["is_pk"])
        logger.info("  ... 共 %d 个字段", len(field_items))
        return

    # 4. 清空旧 Field 节点
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (f:Field) DETACH DELETE f RETURN count(f) AS deleted")
        rec = await result.single()
        deleted = rec["deleted"] if rec else 0
    logger.info("已清空 %d 个旧 Field 节点", deleted)

    # 5. 确保向量索引
    await ensure_field_indexes()

    # 6. 生成 embedding
    embeddings = _get_embeddings()
    field_texts = [f["embed_text"] for f in field_items]
    logger.info("正在生成 %d 个 Field embedding...", len(field_texts))
    field_vectors = embeddings.embed_documents(field_texts)

    # 7. 批量写入
    batch = [
        {
            "table_name": f["table_name"],
            "name": f["name"],
            "type": f["type"],
            "comment": f["comment"],
            "embedding": vec,
            "is_pk": f["is_pk"],
        }
        for f, vec in zip(field_items, field_vectors, strict=True)
    ]
    count = await batch_set_field_embeddings(batch)
    logger.info("Field 节点重建完成，写入 %d 个字段", count)


def main() -> None:
    parser = argparse.ArgumentParser(description="重建 Neo4j Field 节点")
    parser.add_argument("--dry-run", action="store_true", help="预览不写入")
    args = parser.parse_args()

    asyncio.run(rebuild_fields(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
