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
import re
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage

from src.core.config import settings
from src.graph.workflow import build_workflow
from src.harness.online_service import (
    analyze_failures_online_service,
    auto_label_failures_online_service,
    evolve_online_service,
    label_failure_case_service,
    list_candidates_service,
    list_failure_cases_service,
    publish_approved_service,
    review_candidate_service,
)
from src.harness.repository import get_online_harness_repository
from src.models.schemas import (
    ChatHistoryItem,
    ChatHistoryListResponse,
    ChatThreadResponse,
    GraphEdgeCreate,
    HarnessCandidateReviewRequest,
    HarnessFailureLabelRequest,
    HarnessFeedbackRequest,
    HarnessPublishRequest,
    HealthResponse,
    NL2SQLRequest,
    NL2SQLResponse,
    SqlPageRequest,
    SqlPageResponse,
)
from src.services.bfs import _get_graph as load_relation_graph
from src.services.chat_repository import get_chat_repository
from src.services.vector_store import build_few_shot_store, build_schema_store
from src.trace.repository import get_trace_repository
from src.trace.tracer import clear_trace_context, flush_trace, set_trace_context

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

    logger.info("正在初始化聊天历史数据表...")
    get_chat_repository().ensure_tables()
    logger.info("聊天历史数据表初始化完成")

    if settings.trace_enabled:
        logger.info("正在初始化 Trace 追踪数据表...")
        get_trace_repository().ensure_tables()
        logger.info("Trace 追踪数据表初始化完成")

    yield
    from src.services.db_pool import close_all_pools

    close_all_pools()
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
            error="服务未初始化，请稍后重试",
        )

    request_id = str(uuid.uuid4())
    thread_id = request.thread_id or str(uuid.uuid4())
    initial_state = {"query": request.query}
    config = {"configurable": {"thread_id": thread_id}}

    set_trace_context(request_id, thread_id, streaming=False)
    try:
        result = await _app.ainvoke(initial_state, config)
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
        "sql_gen": ["generated_sqls", "final_sqls"],
        "safety": ["safety_reason"],
        "execute": ["execution_results"],
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
        elif key == "execution_results" and isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list) and len(parsed) > 0:
                    # 对列表只保留摘要信息，不在 progress 事件中传输完整数据
                    summary[key] = [
                        {k: r[k] for k in ("success", "rows", "error", "description") if k in r} for r in parsed
                    ]
                else:
                    summary[key] = value
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
    if key in ("generated_sqls", "final_sqls"):
        if isinstance(value, list) and value:
            sqls_preview = [s[:120] for s in value[:2]]
            result = "; ".join(sqls_preview)
            if len(value) > 2:
                result += f" ... 共 {len(value)} 条"
            return result[:300]
        return str(value)[:300]
    # 其他文本
    return s[:300]


# 对话会话存储：{thread_id: [HumanMessage, AIMessage, ...]}
_chat_sessions: dict[str, list] = {}


def _build_chat_summary(done_data: dict) -> str:
    """构建 AI 回复的简要摘要，用于存入对话历史。

    只保留 SQL 和执行状态，不保留完整数据，防止上下文污染。
    SQL 会先压缩空白再截断，确保 FROM/JOIN/WHERE 等关键结构得以保留。
    多 SQL 模式下每条子查询也保留 SQL 摘要，确保后续轮次能提取表名。
    """
    multi = done_data.get("multi_sql", False)
    sqls = done_data.get("final_sqls", [])
    results = done_data.get("execution_results", [])
    success = done_data.get("safe", False)

    parts: list[str] = []
    if multi:
        for i, r in enumerate(results):
            desc = r.get("description", f"查询{i + 1}")
            status = "成功" if r.get("success") else "失败"
            rows = r.get("rows", "?")
            # 多 SQL 模式下也保留压缩后的 SQL，方便后续轮次提取表名
            if i < len(sqls):
                compressed_sql = re.sub(r"\s+", " ", sqls[i]).strip()
                sql_info = compressed_sql[:300]
                parts.append(f"{desc}: {status}({rows}行) SQL[{sql_info}]")
            else:
                parts.append(f"{desc}: {status}({rows}行)")
        summary = "; ".join(parts)
    elif sqls:
        compressed = re.sub(r"\s+", " ", sqls[0]).strip()
        summary = f"SQL: {compressed[:500]}"
    else:
        summary = "查询完成" if success else "查询失败"

    return summary


