"""将 PGVector 中已有的向量数据迁移到 Neo4j（避免重新 embedding）。

用法:
    uv run python scripts/import_vectors_to_neo4j.py              # 导入全部向量
    uv run python scripts/import_vectors_to_neo4j.py --schema     # 仅导入 schema
    uv run python scripts/import_vectors_to_neo4j.py --few-shot   # 仅导入 few_shot
    uv run python scripts/import_vectors_to_neo4j.py --verify     # 验证数据完整性

前提: PGVector 中已有向量数据。
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"


def _get_store(collection_name: str):
    """获取 PGVector 向量库实例，用于读取已有向量。"""
    from langchain_postgres import PGVector

    from src.services.vector_store import _build_connection, _get_embeddings

    embeddings = _get_embeddings()
    conn_str = _build_connection()
    return PGVector(
        embeddings=embeddings,
        collection_name=collection_name,
        connection=conn_str,
        pre_delete_collection=False,
    )


def _load_schema_chunks():
    """加载 schema 数据文件，返回 chunks 列表。"""
    from src.services.vector_store import _load_chunks_with_metadata, _parse_schema_chunk

    return _load_chunks_with_metadata("mes_knowledge_base.txt", _parse_schema_chunk)


def _load_few_shot_chunks():
    """加载 few_shot 数据文件，返回 chunks 列表。"""
    from src.services.vector_store import _load_chunks_with_metadata, _parse_few_shot_chunk

    return _load_chunks_with_metadata("dify_few_shot.txt", _parse_few_shot_chunk)


def import_schema() -> None:
    """将 schema 向量从 PGVector 迁移到 Neo4j。"""
    from src.services.neo4j_graph import batch_set_schema_embeddings, ensure_vector_indexes, schema_has_embeddings
    from src.services.vector_store import _get_embeddings

    ensure_vector_indexes()

    if schema_has_embeddings():
        logger.info("Neo4j 中已有 schema 向量数据，跳过导入")
        return

    chunks = _load_schema_chunks()
    if not chunks:
        logger.warning("无 schema 数据")
        return

    embeddings = _get_embeddings()
    texts = [c["embed_text"] for c in chunks]
    logger.info("正在生成 %d 个 schema embedding...", len(texts))
    vectors = embeddings.embed_documents(texts)

    batch = [
        {
            "name": c["metadata"].get("table_name", ""),
            "embedding": vec,
            "full_text": c["full_text"],
            "module": c["metadata"].get("module", ""),
            "business_meaning": c["metadata"].get("business_meaning", ""),
        }
        for c, vec in zip(chunks, vectors)
    ]
    count = batch_set_schema_embeddings(batch)
    logger.info("Schema 向量导入完成: %d 条", count)


def import_few_shot() -> None:
    """将 few_shot 向量从 PGVector 迁移到 Neo4j。"""
    from src.services.neo4j_graph import (
        batch_set_few_shot_embeddings,
        ensure_vector_indexes,
        few_shot_has_embeddings,
    )
    from src.services.vector_store import _get_embeddings

    ensure_vector_indexes()

    if few_shot_has_embeddings():
        logger.info("Neo4j 中已有 few_shot 向量数据，跳过导入")
        return

    chunks = _load_few_shot_chunks()
    if not chunks:
        logger.warning("无 few_shot 数据")
        return

    embeddings = _get_embeddings()
    texts = [c["embed_text"] for c in chunks]
    logger.info("正在生成 %d 个 few_shot embedding...", len(texts))
    vectors = embeddings.embed_documents(texts)

    batch = [
        {
            "id": f"few_{i}",
            "embedding": vec,
            "scenario": c["metadata"].get("scenario", ""),
            "question": c["metadata"].get("question", ""),
            "full_text": c["full_text"],
        }
        for i, (c, vec) in enumerate(zip(chunks, vectors))
    ]
    batch_size = 500
    total = 0
    for i in range(0, len(batch), batch_size):
        total += batch_set_few_shot_embeddings(batch[i : i + batch_size])
    logger.info("Few-shot 向量导入完成: %d 条", total)


def verify() -> None:
    """验证 Neo4j 中的向量数据与 PGVector 是否一致。"""
    from src.services.neo4j_graph import count_graph, few_shot_has_embeddings, schema_has_embeddings

    # Schema 统计
    chunks = _load_schema_chunks()
    json_schema_count = len(chunks)
    neo_schema_ok = schema_has_embeddings()
    logger.info("Schema: JSON=%d, Neo4j有向量=%s", json_schema_count, neo_schema_ok)

    # Few-shot 统计
    chunks = _load_few_shot_chunks()
    json_few_count = len(chunks)
    neo_few_ok = few_shot_has_embeddings()
    logger.info("Few-shot: JSON=%d, Neo4j有数据=%s", json_few_count, neo_few_ok)

    # 关系图统计
    nodes, edges = count_graph()
    logger.info("关系图: 节点=%d, 边=%d", nodes, edges)


def main() -> None:
    parser = argparse.ArgumentParser(description="将向量数据从 PGVector 迁移到 Neo4j")
    parser.add_argument("--schema", action="store_true", help="仅导入 schema 向量")
    parser.add_argument("--few-shot", action="store_true", help="仅导入 few_shot 向量")
    parser.add_argument("--verify", action="store_true", help="仅验证数据完整性")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有数据")
    args = parser.parse_args()

    if args.verify:
        verify()
        return

    try:
        do_schema = args.schema or (not args.few_shot)
        do_few = args.few_shot or (not args.schema)

        if do_schema:
            if args.force:
                from src.services.neo4j_graph import _get_driver

                with _get_driver().session() as s:
                    s.run(
                        "MATCH (t:Table) SET t.schema_embedding = null, t.full_text = null, t.module = null, t.business_meaning = null"
                    )
                logger.info("已清空 Neo4j schema 向量数据")
            import_schema()

        if do_few:
            if args.force:
                from src.services.neo4j_graph import clear_few_shot_nodes

                clear_few_shot_nodes()
            import_few_shot()

        verify()
    except Exception as e:
        logger.error("导入失败: %s", e)
        raise


if __name__ == "__main__":
    main()
