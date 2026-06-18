"""Neo4j 图数据库服务，用于表关系图的持久化与加载。

职责：
  - Neo4j 连接管理（单例异步驱动）
  - 图数据加载（Neo4j → 内存 dict，与 bfs.py 格式兼容）
  - 图数据写入（全量替换 / 单边 CRUD）
"""

from __future__ import annotations

import asyncio
import json
import logging

from neo4j import AsyncGraphDatabase
from neo4j._async.driver import AsyncDriver

from src.core.config import settings

logger = logging.getLogger(__name__)

_DOMAIN_PREFIX_MAP: dict[str, str] = {
    "t_pd_": "production",
    "t_qm_": "quality",
    "t_wms_": "warehouse",
    "t_ems_": "equipment",
    "t_bd_": "master",
    "t_bc_": "barcode",
}

_driver: AsyncDriver | None = None
_driver_lock = asyncio.Lock()


async def _get_driver() -> AsyncDriver:
    """获取 Neo4j 异步驱动单例，首次调用时验证连接。"""
    global _driver
    if _driver is not None:
        return _driver
    async with _driver_lock:
        if _driver is not None:
            return _driver
        _driver = AsyncGraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        await _driver.verify_connectivity()
        logger.info("Neo4j 连接成功: %s", settings.neo4j_uri)
        return _driver


def _derive_domain(table_name: str) -> str:
    """根据表名前缀推导业务域。"""
    for prefix, domain in _DOMAIN_PREFIX_MAP.items():
        if table_name.startswith(prefix):
            return domain
    return "other"


def _derive_prefix(table_name: str) -> str:
    """提取表名前缀。"""
    for prefix in _DOMAIN_PREFIX_MAP:
        if table_name.startswith(prefix):
            return prefix
    return ""


# ── 图数据加载 ──────────────────────────────────────────────────────


async def load_graph_from_neo4j() -> dict[str, list[dict]]:
    """从 Neo4j 加载完整表关系图，返回与 JSON/PG 格式完全兼容的 dict。

    Neo4j 中只存单向边，加载时自动构建双向 dict（正向 + 反向标记），
    确保 bfs.py 中所有 BFS 算法无需任何改动。

    Returns:
        {table_name: [{"to":..., "from_field":..., "to_field":..., "join":...,
                        "join_type":..., "desc":..., "confidence":..., "note":...}, ...]}
    """
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run("""
            MATCH (a:Table)-[r:JOIN_REL]->(b:Table)
            RETURN a.name AS from_table, b.name AS to_table,
                   r.from_field AS from_field, r.to_field AS to_field,
                   r.join_condition AS join_condition,
                   r.join_type AS join_type, r.description AS description,
                   r.confidence AS confidence, r.note AS note
        """)
        records = [rec async for rec in result]

    graph: dict[str, list[dict]] = {}
    for rec in records:
        ft = _safe_str(rec["from_table"])
        tt = _safe_str(rec["to_table"])
        edge = {
            "to": tt,
            "from_field": _safe_str(rec["from_field"]),
            "to_field": _safe_str(rec["to_field"]),
            "join": _safe_str(rec["join_condition"]),
            "join_type": _safe_str(rec["join_type"], "JOIN"),
            "desc": _safe_str(rec["description"]),
            "confidence": _safe_str(rec["confidence"], "high"),
            "note": _safe_str(rec["note"]),
        }
        # 正向边
        graph.setdefault(ft, []).append(edge)
        # 反向边（保持与 JSON 双向格式兼容）
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
        graph.setdefault(tt, []).append(rev_edge)

    logger.info("从 Neo4j 加载关系图完成，表: %d", len(graph))
    return graph


# ── 图数据写入 ──────────────────────────────────────────────────────


