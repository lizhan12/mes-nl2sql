"""Chat 流式 SSE API + 聊天历史 API。"""

import json
import logging
import re
import time
import uuid
from contextlib import suppress

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from src.core.config import settings
from src.harness.repository import get_online_harness_repository
from src.models.schemas import (
    ChatHistoryItem,
    ChatHistoryListResponse,
    ChatThreadResponse,
    NL2SQLRequest,
)
from src.security.sql_guard import validate_sql
from src.services.chat_repository import get_chat_repository
from src.services.db_pool import execution_connection
from src.trace.models import SPAN_TYPE_DB, SPAN_TYPE_NODE, STATUS_ERROR, STATUS_SUCCESS, SpanInfo
from src.trace.tracer import _persist_span, clear_trace_context, set_trace_context

logger = logging.getLogger(__name__)

# 编译后的 LangGraph app，由 main.py 在 lifespan 中注入
_app = None

# 对话会话存储：{thread_id: [HumanMessage, AIMessage, ...]}
_chat_sessions: dict[str, list] = {}

router = APIRouter(tags=["Chat 对话"])


def set_langgraph_app(app):
    """设置 LangGraph 编译后 app 的全局引用。"""
    global _app
    _app = app


# ── SSE 事件辅助函数 ────────────────────────────────────────────


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


def _summarize_node_output(node_name: str, node_data: dict) -> dict:
    """摘要化节点输出，避免 SSE 流中传输大量文本。

    Returns:
        {"node": str, "fields": {...}, "text_preview": str}
    """
    large_fields = {"schema_docs", "few_shot_docs", "schema_context", "join_hints"}
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

    preview_keys = node_preview_keys.get(node_name, [])
    for pk in preview_keys:
        val = node_data.get(pk)
        if not val:
            continue
        s = _extract_preview(pk, val)
        if s:
            text_preview = s
            break

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


