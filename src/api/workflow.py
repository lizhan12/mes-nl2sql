"""工作流相关接口：NL2SQL 查询。

编译后的 LangGraph app 通过 app.state.workflow_app 共享（由 lifespan 初始化）。
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request

from src.core.config import settings
from src.harness.repository import get_online_harness_repository
from src.models.schemas import NL2SQLRequest, NL2SQLResponse
from src.trace.tracer import clear_trace_context, flush_trace, set_trace_context

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_workflow_app(request: Request):
    """从 app.state 获取已编译的 LangGraph 工作流实例，未初始化时返回 None。"""
    return getattr(request.app.state, "workflow_app", None)


@router.post("/nl2sql", response_model=NL2SQLResponse)
async def nl2sql(request: NL2SQLRequest, http_request: Request):
    """自然语言转 SQL 查询。"""
    import json

    workflow_app = _get_workflow_app(http_request)
    if workflow_app is None:
        return NL2SQLResponse(
            query=request.query,
            error="服务未初始化，请稍后重试",
        )

    request_id = str(uuid.uuid4())
    thread_id = request.thread_id or str(uuid.uuid4())
    streaming = request.streaming if request.streaming is not None else settings.llm_streaming_enabled
    initial_state = {"query": request.query, "streaming": streaming}
    config = {"configurable": {"thread_id": thread_id}}

    set_trace_context(request_id, thread_id, streaming=False)
    try:
        result = await workflow_app.ainvoke(initial_state, config)
    finally:
        flush_trace()
        clear_trace_context()

    # 解析 execution_results
    multi_sql = result.get("multi_sql", False)
    sqls = result.get("final_sqls", [])

    exec_results = []
    exec_result = None
    raw = result.get("execution_results", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                exec_results = parsed
                exec_result = parsed[0] if parsed else None
            elif isinstance(parsed, dict):
                exec_results = [parsed]
                exec_result = parsed
        except (json.JSONDecodeError, TypeError):
            exec_results = [{"raw": raw}]
            exec_result = {"raw": raw}

    knowledge_version = ""
    if settings.enable_online_harness:
        try:
            from src.services.neo4j_graph import get_harness_knowledge_version

            knowledge_version = await get_harness_knowledge_version()
        except Exception as exc:
            logger.warning("读取线上 Harness 版本失败: %s", exc)

    response = NL2SQLResponse(
        query=request.query,
        sql=sqls[0] if sqls else "",
        sqls=sqls,
        safe=result.get("safe", False),
        error=result.get("error", ""),
        tables_used=result.get("expanded_tables", "").split(",") if result.get("expanded_tables") else [],
        join_hints=result.get("join_hints", ""),
        execution_result=exec_result,
        execution_results=exec_results,
        retry_count=result.get("retry_count", 0),
        request_id=request_id,
        knowledge_version=knowledge_version,
        multi_sql=multi_sql,
        sub_queries=result.get("sub_queries", []),
    )

    if settings.enable_online_harness and settings.harness_request_log_enabled:
        await _log_request_async(request_id, request, result, exec_result, knowledge_version)

    return response


async def _log_request_async(
    request_id: str,
    request: NL2SQLRequest,
    result: dict,
    exec_result: dict | None,
    knowledge_version: str,
) -> None:
    """将 NL2SQL 请求写入 Harness 请求日志（数据飞轮入口）。"""
    import asyncio

    try:
        repo = get_online_harness_repository()
        final_sqls = result.get("final_sqls", [])
        await asyncio.to_thread(
            repo.log_request,
            {
                "request_id": request_id,
                "query_text": request.query,
                "generated_sql": "\n;\n".join(result.get("generated_sqls", [])),
                "final_sql": "\n;\n".join(final_sqls),
                "safe": result.get("safe", False),
                "error_text": result.get("error", ""),
                "execution_result": exec_result or {},
                "retry_count": result.get("retry_count", 0),
                "tables_used": result.get("expanded_tables", "").split(",") if result.get("expanded_tables") else [],
                "join_hints": result.get("join_hints", ""),
                "rule_version": knowledge_version,
                "few_shot_version": knowledge_version,
            },
        )
    except Exception as exc:
        logger.warning("线上 Harness 请求日志写入失败: %s", exc)
