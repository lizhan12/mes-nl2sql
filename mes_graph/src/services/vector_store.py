"""向量存储服务，使用 PostgreSQL + pgvector。

每个文档存入 pgvector 时同时携带元数据：
  - 表结构库 (mes_knowledge_base.txt)：table_name, module, business_meaning, full_text
  - SQL 示例库 (dify_few_shot.txt)：scenario, question, full_text

启动时检查集合中是否已有数据，避免重复 embedding。
"""

import logging
from pathlib import Path

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_postgres.vectorstores import PGVector as PGVectorStore

from src.core.config import settings

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
EMBED_MAX_CHARS = 500  # bge-large-zh-v1.5 限制 512 tokens，预留给少数长文本


# ---- 数据加载与元数据解析 ----


def _parse_schema_chunk(chunk: str) -> dict:
    """解析 mes_knowledge_base.txt 中的一个 chunk，提取元数据。

    Chunk 格式：
        表名：t_xxx
        模块：xxx
        业务含义：xxx
        关键字段：
          col1 (type) -- comment
          ...

    Returns:
        {"table_name": str, "module": str, "business_meaning": str, "full_text": str}
    """
    table_name = ""
    module = ""
    business_meaning = ""

    for line in chunk.split("\n"):
        line = line.strip()
        if line.startswith("表名："):
            table_name = line[len("表名：") :].strip()
        elif line.startswith("模块："):
            module = line[len("模块：") :].strip()
        elif line.startswith("业务含义："):
            business_meaning = line[len("业务含义：") :].strip()

    return {
        "table_name": table_name,
        "module": module,
        "business_meaning": business_meaning,
        "full_text": chunk,
    }


def _parse_few_shot_chunk(chunk: str) -> dict:
    """解析 dify_few_shot.txt 中的一个 chunk，提取元数据。

    Chunk 格式：
        场景：xxx
        用户问题：xxx
        SQL：
        SELECT ...

    Returns:
        {"scenario": str, "question": str, "full_text": str}
    """
    scenario = ""
    question = ""

    for line in chunk.split("\n"):
        line = line.strip()
        if line.startswith("场景："):
            scenario = line[len("场景：") :].strip()
        elif line.startswith("用户问题："):
            question = line[len("用户问题：") :].strip()

    return {
        "scenario": scenario,
        "question": question,
        "full_text": chunk,
    }


def _load_chunks_with_metadata(
    file_name: str,
    parser: callable,
    separator: str = "\n---\n",
) -> list[dict]:
    """加载数据文件，解析每个 chunk 的元数据。

    Args:
        file_name: 数据文件名（相对于 data/ 目录）
        parser: 解析函数，签名为 (chunk: str) -> dict
        separator: chunk 分隔符

    Returns:
        [{"full_text": ..., "embed_text": ..., "metadata": {...}}, ...]
    """
    path = _DATA_DIR / file_name
    if not path.exists():
        logger.warning("数据文件不存在: %s", path)
        return []

    content = path.read_text(encoding="utf-8")
    raw_chunks = [c.strip() for c in content.split(separator) if c.strip()]

    results: list[dict] = []
    for chunk in raw_chunks:
        meta = parser(chunk)
        results.append(
            {
                "full_text": chunk,
                "embed_text": chunk[:EMBED_MAX_CHARS],  # 截断用于 embedding
                "metadata": meta,
            }
        )

    logger.info("从 %s 加载了 %d 个 chunk", file_name, len(results))
    return results


# ---- Embedding 与连接 ----


def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.embedding_key,  # type: ignore[arg-type]
        base_url=settings.embedding_base_url,
    )


def _build_connection() -> str:
    """构建 PGVector 连接串。"""
    return settings.app_database_url.replace("postgresql://", "postgresql+psycopg://")


# ---- 向量库构建 ----


def _collection_has_data(store: PGVectorStore) -> bool:
    """检查 PGVector 集合中是否已有数据。"""
    try:
        # 通过查询一条记录来判断集合是否为空
        docs = store.similarity_search("test", k=1)
        return len(docs) > 0
    except Exception:
        return False