@app.post("/chat/stream")
async def chat_stream(request: NL2SQLRequest):
    """对话式 NL2SQL，SSE 流式返回每个节点的执行状态。

    支持多轮对话：通过 thread_id 维护会话历史。
    SSE 事件格式：
      data: {"node": "<节点名>", "status": "progress", "data": {...}}
      data: {"node": "done", "status": "complete", "data": {...}}
    """

    async def event_generator():
        if _app is None:
            yield f"data: {json.dumps({'node': 'error', 'status': 'error', 'data': {'error': '服务未初始化，请稍后重试'}}, ensure_ascii=False)}\n\n"
            return

        thread_id = request.thread_id or str(uuid.uuid4())
        chat_request_id = str(uuid.uuid4())  # 本次请求的唯一标识，用于前端反馈
        config = {"configurable": {"thread_id": thread_id}}

        set_trace_context(chat_request_id, thread_id, streaming=True)

        # 加载会话历史，注入到初始 state
        session_history = _chat_sessions.get(thread_id, [])
        initial_state: dict = {"query": request.query}
        if session_history:
            initial_state["messages"] = session_history

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

            # 最终完成事件：从完整 state 中提取所有关键数据
            # stream_mode="updates" 只返回节点显式输出的字段，不包含 upstream 设置的字段
            # 需要从完整 state 获取 multi_sql、sub_queries、final_sqls
            final_state = await _app.aget_state(config)
            state_values = final_state.values if final_state else {}

            last_node_name = node_names[-1] if node_names else ""
            last_node_data = chunk.get(last_node_name, {}) if chunk else {}
            done_data = _summarize_node_output(last_node_name, last_node_data)

            # done 事件额外携带完整执行结果（含 preview 数据）
            er_raw = state_values.get("execution_results", "") or last_node_data.get("execution_results", "")
            if isinstance(er_raw, str):
                try:
                    er = json.loads(er_raw)
                    done_data["execution_results"] = er
                except (json.JSONDecodeError, TypeError):
                    pass

            # 从完整 state 获取多 SQL 相关字段
            done_data["multi_sql"] = state_values.get("multi_sql", False)
            done_data["sub_queries"] = state_values.get("sub_queries", [])
            done_data["final_sqls"] = state_values.get("final_sqls", [])

            # 保存本轮对话到会话历史（只存用户问题和简要摘要，不存执行数据）
            session_history.append(HumanMessage(content=request.query))
            done_summary = _build_chat_summary(done_data)
            session_history.append(AIMessage(content=done_summary))
            # 限制历史长度，防止上下文过大
            if len(session_history) > 10:
                session_history = session_history[-10:]
            _chat_sessions[thread_id] = session_history

            # 持久化到数据库
            if request.user_id:
                messages_payload = [{"type": msg.__class__.__name__, "content": msg.content} for msg in session_history]
                try:
                    get_chat_repository().save_session(request.user_id, thread_id, messages_payload)
                except Exception as exc:
                    logger.warning("聊天历史持久化失败: %s", exc)

            done_event = {
                "node": "done",
                "status": "complete",
                "thread_id": thread_id,
                "request_id": chat_request_id,
                "trace_id": chat_request_id,
                "data": done_data,
            }
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"

            # 写入 Harness 请求日志，让 Chat 页面的每次查询都进入数据飞轮
            if settings.enable_online_harness and settings.harness_request_log_enabled:
                await _log_chat_request_async(request, chat_request_id, state_values)

            clear_trace_context()

        except Exception as exc:
            logger.error("chat/stream 异常: %s", exc)
            clear_trace_context()
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


# ── 聊天历史 API ───────────────────────────────────────────────────


