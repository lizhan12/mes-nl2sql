"""将 graph.json 与 Neo4j 中现有手工边合并后，全量导入 Neo4j。

步骤:
  1. 读取 tests/graph.json（284 表, 228 边）→ 转换为 {table: [edges]} 格式
  2. 从 Neo4j 导出仅 Neo4j 独有的边（37 条手工边）
  3. 合并二者的边
  4. 调用 replace_all_graph 全量写入 Neo4j
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from neo4j import GraphDatabase

from src.core.config import settings
from src.services.neo4j_graph import count_graph, replace_all_graph


def load_graph_json() -> tuple[dict[str, list[dict]], set[str]]:
    """加载 graph.json，返回 (边dict, 所有表名含独立表)。"""
    json_path = Path(__file__).parent.parent / "tests" / "graph.json"
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    # 收集所有表名
    all_tables = {node["id"] for node in data["nodes"]}

    graph: dict[str, list[dict]] = {}
    for e in data["edges"]:
        from_tbl = e["startNode"]
        to_tbl = e["endNode"]
        col = e["properties"]["column"]
        col_comment = e["properties"]["comment"]

        edge = {
            "to": to_tbl,
            "from_field": col,
            "to_field": "id",
            "join": f"{from_tbl}.{col} = {to_tbl}.id",
            "join_type": "JOIN",
            "desc": f"{from_tbl}.{col} → {to_tbl}.id",
            "confidence": "medium",
            "note": f"自动推断: {col_comment}" if col_comment else "自动推断",
        }
        graph.setdefault(from_tbl, []).append(edge)

        rev_edge = {
            "to": from_tbl,
            "from_field": "id",
            "to_field": col,
            "join": f"{to_tbl}.id = {from_tbl}.{col}",
            "join_type": "JOIN",
            "desc": f"{from_tbl}.{col} → {to_tbl}.id(反向)",
            "confidence": "medium",
            "note": f"自动推断: {col_comment}" if col_comment else "自动推断",
        }
        graph.setdefault(to_tbl, []).append(rev_edge)

    return graph, all_tables


def export_neo4j_only_edges(graph_json_edges: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """从 Neo4j 导出仅在 Neo4j 中存在、不在 graph.json 中的边。"""
    # 构建 graph.json 边的 pair 集合
    json_pairs = set()
    for from_tbl, edges in graph_json_edges.items():
        for e in edges:
            if "(反向)" not in e.get("desc", ""):
                json_pairs.add((from_tbl, e["to"]))

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    driver.verify_connectivity()

    neo4j_graph: dict[str, list[dict]] = {}
    with driver.session() as session:
        result = session.run("""
            MATCH (a:Table)-[r:JOIN_REL]->(b:Table)
            RETURN a.name AS from_table, b.name AS to_table,
                   r.from_field AS from_field, r.to_field AS to_field,
                   r.join_condition AS join_condition,
                   r.join_type AS join_type, r.description AS description,
                   r.confidence AS confidence, r.note AS note
        """)
        for rec in result:
            ft = rec["from_table"]
            tt = rec["to_table"]
            pair = (ft, tt)

            if pair in json_pairs:
                continue  # 跳过已在 graph.json 中的边

            edge = {
                "to": tt,
                "from_field": rec["from_field"] or "",
                "to_field": rec["to_field"] or "",
                "join": rec["join_condition"] or f"{ft}.{rec['from_field']} = {tt}.{rec['to_field']}",
                "join_type": rec["join_type"] or "JOIN",
                "desc": rec["description"] or f"手工维护: {ft} → {tt}",
                "confidence": rec["confidence"] or "high",
                "note": rec["note"] or "从 Neo4j 保留的手工边",
            }
            neo4j_graph.setdefault(ft, []).append(edge)

            # 反向边
            rev_edge = {
                "to": ft,
                "from_field": edge["to_field"],
                "to_field": edge["from_field"],
                "join": f"{tt}.{edge['to_field']} = {ft}.{edge['from_field']}",
                "join_type": edge["join_type"],
                "desc": f"{edge['desc']}(反向)",
                "confidence": edge["confidence"],
                "note": edge["note"],
            }
            neo4j_graph.setdefault(tt, []).append(rev_edge)

        print(
            f"从 Neo4j 导出独有边: {len([e for edges in neo4j_graph.values() for e in edges if '(反向)' not in e.get('desc', '')])} 条"
        )

    driver.close()
    return neo4j_graph


def merge_graphs(json_graph: dict, neo4j_graph: dict) -> dict[str, list[dict]]:
    """合并两个图：neo4j 手工边追加到 json 图中（去重）。"""
    merged: dict[str, list[dict]] = {k: list(v) for k, v in json_graph.items()}

    for from_tbl, edges in neo4j_graph.items():
        existing_edges = merged.get(from_tbl, [])
        for e in edges:
            # 检查是否已存在相同 from→to 的边
            if "(反向)" in e.get("desc", ""):
                continue  # 跳过反向边，让 replace_all_graph 自己处理
            dup = any(
                existing["to"] == e["to"] for existing in existing_edges if "(反向)" not in existing.get("desc", "")
            )
            if not dup:
                merged.setdefault(from_tbl, []).append(e)

    return merged


def main():
    print("=" * 60)
    print("Step 1: 加载 graph.json")
    print("=" * 60)
    json_graph, standalone_tables = load_graph_json()
    json_forward_edges = sum(1 for edges in json_graph.values() for e in edges if "(反向)" not in e.get("desc", ""))
    print(f"  graph.json: {len(standalone_tables)} 表, {json_forward_edges} 正向边")
    print(f"    有关系的表: {len(json_graph)}, 独立表: {len(standalone_tables) - len(json_graph)}")

    print("\n" + "=" * 60)
    print("Step 2: 从 Neo4j 导出独有手工边")
    print("=" * 60)
    neo4j_graph = export_neo4j_only_edges(json_graph)
    neo4j_forward_edges = sum(1 for edges in neo4j_graph.values() for e in edges if "(反向)" not in e.get("desc", ""))
    print(f"  Neo4j 补: {neo4j_forward_edges} 正向边")

    print("\n" + "=" * 60)
    print("Step 3: 合并图数据 + 补入独立表")
    print("=" * 60)
    merged_graph = merge_graphs(json_graph, neo4j_graph)
    # 将独立表（无边的表）也加入，确保在 Neo4j 中创建节点
    for tbl in standalone_tables:
        if tbl not in merged_graph:
            merged_graph[tbl] = []

    merged_forward_edges = sum(1 for edges in merged_graph.values() for e in edges if "(反向)" not in e.get("desc", ""))
    print(f"  合并后: {len(merged_graph)} 表 (含独立表), {merged_forward_edges} 正向边")

    print("\n" + "=" * 60)
    print("Step 4: 全量写入 Neo4j")
    print("=" * 60)
    try:
        imported = replace_all_graph(merged_graph)
        print(f"  写入成功: {imported} 条边")

        neo_nodes, neo_edges = count_graph()
        print(f"  Neo4j 验证: {neo_nodes} 节点, {neo_edges} 边")

        print("\n" + "=" * 60)
        print("导入完成!")
        print(f"  节点: {neo_nodes}")
        print(f"  边:   {neo_edges}")
        print("=" * 60)
    except Exception as e:
        print(f"导入失败: {e}")
        raise


if __name__ == "__main__":
    main()
