"""关系图管理 API。"""

import json as _json
from pathlib import Path as _Path

from fastapi import APIRouter, HTTPException

from src.models.schemas import GraphEdgeCreate
from src.services.bfs import _get_graph as load_relation_graph

router = APIRouter(prefix="/api/graph", tags=["关系图管理"])


@router.get("")
async def get_relation_graph():
    """返回完整的表关系图数据，供前端可视化使用。"""
    return {"graph": load_relation_graph()}


@router.get("/version")
async def get_graph_version():
    """获取当前图版本号。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    return {"version": repo.get_version()}


@router.post("/sync")
async def sync_graph_from_json():
    """从本地 JSON 文件全量同步到 PG 数据库。"""
    from src.services.graph_repository import get_graph_repository

    graph_path = _Path(__file__).parent.parent.parent / "data" / "mes_relation_graph.json"
    with open(graph_path, encoding="utf-8") as f:
        data = _json.load(f)
    graph = data["graph"] if isinstance(data, dict) and "graph" in data else data

    repo = get_graph_repository()
    repo.ensure_tables()
    count = repo.replace_all(graph)
    return {"message": f"同步完成，共导入 {count} 条边", "count": count, "version": repo.get_version()}


@router.get("/edges")
async def list_graph_edges(from_table: str = "", confidence: str = "", limit: int = 500):
    """列表查询关系边。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    return {"edges": repo.list_edges(from_table=from_table, confidence=confidence, limit=limit)}


@router.get("/edges/{edge_id}")
async def get_graph_edge(edge_id: int):
    """获取单条关系边详情。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    edge = repo.get_edge(edge_id)
    if not edge:
        raise HTTPException(status_code=404, detail=f"边 {edge_id} 不存在")
    return edge


@router.post("/edges")
async def add_graph_edge(edge: GraphEdgeCreate):
    """添加一条关系边。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    edge_id = repo.add_edge(edge.to_graph_edge())
    return {"id": edge_id, "message": "添加成功", "version": repo.get_version()}


@router.put("/edges/{edge_id}")
async def update_graph_edge(edge_id: int, edge: GraphEdgeCreate):
    """更新一条关系边。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    if not repo.get_edge(edge_id):
        raise HTTPException(status_code=404, detail=f"边 {edge_id} 不存在")
    repo.update_edge(edge_id, edge.to_graph_edge())
    return {"id": edge_id, "message": "更新成功", "version": repo.get_version()}


@router.delete("/edges/{edge_id}")
async def delete_graph_edge(edge_id: int):
    """删除一条关系边。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    if not repo.get_edge(edge_id):
        raise HTTPException(status_code=404, detail=f"边 {edge_id} 不存在")
    repo.delete_edge(edge_id)
    return {"id": edge_id, "message": "删除成功", "version": repo.get_version()}