@app.get("/chat/history", response_model=ChatHistoryListResponse)
async def list_chat_history(user_id: str, limit: int = 50):
    """获取用户的所有对话记录列表。"""
    sessions = get_chat_repository().list_user_sessions(user_id, limit)
    return ChatHistoryListResponse(sessions=[ChatHistoryItem(**s) for s in sessions])


@app.get("/chat/history/{thread_id}", response_model=ChatThreadResponse)
async def get_chat_thread(thread_id: str, user_id: str):
    """获取指定对话线程的完整消息记录。"""
    messages = get_chat_repository().load_session(user_id, thread_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="对话记录不存在")
    return ChatThreadResponse(thread_id=thread_id, user_id=user_id, messages=messages)


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


@app.post("/admin/harness/auto-label-failures")
async def auto_label_harness_failures(
    limit: int = 50,
    sync_failures: bool = True,
    generate_model: str = "",
    eval_model: str = "",
):
    """LLM 自动标注 + 多维度评估失败案例。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(
        auto_label_failures_online_service,
        limit,
        sync_failures,
        settings.execution_database_url,
        generate_model or None,
        eval_model or None,
    )
    return result


@app.post("/admin/harness/evolve-online")
async def evolve_harness_online(limit: int = 200, sync_failures: bool = True):
    """从线上数据库日志生成并发布运行时知识。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    result = await asyncio.to_thread(evolve_online_service, limit, sync_failures)
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


@app.post("/admin/harness/feedback")
async def submit_harness_feedback(request: HarnessFeedbackRequest):
    """用户点赞/点踩反馈。点踩时自动创建失败案例进入 Harness 闭环。"""
    if not settings.enable_online_harness:
        return {"error": "线上 Harness 未启用"}
    rating = 1 if request.rating == "up" else -1
    result = await asyncio.to_thread(
        get_online_harness_repository().submit_user_feedback,
        request.request_id,
        rating,
        request.reason,
    )
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


async def _log_chat_request_async(
    request: NL2SQLRequest,
    request_id: str,
    state_values: dict,
) -> None:
    """将 Chat 页面的流式查询写入 Harness 请求日志。"""
    try:
        repo = get_online_harness_repository()

        # 从 state_values 提取执行结果
        er_raw = state_values.get("execution_results", "")
        exec_result = {}
        if isinstance(er_raw, str):
            try:
                parsed = json.loads(er_raw)
                if isinstance(parsed, list) and parsed:
                    exec_result = parsed[0]
                elif isinstance(parsed, dict):
                    exec_result = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        generated_sqls = state_values.get("generated_sqls", [])
        final_sqls = state_values.get("final_sqls", [])
        expanded_tables = state_values.get("expanded_tables", "")

        knowledge_version = ""
        try:
            knowledge_version = repo.load_published_knowledge().version
        except Exception as exc:
            logger.warning("读取线上 Harness 版本失败: %s", exc)

        await asyncio.to_thread(
            repo.log_request,
            {
                "request_id": request_id,
                "query_text": request.query,
                "generated_sql": "\n;\n".join(generated_sqls),
                "final_sql": "\n;\n".join(final_sqls),
                "safe": state_values.get("safe", False),
                "error_text": state_values.get("error", ""),
                "execution_result": exec_result or {},
                "retry_count": state_values.get("retry_count", 0),
                "tables_used": expanded_tables.split(",")
                if isinstance(expanded_tables, str) and expanded_tables
                else [],
                "join_hints": state_values.get("join_hints", ""),
                "rule_version": knowledge_version,
                "few_shot_version": knowledge_version,
            },
        )
    except Exception as exc:
        logger.warning("Chat 流 Harness 请求日志写入失败: %s", exc)


@app.post("/execute/page", response_model=SqlPageResponse)
async def execute_page(req: SqlPageRequest):
    """分页执行 SQL。"""
    from src.graph.nodes import execute_paginated_sql

    result = execute_paginated_sql(req.sql, req.page, req.page_size)
    return SqlPageResponse(**result)


