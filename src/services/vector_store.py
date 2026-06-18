"""向量存储服务，使用 Neo4j 作为向量存储后端。

每个文档存入 Neo4j 时同时携带元数据：
  - 表结构库 (mes_knowledge_base.txt)：table_name, module, business_meaning, full_text, columns, relations, scenarios
  - SQL 示例库 (dify_few_shot.txt)：scenario, question, full_text
  - 关键词索引：table_name -> keywords 映射，用于混合检索

启动时检查 Neo4j 中是否已有数据，避免重复 embedding。
"""

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from openai import OpenAI

from src.core.config import settings

if TYPE_CHECKING:
    from src.services.neo4j_vector_store import Neo4jVectorStore

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
EMBED_MAX_CHARS = 800  # bge-large-zh-v1.5 支持 512 tokens，中文约 1.5 字符/token，800 字符安全
_EMBED_BATCH_SIZE = 20  # SiliconFlow 单次请求文本数上限

# 全局关键词索引：{关键词 -> [表名列表]}
_keyword_index: dict[str, list[str]] = {}


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
        关联关系：
          JOIN t_xxx ON ... -- description
          ...
        适用场景：xxx

    Returns:
        {table_name, module, business_meaning, full_text, columns, relations, scenarios}
    """
    table_name = ""
    module = ""
    business_meaning = ""
    columns: list[str] = []  # "col_name(comment)" 格式
    relations: list[str] = []  # "t_xxx(yyy)" 格式
    scenarios: list[str] = []
    section: str = ""

    for line in chunk.split("\n"):
        stripped = line.strip()
        if stripped.startswith("表名："):
            table_name = stripped[len("表名：") :].strip()
        elif stripped.startswith("模块："):
            module = stripped[len("模块：") :].strip()
        elif stripped.startswith("业务含义："):
            business_meaning = stripped[len("业务含义：") :].strip()
        elif stripped == "关键字段：":
            section = "columns"
        elif stripped == "关联关系：":
            section = "relations"
        elif stripped.startswith("适用场景："):
            section = "scenarios"
            scenarios.append(stripped[len("适用场景：") :].strip())
        elif stripped and section == "columns" and " -- " in stripped:
            # "col_name (type) -- comment" -> "col_name(comment)"
            col_match = re.match(r"(\w+)\s*\(.*?\)\s*--\s*(.*)", stripped)
            if col_match:
                col_name, comment = col_match.group(1), col_match.group(2).rstrip(")")
                columns.append(f"{col_name}({comment})")
            else:
                columns.append(stripped)
        elif stripped and section == "relations":
            # "JOIN t_xxx ON ... -- description" -> "t_xxx(description)"
            rel_match = re.match(r"JOIN\s+(\w+)\s+ON.*--\s*(.*)", stripped)
            if rel_match:
                rel_table, rel_desc = rel_match.group(1), rel_match.group(2)
                relations.append(f"{rel_table}({rel_desc})")
        elif stripped and section == "scenarios":
            scenarios.append(stripped)

    return {
        "table_name": table_name,
        "module": module,
        "business_meaning": business_meaning,
        "full_text": chunk,
        "columns": columns,
        "relations": relations,
        "scenarios": scenarios,
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


def _build_few_shot_embed_text(meta: dict) -> str:
    """构造 few-shot 的 embedding 文本，只包含场景和问题，避免 SQL 语法干扰语义匹配。

    Args:
        meta: 包含 scenario 和 question 的元数据字典

    Returns:
        用于 embedding 的文本字符串
    """
    scenario = meta.get("scenario", "")
    question = meta.get("question", "")
    return f"{scenario} {question}".strip()[:EMBED_MAX_CHARS]


def _build_schema_embed_text(meta: dict) -> str:
    """构造表结构的紧凑 embedding 文本，保留全部列名+注释+场景。

    格式：表 t_xxx 模块名 业务含义 列: col1(注释1) col2(注释2) ... 场景: 场景1,场景2
    确保在 EMBED_MAX_CHARS 内包含尽可能多的关键信息。

    注意：不包含关联关系（JOIN），JOIN 由 Neo4j :JOIN_REL 边管理。
    """
    parts: list[str] = []

    # 基本信息
    header = f"表 {meta['table_name']}"
    if meta.get("module"):
        header += f" {meta['module']}"
    if meta.get("business_meaning") and meta["business_meaning"] != "（无注释）":
        header += f" {meta['business_meaning']}"
    parts.append(header)

    # 列信息（列名+注释全部保留，这是向量检索匹配的核心）
    columns = meta.get("columns", [])
    if columns:
        cols_text = " ".join(columns)
        parts.append(f"列: {cols_text}")

    # 适用场景
    scenarios = meta.get("scenarios", [])
    if scenarios:
        parts.append(f"场景: {','.join(scenarios)}")

    embed_text = " ".join(parts)
    if len(embed_text) > EMBED_MAX_CHARS:
        # 智能裁减：按优先级逐步丢弃低优先级部分
        # 优先级：表名+模块+业务含义 > 列信息 > 适用场景
        # 1. 先去掉场景
        if scenarios and len(embed_text) > EMBED_MAX_CHARS:
            parts_trimmed = [p for p in parts if not p.startswith("场景:")]
            embed_text = " ".join(parts_trimmed)
        # 2. 列信息过长时，截断列列表但保留列名（去掉注释）
        if columns and len(embed_text) > EMBED_MAX_CHARS:
            col_names_only = " ".join(c.split("(")[0] for c in columns)
            parts_trimmed = [p for p in parts if not p.startswith("列:")]
            parts_trimmed.append(f"列: {col_names_only}")
            embed_text = " ".join(parts_trimmed)
        # 3. 最终兜底截断
        if len(embed_text) > EMBED_MAX_CHARS:
            embed_text = embed_text[:EMBED_MAX_CHARS]
    return embed_text


def _build_keyword_index(chunks: list[dict]) -> dict[str, list[str]]:
    """从 schema chunk 中构建关键词→表名倒排索引。

    提取来源：
      - 表名本身
      - 模块名（分词）
      - 业务含义（分词）
      - 列注释中的中文关键词
      - 关联表描述中的中文关键词
      - 适用场景（分词）

    Returns:
        {"工单": ["t_pd_wo", ...], "过站": ["t_pd_sn_travel", ...], ...}
    """
    index: defaultdict[str, set[str]] = defaultdict(set)

    def _extract_terms(text: str) -> list[str]:
        """从中文文本中提取有意义的短词（2-5 字片段）。"""
        # 简单策略：按标点分割后取 2-5 字片段
        parts = re.split(r"[,，/、；;]", text)
        terms: list[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # 取整段
            terms.append(part)
            # 也取 2-4 字滑动窗口
            if len(part) >= 2:
                for win_size in (2, 3, 4):
                    for i in range(len(part) - win_size + 1):
                        terms.append(part[i : i + win_size])
        return terms

    for item in chunks:
        meta = item["metadata"]
        table_name = meta.get("table_name", "")
        if not table_name:
            continue

        sources: list[str] = []
        sources.append(table_name)
        sources.append(meta.get("module", ""))
        sources.append(meta.get("business_meaning", ""))
        for col in meta.get("columns", []):
            # 提取注释部分
            if "(" in col and ")" in col:
                sources.append(col[col.rindex("(") + 1 : col.rindex(")")])
        for rel in meta.get("relations", []):
            if "(" in rel and ")" in rel:
                sources.append(rel[rel.rindex("(") + 1 : rel.rindex(")")])
        for sc in meta.get("scenarios", []):
            sources.append(sc)

        for source in sources:
            for term in _extract_terms(source):
                if term and len(term) >= 2:
                    index[term].add(table_name)

    # 转为 {关键词: [表名列表]}
    return {k: list(v) for k, v in index.items()}


def keyword_search_schema(query: str, top_n: int = 10) -> list[str]:
    """关键词精确匹配搜索：从用户查询中提取关键词，匹配倒排索引。

    Args:
        query: 用户查询文本
        top_n: 返回最多表名数

    Returns:
        按关键词命中数降序排列的表名列表
    """
    if not _keyword_index:
        return []

    # 提取查询中的中文片段（2-5 字窗口）
    terms: list[str] = []
    for win_size in (2, 3, 4, 5):
        for i in range(len(query) - win_size + 1):
            terms.append(query[i : i + win_size])
    terms.append(query)  # 也加完整查询

    # 去重
    terms = list(dict.fromkeys(terms))

    # 匹配关键词索引
    table_hits: defaultdict[str, int] = defaultdict(int)
    for term in terms:
        matched_tables = _keyword_index.get(term, [])
        for tname in matched_tables:
            table_hits[tname] += 1

    # 按命中数降序，取 top_n
    sorted_tables = sorted(table_hits.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in sorted_tables[:top_n]]


def _load_chunks_with_metadata(
    file_name: str,
    parser: callable,
    separator: str = "\n---\n",
) -> list[dict]:
    """加载数据文件，解析每个 chunk 的元数据。

    对于表结构文件，embed_text 使用紧凑摘要格式（保留全部列名+注释+关联），
    而非简单截断。对于 few_shot 文件，仍使用截断方式。

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

    is_schema = file_name == "mes_knowledge_base.txt"
    is_few_shot = file_name == "dify_few_shot.txt"

    results: list[dict] = []
    for chunk in raw_chunks:
        meta = parser(chunk)
        if is_schema:
            embed_text = _build_schema_embed_text(meta)
        elif is_few_shot:
            # few-shot 只 embedding 场景+问题，不包含 SQL，避免 SQL 语法干扰语义匹配
            scenario = meta.get("scenario", "")
            question = meta.get("question", "")
            embed_text = f"{scenario} {question}".strip()[:EMBED_MAX_CHARS]
        else:
            embed_text = chunk[:EMBED_MAX_CHARS]
        results.append(
            {
                "full_text": chunk,
                "embed_text": embed_text,
                "metadata": meta,
            }
        )

    logger.info("从 %s 加载了 %d 个 chunk", file_name, len(results))
    return results


