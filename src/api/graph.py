"""表关系图管理接口：查询、同步、增删改关系边。"""

from fastapi import APIRouter, HTTPException

from src.core.config import settings
from src.models.schemas import GraphEdgeCreate
from src.services.bfs import _get_graph as load_relation_graph

router = APIRouter(prefix="/api/graph")


@router.get("")
async def get_relation_graph():
    """返回完整的表关系图数据，供前端可视化使用。"""
    return {"graph": await load_relation_graph()}


@router.get("/version")
async def get_graph_version():
    """获取当前图版本号（Neo4j 用边数模拟）。"""
    from src.services.neo4j_graph import get_graph_version as neo4j_version

    return {"version": await neo4j_version()}


@router.post("/sync")
async def sync_graph_from_json():
    """从本地 JSON 文件全量同步到 Neo4j 数据库。"""
    if not settings.neo4j_graph_auto_init:
        raise HTTPException(
            status_code=403,
            detail="neo4j_graph_auto_init=False，禁止从本地 JSON 全量同步（防止覆盖线上精简知识库）",
        )

    import json as _json
    from pathlib import Path as _Path

    from src.services.neo4j_graph import get_graph_version, replace_all_graph

    graph_path = _Path(__file__).parents[2] / "data" / "mes_relation_graph.json"
    with open(graph_path, encoding="utf-8") as f:
        data = _json.load(f)
    graph = data["graph"] if isinstance(data, dict) and "graph" in data else data

    count = await replace_all_graph(graph)
    return {"message": f"同步完成，共导入 {count} 条边", "count": count, "version": await get_graph_version()}


@router.get("/edges")
async def list_graph_edges(from_table: str = "", confidence: str = "", limit: int = 500):
    """列表查询关系边（Neo4j）。"""
    from src.services.neo4j_graph import list_edges as neo4j_list_edges

    return {"edges": await neo4j_list_edges(from_table=from_table, confidence=confidence, limit=limit)}


@router.get("/edges/detail")
async def get_graph_edge(from_table: str = "", to_table: str = ""):
    """获取单条关系边详情（按 from_table + to_table 查找）。"""
    if not from_table or not to_table:
        raise HTTPException(status_code=400, detail="请提供 from_table 和 to_table 参数")
    from src.services.neo4j_graph import get_edge as neo4j_get_edge

    edge = await neo4j_get_edge(from_table, to_table)
    if not edge:
        raise HTTPException(status_code=404, detail=f"边 {from_table} → {to_table} 不存在")
    return edge


@router.post("/edges")
async def add_graph_edge(edge: GraphEdgeCreate):
    """添加一条关系边（Neo4j）。"""
    from src.services.neo4j_graph import add_edge as neo4j_add_edge
    from src.services.neo4j_graph import get_graph_version

    await neo4j_add_edge(
        edge.from_table,
        edge.to_table,
        {
            "from_field": edge.from_field,
            "to_field": edge.to_field,
            "join": edge.join_condition,
            "join_type": edge.join_type,
            "desc": edge.description,
            "confidence": edge.confidence,
            "note": edge.note,
        },
    )
    return {"message": "添加成功", "version": await get_graph_version()}


@router.put("/edges")
async def update_graph_edge(
    from_table: str = "",
    to_table: str = "",
    edge: GraphEdgeCreate | None = None,
):
    """更新一条关系边（Neo4j，按 from_table + to_table 匹配）。"""
    if not from_table or not to_table:
        raise HTTPException(status_code=400, detail="请提供 from_table 和 to_table 参数")
    if not edge:
        raise HTTPException(status_code=400, detail="请提供要更新的边数据")
    from src.services.neo4j_graph import get_graph_version
    from src.services.neo4j_graph import update_edge as neo4j_update_edge

    ok = await neo4j_update_edge(
        from_table,
        to_table,
        {
            "from_field": edge.from_field,
            "to_field": edge.to_field,
            "join": edge.join_condition,
            "join_type": edge.join_type,
            "desc": edge.description,
            "confidence": edge.confidence,
            "note": edge.note,
        },
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"边 {from_table} → {to_table} 不存在")
    return {"message": "更新成功", "version": await get_graph_version()}


@router.delete("/edges")
async def delete_graph_edge(from_table: str = "", to_table: str = ""):
    """删除一条关系边（Neo4j，按 from_table + to_table 匹配）。"""
    if not from_table or not to_table:
        raise HTTPException(status_code=400, detail="请提供 from_table 和 to_table 参数")
    from src.services.neo4j_graph import delete_edge as neo4j_delete_edge
    from src.services.neo4j_graph import get_graph_version

    await neo4j_delete_edge(from_table, to_table)
    return {"message": "删除成功", "version": await get_graph_version()}
