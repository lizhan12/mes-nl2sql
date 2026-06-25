"""知识图谱单点查询接口：表 DDL、字段、邻居、路径。"""

from fastapi import APIRouter, HTTPException, Query

from src.models.schemas import (
    GraphPathResponse,
    NeighborEdge,
    PathEdge,
    TableDDLResponse,
    TableFieldsResponse,
    TableFieldWithPK,
    TableNeighborsResponse,
)

router = APIRouter(prefix="/api/knowledge")


@router.get("/table/{name}/ddl", response_model=TableDDLResponse)
async def get_table_ddl(name: str):
    """获取指定表的 DDL 定义（通过 Neo4j Table + Field 节点生成）。

    返回包含表元信息、字段列表和生成的 CREATE TABLE DDL 语句。
    """
    from src.services.neo4j_graph import get_table_ddl as neo4j_ddl

    result = await neo4j_ddl(name)
    if not result:
        raise HTTPException(status_code=404, detail=f"表 {name} 不存在")
    return result


@router.get("/table/{name}/fields", response_model=TableFieldsResponse)
async def get_table_fields_api(name: str):
    """获取指定表的所有字段信息（从 Neo4j Field 节点）。

    返回字段名、类型、注释、是否主键等完整信息。
    """
    from src.services.neo4j_graph import get_table_fields as neo4j_fields

    fields = await neo4j_fields(name)
    return TableFieldsResponse(
        table_name=name,
        fields=[TableFieldWithPK(**f) for f in fields],
        field_count=len(fields),
    )


@router.get("/table/{name}/neighbors", response_model=TableNeighborsResponse)
async def get_table_neighbors(name: str):
    """获取指定表的邻居表（通过 JOIN_REL 关系）。

    返回出边（本表→邻居）和入边（邻居→本表）两类关系。
    """
    from src.services.neo4j_graph import get_table_neighbors as neo4j_neighbors

    result = await neo4j_neighbors(name)
    return TableNeighborsResponse(
        table_name=result["table_name"],
        outgoing=[NeighborEdge(**e) for e in result["outgoing"]],
        incoming=[NeighborEdge(**e) for e in result["incoming"]],
        total_neighbors=len(result["outgoing"]) + len(result["incoming"]),
    )


@router.get("/graph/path", response_model=GraphPathResponse)
async def find_graph_path(
    from_table: str = Query(..., min_length=1, description="起始表名"),
    to_table: str = Query(..., min_length=1, description="目标表名"),
    max_depth: int = Query(5, ge=1, le=10, description="最大搜索深度"),
):
    """查找两张表之间通过 JOIN_REL 关系的最短路径。

    使用 Neo4j shortestPath 算法，返回路径中的每一条边及其 JOIN 信息。
    若未找到路径，返回 found=False。
    """
    from src.services.neo4j_graph import find_graph_path as neo4j_path

    result = await neo4j_path(from_table, to_table, max_depth)
    if not result:
        return GraphPathResponse(
            from_table=from_table,
            to_table=to_table,
            path=[],
            depth=0,
            found=False,
        )
    return GraphPathResponse(
        from_table=result["from_table"],
        to_table=result["to_table"],
        path=[PathEdge(**e) for e in result["path"]],
        depth=result["depth"],
        found=True,
    )