async def replace_all_graph(graph: dict[str, list[dict]]) -> int:
    """清空 Neo4j 中的图数据并全量导入新数据。

    只创建正向边（跳过 desc 含"(反向)"的边），避免双向冗余存储。

    Args:
        graph: 与 JSON 格式兼容的图 dict

    Returns:
        导入的边数量
    """
    driver = await _get_driver()

    # 收集所有唯一表名
    all_table_names: set[str] = set(graph.keys())
    for edges in graph.values():
        for e in edges:
            all_table_names.add(e["to"])

    async with driver.session() as session:
        # 建立唯一约束
        await session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (t:Table) REQUIRE t.name IS UNIQUE")

        # 清空现有数据
        await session.run("MATCH (n:Table) DETACH DELETE n")

        # 批量创建节点
        node_params = [
            {"name": t, "domain": _derive_domain(t), "prefix": _derive_prefix(t)} for t in sorted(all_table_names)
        ]
        await session.run(
            "UNWIND $nodes AS n MERGE (t:Table {name: n.name}) SET t.domain = n.domain, t.prefix = n.prefix",
            {"nodes": node_params},
        )
        logger.info("Neo4j 已创建 %d 个 Table 节点", len(all_table_names))

        # 创建边（只创建正向边，跳过反向标记）
        edge_count = 0
        for from_table, edges in graph.items():
            for e in edges:
                desc = e.get("desc", "")
                if "(反向)" in desc:
                    continue  # 跳过反向边
                # 全量替换场景已 DETACH DELETE 所有节点，使用 CREATE 避免同表对多条 JOIN 被 MERGE 去重
                await session.run(
                    """
                    MATCH (a:Table {name: $from_table})
                    MATCH (b:Table {name: $to_table})
                    CREATE (a)-[r:JOIN_REL]->(b)
                    SET r.from_field = $from_field,
                        r.to_field = $to_field,
                        r.join_condition = $join,
                        r.join_type = $join_type,
                        r.description = $desc,
                        r.confidence = $confidence,
                        r.note = $note
                    """,
                    {
                        "from_table": from_table,
                        "to_table": e["to"],
                        "from_field": e.get("from_field", ""),
                        "to_field": e.get("to_field", ""),
                        "join": e.get("join", ""),
                        "join_type": e.get("join_type", "JOIN"),
                        "desc": desc,
                        "confidence": e.get("confidence", "high"),
                        "note": e.get("note", ""),
                    },
                )
                edge_count += 1

    logger.info("Neo4j 全量替换完成，节点: %d，边: %d（单向）", len(all_table_names), edge_count)
    return edge_count


async def add_edge(from_table: str, to_table: str, edge: dict) -> None:
    """添加一条 JOIN_REL 边。"""
    driver = await _get_driver()
    async with driver.session() as session:
        await session.run("MERGE (t:Table {name: $name})", {"name": from_table})
        await session.run("MERGE (t:Table {name: $name})", {"name": to_table})
        await session.run(
            """
            MATCH (a:Table {name: $from}), (b:Table {name: $to})
            MERGE (a)-[r:JOIN_REL]->(b)
            SET r.from_field = $from_field, r.to_field = $to_field,
                r.join_condition = $join, r.join_type = $join_type,
                r.description = $desc, r.confidence = $confidence,
                r.note = $note
            """,
            {
                "from": from_table,
                "to": to_table,
                "from_field": edge.get("from_field", ""),
                "to_field": edge.get("to_field", ""),
                "join": edge.get("join", ""),
                "join_type": edge.get("join_type", "JOIN"),
                "desc": edge.get("desc", ""),
                "confidence": edge.get("confidence", "high"),
                "note": edge.get("note", ""),
            },
        )
    logger.info("Neo4j 添加边: %s → %s", from_table, to_table)


async def delete_edge(from_table: str, to_table: str) -> None:
    """删除一条 JOIN_REL 边（同时删除正向和可能存在的反向边）。"""
    driver = await _get_driver()
    async with driver.session() as session:
        await session.run(
            """
            MATCH (a:Table {name: $from})-[r:JOIN_REL]-(b:Table {name: $to})
            DELETE r
            """,
            {"from": from_table, "to": to_table},
        )
    logger.info("Neo4j 删除边: %s ↔ %s", from_table, to_table)


