"""将 mes_knowledge_base.txt 的字段数据（full_text / embedding）同步到 Neo4j。

用法: uv run python scripts/sync_kb_to_neo4j.py
"""
import asyncio
import logging

from src.services.neo4j_graph import _derive_domain, _derive_prefix, _get_driver
from src.services.vector_store import _build_schema_embed_text, _get_embeddings, _parse_schema_chunk

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_KB_FILE = __import__("pathlib").Path(__file__).parent.parent / "data" / "mes_knowledge_base.txt"


def load_chunks():
    """从知识库文件加载所有 chunk。"""
    if not _KB_FILE.exists():
        logger.error("知识库文件不存在: %s", _KB_FILE)
        return []

    content = _KB_FILE.read_text(encoding="utf-8")
    chunks = [c.strip() for c in content.split("\n---\n") if c.strip()]
    logger.info("从 %s 加载了 %d 个 chunk", _KB_FILE, len(chunks))
    return chunks


async def sync_all():
    chunks = load_chunks()
    if not chunks:
        return

    driver = await _get_driver()
    embeddings = _get_embeddings()

    success = 0
    skip = 0

    async with driver.session() as session:
        for chunk in chunks:
            meta = _parse_schema_chunk(chunk)
            table_name = meta.get("table_name", "")
            if not table_name:
                logger.warning("chunk 无法解析表名，跳过: %s...", chunk[:60])
                skip += 1
                continue

            module = meta.get("module", "")
            business_meaning = meta.get("business_meaning", "")

            # 构建 embedding
            embed_text = _build_schema_embed_text(meta)
            if not embed_text.strip():
                embed_text = chunk
            vector = embeddings.embed_query(embed_text)

            domain = _derive_domain(table_name)
            prefix = _derive_prefix(table_name)

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
                    "full_text": chunk,
                    "module": module,
                    "business_meaning": business_meaning,
                    "domain": domain,
                    "prefix": prefix,
                },
            )
            success += 1
            if success % 10 == 0:
                logger.info("进度: %d/%d", success, len(chunks))

    logger.info("同步完成: %d 成功, %d 跳过", success, skip)


if __name__ == "__main__":
    asyncio.run(sync_all())
