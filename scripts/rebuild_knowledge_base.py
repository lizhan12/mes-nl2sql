"""一键重建知识库脚本。

与 main.py 启动时的初始化流程完全一致，包含：
  1. 表结构向量库重建（mes_knowledge_base.txt → Neo4j Table 节点）
  2. SQL 示例向量库重建（dify_few_shot.txt → Neo4j FewShot 节点）
  3. 关系图初始化（PG / JSON → Neo4j JOIN_REL 边）
  4. 字段级向量索引（Neo4j Field 节点）
  5. 关键词倒排索引（内存）

用法：
  uv run python scripts/rebuild_knowledge_base.py          # 增量（已有数据则跳过）
  uv run python scripts/rebuild_knowledge_base.py --force  # 强制全量重建
"""

import logging
import os
import sys

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("rebuild_knowledge_base")


def main() -> None:
    force_rebuild = "--force" in sys.argv

    logger.info("=" * 60)
    if force_rebuild:
        logger.info("强制重建知识库（全部数据将被清除后重建）")
    else:
        logger.info("增量构建知识库（已有数据则跳过，无数据则初始化）")
    logger.info("=" * 60)

    # ── 1. 表结构向量库 ────────────────────────────────────────────
    logger.info("\n[1/4] 构建表结构向量库...")
    from src.services.vector_store import build_neo4j_schema_store

    schema_store = build_neo4j_schema_store(force_rebuild=force_rebuild)
    logger.info("[1/4] 表结构向量库构建完成")

    # ── 2. SQL 示例向量库 ──────────────────────────────────────────
    logger.info("\n[2/4] 构建 SQL 示例向量库...")
    from src.services.vector_store import build_neo4j_few_shot_store

    few_shot_store = build_neo4j_few_shot_store(force_rebuild=force_rebuild)
    logger.info("[2/4] SQL 示例向量库构建完成")

    # ── 3. 关系图初始化 ────────────────────────────────────────────
    logger.info("\n[3/4] 初始化表关系图...")
    from src.services.neo4j_graph import count_graph, init_neo4j_graph

    if force_rebuild:
        # 强制重建时清空已有的关系图
        from src.services.neo4j_graph import _get_driver

        driver = _get_driver()
        with driver.session() as session:
            session.run("MATCH (t:Table) DETACH DELETE t")
            logger.info("已清空 Neo4j 关系图节点和边")
        init_neo4j_graph()
    else:
        init_neo4j_graph()

    node_count, edge_count = count_graph()
    logger.info("[3/4] 关系图初始化完成，共 %d 节点, %d 边", node_count, edge_count)

    # ── 4. 验证 ─────────────────────────────────────────────────────
    logger.info("\n[4/4] 验证知识库数据...")
    from src.services.neo4j_graph import (
        few_shot_has_embeddings,
        field_has_embeddings,
        schema_has_embeddings,
    )

    checks = {
        "表结构向量 (Table.schema_embedding)": schema_has_embeddings(),
        "SQL 示例向量 (FewShot.question_embedding)": few_shot_has_embeddings(),
        "字段向量 (Field.field_embedding)": field_has_embeddings(),
        "关系图 (Table 节点 + JOIN_REL 边)": node_count > 0,
    }

    all_ok = True
    for name, ok in checks.items():
        status = "✓" if ok else "✗ 缺失!"
        if not ok:
            all_ok = False
        logger.info("  %s %s", status, name)

    logger.info("\n" + "=" * 60)
    if all_ok:
        logger.info("知识库重建完成，所有检查通过！")
    else:
        logger.warning("知识库重建完成，但部分数据缺失，请检查日志")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