async def update_edge(from_table: str, to_table: str, edge: dict) -> bool:
    """更新一条 JOIN_REL 边的属性。

    Args:
        from_table: 源表名
        to_table: 目标表名
        edge: 新的边属性 dict

    Returns:
        是否找到并更新了边
    """
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (a:Table {name: $from})-[r:JOIN_REL]->(b:Table {name: $to})
            SET r.from_field = $from_field, r.to_field = $to_field,
                r.join_condition = $join, r.join_type = $join_type,
                r.description = $desc, r.confidence = $confidence,
                r.note = $note
            RETURN count(r) AS updated
            """,
            {
                "from": from_table,
                "to": to_table,
                "from_field": edge.get("from_field", ""),
                "to_field": edge.get("to_field", ""),
                "join": edge.get("join", ""),
                "join_type": edge.get("join_type", "JOIN"),
                "desc": edge.get("desc", ""),
                "confidence": edge.get("confidence", "high"),
                "note": edge.get("note", ""),
            },
        )
        updated = (await result.single())["updated"]
    if updated:
        logger.info("Neo4j 更新边: %s → %s", from_table, to_table)
    return updated > 0


async def get_edge(from_table: str, to_table: str) -> dict | None:
    """获取单条 JOIN_REL 边的详情。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (a:Table {name: $from})-[r:JOIN_REL]->(b:Table {name: $to})
            RETURN a.name AS from_table, b.name AS to_table,
                   r.from_field AS from_field, r.to_field AS to_field,
                   r.join_condition AS join_condition,
                   r.join_type AS join_type, r.description AS description,
                   r.confidence AS confidence, r.note AS note
            """,
            {"from": from_table, "to": to_table},
        )
        rec = await result.single()
        if not rec:
            return None
        return {
            "from_table": rec["from_table"],
            "to_table": rec["to_table"],
            "from_field": _safe_str(rec["from_field"]),
            "to_field": _safe_str(rec["to_field"]),
            "join_condition": _safe_str(rec["join_condition"]),
            "join_type": _safe_str(rec["join_type"], "JOIN"),
            "description": _safe_str(rec["description"]),
            "confidence": _safe_str(rec["confidence"], "high"),
            "note": _safe_str(rec["note"]),
        }


async def list_edges(from_table: str = "", confidence: str = "", limit: int = 500) -> list[dict]:
    """列表查询 JOIN_REL 边。"""
    driver = await _get_driver()
    conditions = []
    params: dict = {"limit": limit}
    if from_table:
        conditions.append("(a.name = $from_table OR b.name = $from_table)")
        params["from_table"] = from_table
    if confidence:
        conditions.append("r.confidence = $confidence")
        params["confidence"] = confidence

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"""
        MATCH (a:Table)-[r:JOIN_REL]->(b:Table)
        {where}
        RETURN a.name AS from_table, b.name AS to_table,
               r.from_field AS from_field, r.to_field AS to_field,
               r.join_condition AS join_condition,
               r.join_type AS join_type, r.description AS description,
               r.confidence AS confidence, r.note AS note
        ORDER BY a.name
        LIMIT $limit
    """

    async with driver.session() as session:
        result = await session.run(query, params)
        return [
            {
                "from_table": rec["from_table"],
                "to_table": rec["to_table"],
                "from_field": _safe_str(rec["from_field"]),
                "to_field": _safe_str(rec["to_field"]),
                "join_condition": _safe_str(rec["join_condition"]),
                "join_type": _safe_str(rec["join_type"], "JOIN"),
                "description": _safe_str(rec["description"]),
                "confidence": _safe_str(rec["confidence"], "high"),
                "note": _safe_str(rec["note"]),
            }
            async for rec in result
        ]


async def get_graph_version() -> int:
    """获取图版本号（用边数模拟）。"""
    _, edges = await count_graph()
    return edges


async def count_graph() -> tuple[int, int]:
    """查询 Neo4j 中的节点数和边数，用于验证。"""
    driver = await _get_driver()
    async with driver.session() as session:
        r1 = await session.run("MATCH (n:Table) RETURN count(n) AS c")
        node_count = (await r1.single())["c"]
        r2 = await session.run("MATCH ()-[r:JOIN_REL]->() RETURN count(r) AS c")
        edge_count = (await r2.single())["c"]
    return node_count, edge_count


# ── 向量索引 ────────────────────────────────────────────────────────

_VECTOR_DIMENSIONS = 1024  # bge-large-zh-v1.5


async def ensure_vector_indexes() -> None:
    """确保 Neo4j 中存在所需的向量索引（schema + few_shot + evolved_few_shot + runtime_rule）。"""
    driver = await _get_driver()
    async with driver.session() as session:
        try:
            await session.run(
                """
                CREATE VECTOR INDEX schema_embedding_idx IF NOT EXISTS
                FOR (t:Table) ON (t.schema_embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: $dim,
                    `vector.similarity_function`: 'cosine'
                }}
                """,
                {"dim": _VECTOR_DIMENSIONS},
            )
            logger.info("向量索引 schema_embedding_idx 已就绪")
        except Exception as e:
            logger.warning("创建 schema_embedding_idx 失败: %s", e)

        try:
            await session.run(
                """
                CREATE VECTOR INDEX few_shot_embedding_idx IF NOT EXISTS
                FOR (f:FewShot) ON (f.question_embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: $dim,
                    `vector.similarity_function`: 'cosine'
                }}
                """,
                {"dim": _VECTOR_DIMENSIONS},
            )
            logger.info("向量索引 few_shot_embedding_idx 已就绪")
        except Exception as e:
            logger.warning("创建 few_shot_embedding_idx 失败: %s", e)

        try:
            await session.run(
                """
                CREATE VECTOR INDEX evolved_few_shot_embedding_idx IF NOT EXISTS
                FOR (f:EvolvedFewShot) ON (f.question_embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: $dim,
                    `vector.similarity_function`: 'cosine'
                }}
                """,
                {"dim": _VECTOR_DIMENSIONS},
            )
            logger.info("向量索引 evolved_few_shot_embedding_idx 已就绪")
        except Exception as e:
            logger.warning("创建 evolved_few_shot_embedding_idx 失败: %s", e)

        try:
            await session.run(
                """
                CREATE VECTOR INDEX runtime_rule_embedding_idx IF NOT EXISTS
                FOR (r:RuntimeRule) ON (r.question_embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: $dim,
                    `vector.similarity_function`: 'cosine'
                }}
                """,
                {"dim": _VECTOR_DIMENSIONS},
            )
            logger.info("向量索引 runtime_rule_embedding_idx 已就绪")
        except Exception as e:
            logger.warning("创建 runtime_rule_embedding_idx 失败: %s", e)


# ── 向量数据写入 ────────────────────────────────────────────────────


async def batch_set_schema_embeddings(items: list[dict]) -> int:
    """批量设置 Table 节点的 schema_embedding 及相关属性。

    Args:
        items: [{"name": table_name, "embedding": list[float], "full_text": str,
                  "module": str, "business_meaning": str}, ...]

    Returns:
        更新的节点数
    """
    if not items:
        return 0
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            UNWIND $batch AS item
            MATCH (t:Table {name: item.name})
            SET t.schema_embedding = item.embedding,
                t.full_text = item.full_text,
                t.module = item.module,
                t.business_meaning = item.business_meaning
            RETURN count(t) AS updated
            """,
            {"batch": items},
        )
        count = (await result.single())["updated"]
    logger.info("批量写入 %d 个 Table 节点的 schema_embedding", count)
    return count