def _build_chat_summary(done_data: dict) -> str:
    """构建 AI 回复的简要摘要，用于存入对话历史。

    只保留 SQL 和执行状态，不保留完整数据，防止上下文污染。
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

    # 非 MES 业务域问题
    if done_data.get("non_mes_domain"):
        summary = "域外问题：已拒绝"

    return summary


async def _log_chat_request_async(
    request: NL2SQLRequest,
    request_id: str,
    state_values: dict,
) -> None:
    """将 Chat 页面的流式查询写入 Harness 请求日志。"""
    try:
        repo = get_online_harness_repository()

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

        await __import__("asyncio").to_thread(
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


def _persist_chat_session(thread_id: str, request: NL2SQLRequest, summary: str):
    """保存对话会话历史到内存和数据库。"""
    session_history = _chat_sessions.get(thread_id, [])
    session_history.append(HumanMessage(content=request.query))
    session_history.append(AIMessage(content=summary))
    if len(session_history) > 10:
        session_history = session_history[-10:]
    _chat_sessions[thread_id] = session_history

    if request.user_id:
        messages_payload = [{"type": msg.__class__.__name__, "content": msg.content} for msg in session_history]
        try:
            get_chat_repository().save_session(request.user_id, thread_id, messages_payload)
        except Exception as exc:
            logger.warning("聊天历史持久化失败: %s", exc)


# ── Chat 流式 SSE 端点 ──────────────────────────────────────────


@router.post("/chat/stream")
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
        chat_request_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        set_trace_context(chat_request_id, thread_id, streaming=True)

        # ── 指标路由层 ───────────────────────────────────────────
        from src.services.metric_router import route as metric_route
        from src.services.metric_router import route_clarification

        route_span_id = str(uuid.uuid4())
        route_span = SpanInfo(
            span_id=route_span_id,
            trace_id=chat_request_id,
            node_name="metric_route",
            span_type=SPAN_TYPE_NODE,
            status=STATUS_SUCCESS,
            start_time=time.time(),
            input_data={"query": request.query},
        )
        try:
            if request.metric_id:
                route_result = await route_clarification(request.query, request.metric_id)
            else:
                route_result = await metric_route(request.query)
            route_span.output_data = {"channel": route_result.channel, "matched_term": route_result.matched_term}
            if route_result.metric_id:
                route_span.output_data["metric_id"] = route_result.metric_id
                route_span.output_data["metric_name"] = route_result.metric_name
            route_span.end_time = time.time()
            route_span.duration_ms = int((route_span.end_time - route_span.start_time) * 1000)
            _persist_span(route_span)
        except Exception as route_exc:
            route_span.status = STATUS_ERROR
            route_span.error_text = str(route_exc)
            route_span.end_time = time.time()
            route_span.duration_ms = int((route_span.end_time - route_span.start_time) * 1000)
            _persist_span(route_span)
            raise

        if route_result.channel == "multi_metric":
            yield f"data: {json.dumps({'node': 'metric', 'status': 'progress', 'thread_id': thread_id, 'data': {'multi_metric_ids': route_result.multi_metric_ids, 'multi_sqls': [{k: v for k, v in s.items() if k != 'sql_params'} for s in route_result.multi_sqls]}}, ensure_ascii=False)}\n\n"

            execution_results = []
            for s in route_result.multi_sqls:
                yield f"data: {json.dumps({'node': 'metric', 'status': 'progress', 'thread_id': thread_id, 'data': {'metric_id': s['metric_id'], 'sql': s['sql'], 'explain': s['explain']}}, ensure_ascii=False)}\n\n"

                try:
                    with execution_connection() as conn, conn.cursor() as cur:
                        safe_sql = validate_sql(s["sql"])
                        # 先用 EXPLAIN 校验 SQL 语法/表名/字段名
                        cur.execute(f"EXPLAIN {safe_sql}", s.get("sql_params", []))
                        cur.execute(safe_sql, s.get("sql_params", []))
                        cols = [desc[0] for desc in cur.description] if cur.description else []
                        rows = cur.fetchall()
                        d = [[str(v) for v in row] for row in rows]
                        execution_results.append(
                            {
                                "success": True,
                                "columns": cols,
                                "rows": len(d),
                                "data": d[:50],
                                "metric_id": s["metric_id"],
                                "empty_result": len(d) == 0,
                                "empty_message": f"{s['metric_name']}暂无数据。" if len(d) == 0 else "",
                            }
                        )
                except Exception as exc:
                    execution_results.append(
                        {
                            "success": False,
                            "error": str(exc),
                            "metric_id": s["metric_id"],
                        }
                    )

            all_empty = all(r.get("empty_result", False) for r in execution_results if r.get("success"))
            multi_empty_message = ""
            if all_empty:
                multi_empty_message = "所有指标均暂无数据，可能是您指定的筛选条件没有匹配到数据。"

            done_event = {
                "node": "done",
                "status": "complete",
                "thread_id": thread_id,
                "request_id": chat_request_id,
                "trace_id": chat_request_id,
                "data": {
                    "channel": "multi_metric",
                    "multi_metric_ids": route_result.multi_metric_ids,
                    "execution_results": execution_results,
                    "empty_result": all_empty,
                    "empty_message": multi_empty_message,
                },
            }
            if request.user_id:
                total_rows = sum(r.get("rows", 0) for r in execution_results if r.get("success"))
                with suppress(Exception):
                    get_chat_repository().log_route(request.user_id, thread_id, "multi_metric", total_rows)
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
            clear_trace_context()
            return

        if route_result.channel == "clarify":
            yield f"data: {json.dumps({'node': 'clarify', 'status': 'progress', 'thread_id': thread_id, 'data': {'matched_term': route_result.matched_term, 'candidates': route_result.candidates, 'clarification_prompt': route_result.clarification_prompt}}, ensure_ascii=False)}\n\n"
            done_event = {
                "node": "done",
                "status": "complete",
                "thread_id": thread_id,
                "request_id": chat_request_id,
                "trace_id": chat_request_id,
                "data": {
                    "channel": "clarify",
                    "matched_term": route_result.matched_term,
                    "candidates": route_result.candidates,
                },
            }
            if request.user_id:
                with suppress(Exception):
                    get_chat_repository().log_route(request.user_id, thread_id, "clarify", 0)
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
            clear_trace_context()
            return

        if route_result.channel == "ask":
            yield f"data: {json.dumps({'node': 'ask', 'status': 'progress', 'thread_id': thread_id, 'data': {'metric_id': route_result.metric_id, 'metric_name': route_result.metric_name, 'clarification_prompt': route_result.clarification_prompt}}, ensure_ascii=False)}\n\n"
            done_event = {
                "node": "done",
                "status": "complete",
                "thread_id": thread_id,
                "request_id": chat_request_id,
                "trace_id": chat_request_id,
                "data": {
                    "channel": "ask",
                    "metric_id": route_result.metric_id,
                    "metric_name": route_result.metric_name,
                    "clarification_prompt": route_result.clarification_prompt,
                },
            }
            if request.user_id:
                with suppress(Exception):
                    get_chat_repository().log_route(request.user_id, thread_id, "ask", 0)
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
            clear_trace_context()
            return

        if route_result.channel == "metric":
            yield f"data: {json.dumps({'node': 'metric', 'status': 'progress', 'thread_id': thread_id, 'data': {'metric_id': route_result.metric_id, 'metric_name': route_result.metric_name, 'sql': route_result.sql, 'explain': route_result.explain, 'params': route_result.params}}, ensure_ascii=False)}\n\n"

            exec_span_id = str(uuid.uuid4())
            exec_span = SpanInfo(
                span_id=exec_span_id,
                trace_id=chat_request_id,
                node_name="metric_execute",
                span_type=SPAN_TYPE_DB,
                status=STATUS_SUCCESS,
                start_time=time.time(),
                input_data={"sql": route_result.sql[:500]},
            )
            try:
                with execution_connection() as conn, conn.cursor() as cur:
                    safe_sql = validate_sql(route_result.sql)
                    # 先用 EXPLAIN 校验 SQL 语法/表名/字段名
                    cur.execute(f"EXPLAIN {safe_sql}", route_result.sql_params)
                    cur.execute(safe_sql, route_result.sql_params)
                    columns = [desc[0] for desc in cur.description] if cur.description else []
                    rows = cur.fetchall()
                    data = [[str(v) for v in row] for row in rows]
                    empty_result = len(data) == 0
                    empty_message = ""
                    if empty_result:
                        if any(w in request.query for w in ("今天", "今日", "当天", "当日")):
                            empty_message = f"今天暂无{route_result.metric_name}数据，可能是今天还没有生产记录。"
                        elif any(w in request.query for w in ("昨天", "昨日")):
                            empty_message = f"昨天暂无{route_result.metric_name}数据。"
                        elif any(w in request.query for w in ("本周", "这周")):
                            empty_message = f"本周暂无{route_result.metric_name}数据。"
                        else:
                            empty_message = f"查询成功，但暂无{route_result.metric_name}数据。可能是您指定的筛选条件没有匹配到数据，请检查产线名、料号等参数是否正确。"
                    execution_result = {
                        "success": True,
                        "columns": columns,
                        "rows": len(data),
                        "data": data[:100],
                        "description": route_result.metric_name,
                        "empty_result": empty_result,
                        "empty_message": empty_message,
                    }
                exec_span.output_data = {"rows": len(data), "columns": columns[:10]}
                exec_span.end_time = time.time()
                exec_span.duration_ms = int((exec_span.end_time - exec_span.start_time) * 1000)
                _persist_span(exec_span)
            except Exception as exc:
                exec_span.status = STATUS_ERROR
                exec_span.error_text = str(exc)
                exec_span.end_time = time.time()
                exec_span.duration_ms = int((exec_span.end_time - exec_span.start_time) * 1000)
                _persist_span(exec_span)
                execution_result = {"success": False, "error": str(exc), "description": route_result.metric_name}

            summary = f"指标查询: {route_result.metric_name} ({route_result.metric_id}) SQL: {route_result.sql[:200]}"
            _persist_chat_session(thread_id, request, summary)

            if request.user_id:
                row_count = execution_result.get("rows", 0) if execution_result.get("success") else 0
                with suppress(Exception):
                    get_chat_repository().log_route(request.user_id, thread_id, "metric", row_count)

            done_event = {
                "node": "done",
                "status": "complete",
                "thread_id": thread_id,
                "request_id": chat_request_id,
                "trace_id": chat_request_id,
                "data": {
                    "channel": "metric",
                    "metric_id": route_result.metric_id,
                    "metric_name": route_result.metric_name,
                    "sql": route_result.sql,
                    "execution_results": [execution_result],
                    "final_sqls": [route_result.sql],
                    "empty_result": execution_result.get("empty_result", False),
                    "empty_message": execution_result.get("empty_message", ""),
                },
            }
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
            clear_trace_context()
            return

        # ── NL2SQL 通道（未命中指标，走 LangGraph 工作流）─────────
        session_history = _chat_sessions.get(thread_id, [])
        initial_state: dict = {"query": request.query}
        if session_history:
            initial_state["messages"] = session_history

        node_names: list[str] = []
        last_chunk: dict = {}
        try:
            async for chunk in _app.astream(initial_state, config, stream_mode="updates"):
                node_names = list(chunk.keys())
                last_chunk = chunk
                for node_name in node_names:
                    node_data = chunk[node_name]
                    event = {
                        "node": node_name,
                        "status": "progress",
                        "thread_id": thread_id,
                        "data": _summarize_node_output(node_name, node_data),
                    }
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            final_state = await _app.aget_state(config)
            state_values = final_state.values if final_state else {}

            last_node_name = node_names[-1] if node_names else ""
            last_node_data = last_chunk.get(last_node_name, {}) if last_chunk else {}
            done_data = _summarize_node_output(last_node_name, last_node_data)

            er_raw = state_values.get("execution_results", "") or last_node_data.get("execution_results", "")
            if isinstance(er_raw, str):
                try:
                    er = json.loads(er_raw)
                    done_data["execution_results"] = er
                except (json.JSONDecodeError, TypeError):
                    pass

            done_data["multi_sql"] = state_values.get("multi_sql", False)
            done_data["sub_queries"] = state_values.get("sub_queries", [])
            done_data["final_sqls"] = state_values.get("final_sqls", [])

            total_rows = 0

            # 非 MES 业务域问题：直接返回拒绝提示，不走 empty_message 逻辑
            if state_values.get("non_mes_domain", False):
                done_data["non_mes_domain"] = True
                done_data["error"] = "抱歉，您的问题不属于 MES 业务域范围，我无法回答。请提出与生产、质量、仓库、设备、基础数据等 MES 相关的问题。"
            else:
                exec_results = done_data.get("execution_results", [])
                if isinstance(exec_results, list):
                    all_success = all(r.get("success", False) for r in exec_results if isinstance(r, dict))
                    total_rows = sum(r.get("rows", 0) for r in exec_results if isinstance(r, dict) and r.get("success"))
                    if all_success and total_rows == 0:
                        if any(w in request.query for w in ("今天", "今日", "当天", "当日")):
                            done_data["empty_message"] = "今天暂无数据，可能是今天还没有生产记录。"
                        else:
                            done_data["empty_message"] = "查询成功，但暂无匹配数据。请检查筛选条件是否正确。"
                        done_data["empty_result"] = True

            done_data["channel"] = "nl2sql"

            session_history.append(HumanMessage(content=request.query))
            done_summary = _build_chat_summary(done_data)
            session_history.append(AIMessage(content=done_summary))
            if len(session_history) > 10:
                session_history = session_history[-10:]
            _chat_sessions[thread_id] = session_history

            if request.user_id:
                messages_payload = [
                    {"type": msg.__class__.__name__, "content": msg.content} for msg in session_history
                ]
                try:
                    get_chat_repository().save_session(request.user_id, thread_id, messages_payload)
                except Exception as exc:
                    logger.warning("聊天历史持久化失败: %s", exc)

            if request.user_id:
                with suppress(Exception):
                    get_chat_repository().log_route(request.user_id, thread_id, "nl2sql", total_rows)

            done_event = {
                "node": "done",
                "status": "complete",
                "thread_id": thread_id,
                "request_id": chat_request_id,
                "trace_id": chat_request_id,
                "data": done_data,
            }
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"

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


# ── 聊天历史 API ───────────────────────────────────────────────


@router.get("/chat/history", response_model=ChatHistoryListResponse)
async def list_chat_history(user_id: str, limit: int = 50):
    """获取用户的所有对话记录列表。"""
    sessions = get_chat_repository().list_user_sessions(user_id, limit)
    return ChatHistoryListResponse(sessions=[ChatHistoryItem(**s) for s in sessions])


@router.get("/chat/history/{thread_id}", response_model=ChatThreadResponse)
async def get_chat_thread(thread_id: str, user_id: str):
    """获取指定对话线程的完整消息记录。"""
    messages = get_chat_repository().load_session(user_id, thread_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="对话记录不存在")
    return ChatThreadResponse(thread_id=thread_id, user_id=user_id, messages=messages)
