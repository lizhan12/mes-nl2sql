"""FastAPI 应用入口。

启动方式：
  uv run uvicorn src.main:app --reload
  uv run python src/main.py

强制重建向量库（重新 embedding）：
  uv run python src/main.py --rebuild
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.core.config import settings
from src.graph.workflow import build_workflow
from src.harness.online_service import (
    analyze_failures_online_service,
    label_failure_case_service,
    list_candidates_service,
    list_failure_cases_service,
    publish_approved_service,
    review_candidate_service,
)
from src.harness.repository import get_online_harness_repository
from src.models.schemas import (
    HarnessCandidateReviewRequest,
    HarnessFailureLabelRequest,
    HarnessPublishRequest,
    HealthResponse,
    NL2SQLRequest,
    NL2SQLResponse,
)
from src.services.vector_store import build_few_shot_store, build_schema_store

# ---- 日志配置 ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
UI_DIST_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"

# ---- 全局变量 ----
_app = None  # 编译后的 LangGraph app
_force_rebuild = "--rebuild" in sys.argv or os.environ.get("FORCE_REBUILD", "").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化向量库和 LangGraph 工作流。"""
    global _app

    logger.info("正在初始化向量库...")
    schema_store = build_schema_store(force_rebuild=_force_rebuild)
    few_shot_store = build_few_shot_store(force_rebuild=_force_rebuild)
    logger.info("向量库初始化完成")

    logger.info("正在编译 LangGraph 工作流...")
    _app = build_workflow(schema_store, few_shot_store)
    logger.info("服务就绪，等待请求")

    if settings.enable_online_harness and settings.harness_auto_init_db:
        logger.info("正在初始化线上 Harness 数据表...")
        get_online_harness_repository().ensure_tables()
        logger.info("线上 Harness 数据表初始化完成")

    yield
    logger.info("服务关闭")


