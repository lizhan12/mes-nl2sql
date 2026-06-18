"""将表关系图数据从 JSON 文件导入到 Neo4j。

用法:
    uv run python scripts/import_graph_to_neo4j.py          # 全量导入
    uv run python scripts/import_graph_to_neo4j.py --verify # 验证数据完整性

数据来源: data/mes_relation_graph.json
目标: Neo4j (Table 节点 + JOIN_REL 关系)
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_json_graph() -> dict[str, list[dict]]:
    """从 JSON 文件加载图数据。"""
    json_path = Path(__file__).parent.parent / "data" / "mes_relation_graph.json"
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    graph = data.get("graph", data) if isinstance(data, dict) else data
    logger.info("从 JSON 加载图数据，表: %d", len(graph))
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description="导入表关系图到 Neo4j")
    parser.add_argument("--verify", action="store_true", help="仅验证数据完整性，不导入")
    parser.add_argument("--dry-run", action="store_true", help="预览导入内容，不实际写入")
    args = parser.parse_args()

    graph = load_json_graph()

    # 统计 JSON 中的节点和边
    all_tables: set[str] = set(graph.keys())
    edge_count = 0
    for from_table, edges in graph.items():
        for e in edges:
            all_tables.add(e["to"])
            if "(反向)" not in e.get("desc", ""):
                edge_count += 1

    logger.info("JSON 文件统计: 节点=%d, 正向边=%d", len(all_tables), edge_count)

    if args.verify:
        # 验证模式：对比 Neo4j 与 JSON 数据
        from src.services.neo4j_graph import count_graph

        neo_nodes, neo_edges = count_graph()
        logger.info("Neo4j 当前统计: 节点=%d, 边=%d", neo_nodes, neo_edges)

        if neo_nodes == 0:
            logger.warning("Neo4j 中无数据，请先运行导入: uv run python scripts/import_graph_to_neo4j.py")
        else:
            node_ok = neo_nodes == len(all_tables)
            edge_ok = neo_edges == edge_count
            if node_ok and edge_ok:
                logger.info("验证通过: 节点 %d/%d, 边 %d/%d", neo_nodes, len(all_tables), neo_edges, edge_count)
            else:
                logger.warning(
                    "数据不一致: 节点 %d vs %d, 边 %d vs %d", neo_nodes, len(all_tables), neo_edges, edge_count
                )
        return

    if args.dry_run:
        logger.info("--dry-run 模式，预览导入内容:")
        logger.info("  将创建 %d 个 Table 节点", len(all_tables))
        logger.info("  将创建 %d 条 JOIN_REL 边（单向）", edge_count)

        sample_count = 0
        for from_table, edges in graph.items():
            for e in edges:
                if "(反向)" in e.get("desc", ""):
                    continue
                logger.info("  %s → %s (%s)", from_table, e["to"], e.get("desc", ""))
                sample_count += 1
                if sample_count >= 10:
                    logger.info("  ... (共 %d 条边)", edge_count)
                    return
        return

    # 执行导入（async 函数需通过 asyncio.run 调用）
    import asyncio

    from src.services.neo4j_graph import count_graph, replace_all_graph

    async def _run() -> None:
        imported = await replace_all_graph(graph)
        logger.info("导入成功: %d 条边已写入 Neo4j", imported)

        # 验证导入结果
        neo_nodes, neo_edges = await count_graph()
        logger.info("导入后 Neo4j: 节点=%d, 边=%d", neo_nodes, neo_edges)

        if neo_nodes != len(all_tables):
            logger.warning("节点数不一致: %d vs %d", neo_nodes, len(all_tables))
        if neo_edges != edge_count:
            logger.warning("边数不一致: %d vs %d", neo_edges, edge_count)

    try:
        asyncio.run(_run())
    except Exception as e:
        logger.error("导入失败: %s", e)
        raise


if __name__ == "__main__":
    main()
