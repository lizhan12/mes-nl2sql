"""对比 graph.json 与 Neo4j 中现有数据，找出差异。"""

import json
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from neo4j import GraphDatabase

from src.core.config import settings

GRAPH_JSON = Path(__file__).parent.parent / "tests" / "graph.json"


def load_graph_json() -> dict:
    """加载 graph.json。"""
    with open(GRAPH_JSON, encoding="utf-8") as f:
        data = json.load(f)
    nodes = {n["id"]: n["properties"] for n in data["nodes"]}
    edges = set()
    for e in data["edges"]:
        edges.add((e["startNode"], e["endNode"]))
    return nodes, edges


def query_neo4j():
    """查询 Neo4j 中现有数据。"""
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        driver.verify_connectivity()
        print(f"Neo4j 连接成功: {settings.neo4j_uri}")
    except Exception as e:
        print(f"Neo4j 连接失败: {e}")
        return None, None, set(), set()

    with driver.session() as session:
        # 查询所有 Table 节点
        table_result = session.run(
            "MATCH (t:Table) RETURN t.name AS name, t.domain AS domain, t.prefix AS prefix ORDER BY t.name"
        )
        neo4j_tables = {}
        for rec in table_result:
            neo4j_tables[rec["name"]] = {
                "domain": rec["domain"] or "",
                "prefix": rec["prefix"] or "",
            }

        # 查询所有 JOIN_REL 边
        edge_result = session.run(
            "MATCH (a:Table)-[r:JOIN_REL]->(b:Table) "
            "RETURN a.name AS from_table, b.name AS to_table, "
            "r.from_field AS from_field, r.to_field AS to_field, "
            "r.description AS description"
        )
        neo4j_edges = set()
        neo4j_edge_details = []
        for rec in edge_result:
            pair = (rec["from_table"], rec["to_table"])
            neo4j_edges.add(pair)
            neo4j_edge_details.append(
                {
                    "from": rec["from_table"],
                    "to": rec["to_table"],
                    "from_field": rec["from_field"] or "",
                    "to_field": rec["to_field"] or "",
                    "description": rec["description"] or "",
                }
            )

    driver.close()
    return neo4j_tables, neo4j_edge_details, neo4j_edges, set(neo4j_tables.keys())


def main():
    print("=" * 60)
    print("Graph Comparison: graph.json vs Neo4j")
    print("=" * 60)

    # 1. 加载 graph.json
    json_nodes, json_edges = load_graph_json()
    json_table_names = set(json_nodes.keys())
    print(f"\n[graph.json] 表节点: {len(json_nodes)}, 边: {len(json_edges)}")

    # 2. 查询 Neo4j
    neo4j_tables, neo4j_edge_details, neo4j_edges, neo4j_table_names = query_neo4j()
    if neo4j_tables is None:
        print("Neo4j 无数据或连接失败，退出。")
        return

    print(f"[Neo4j]     表节点: {len(neo4j_tables)}, 边: {len(neo4j_edges)}")

    # 3. 对比差异
    print("\n" + "=" * 60)
    print("差异分析")
    print("=" * 60)

    # ── 表节点差异 ──
    only_in_json = json_table_names - neo4j_table_names
    only_in_neo4j = neo4j_table_names - json_table_names
    common_tables = json_table_names & neo4j_table_names

    print("\n--- 表节点对比 ---")
    print(f"  共有表: {len(common_tables)}")
    print(f"  仅在 graph.json 中: {len(only_in_json)}")
    if only_in_json:
        print(f"    {', '.join(sorted(only_in_json)[:20])}")
        if len(only_in_json) > 20:
            print(f"    ... 等共 {len(only_in_json)} 张表")
    print(f"  仅在 Neo4j 中: {len(only_in_neo4j)}")
    if only_in_neo4j:
        print(f"    {', '.join(sorted(only_in_neo4j)[:20])}")
        if len(only_in_neo4j) > 20:
            print(f"    ... 等共 {len(only_in_neo4j)} 张表")

    # ── 边差异 ──
    print("\n--- 边对比 ---")
    only_json_edges = json_edges - neo4j_edges
    only_neo4j_edges = neo4j_edges - json_edges
    common_edges = json_edges & neo4j_edges

    print(f"  共有边: {len(common_edges)}")
    print(f"  仅在 graph.json 中: {len(only_json_edges)}")
    if only_json_edges:
        for e in sorted(only_json_edges)[:15]:
            print(f"    {e[0]} → {e[1]}")
        if len(only_json_edges) > 15:
            print(f"    ... 等共 {len(only_json_edges)} 条边")
    print(f"  仅在 Neo4j 中: {len(only_neo4j_edges)}")
    if only_neo4j_edges:
        for e in sorted(only_neo4j_edges)[:15]:
            print(f"    {e[0]} → {e[1]}")
        if len(only_neo4j_edges) > 15:
            print(f"    ... 等共 {len(only_neo4j_edges)} 条边")

    # ── 汇总 ──
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    print(f"  graph.json: {len(json_nodes)} 表, {len(json_edges)} 边")
    print(f"  Neo4j:      {len(neo4j_tables)} 表, {len(neo4j_edges)} 边")
    print(f"  新增表 (json独有): {len(only_in_json)}")
    print(f"  删除表 (neo4j独有): {len(only_in_neo4j)}")
    print(f"  新增边 (json独有): {len(only_json_edges)}")
    print(f"  删除边 (neo4j独有): {len(only_neo4j_edges)}")


if __name__ == "__main__":
    main()