async def batch_set_few_shot_embeddings(items: list[dict]) -> int:
    """批量创建/更新 FewShot 节点及其 question_embedding。

    Args:
        items: [{"id": str, "embedding": list[float], "scenario": str,
                  "question": str, "full_text": str}, ...]

    Returns:
        创建/更新的节点数
    """
    if not items:
        return 0
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            UNWIND $batch AS item
            MERGE (f:FewShot {id: item.id})
            SET f.question_embedding = item.embedding,
                f.scenario = item.scenario,
                f.question = item.question,
                f.full_text = item.full_text
            RETURN count(f) AS updated
            """,
            {"batch": items},
        )
        count = (await result.single())["updated"]
    logger.info("批量写入 %d 个 FewShot 节点的 question_embedding", count)
    return count


async def clear_few_shot_nodes() -> int:
    """删除所有 FewShot 节点。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (f:FewShot) DETACH DELETE f RETURN count(f) AS deleted")
        count = (await result.single())["deleted"]
    logger.info("已删除 %d 个 FewShot 节点", count)
    return count


# ── 向量数据检查 ────────────────────────────────────────────────────


async def schema_has_embeddings() -> bool:
    """检查 Table 节点是否已有 schema_embedding。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (t:Table) WHERE t.schema_embedding IS NOT NULL RETURN count(t) AS c")
        rec = await result.single()
        return bool(rec and rec["c"] > 0)


async def few_shot_has_embeddings() -> bool:
    """检查 FewShot 节点是否已有数据。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (f:FewShot) RETURN count(f) AS c")
        rec = await result.single()
        return bool(rec and rec["c"] > 0)


