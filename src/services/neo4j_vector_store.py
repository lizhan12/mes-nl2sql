"""Neo4j 向量存储，实现与 PGVector 兼容的检索接口。

使用 Neo4j 原生向量索引（5.11+）进行相似度搜索。
"""

from __future__ import annotations

import logging

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from neo4j import GraphDatabase

from src.core.config import settings

logger = logging.getLogger(__name__)

_VECTOR_DIMENSIONS = 1024


class Neo4jVectorStore:
    """Neo4j 向量存储，使用原生向量索引进行相似度搜索。

    支持两种集合：
      - "schema": 从 Table 节点的 schema_embedding 属性检索
      - "few_shot": 从 FewShot 节点的 question_embedding 属性检索
    """

    def __init__(self, collection_name: str, embedding: Embeddings) -> None:
        self._collection = collection_name
        self._embedding = embedding
        self._driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))

    # ── 检索 ────────────────────────────────────────────────────────

    def similarity_search(self, query: str, k: int = 4) -> list[Document]:
        """语义搜索，返回 Document 列表。"""
        return [doc for doc, _score in self.similarity_search_with_score(query, k=k)]

    def similarity_search_with_score(self, query: str, k: int = 4) -> list[tuple[Document, float]]:
        """带分数的语义搜索。"""
        query_vec = self._embedding.embed_query(query)
        if self._collection == "schema":
            return self._schema_search(query_vec, k)
        return self._few_shot_search(query_vec, k)

    def _schema_search(self, query_vec: list[float], k: int) -> list[tuple[Document, float]]:
        """在 Table 节点上做向量相似度搜索。"""
        try:
            with self._driver.session() as session:
                result = session.run(
                    """
                    MATCH (t:Table)
                    WHERE t.schema_embedding IS NOT NULL
                    WITH t, vector.similarity.cosine(t.schema_embedding, $query_vec) AS score
                    WHERE score >= $threshold
                    RETURN t.name AS name, t.full_text AS full_text,
                           t.module AS module, t.business_meaning AS business_meaning,
                           score
                    ORDER BY score DESC
                    LIMIT $k
                    """,
                    {"query_vec": query_vec, "k": k, "threshold": 0.55},
                )
                return [
                    (
                        Document(
                            page_content=rec["full_text"] or "",
                            metadata={
                                "table_name": rec["name"],
                                "module": rec["module"] or "",
                                "business_meaning": rec["business_meaning"] or "",
                                "full_text": rec["full_text"] or "",
                            },
                        ),
                        rec["score"],
                    )
                    for rec in result
                ]
        except Exception as e:
            logger.warning("Neo4j schema 向量搜索失败: %s", e)
            return []

    def _few_shot_search(self, query_vec: list[float], k: int) -> list[tuple[Document, float]]:
        """在 FewShot 节点上做向量相似度搜索。"""
        try:
            with self._driver.session() as session:
                result = session.run(
                    """
                    MATCH (f:FewShot)
                    WHERE f.question_embedding IS NOT NULL
                    WITH f, vector.similarity.cosine(f.question_embedding, $query_vec) AS score
                    RETURN f.full_text AS full_text, f.scenario AS scenario,
                           f.question AS question, score
                    ORDER BY score DESC
                    LIMIT $k
                    """,
                    {"query_vec": query_vec, "k": k},
                )
                return [
                    (
                        Document(
                            page_content=rec["full_text"] or "",
                            metadata={
                                "scenario": rec["scenario"] or "",
                                "question": rec["question"] or "",
                                "full_text": rec["full_text"] or "",
                            },
                        ),
                        rec["score"],
                    )
                    for rec in result
                ]
        except Exception as e:
            logger.warning("Neo4j few_shot 向量搜索失败: %s", e)
            return []

    # ── 写入 ────────────────────────────────────────────────────────

    def add_texts(
        self, texts: list[str], metadatas: list[dict] | None = None, ids: list[str] | None = None
    ) -> list[str]:
        """批量添加向量文档（不在此处做 embedding，由外部调用后批量写入）。"""
        return ids or []

    def delete_collection(self) -> None:
        """清空向量数据。"""
        if self._collection == "few_shot":
            from src.services.neo4j_graph import clear_few_shot_nodes

            clear_few_shot_nodes()
        else:
            with self._driver.session() as session:
                session.run(
                    "MATCH (t:Table) SET t.schema_embedding = null, t.full_text = null, t.module = null, t.business_meaning = null"
                )
            logger.info("已清空 Table 节点的 schema_embedding")

    def create_collection(self) -> None:
        """创建集合（向量索引在 ensure_vector_indexes 中统一创建）。"""
        from src.services.neo4j_graph import ensure_vector_indexes

        ensure_vector_indexes()

    # ── 工具 ────────────────────────────────────────────────────────

    @property
    def collection_name(self) -> str:
        return self._collection
