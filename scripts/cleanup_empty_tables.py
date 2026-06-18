"""清理 Neo4j 中没有字段的空表和对应关系。

删除所有没有关联 :Field 节点的 :Table 节点及其 :JOIN_REL 边。

用法：
  uv run python scripts/cleanup_empty_tables.py          # 仅列出空表，不删除
  uv run python scripts/cleanup_empty_tables.py --exec   # 执行删除
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("cleanup_empty_tables")


def main() -> None:
    dry_run = "--exec" not in sys.argv

    from src.services.neo4j_graph import _get_driver

    driver = _get_driver()

    with driver.session() as session:
        # 1. 查找没有 Field 节点的 Table
        result = session.run(
            """
            MATCH (t:Table)
            WHERE NOT EXISTS { MATCH (:Field {table_name: t.name}) }
            RETURN t.name AS table_name
            ORDER BY t.name
            """
        )
        empty_tables = [rec["table_name"] for rec in result]

        if not empty_tables:
            logger.info("没有发现空表（所有 Table 节点都有对应的 Field 节点）")
            return

        logger.info("发现 %d 张空表（无 Field 节点）：", len(empty_tables))
        for name in empty_tables:
            logger.info("  - %s", name)

        if dry_run:
            logger.info("\n⚠ 当前为预览模式，未执行删除。使用 --exec 参数执行删除。")
            return

        # 2. 删除空表及其关系
        logger.info("\n开始删除...")
        for name in empty_tables:
            session.run(
                """
                MATCH (t:Table {name: $name})
                DETACH DELETE t
                """,
                {"name": name},
            )
            logger.info("  已删除: %s", name)

        # 3. 输出清理后统计
        node_count = session.run("MATCH (t:Table) RETURN count(t) AS c").single()["c"]
        edge_count = session.run("MATCH ()-[r:JOIN_REL]->() RETURN count(r) AS c").single()["c"]
        field_count = session.run("MATCH (f:Field) RETURN count(f) AS c").single()["c"]
        logger.info("\n清理完成。Neo4j 当前: %d Table节点, %d JOIN_REL边, %d Field节点", node_count, edge_count, field_count)


if __name__ == "__main__":
    main()