async def evolved_few_shot_has_embeddings() -> bool:
    """检查 EvolvedFewShot 节点是否已有向量数据。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:EvolvedFewShot) WHERE f.question_embedding IS NOT NULL RETURN count(f) AS c"
        )
        rec = await result.single()
        return bool(rec and rec["c"] > 0)


async def get_evolved_few_shot_without_embeddings() -> list[dict]:
    """查询缺失向量化的 EvolvedFewShot 节点。

    Returns:
        [{"id": str, "question": str, "scenario": str, "full_text": str}, ...]
    """
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:EvolvedFewShot)
            WHERE f.question_embedding IS NULL
            RETURN f.id AS id, f.question AS question,
                   f.scenario AS scenario, f.full_text AS full_text
            ORDER BY f.id
            """
        )
        return [
            {
                "id": rec["id"],
                "question": rec["question"] or "",
                "scenario": rec["scenario"] or "",
                "full_text": rec["full_text"] or "",
            }
            async for rec in result
        ]


async def batch_set_evolved_few_shot_embeddings(batch: list[dict]) -> int:
    """批量设置 EvolvedFewShot 节点的向量。

    Args:
        batch: [{"id", "embedding", "scenario", "question", "full_text"}]

    Returns:
        成功写入的记录数
    """
    driver = await _get_driver()
    total = 0
    async with driver.session() as session:
        for item in batch:
            await session.run(
                """
                MERGE (f:EvolvedFewShot {id: $id})
                SET f.question_embedding = $embedding,
                    f.scenario = $scenario,
                    f.question = $question,
                    f.full_text = $full_text
                """,
                {
                    "id": item["id"],
                    "embedding": item["embedding"],
                    "scenario": item.get("scenario", ""),
                    "question": item.get("question", ""),
                    "full_text": item.get("full_text", ""),
                },
            )
            total += 1
    return total


