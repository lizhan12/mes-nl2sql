"""NL2SQL 非流式 API。"""

import json
import logging
import uuid

from fastapi import APIRouter

from src.core.config import settings
from src.harness.repository import get_online_harness_repository
from src.models.schemas import NL2SQLRequest, NL2SQLResponse

logger = logging.getLogger(__name__)

# 编译后的 LangGraph app，由 main.py 在 lifespan 中注入
_app = None

router = APIRouter(tags=["NL2SQL"])


def set_langgraph_app(app):
    """设置 LangGraph 编译后 app 的全局引用。"""
    global _app
    _app = app


async def _log_request_async(
    request_id: str,
    request: NL2SQLRequest,
    result: dict,
    exec_result: dict | None,
    knowledge_version: str,
) -> None:
    try:
        repo = get_online_harness_repository()
        await __import__("asyncio").to_thread(
            repo.log_request,
            {
                "request_id": request_id,
                "query_text": request.query,
                "generated_sql": "\n;\n".join(result.get("generated_sqls", [])),
                "final_sql": "\n;\n".join(result.get("final_sqls", [])),
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


@router.post("/nl2sql", response_model=NL2SQLResponse)
async def nl2sql(request: NL2SQLRequest):
    """自然语言转 SQL 查询。"""
    if _app is None:
        return NL2SQLResponse(
            query=request.query,
            error="服务未初始化，请稍后重试",
        )

    request_id = str(uuid.uuid4())
    thread_id = request.thread_id or str(uuid.uuid4())
    initial_state = {"query": request.query}
    config = {"configurable": {"thread_id": thread_id}}

    from src.trace.tracer import clear_trace_context, flush_trace, set_trace_context

    set_trace_context(request_id, thread_id, streaming=False)
    try:
        result = await _app.ainvoke(initial_state, config)
    finally:
        flush_trace()
        clear_trace_context()

    # 解析 execution_results
    multi_sql = result.get("multi_sql", False)
    sqls = result.get("final_sqls", [])

    # 非 MES 业务域问题：流水线已跳过后半段，直接返回提示
    if result.get("non_mes_domain", False):
        return NL2SQLResponse(
            query=request.query,
            error="抱歉，您的问题不属于 MES 业务域范围，我无法回答。请提出与生产、质量、仓库、设备、基础数据等 MES 相关的问题。",
            request_id=request_id,
        )

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
            knowledge_version = get_online_harness_repository().load_published_knowledge().version
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