# ---- Embedding 与连接 ----


class _DirectEmbeddings(Embeddings):
    """直接调用 OpenAI 兼容 API 的 embedding，绕过 langchain_openai 的 token 分块问题。"""

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=settings.embedding_key,
            base_url=settings.embedding_base_url,
        )
        self._model = settings.embedding_model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), _EMBED_BATCH_SIZE):
            batch = texts[i : i + _EMBED_BATCH_SIZE]
            resp = self._client.embeddings.create(model=self._model, input=batch)
            all_embeddings.extend([d.embedding for d in resp.data])
        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        resp = self._client.embeddings.create(model=self._model, input=[text])
        return resp.data[0].embedding


def _get_embeddings() -> _DirectEmbeddings:
    return _DirectEmbeddings()


# ---- 检索 ----

# 相似度阈值：低于此值的向量召回结果直接丢弃
_SIMILARITY_THRESHOLD = 0.55


async def search_schema(
    store: "Neo4jVectorStore",
    query: str,
    k: int | None = None,
    similarity_threshold: float | None = None,
) -> list[str]:
    """向量检索相关表结构，支持相似度阈值过滤。

    Args:
        store: Neo4jVectorStore 向量库实例
        query: 查询文本
        k: 返回数量，默认使用配置的 retrieval_top_k
        similarity_threshold: 相似度阈值，低于此值的结果丢弃。默认 0.55

    Returns:
        完整文本列表（从 metadata.full_text 取）
    """
    threshold = similarity_threshold if similarity_threshold is not None else _SIMILARITY_THRESHOLD
    docs = await store.similarity_search_with_score(query, k=k or settings.retrieval_top_k)
    result: list[str] = []
    for doc, score in docs:
        if score < threshold:
            continue
        text = _get_full_text(doc)
        if text and text not in result:
            result.append(text)
    return result