async def runtime_rule_has_embeddings() -> bool:
    """检查 RuntimeRule 节点是否已有向量数据。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (r:RuntimeRule) WHERE r.question_embedding IS NOT NULL RETURN count(r) AS c")
        rec = await result.single()
        return bool(rec and rec["c"] > 0)


async def batch_set_runtime_rule_embeddings(batch: list[dict]) -> int:
    """批量设置 RuntimeRule 节点的向量。

    Args:
        batch: [{"id", "embedding", "question", "normalized_question", ...}]

    Returns:
        成功写入的记录数
    """
    import json

    driver = await _get_driver()
    async with driver.session() as session:
        for item in batch:
            # 规范化 required_tables / required_joins：确保是 list 再序列化
            req_tables = item.get("required_tables", [])
            if isinstance(req_tables, str):
                try:
                    req_tables = json.loads(req_tables)
                    if not isinstance(req_tables, list):
                        req_tables = []
                except (json.JSONDecodeError, TypeError):
                    req_tables = []
            req_joins = item.get("required_joins", [])
            if isinstance(req_joins, str):
                try:
                    req_joins = json.loads(req_joins)
                    if not isinstance(req_joins, list):
                        req_joins = []
                except (json.JSONDecodeError, TypeError):
                    req_joins = []
            await session.run(
                """
                MERGE (r:RuntimeRule {normalized_question: $normalized_question})
                SET r.question_embedding = $embedding,
                    r.question = $question,
                    r.preferred_main_table = $preferred_main_table,
                    r.required_tables = $required_tables,
                    r.required_joins = $required_joins,
                    r.source = $source
                """,
                {
                    "normalized_question": item.get("normalized_question", ""),
                    "embedding": item["embedding"],
                    "question": item.get("question", ""),
                    "preferred_main_table": item.get("preferred_main_table", ""),
                    "required_tables": json.dumps(req_tables, ensure_ascii=False),
                    "required_joins": json.dumps(req_joins, ensure_ascii=False),
                    "source": item.get("source", ""),
                },
            )
    return len(batch)


# ── Harness 运行时知识 ─────────────────────────────────────────────


async def ensure_harness_knowledge_indexes() -> None:
    """创建 Harness 运行时知识的约束和索引。

    节点标签:
      - RuntimeRule: 运行时规则
      - EvolvedFewShot: 进化 few-shot 示例
      - KnowledgeVersion: 知识版本记录
    """
    driver = await _get_driver()
    async with driver.session() as session:
        await session.run(
            "CREATE CONSTRAINT runtime_rule_normalized_unique IF NOT EXISTS "
            "FOR (r:RuntimeRule) REQUIRE r.normalized_question IS UNIQUE"
        )
        await session.run(
            "CREATE CONSTRAINT few_shot_id_unique IF NOT EXISTS FOR (f:EvolvedFewShot) REQUIRE f.id IS UNIQUE"
        )
        await session.run(
            "CREATE CONSTRAINT knowledge_version_unique IF NOT EXISTS FOR (v:KnowledgeVersion) REQUIRE v.id IS UNIQUE"
        )
    logger.info("Harness 知识索引（RuntimeRule / EvolvedFewShot / KnowledgeVersion）已就绪")


async def publish_harness_knowledge(
    version: str,
    rules: list[dict],
    few_shot_text: str,
    source: str = "online_harness",
) -> None:
    """将运行时规则和进化 few-shot 发布到 Neo4j。

    采用全量替换策略：删除旧数据后批量写入。
    few_shot_text 按 "\\n---\\n" 分割为独立 chunk 逐条存储。

    Args:
        version: 版本号
        rules: 运行时规则列表
        few_shot_text: 进化 few-shot 文本（以 --- 分隔的 chunk）
        source: 来源标识（online_harness / candidate_publish）
    """
    from datetime import datetime

    driver = await _get_driver()
    now = datetime.now().isoformat()
    import json  # 防御性导入，避免 .pyc 缓存残留导致的 NameError

    async with driver.session() as session:
        # 1. 清空旧数据
        await session.run("MATCH (r:RuntimeRule) DETACH DELETE r")
        await session.run("MATCH (f:EvolvedFewShot) DETACH DELETE f")
        await session.run("MATCH (v:KnowledgeVersion) DETACH DELETE v")
        logger.info("已清空 Harness 知识旧数据")

        # 2. 写入运行时规则
        rule_count = 0
        for rule in rules:
            normalized_q = str(rule.get("normalized_question", "") or "")
            # 规范化 required_tables / required_joins：确保是 list 再序列化，防止双重编码
            req_tables = rule.get("required_tables", [])
            if isinstance(req_tables, str):
                try:
                    req_tables = json.loads(req_tables)
                    if not isinstance(req_tables, list):
                        req_tables = []
                except (json.JSONDecodeError, TypeError):
                    req_tables = []
            req_joins = rule.get("required_joins", [])
            if isinstance(req_joins, str):
                try:
                    req_joins = json.loads(req_joins)
                    if not isinstance(req_joins, list):
                        req_joins = []
                except (json.JSONDecodeError, TypeError):
                    req_joins = []
            await session.run(
                """
                MERGE (r:RuntimeRule {normalized_question: $normalized_q})
                SET r.question = $question,
                    r.preferred_main_table = $preferred_main_table,
                    r.required_tables = $required_tables,
                    r.required_joins = $required_joins,
                    r.source = $source,
                    r.created_at = $created_at
                """,
                {
                    "normalized_q": normalized_q,
                    "question": str(rule.get("question", "")),
                    "preferred_main_table": str(rule.get("preferred_main_table", "")),
                    "required_tables": json.dumps(req_tables, ensure_ascii=False),
                    "required_joins": json.dumps(req_joins, ensure_ascii=False),
                    "source": source,
                    "created_at": now,
                },
            )
            rule_count += 1

        # 3. 写入进化 few-shot
        few_shot_count = 0
        if few_shot_text.strip():
            chunks = [c.strip() for c in few_shot_text.split("\n---\n") if c.strip()]
            for i, chunk in enumerate(chunks):
                # 从 chunk 中提取场景和问题
                question = ""
                scenario = ""
                for line in chunk.split("\n"):
                    line = line.strip()
                    if line.startswith("场景："):
                        scenario = line[len("场景：") :].strip()
                    elif line.startswith("用户问题："):
                        question = line[len("用户问题：") :].strip()

                await session.run(
                    """
                    MERGE (f:EvolvedFewShot {id: $fid})
                    SET f.question = $question,
                        f.scenario = $scenario,
                        f.full_text = $full_text,
                        f.created_at = $created_at
                    """,
                    {
                        "fid": f"efs_{i}",
                        "question": question,
                        "scenario": scenario,
                        "full_text": chunk,
                        "created_at": now,
                    },
                )
                few_shot_count += 1

        # 4. 写入版本记录
        await session.run(
            """
            MERGE (v:KnowledgeVersion {id: 'current'})
            SET v.version = $version,
                v.source = $source,
                v.rule_count = $rule_count,
                v.few_shot_count = $few_shot_count,
                v.created_at = $created_at
            """,
            {
                "version": version,
                "source": source,
                "rule_count": rule_count,
                "few_shot_count": few_shot_count,
                "created_at": now,
            },
        )

    logger.info(
        "Harness 知识发布到 Neo4j 完成: version=%s, rules=%d, few_shot=%d",
        version,
        rule_count,
        few_shot_count,
    )


async def load_published_rules() -> list[dict]:
    """从 Neo4j 加载已发布的运行时规则。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (r:RuntimeRule)
            RETURN r.question AS question,
                   r.normalized_question AS normalized_question,
                   r.preferred_main_table AS preferred_main_table,
                   r.required_tables AS required_tables,
                   r.required_joins AS required_joins,
                   r.source AS source,
                   COALESCE(r.enabled, true) AS enabled
            """
        )
        rules: list[dict] = []
        async for rec in result:
            rule = {
                "question": rec["question"],
                "normalized_question": rec["normalized_question"],
                "preferred_main_table": rec["preferred_main_table"] or "",
                "source": rec["source"],
                "enabled": rec["enabled"] if rec["enabled"] is not None else True,
            }
            # 还原 JSON 数组（兼容双重编码）
            tables_raw = rec["required_tables"]
            if isinstance(tables_raw, str):
                try:
                    parsed = json.loads(tables_raw)
                    if isinstance(parsed, list):
                        rule["required_tables"] = parsed
                    elif isinstance(parsed, str):
                        # 双重编码：再解一层
                        parsed2 = json.loads(parsed)
                        rule["required_tables"] = parsed2 if isinstance(parsed2, list) else []
                    else:
                        rule["required_tables"] = []
                except (json.JSONDecodeError, TypeError):
                    rule["required_tables"] = []
            else:
                rule["required_tables"] = tables_raw or []

            joins_raw = rec["required_joins"]
            if isinstance(joins_raw, str):
                try:
                    parsed = json.loads(joins_raw)
                    if isinstance(parsed, list):
                        rule["required_joins"] = parsed
                    elif isinstance(parsed, str):
                        # 双重编码：再解一层
                        parsed2 = json.loads(parsed)
                        rule["required_joins"] = parsed2 if isinstance(parsed2, list) else []
                    else:
                        rule["required_joins"] = []
                except (json.JSONDecodeError, TypeError):
                    rule["required_joins"] = []
            else:
                rule["required_joins"] = joins_raw or []

            rules.append(rule)
    logger.info("从 Neo4j 加载运行时规则: %d 条", len(rules))
    return rules


async def load_published_few_shot_text() -> str:
    """从 Neo4j 加载已发布的进化 few-shot 文本（重新拼接为文本）。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:EvolvedFewShot)
            WHERE COALESCE(f.enabled, true) = true
            RETURN f.full_text AS full_text
            ORDER BY f.id
            """
        )
        chunks = [rec["full_text"] async for rec in result]
    text = "\n---\n".join(chunks) if chunks else ""
    logger.info("从 Neo4j 加载进化 few-shot: %d 条", len(chunks))
    return text


async def get_harness_knowledge_version() -> str:
    """获取当前 Harness 知识版本号。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (v:KnowledgeVersion {id: 'current'}) RETURN v.version AS version")
        rec = await result.single()
        return str(rec["version"]) if rec else ""