app = FastAPI(
    title="MES NL2SQL API",
    description="MES 自然语言转 SQL 查询服务，基于 LangGraph",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if UI_DIST_DIR.exists():
    app.mount("/console/assets", StaticFiles(directory=UI_DIST_DIR / "assets"), name="console-assets")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查。"""
    return HealthResponse(status="ok")


@app.get("/")
async def root_redirect():
    """默认跳转到测试页面。"""
    if UI_DIST_DIR.exists():
        return RedirectResponse(url="/console")
    return RedirectResponse(url="/docs")


@app.get("/console")
async def console_index():
    """返回测试页面首页。"""
    if not UI_DIST_DIR.exists():
        return {"error": "前端页面尚未构建，请先执行 web 构建"}
    return FileResponse(UI_DIST_DIR / "index.html")


@app.get("/console/{full_path:path}")
async def console_spa_fallback(full_path: str):
    """SPA 回退到 index.html。"""
    target = UI_DIST_DIR / full_path
    if UI_DIST_DIR.exists() and target.exists() and target.is_file():
        return FileResponse(target)
    if not UI_DIST_DIR.exists():
        return {"error": "前端页面尚未构建，请先执行 web 构建"}
    return FileResponse(UI_DIST_DIR / "index.html")


@app.post("/nl2sql", response_model=NL2SQLResponse)
async def nl2sql(request: NL2SQLRequest):
    """自然语言转 SQL 查询。"""
    if _app is None:
        return NL2SQLResponse(
            query=request.query,
            sql="",
            safe=False,
            error="服务未初始化，请稍后重试",
        )

    request_id = str(uuid.uuid4())
    thread_id = request.thread_id or str(uuid.uuid4())
    initial_state = {"query": request.query}
    config = {"configurable": {"thread_id": thread_id}}
    result = await _app.ainvoke(initial_state, config)

    # 解析 execution_result
    exec_result = None
    raw = result.get("execution_result", "")
    if raw:
        try:
            import json

            exec_result = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            exec_result = {"raw": raw}
    knowledge_version = ""
    if settings.enable_online_harness:
        try:
            knowledge_version = get_online_harness_repository().load_published_knowledge().version
        except Exception as exc:
            logger.warning("读取线上 Harness 版本失败: %s", exc)

    response = NL2SQLResponse(
        query=request.query,
        sql=result.get("final_sql", ""),
        safe=result.get("safe", False),
        error=result.get("error", ""),
        tables_used=result.get("expanded_tables", "").split(",") if result.get("expanded_tables") else [],
        join_hints=result.get("join_hints", ""),
        execution_result=exec_result,
        retry_count=result.get("retry_count", 0),
        request_id=request_id,
        knowledge_version=knowledge_version,
    )

    if settings.enable_online_harness and settings.harness_request_log_enabled:
        await _log_request_async(request_id, request, result, exec_result, knowledge_version)

    return response


def _summarize_node_output(node_name: str, node_data: dict) -> dict:
    """摘要化节点输出，避免 SSE 流中传输大量文本。

    Returns:
        {"node": str, "fields": {...}, "text_preview": str}
    """
    large_fields = {"schema_docs", "few_shot_docs", "schema_context", "join_hints"}
    # 每个节点可能包含的关键文本字段，用于生成预览
    node_preview_keys: dict[str, list[str]] = {
        "intent": ["intent_summary", "intent_json"],
        "retrieval": ["schema_docs", "few_shot_docs"],
        "bfs": ["join_hints", "expanded_tables"],
        "schema": ["schema_context"],
        "sql_gen": ["generated_sql", "final_sql"],
        "safety": ["safety_reason"],
        "execute": ["execution_result"],
    }
    summary: dict = {}
    text_preview = ""

    # 先尝试从当前节点名称对应的关键字段提取预览
    preview_keys = node_preview_keys.get(node_name, [])
    for pk in preview_keys:
        val = node_data.get(pk)
        if not val:
            continue
        s = _extract_preview(pk, val)
        if s:
            text_preview = s
            break

    # 如果没找到，遍历所有字段
    if not text_preview:
        for key, value in node_data.items():
            s = _extract_preview(key, value)
            if s:
                text_preview = s
                break

    for key, value in node_data.items():
        if key in large_fields and isinstance(value, str) and len(value) > 300:
            summary[key] = {"length": len(value), "truncated": True}
        elif key == "execution_result" and isinstance(value, str):
            try:
                parsed = json.loads(value)
                summary[key] = {k: parsed[k] for k in ("success", "rows", "error") if k in parsed}
                if parsed.get("columns"):
                    summary[key]["column_count"] = len(parsed["columns"])
            except (json.JSONDecodeError, TypeError):
                summary[key] = value
        else:
            summary[key] = value

    summary["text_preview"] = text_preview
    return summary


def _extract_preview(key: str, value: object) -> str:
    """从节点输出的单个字段提取文本预览。"""
    if not isinstance(value, (str, list)):
        return ""
    if isinstance(value, list):
        if not value:
            return ""
        s = str(value)
    else:
        s = value
    s = s.strip()
    if not s:
        return ""
    # 意图 JSON 提取关键信息
    if key in ("intent_json",):
        try:
            parsed = json.loads(s)
            parts = []
            sq = parsed.get("search_queries", [])
            if sq:
                parts.append(f"搜索词: {sq[:3]}")
            intent_type = parsed.get("intent") or parsed.get("type")
            if intent_type:
                parts.append(f"意图: {intent_type}")
            if parts:
                return "; ".join(parts)[:300]
        except (json.JSONDecodeError, TypeError):
            pass
    # 展开的表名
    if key == "expanded_tables" and s:
        return f"关联表: {s[:300]}"
    # SQL
    if key in ("generated_sql", "final_sql"):
        return s[:300]
    # 其他文本
    return s[:300]


@app.post("/chat/stream")
async def chat_stream(request: NL2SQLRequest):
    """对话式 NL2SQL，SSE 流式返回每个节点的执行状态。

    SSE 事件格式：
      data: {"node": "<节点名>", "status": "progress", "data": {...}}
      data: {"node": "done", "status": "complete", "data": {...}}
    """

    async def event_generator():
        if _app is None:
            yield f"data: {json.dumps({'node': 'error', 'status': 'error', 'data': {'error': '服务未初始化，请稍后重试'}}, ensure_ascii=False)}\n\n"
            return

        thread_id = request.thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = {"query": request.query}

        try:
            async for chunk in _app.astream(initial_state, config, stream_mode="updates"):
                node_names = list(chunk.keys())
                for node_name in node_names:
                    node_data = chunk[node_name]
                    event = {
                        "node": node_name,
                        "status": "progress",
                        "thread_id": thread_id,
                        "data": _summarize_node_output(node_name, node_data),
                    }
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # 最终完成事件：从最后一个节点中提取执行结果
            last_node_name = node_names[-1] if node_names else ""
            last_node_data = chunk.get(last_node_name, {}) if chunk else {}
            done_data = _summarize_node_output(last_node_name, last_node_data)

            # done 事件额外携带完整执行结果（含 preview 数据）
            er_raw = last_node_data.get("execution_result", "")
            if isinstance(er_raw, str):
                try:
                    er = json.loads(er_raw)
                    done_data["execution_result"] = er
                except (json.JSONDecodeError, TypeError):
                    pass

            done_event = {
                "node": "done",
                "status": "complete",
                "thread_id": thread_id,
                "data": done_data,
            }
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"

        except Exception as exc:
            logger.error("chat/stream 异常: %s", exc)
            error_event = {
                "node": "error",
                "status": "error",
                "thread_id": thread_id,
                "data": {"error": str(exc)},
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/admin/harness/failure-cases")
async def list_harness_failure_cases(status: str = "", limit: int = 50):
    """查看线上 Harness 失败案例。"""
    if not settings.enable_online_harness:
        return {"items": [], "error": "线上 Harness 未启用"}
    items = await asyncio.to_thread(list_failure_cases_service, status or None, limit)
    return {"items": items}


@app.post("/admin/harness/failure-cases/{failure_case_id}/label")
async def label_harness_failure_case(failure_case_id: int, request: HarnessFailureLabelRequest):
    """给失败案例补充正确 SQL。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(
        label_failure_case_service,
        failure_case_id,
        request.correct_sql,
        request.note,
        request.label_type,
    )
    return result


@app.post("/admin/harness/analyze-failures")
async def analyze_harness_failures(limit: int = 200, sync_failures: bool = True):
    """分析失败案例并生成候选规则。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(analyze_failures_online_service, limit, sync_failures)
    return result


@app.get("/admin/harness/candidates")
async def list_harness_candidates(status: str = "", limit: int = 50):
    """查看候选规则。"""
    if not settings.enable_online_harness:
        return {"items": [], "error": "线上 Harness 未启用"}
    items = await asyncio.to_thread(list_candidates_service, status or None, limit)
    return {"items": items}


@app.post("/admin/harness/candidates/{candidate_id}/review")
async def review_harness_candidate(candidate_id: int, request: HarnessCandidateReviewRequest):
    """审核候选规则。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(review_candidate_service, candidate_id, request.action, request.note)
    return result


@app.post("/admin/harness/publish")
async def publish_harness_candidates(request: HarnessPublishRequest):
    """发布已审核通过的候选规则。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(publish_approved_service, request.version or None)
    return result


async def _log_request_async(
    request_id: str,
    request: NL2SQLRequest,
    result: dict,
    exec_result: dict | None,
    knowledge_version: str,
) -> None:
    try:
        repo = get_online_harness_repository()
        await asyncio.to_thread(
            repo.log_request,
            {
                "request_id": request_id,
                "query_text": request.query,
                "generated_sql": result.get("generated_sql", ""),
                "final_sql": result.get("final_sql", ""),
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host=settings.host, port=settings.port, reload=True)