async def search_schema_with_meta(
    store: "Neo4jVectorStore",
    query: str,
    k: int | None = None,
    similarity_threshold: float | None = None,
) -> list[tuple[Document, float]]:
    """向量检索相关表结构，返回完整 Document + 相似度分数。

    Returns:
        [(Document, score), ...] 按分数降序排列
    """
    threshold = similarity_threshold if similarity_threshold is not None else _SIMILARITY_THRESHOLD
    docs = await store.similarity_search_with_score(query, k=k or settings.retrieval_top_k)
    return [(doc, score) for doc, score in docs if score >= threshold]


async def hybrid_search_schema(
    store: "Neo4jVectorStore",
    query: str,
    k: int | None = None,
    similarity_threshold: float | None = None,
    keyword_top_n: int = 10,
) -> list[str]:
    """混合检索：向量语义搜索 + 关键词精确匹配。

    策略：
      1. 向量检索：语义相似度匹配，返回 top_k 结果
      2. 关键词检索：从查询中提取关键词，匹配倒排索引，返回命中的表名列表
      3. 用关键词结果从本地 schema_lookup 精确补充完整 chunk
      4. 合并去重，向量结果优先，关键词结果追加

    Args:
        store: Neo4jVectorStore 向量库实例
        query: 查询文本
        k: 向量检索返回数量
        similarity_threshold: 相似度阈值
        keyword_top_n: 关键词检索返回表名数上限

    Returns:
        合并去重后的完整文本列表
    """
    # 步骤1: 向量检索
    vector_results = await search_schema(store, query, k=k, similarity_threshold=similarity_threshold)

    # 步骤2: 关键词检索（返回表名列表）
    keyword_table_names = keyword_search_schema(query, top_n=keyword_top_n)

    # 步骤3: 用关键词命中的表名，从本地 schema_lookup 精确取完整 chunk
    lookup = _get_schema_lookup()
    keyword_full_texts: list[str] = []
    for tname in keyword_table_names:
        doc = lookup.get(tname)
        if doc and doc not in keyword_full_texts:
            keyword_full_texts.append(doc)

    # 步骤4: 合并去重，向量结果优先
    seen: set[str] = set()
    merged: list[str] = []
    for text in vector_results:
        if text and text not in seen:
            seen.add(text)
            merged.append(text)
    for text in keyword_full_texts:
        if text and text not in seen:
            seen.add(text)
            merged.append(text)

    logger.info(
        "混合检索: 向量=%d (阈值>=%.2f) + 关键词=%d -> 合并=%d",
        len(vector_results),
        similarity_threshold or _SIMILARITY_THRESHOLD,
        len(keyword_full_texts),
        len(merged),
    )
    return merged