# ── 图数据初始化 ────────────────────────────────────────────────────


async def init_neo4j_graph() -> None:
    """初始化 Neo4j 表关系图。

    若 Neo4j 中已有 Table 节点（含 JOIN_REL 边），跳过初始化。
    若 neo4j_graph_auto_init 为 False，即使 Neo4j 为空也不从 JSON 重建。
    否则从本地 JSON 加载图数据并全量导入 Neo4j。
    """
    node_count, edge_count = await count_graph()
    if node_count > 0:
        logger.info("Neo4j 关系图已有数据（%d 节点, %d 边），跳过初始化", node_count, edge_count)
        return

    if not settings.neo4j_graph_auto_init:
        logger.warning("Neo4j 关系图为空，但 neo4j_graph_auto_init=False，跳过自动初始化（防止覆盖线上精简知识库）")
        return

    logger.info("Neo4j 关系图为空，开始初始化...")

    graph: dict[str, list[dict]] = {}

    # 从本地 JSON 加载（PG graph_edges 已废弃，不再维护）
    import json
    from pathlib import Path

    graph_path = Path(__file__).parent.parent.parent / "data" / "mes_relation_graph.json"
    if graph_path.exists():
        with open(graph_path, encoding="utf-8") as f:
            data = json.load(f)
        graph = data["graph"] if isinstance(data, dict) and "graph" in data else data
        logger.info("从 JSON 文件加载关系图，%d 个表", len(graph))
    else:
        logger.warning("关系图 JSON 文件不存在: %s", graph_path)
        return

    if not graph:
        logger.warning("无关系图数据可导入 Neo4j")
        return

    edge_count = await replace_all_graph(graph)
    logger.info("Neo4j 关系图初始化完成，%d 个表，%d 条边", len(graph), edge_count)