def build_schema_store(force_rebuild: bool = False) -> PGVectorStore:
    """构建表结构向量库。

    从 mes_knowledge_base.txt 加载 MES 表结构定义，
    每个 chunk 附带元数据：table_name, module, business_meaning, full_text。

    Args:
        force_rebuild: 是否强制重建（忽略已有数据）
    """
    chunks = _load_chunks_with_metadata("mes_knowledge_base.txt", _parse_schema_chunk)
    embeddings = _get_embeddings()
    conn_str = _build_connection()

    store = PGVector(
        embeddings=embeddings,
        collection_name="mes_schema_embeddings",
        connection=conn_str,
        pre_delete_collection=False,  # 不自动删除，手动检查
    )

    if force_rebuild or not _collection_has_data(store):
        if force_rebuild:
            logger.info("强制重建 schema 向量库...")
            store.delete_collection()
            store.create_collection()
        else:
            logger.info("schema 向量库为空，开始初始化...")

        if chunks:
            ids = [f"schema_{i}" for i in range(len(chunks))]
            texts = [c["embed_text"] for c in chunks]
            metadatas = [c["metadata"] for c in chunks]
            store.add_texts(texts=texts, ids=ids, metadatas=metadatas)
            logger.info("schema 向量库初始化完成，共 %d 条记录", len(chunks))
    else:
        logger.info("schema 向量库已有数据，跳过初始化")

    return store


def build_few_shot_store(force_rebuild: bool = False) -> PGVectorStore:
    """构建 SQL 示例向量库。

    从 dify_few_shot.txt 加载 SQL 问答对，
    每个 chunk 附带元数据：scenario, question, full_text。

    Args:
        force_rebuild: 是否强制重建（忽略已有数据）
    """
    chunks = _load_chunks_with_metadata("dify_few_shot.txt", _parse_few_shot_chunk)
    embeddings = _get_embeddings()
    conn_str = _build_connection()

    store = PGVector(
        embeddings=embeddings,
        collection_name="mes_few_shot_embeddings",
        connection=conn_str,
        pre_delete_collection=False,
    )

    if force_rebuild or not _collection_has_data(store):
        if force_rebuild:
            logger.info("强制重建 few_shot 向量库...")
            store.delete_collection()
            store.create_collection()
        else:
            logger.info("few_shot 向量库为空，开始初始化...")

        if chunks:
            ids = [f"few_{i}" for i in range(len(chunks))]
            texts = [c["embed_text"] for c in chunks]
            metadatas = [c["metadata"] for c in chunks]
            store.add_texts(texts=texts, ids=ids, metadatas=metadatas)
            logger.info("few_shot 向量库初始化完成，共 %d 条记录", len(chunks))
    else:
        logger.info("few_shot 向量库已有数据，跳过初始化")

    return store


# ---- 检索 ----


def search_schema(store: PGVectorStore, query: str, k: int | None = None) -> list[str]:
    """检索相关表结构，返回完整文本（从 metadata.full_text 取，不受 embedding 截断影响）。"""
    docs = store.similarity_search(query, k=k or settings.retrieval_top_k)
    return [_get_full_text(d) for d in docs]


def search_schema_with_meta(store: PGVectorStore, query: str, k: int | None = None) -> list[Document]:
    """检索相关表结构，返回完整 Document（含 page_content + metadata）。"""
    return store.similarity_search(query, k=k or settings.retrieval_top_k)


def search_few_shot(store: PGVectorStore, query: str, k: int | None = None) -> list[str]:
    """检索相关 SQL 示例，返回完整文本（从 metadata.full_text 取，不受 embedding 截断影响）。"""
    docs = store.similarity_search(query, k=k or settings.few_shot_top_k)
    return [_get_full_text(d) for d in docs]


def search_few_shot_with_meta(store: PGVectorStore, query: str, k: int | None = None) -> list[Document]:
    """检索相关 SQL 示例，返回完整 Document（含 page_content + metadata）。"""
    return store.similarity_search(query, k=k or settings.few_shot_top_k)


def _get_full_text(doc: Document) -> str:
    """从 Document 的 metadata 中取 full_text，若无则回退到 page_content。"""
    return doc.metadata.get("full_text", doc.page_content)