# ── 关系图管理 API ─────────────────────────────────────────────────


@app.get("/api/graph")
async def get_relation_graph():
    """返回完整的表关系图数据，供前端可视化使用。"""
    return {"graph": load_relation_graph()}


@app.get("/api/graph/version")
async def get_graph_version():
    """获取当前图版本号。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    return {"version": repo.get_version()}


@app.post("/api/graph/sync")
async def sync_graph_from_json():
    """从本地 JSON 文件全量同步到 PG 数据库。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    count = repo.replace_all(load_relation_graph())
    return {"message": f"同步完成，共导入 {count} 条边", "count": count, "version": repo.get_version()}


@app.get("/api/graph/edges")
async def list_graph_edges(from_table: str = "", confidence: str = "", limit: int = 500):
    """列表查询关系边。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    return {"edges": repo.list_edges(from_table=from_table, confidence=confidence, limit=limit)}


@app.get("/api/graph/edges/{edge_id}")
async def get_graph_edge(edge_id: int):
    """获取单条关系边详情。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    edge = repo.get_edge(edge_id)
    if not edge:
        raise HTTPException(status_code=404, detail=f"边 {edge_id} 不存在")
    return edge


@app.post("/api/graph/edges")
async def add_graph_edge(edge: GraphEdgeCreate):
    """添加一条关系边。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    edge_id = repo.add_edge(edge.to_graph_edge())
    return {"id": edge_id, "message": "添加成功", "version": repo.get_version()}


@app.put("/api/graph/edges/{edge_id}")
async def update_graph_edge(edge_id: int, edge: GraphEdgeCreate):
    """更新一条关系边。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    if not repo.get_edge(edge_id):
        raise HTTPException(status_code=404, detail=f"边 {edge_id} 不存在")
    repo.update_edge(edge_id, edge.to_graph_edge())
    return {"id": edge_id, "message": "更新成功", "version": repo.get_version()}


@app.delete("/api/graph/edges/{edge_id}")
async def delete_graph_edge(edge_id: int):
    """删除一条关系边。"""
    from src.services.graph_repository import get_graph_repository

    repo = get_graph_repository()
    repo.ensure_tables()
    if not repo.get_edge(edge_id):
        raise HTTPException(status_code=404, detail=f"边 {edge_id} 不存在")
    repo.delete_edge(edge_id)
    return {"id": edge_id, "message": "删除成功", "version": repo.get_version()}


# ── Trace 查询 API ─────────────────────────────────────────────────


@app.get("/api/trace/{trace_id}")
async def get_trace(trace_id: str):
    """获取单次请求的所有 trace spans。"""
    try:
        spans = get_trace_repository().query_by_trace_id(trace_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询 trace 失败: {exc}") from exc
    if not spans:
        raise HTTPException(status_code=404, detail=f"trace {trace_id} 不存在")
    return {"trace_id": trace_id, "spans": spans, "count": len(spans)}


@app.get("/api/trace/thread/{thread_id}")
async def get_thread_traces(thread_id: str):
    """获取整个会话的所有 trace spans。"""
    try:
        spans = get_trace_repository().query_by_thread_id(thread_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询 trace 失败: {exc}") from exc
    return {"thread_id": thread_id, "spans": spans, "count": len(spans)}


@app.get("/api/trace/recent")
async def get_recent_traces(limit: int = 50):
    """获取最近的 trace 摘要列表。"""
    try:
        summaries = get_trace_repository().query_recent_traces(limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询 trace 失败: {exc}") from exc
    return {"traces": [s.__dict__ for s in summaries], "count": len(summaries)}


@app.get("/api/trace/stats")
async def get_trace_stats(node: str = "", days: int = 7):
    """获取 trace 统计信息：各节点 P50/P95/P99 耗时、成功率、token 消耗。"""
    try:
        stats = get_trace_repository().get_trace_stats(node_name=node, days=days)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询 trace 统计失败: {exc}") from exc
    return stats


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host=settings.host, port=settings.port, reload=True)
