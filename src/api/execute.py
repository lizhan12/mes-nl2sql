"""SQL 分页执行 API。"""

from fastapi import APIRouter, HTTPException

from src.graph.nodes import execute_paginated_sql
from src.models.schemas import SqlPageRequest, SqlPageResponse
from src.security.sql_guard import SecurityError, validate_sql

router = APIRouter(tags=["SQL 执行"])


@router.post("/execute/page", response_model=SqlPageResponse)
async def execute_page(req: SqlPageRequest):
    """分页执行 SQL（含安全校验）。"""
    try:
        safe_sql = validate_sql(req.sql)
    except SecurityError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    result = execute_paginated_sql(safe_sql, req.page, req.page_size)
    return SqlPageResponse(**result)