# ---- 本地 Schema 查询缓存 ----

_schema_lookup_cache: dict[str, str] | None = None


def _get_schema_lookup() -> dict[str, str]:
    """获取本地 schema 表名→完整 chunk 映射（惰性加载）。"""
    global _schema_lookup_cache
    if _schema_lookup_cache is not None:
        return _schema_lookup_cache

    path = _DATA_DIR / "mes_knowledge_base.txt"
    if not path.exists():
        _schema_lookup_cache = {}
        return _schema_lookup_cache

    lookup: dict[str, str] = {}
    for chunk in path.read_text(encoding="utf-8").split("\n---\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = re.search(r"表名：(\w+)", chunk)
        if match:
            lookup[match.group(1)] = chunk

    _schema_lookup_cache = lookup
    return lookup


async def search_few_shot(store: "Neo4jVectorStore", query: str, k: int | None = None) -> list[str]:
    """检索相关 SQL 示例，返回完整文本（从 metadata.full_text 取，不受 embedding 截断影响）。"""
    docs = await store.similarity_search(query, k=k or settings.few_shot_top_k)
    return [_get_full_text(d) for d in docs]


async def search_few_shot_with_meta(store: "Neo4jVectorStore", query: str, k: int | None = None) -> list[Document]:
    """检索相关 SQL 示例，返回完整 Document（含 page_content + metadata）。"""
    return await store.similarity_search(query, k=k or settings.few_shot_top_k)


def _get_full_text(doc: Document) -> str:
    """从 Document 的 metadata 中取 full_text，若无则回退到 page_content。"""
    return doc.metadata.get("full_text", doc.page_content)


# ── 字段级向量检索 ──────────────────────────────────────────────────


async def _init_field_embeddings(
    chunks: list[dict], embeddings: _DirectEmbeddings, force_rebuild: bool = False
) -> None:
    """初始化字段级向量索引，为每个字段创建 Neo4j Field 节点。

    Args:
        chunks: _load_chunks_with_metadata 返回的 chunk 列表
        embeddings: embedding 实例
        force_rebuild: 是否强制重建
    """
    from src.services.neo4j_graph import (
        batch_set_field_embeddings,
        ensure_field_indexes,
        field_has_embeddings,
    )

    await ensure_field_indexes()

    if force_rebuild or not await field_has_embeddings():
        if force_rebuild:
            logger.info("强制重建 Field 向量索引...")
        else:
            logger.info("Field 向量索引为空，开始初始化...")

        # 从 Neo4j JOIN_REL 推断主键/外键字段
        pk_fk_fields: dict[str, set[str]] = {}
        try:
            from src.services.neo4j_graph import _get_driver

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
                    ff = rec["from_field"]
                    tf = rec["to_field"]
                    pk_fk_fields.setdefault(ft, set()).add(ff)
                    pk_fk_fields.setdefault(tt, set()).add(tf)
        except Exception as e:
            logger.warning("从 JOIN_REL 推断 PK/FK 失败: %s", e)

        field_items: list[dict] = []
        for c in chunks:
            meta = c["metadata"]
            table_name = meta.get("table_name", "")
            pk_fk_set = pk_fk_fields.get(table_name, set())
            # 从 full_text 重新解析字段，保留 type 信息
            # 原始格式: "  col_name (type) -- comment"，type 可能含嵌套括号如 varchar(40)
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

        if field_items:
            field_texts = [f["embed_text"] for f in field_items]
            logger.info("正在生成 %d 个 Field embedding...", len(field_texts))
            field_vectors = embeddings.embed_documents(field_texts)
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
            await batch_set_field_embeddings(batch)
            logger.info("Field 向量索引初始化完成，共 %d 个字段", len(field_items))
    else:
        logger.info("Field 向量索引已有数据，跳过初始化")


async def search_fields(query: str, k: int = 30, threshold: float = 0.55) -> list[dict]:
    """字段级语义搜索。

    对用户查询做向量检索，返回语义相关的字段信息。

    Args:
        query: 用户查询文本
        k: 返回数量上限
        threshold: 相似度阈值

    Returns:
        [{table_name, field_name, type, comment, score}, ...]
    """
    from src.services.neo4j_graph import field_similarity_search

    embeddings = _get_embeddings()
    query_vec = embeddings.embed_query(query)
    return await field_similarity_search(query_vec, threshold=threshold, limit=k)


# ── Neo4j 向量库构建 ────────────────────────────────────────────────


async def build_neo4j_schema_store(force_rebuild: bool = False) -> "Neo4jVectorStore":
    """构建 Neo4j 表结构向量库。

    从 mes_knowledge_base.txt 加载数据，生成 embedding 后写入 Table 节点的
    schema_embedding 属性。同时构建关键词倒排索引。

    Args:
        force_rebuild: 是否强制重建（忽略已有数据）
    """
    global _keyword_index
    from src.services.neo4j_graph import batch_set_schema_embeddings, ensure_vector_indexes, schema_has_embeddings
    from src.services.neo4j_vector_store import Neo4jVectorStore

    await ensure_vector_indexes()

    embeddings = _get_embeddings()
    store = Neo4jVectorStore("schema", embeddings)

    if force_rebuild or not await schema_has_embeddings():
        if force_rebuild:
            logger.info("强制重建 Neo4j schema 向量库...")
        else:
            logger.info("Neo4j schema 向量库为空，开始初始化...")

        chunks = _load_chunks_with_metadata("mes_knowledge_base.txt", _parse_schema_chunk)
        if chunks:
            # 生成 embedding
            texts = [c["embed_text"] for c in chunks]
            logger.info("正在生成 %d 个 schema embedding...", len(texts))
            vectors = embeddings.embed_documents(texts)

            # 批量写入 Neo4j
            batch = [
                {
                    "name": c["metadata"].get("table_name", ""),
                    "embedding": vec,
                    "full_text": c["full_text"],
                    "module": c["metadata"].get("module", ""),
                    "business_meaning": c["metadata"].get("business_meaning", ""),
                }
                for c, vec in zip(chunks, vectors, strict=True)
            ]
            await batch_set_schema_embeddings(batch)
            logger.info("Neo4j schema 向量库初始化完成，共 %d 条记录", len(chunks))

        # 构建关键词倒排索引
        _keyword_index = _build_keyword_index(chunks)
        logger.info("关键词索引构建完成，共 %d 个词条", len(_keyword_index))

        # 初始化字段级向量索引（仅首次，无数据时执行）
        await _init_field_embeddings(chunks, embeddings, force_rebuild)
    else:
        logger.info("Neo4j schema 向量库已有数据，跳过初始化")
        if not _keyword_index:
            # 从 Neo4j 构建关键词索引，不再读本地文件
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
                _keyword_index = _build_keyword_index(chunks)
                logger.info("关键词索引构建完成（从 Neo4j），共 %d 个词条", len(_keyword_index))
            except Exception as exc:
                logger.warning("从 Neo4j 构建关键词索引失败: %s", exc)

    return store


async def build_neo4j_few_shot_store(force_rebuild: bool = False) -> "Neo4jVectorStore":
    """构建 Neo4j SQL 示例向量库。

    从 dify_few_shot.txt 加载数据，生成 embedding 后写入 FewShot 节点的
    question_embedding 属性。

    Args:
        force_rebuild: 是否强制重建（忽略已有数据）
    """
    from src.services.neo4j_graph import (
        batch_set_few_shot_embeddings,
        clear_few_shot_nodes,
        ensure_vector_indexes,
        few_shot_has_embeddings,
    )
    from src.services.neo4j_vector_store import Neo4jVectorStore

    await ensure_vector_indexes()

    embeddings = _get_embeddings()
    store = Neo4jVectorStore("few_shot", embeddings)

    if force_rebuild or not await few_shot_has_embeddings():
        if force_rebuild:
            logger.info("强制重建 Neo4j few_shot 向量库...")
            await clear_few_shot_nodes()
        else:
            logger.info("Neo4j few_shot 向量库为空，开始初始化...")

        chunks = _load_chunks_with_metadata("dify_few_shot.txt", _parse_few_shot_chunk)
        if chunks:
            # 生成 embedding
            texts = [c["embed_text"] for c in chunks]
            logger.info("正在生成 %d 个 few_shot embedding...", len(texts))
            vectors = embeddings.embed_documents(texts)

            # 批量写入 Neo4j
            # 处理超过 1000 个向量的情况，分批写入
            batch = [
                {
                    "id": f"few_{i}",
                    "embedding": vec,
                    "scenario": c["metadata"].get("scenario", ""),
                    "question": c["metadata"].get("question", ""),
                    "full_text": c["full_text"],
                }
                for i, (c, vec) in enumerate(zip(chunks, vectors, strict=True))
            ]
            # 分批写入，每批最多 500 条
            batch_size = 500
            total = 0
            for i in range(0, len(batch), batch_size):
                total += await batch_set_few_shot_embeddings(batch[i : i + batch_size])
            logger.info("Neo4j few_shot 向量库初始化完成，共 %d 条记录", total)
    else:
        logger.info("Neo4j few_shot 向量库已有数据，跳过初始化")

    return store


async def build_neo4j_evolved_few_shot_store(force_rebuild: bool = False) -> "Neo4jVectorStore | None":
    """构建 Neo4j 进化 SQL 示例向量库。

    从 Neo4j 中已发布的 EvolvedFewShot 节点加载数据，生成 embedding 后写入
    question_embedding 属性。

    Args:
        force_rebuild: 是否强制重建（忽略已有数据）

    Returns:
        Neo4jVectorStore 实例，如果无数据则返回 None
    """
    from src.services.neo4j_graph import (
        batch_set_evolved_few_shot_embeddings,
        ensure_vector_indexes,
        evolved_few_shot_has_embeddings,
        get_evolved_few_shot_without_embeddings,
        load_published_few_shot_text,
    )
    from src.services.neo4j_vector_store import Neo4jVectorStore

    await ensure_vector_indexes()

    embeddings = _get_embeddings()
    store = Neo4jVectorStore("evolved_few_shot", embeddings)

    if force_rebuild or not await evolved_few_shot_has_embeddings():
        if force_rebuild:
            logger.info("强制重建 Neo4j evolved_few_shot 向量库...")
        else:
            logger.info("Neo4j evolved_few_shot 向量库为空，开始初始化...")

        # 从 Neo4j 加载已发布的进化示例
        text = await load_published_few_shot_text()
        if not text:
            logger.info("无已发布的进化示例，跳过初始化")
            return None

        chunks = [c.strip() for c in text.split("\n---\n") if c.strip()]
        if not chunks:
            logger.info("进化示例文本为空，跳过初始化")
            return None

        # 解析每个 chunk
        parsed_chunks = []
        for chunk in chunks:
            meta = _parse_few_shot_chunk(chunk)
            embed_text = _build_few_shot_embed_text(meta)
            parsed_chunks.append(
                {
                    "metadata": meta,
                    "embed_text": embed_text,
                    "full_text": chunk,
                }
            )

        # 生成 embedding
        texts = [c["embed_text"] for c in parsed_chunks]
        logger.info("正在生成 %d 个 evolved_few_shot embedding...", len(texts))
        vectors = embeddings.embed_documents(texts)

        # 批量写入 Neo4j
        batch = [
            {
                "id": f"evolved_{i}",
                "embedding": vec,
                "scenario": c["metadata"].get("scenario", ""),
                "question": c["metadata"].get("question", ""),
                "full_text": c["full_text"],
            }
            for i, (c, vec) in enumerate(zip(parsed_chunks, vectors, strict=True))
        ]
        total = await batch_set_evolved_few_shot_embeddings(batch)
        logger.info("Neo4j evolved_few_shot 向量库初始化完成，共 %d 条记录", total)
    else:
        # 检查是否有缺失 embedding 的节点
        missing_nodes = await get_evolved_few_shot_without_embeddings()
        if missing_nodes:
            logger.info("发现 %d 个缺失向量化的 EvolvedFewShot 节点，开始补全...", len(missing_nodes))

            # 为缺失节点生成 embedding
            texts = [
                _build_few_shot_embed_text(
                    {
                        "scenario": node["scenario"],
                        "question": node["question"],
                    }
                )
                for node in missing_nodes
            ]

            logger.info("正在生成 %d 个补全 embedding...", len(texts))
            vectors = embeddings.embed_documents(texts)

            # 批量写入
            batch = [
                {
                    "id": node["id"],
                    "embedding": vec,
                    "scenario": node["scenario"],
                    "question": node["question"],
                    "full_text": node["full_text"],
                }
                for node, vec in zip(missing_nodes, vectors, strict=True)
            ]
            total = await batch_set_evolved_few_shot_embeddings(batch)
            logger.info("EvolvedFewShot 向量化补全完成，共处理 %d 条记录", total)
        else:
            logger.info("Neo4j evolved_few_shot 向量库已有数据，跳过初始化")

    return store


async def build_neo4j_runtime_rule_store(force_rebuild: bool = False) -> "Neo4jVectorStore | None":
    """构建 Neo4j 运行时规则向量库。

    从 Neo4j 中已发布的 RuntimeRule 节点加载数据，生成 embedding 后写入
    question_embedding 属性。

    Args:
        force_rebuild: 是否强制重建（忽略已有数据）

    Returns:
        Neo4jVectorStore 实例，如果无数据则返回 None
    """
    import json

    from src.services.neo4j_graph import (
        batch_set_runtime_rule_embeddings,
        ensure_vector_indexes,
        load_published_rules,
        runtime_rule_has_embeddings,
    )
    from src.services.neo4j_vector_store import Neo4jVectorStore

    await ensure_vector_indexes()

    embeddings = _get_embeddings()
    store = Neo4jVectorStore("runtime_rule", embeddings)

    if force_rebuild or not await runtime_rule_has_embeddings():
        if force_rebuild:
            logger.info("强制重建 Neo4j runtime_rule 向量库...")
        else:
            logger.info("Neo4j runtime_rule 向量库为空，开始初始化...")

        # 从 Neo4j 加载已发布的运行时规则
        rules = await load_published_rules()
        if not rules:
            logger.info("无已发布的运行时规则，跳过初始化")
            return None

        # 为每个规则生成 embedding（使用问题文本）
        texts = [f"问题：{rule.get('question', '')}" for rule in rules]
        logger.info("正在生成 %d 个 runtime_rule embedding...", len(texts))
        vectors = embeddings.embed_documents(texts)

        # 批量写入 Neo4j
        batch = [
            {
                "id": f"rule_{i}",
                "embedding": vec,
                "question": rule.get("question", ""),
                "normalized_question": rule.get("normalized_question", ""),
                "preferred_main_table": rule.get("preferred_main_table", ""),
                "required_tables": json.dumps(rule.get("required_tables", []), ensure_ascii=False),
                "required_joins": json.dumps(rule.get("required_joins", []), ensure_ascii=False),
                "source": rule.get("source", ""),
            }
            for i, (rule, vec) in enumerate(zip(rules, vectors, strict=True))
        ]
        total = await batch_set_runtime_rule_embeddings(batch)
        logger.info("Neo4j runtime_rule 向量库初始化完成，共 %d 条记录", total)
    else:
        logger.info("Neo4j runtime_rule 向量库已有数据，跳过初始化")

    return store


async def search_evolved_few_shot(store: "Neo4jVectorStore", query: str, k: int | None = None) -> list[str]:
    """检索相关进化 SQL 示例，返回完整文本。"""
    docs = await store.similarity_search(query, k=k or settings.few_shot_top_k)
    return [_get_full_text(d) for d in docs]


async def search_runtime_rules(
    store: "Neo4jVectorStore", query: str, k: int = 3, threshold: float | None = None
) -> list[dict]:
    """检索相关运行时规则，返回匹配的规则列表。

    Args:
        store: Neo4jVectorStore 实例
        query: 用户查询
        k: 返回的最大规则数
        threshold: 相似度阈值（默认从 settings.runtime_rule_similarity_threshold 读取）

    Returns:
        匹配的规则列表，每个规则包含 question, preferred_main_table, required_tables, required_joins 等
    """
    import json

    if threshold is None:
        threshold = settings.runtime_rule_similarity_threshold

    docs_with_scores = await store.similarity_search_with_score(query, k=k)
    results = []
    for doc, score in docs_with_scores:
        if score >= threshold:
            meta = doc.metadata
            results.append(
                {
                    "question": meta.get("question", ""),
                    "normalized_question": meta.get("normalized_question", ""),
                    "preferred_main_table": meta.get("preferred_main_table", ""),
                    "required_tables": json.loads(meta.get("required_tables", "[]")),
                    "required_joins": json.loads(meta.get("required_joins", "[]")),
                    "source": meta.get("source", ""),
                    "score": score,
                }
            )
    return results
