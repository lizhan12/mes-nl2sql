"""
解析 mes数据库.txt (PostgreSQL DDL)，生成 Neo4j 知识图谱 JSON。
输出 graph.json 包含：
- nodes: 每个表作为一个节点，附带表注释和列信息
- edges: 基于列名推断的表间关联关系
"""

import json
import re
from collections import defaultdict
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────
DDL_FILE = Path(__file__).parent.parent / "tests" / "mes数据库.txt"
OUTPUT_FILE = Path(__file__).parent.parent / "tests" / "graph.json"


def parse_ddl(filepath: Path) -> list[dict]:
    """解析 DDL 文件，返回表信息列表。"""
    text = filepath.read_text(encoding="utf-8")

    tables = []

    # 匹配每个 CREATE TABLE ... ( ... );
    # 使用正则提取表名和列定义块
    create_pattern = re.compile(
        r"CREATE TABLE public\.(\w+)\s*\((.*?)\);",
        re.DOTALL | re.IGNORECASE,
    )
    for match in create_pattern.finditer(text):
        table_name = match.group(1)
        columns_block = match.group(2)

        # 解析列定义
        columns = []
        # 按行分割，处理列定义
        lines = columns_block.split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("CONSTRAINT") or line.startswith("--"):
                continue
            # 匹配列名和注释
            # 格式: col_name type ... -- comment
            col_match = re.match(r'"?(\w+)"?\s+', line)
            if col_match:
                col_name = col_match.group(1)
                comment = ""
                comment_match = re.search(r"--\s*(.*)", line)
                if comment_match:
                    comment = comment_match.group(1).strip()
                columns.append({"name": col_name, "comment": comment})

        # 查找表注释
        table_comment = ""
        comment_pattern = re.compile(
            rf"COMMENT ON TABLE public\.{re.escape(table_name)}\s+IS\s+'([^']*)';",
            re.IGNORECASE,
        )
        comment_match = comment_pattern.search(text)
        if comment_match:
            table_comment = comment_match.group(1)

        tables.append(
            {
                "name": table_name,
                "comment": table_comment,
                "columns": columns,
            }
        )

    return tables


def infer_relationships(tables: list[dict]) -> list[dict]:
    """根据列名推断表间关联关系。"""
    table_names = {t["name"] for t in tables}
    relationships = []

    # 建立列名到表的快速索引
    # 例如 column "part_id" 可能关联到 "t_bd_part"
    # 去掉 t_ 前缀做匹配
    name_to_table = {}
    for t in tables:
        # 去掉 t_ 前缀的短名
        short = t["name"]
        for prefix in [
            "t_basic_",
            "t_bd_",
            "t_bc_",
            "t_pd_",
            "t_ems_",
            "t_qm_",
            "t_wms_",
            "t_lb_",
            "t_msd_",
            "t_print_",
            "t_packing_",
            "t_tool_",
            "t_rma_",
            "t_ht_",
            "t_dev_",
            "t_solder_",
            "t_rollback_",
            "t_demo_",
        ]:
            if short.startswith(prefix):
                short = short[len(prefix) :]
                break
        else:
            if short.startswith("t_"):
                short = short[2:]
        name_to_table[short] = t["name"]

    # 也建立完整表名的映射
    for t in tables:
        name_to_table[t["name"]] = t["name"]

    for table in tables:
        table_name = table["name"]
        for col in table["columns"]:
            col_name = col["name"]

            # 跳过通用字段
            if col_name in (
                "id",
                "create_user",
                "create_time",
                "update_user",
                "update_time",
                "create_user_id",
                "update_user_id",
                "is_enabled",
                "remark",
                "current_status",
            ):
                continue

            # 匹配 _id 结尾的列（外键）
            if col_name.endswith("_id"):
                # 去掉 _id 后缀
                ref_key = col_name[:-3]  # e.g. "part_id" -> "part"

                # 尝试匹配目标表
                target_table = None
                if ref_key in name_to_table:
                    target_table = name_to_table[ref_key]

                if target_table and target_table != table_name:
                    # 去重检查
                    dup = any(
                        r["from"] == table_name and r["to"] == target_table and r["column"] == col_name
                        for r in relationships
                    )
                    if not dup:
                        relationships.append(
                            {
                                "from": table_name,
                                "to": target_table,
                                "column": col_name,
                                "comment": col.get("comment", ""),
                            }
                        )

    return relationships


def build_graph(tables: list[dict], relationships: list[dict]) -> dict:
    """构建 Neo4j 兼容的图 JSON 结构。"""
    nodes = []
    for t in tables:
        nodes.append(
            {
                "id": t["name"],
                "labels": ["Table"],
                "properties": {
                    "name": t["name"],
                    "comment": t["comment"],
                    "column_count": len(t["columns"]),
                    "columns": json.dumps(t["columns"], ensure_ascii=False),
                },
            }
        )

    edges = []
    for i, rel in enumerate(relationships):
        edges.append(
            {
                "id": f"rel_{i}",
                "type": "REFERENCES",
                "startNode": rel["from"],
                "endNode": rel["to"],
                "properties": {
                    "column": rel["column"],
                    "comment": rel["comment"],
                },
            }
        )

    return {"nodes": nodes, "edges": edges}


def main():
    print(f"解析 DDL 文件: {DDL_FILE}")
    tables = parse_ddl(DDL_FILE)
    print(f"  发现 {len(tables)} 张表")

    print("推断表间关联关系...")
    relationships = infer_relationships(tables)
    print(f"  推断出 {len(relationships)} 条关联关系")

    print("构建图结构...")
    graph = build_graph(tables, relationships)

    print(f"写入: {OUTPUT_FILE}")
    OUTPUT_FILE.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 统计
    print("\n=== 统计 ===")
    print(f"节点数 (表): {len(graph['nodes'])}")
    print(f"边数 (关联): {len(graph['edges'])}")

    # 显示关联最多的 top 10 表
    rel_count = defaultdict(int)
    for e in graph["edges"]:
        rel_count[e["startNode"]] += 1
    top_tables = sorted(rel_count.items(), key=lambda x: -x[1])[:10]
    print("\n关联最多的表 (Top 10):")
    for name, count in top_tables:
        table_info = next((t for t in tables if t["name"] == name), None)
        comment = table_info["comment"] if table_info else ""
        print(f"  {name}: {count} 条关联  [{comment}]")

    print("\n完成!")


if __name__ == "__main__":
    main()
