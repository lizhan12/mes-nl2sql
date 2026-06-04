"""关系图 PG 持久化仓储。

提供表关系图的 CRUD 操作，支持版本号管理用于缓存失效。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from src.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class GraphEdge:
    """关系边数据对象。"""

    id: int | None = None
    from_table: str = ""
    to_table: str = ""
    from_field: str = ""
    to_field: str = ""
    join_condition: str = ""
    join_type: str = "JOIN"
    description: str = ""
    confidence: str = "high"
    note: str = ""


class GraphRepository:
    """关系图 PG 仓储。"""

    def __init__(self, db_url: str = "") -> None:
        self.db_url = (db_url or settings.app_database_url).replace("+asyncpg", "")

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.db_url, row_factory=dict_row)

    # ── DDL ────────────────────────────────────────────────────────

    def ensure_tables(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS graph_edges (
            id BIGSERIAL PRIMARY KEY,
            from_table TEXT NOT NULL,
            to_table TEXT NOT NULL,
            from_field TEXT NOT NULL,
            to_field TEXT NOT NULL,
            join_condition TEXT NOT NULL,
            join_type TEXT NOT NULL DEFAULT 'JOIN',
            description TEXT NOT NULL DEFAULT '',
            confidence TEXT NOT NULL DEFAULT 'high',
            note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_graph_edges_from
            ON graph_edges (from_table);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_to
            ON graph_edges (to_table);

        CREATE TABLE IF NOT EXISTS graph_version (
            id INTEGER PRIMARY KEY DEFAULT 1,
            version INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- 确保有一条版本记录
        INSERT INTO graph_version (id, version)
        VALUES (1, 1)
        ON CONFLICT (id) DO NOTHING;
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(ddl)
            conn.commit()
        logger.info("graph_edges / graph_version 表初始化完成")

    # ── 版本管理 ───────────────────────────────────────────────────

    def get_version(self) -> int:
        """获取当前图版本号。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT version FROM graph_version WHERE id = 1")
            row = cur.fetchone()
            return row["version"] if row else 1

    def bump_version(self) -> int:
        """递增版本号（每次写操作后调用），返回新版本号。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE graph_version SET version = version + 1, updated_at = NOW() WHERE id = 1 RETURNING version"
            )
            row = cur.fetchone()
            conn.commit()
            new_version = row["version"] if row else 1
            logger.info("图版本已更新: %d", new_version)
            return new_version

    # ── 读取完整图 ─────────────────────────────────────────────────

    def load_full_graph(self) -> dict[str, list[dict]]:
        """从 PG 加载完整图，返回与 JSON 格式兼容的 dict。

        Returns:
            {table_name: [{"to": ..., "from_field": ..., ...}, ...]}
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM graph_edges ORDER BY from_table, id")
            rows = cur.fetchall()

        graph: dict[str, list[dict]] = {}
        for row in rows:
            from_table = row["from_table"]
            if from_table not in graph:
                graph[from_table] = []
            graph[from_table].append(self._row_to_edge_dict(row))

        return graph

    # ── 全量替换（用于同步）────────────────────────────────────────

    def replace_all(self, graph: dict[str, list[dict]]) -> int:
        """清空现有边并全量导入新数据，返回导入的边数量。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM graph_edges")
            count = 0
            for from_table, edges in graph.items():
                for edge in edges:
                    cur.execute(
                        """
                        INSERT INTO graph_edges
                            (from_table, to_table, from_field, to_field, join_condition,
                             join_type, description, confidence, note)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            from_table,
                            edge.get("to", ""),
                            edge.get("from_field", ""),
                            edge.get("to_field", ""),
                            edge.get("join", ""),
                            edge.get("join_type", "JOIN"),
                            edge.get("desc", ""),
                            edge.get("confidence", "high"),
                            edge.get("note", ""),
                        ),
                    )
                    count += 1
            conn.commit()
        self.bump_version()
        logger.info("全量同步完成，共导入 %d 条边", count)
        return count

    # ── 边 CRUD ────────────────────────────────────────────────────

    def add_edge(self, edge: GraphEdge) -> int:
        """添加一条关系边，返回新边的 ID。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO graph_edges
                    (from_table, to_table, from_field, to_field, join_condition,
                     join_type, description, confidence, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    edge.from_table,
                    edge.to_table,
                    edge.from_field,
                    edge.to_field,
                    edge.join_condition,
                    edge.join_type,
                    edge.description,
                    edge.confidence,
                    edge.note,
                ),
            )
            row = cur.fetchone()
            conn.commit()
        edge_id = row["id"] if row else 0
        self.bump_version()
        return edge_id

    def update_edge(self, edge_id: int, edge: GraphEdge) -> bool:
        """更新一条关系边。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE graph_edges SET
                    from_table = %s, to_table = %s, from_field = %s, to_field = %s,
                    join_condition = %s, join_type = %s, description = %s,
                    confidence = %s, note = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (
                    edge.from_table,
                    edge.to_table,
                    edge.from_field,
                    edge.to_field,
                    edge.join_condition,
                    edge.join_type,
                    edge.description,
                    edge.confidence,
                    edge.note,
                    edge_id,
                ),
            )
            conn.commit()
        self.bump_version()
        return cur.rowcount > 0

    def delete_edge(self, edge_id: int) -> bool:
        """删除一条关系边。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM graph_edges WHERE id = %s", (edge_id,))
            conn.commit()
        self.bump_version()
        return cur.rowcount > 0

    def get_edge(self, edge_id: int) -> dict | None:
        """获取单条边详情。"""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM graph_edges WHERE id = %s", (edge_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_edges(self, from_table: str = "", confidence: str = "", limit: int = 500) -> list[dict]:
        """列表查询边。"""
        conditions = []
        params: list = []
        if from_table:
            conditions.append("(from_table = %s OR to_table = %s)")
            params.extend([from_table, from_table])
        if confidence:
            conditions.append("confidence = %s")
            params.append(confidence)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM graph_edges {where} ORDER BY id LIMIT %s"
        params.append(limit)

        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    # ── 工具 ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_edge_dict(row: dict) -> dict:
        """将 PG 行转为 BFS 服务兼容的 JSON 边格式。"""
        return {
            "to": row["to_table"],
            "from_field": row["from_field"],
            "to_field": row["to_field"],
            "join": row["join_condition"],
            "join_type": row["join_type"],
            "desc": row["description"],
            "confidence": row["confidence"],
            "note": row["note"],
        }

    @staticmethod
    def _edge_dict_to_graph_edge(from_table: str, edge_dict: dict) -> GraphEdge:
        """将 JSON 边格式转为 GraphEdge 对象。"""
        return GraphEdge(
            from_table=from_table,
            to_table=edge_dict.get("to", ""),
            from_field=edge_dict.get("from_field", ""),
            to_field=edge_dict.get("to_field", ""),
            join_condition=edge_dict.get("join", ""),
            join_type=edge_dict.get("join_type", "JOIN"),
            description=edge_dict.get("desc", ""),
            confidence=edge_dict.get("confidence", "high"),
            note=edge_dict.get("note", ""),
        )


# 全局单例
_graph_repo: GraphRepository | None = None


def get_graph_repository() -> GraphRepository:
    global _graph_repo
    if _graph_repo is None:
        _graph_repo = GraphRepository()
    return _graph_repo