# ── 字段级向量索引 ──────────────────────────────────────────────────


async def ensure_field_indexes() -> None:
    """确保 Neo4j 中存在 Field 节点的向量索引。"""
    driver = await _get_driver()
    async with driver.session() as session:
        try:
            await session.run(
                """
                CREATE VECTOR INDEX field_embedding_idx IF NOT EXISTS
                FOR (f:Field) ON (f.field_embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: $dim,
                    `vector.similarity_function`: 'cosine'
                }}
                """,
                {"dim": _VECTOR_DIMENSIONS},
            )
            logger.info("向量索引 field_embedding_idx 已就绪")
        except Exception as e:
            logger.warning("创建 field_embedding_idx 失败: %s", e)


async def batch_set_field_embeddings(items: list[dict]) -> int:
    """批量创建/更新 Field 节点及其 field_embedding。

    Args:
        items: [{"table_name": str, "name": str, "type": str,
                  "comment": str, "embedding": list[float],
                  "is_pk": bool}, ...]

    Returns:
        创建/更新的节点数
    """
    if not items:
        return 0
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            UNWIND $batch AS item
            MERGE (f:Field {table_name: item.table_name, name: item.name})
            SET f.type = item.type,
                f.comment = item.comment,
                f.field_embedding = item.embedding,
                f.is_pk = item.is_pk
            RETURN count(f) AS updated
            """,
            {"batch": items},
        )
        count = (await result.single())["updated"]
    logger.info("批量写入 %d 个 Field 节点的 field_embedding", count)
    return count


async def field_has_embeddings() -> bool:
    """检查 Field 节点是否已有 embedding 数据。"""
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run("MATCH (f:Field) WHERE f.field_embedding IS NOT NULL RETURN count(f) AS c")
        rec = await result.single()
        return bool(rec and rec["c"] > 0)


async def field_similarity_search(query_vec: list[float], threshold: float = 0.55, limit: int = 30) -> list[dict]:
    """字段级语义搜索。

    Args:
        query_vec: 查询向量
        threshold: 相似度阈值
        limit: 返回数量上限

    Returns:
        [{table_name, field_name, type, comment, score}, ...]
    """
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            CALL db.index.vector.queryNodes('field_embedding_idx', $limit, $query_vec)
            YIELD node, score
            WHERE score >= $threshold
            RETURN node.table_name AS table_name,
                   node.name AS field_name,
                   node.type AS type,
                   node.comment AS comment,
                   score
            ORDER BY score DESC
            """,
            {"query_vec": query_vec, "threshold": threshold, "limit": limit},
        )
        return [
            {
                "table_name": rec["table_name"],
                "field_name": rec["field_name"],
                "type": rec["type"] or "",
                "comment": rec["comment"] or "",
                "score": rec["score"],
            }
            async for rec in result
        ]


async def get_table_fields(table_name: str) -> list[dict]:
    """获取某张表的所有字段信息（含 is_pk 标记）。

    Returns:
        [{name, type, comment, is_pk}, ...] 按原始顺序排序（无法保证，按 name 排序作为兜底）
    """
    driver = await _get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (f:Field {table_name: $table_name})
            RETURN f.name AS name,
                   f.type AS type,
                   f.comment AS comment,
                   f.is_pk AS is_pk
            ORDER BY f.name
            """,
            {"table_name": table_name},
        )
        return [
            {
                "name": rec["name"],
                "type": rec["type"] or "",
                "comment": rec["comment"] or "",
                "is_pk": bool(rec["is_pk"]),
            }
            async for rec in result
        ]


# ── 工具 ────────────────────────────────────────────────────────────


def _safe_str(value: object, default: str = "") -> str:
    """安全提取字符串值，处理 None。"""
    if value is None:
        return default
    return str(value)
