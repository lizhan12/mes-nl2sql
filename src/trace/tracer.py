"""Trace 核心追踪逻辑。

提供：
  - @trace_node 装饰器：自动为 LangGraph 节点函数创建 span
  - trace_llm_call()：包裹 LLM 调用，捕获 token 用量和耗时
  - set_trace_context / clear_trace_context：管理请求级 trace 上下文（基于 contextvars）
  - flush_trace()：批量持久化内存中的 spans

持久化策略：
  - 流式请求：每个 span 完成后立即写入 DB
  - 非流式请求：暂存内存，请求结束后批量写入
"""

from __future__ import annotations

import functools
import logging
import time
import traceback
import uuid
from contextvars import ContextVar
from typing import Any

from src.core.config import settings
from src.services.llm import get_llm
from src.trace.models import SPAN_TYPE_LLM, SPAN_TYPE_NODE, STATUS_ERROR, STATUS_RUNNING, STATUS_SUCCESS, SpanInfo
from src.trace.repository import get_trace_repository

logger = logging.getLogger(__name__)

# ── contextvars：每个请求独立的 trace 上下文 ──
_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")
_thread_id_ctx: ContextVar[str] = ContextVar("thread_id", default="")
_streaming_mode_ctx: ContextVar[bool] = ContextVar("streaming_mode", default=False)
_span_buffer_ctx: ContextVar[list[SpanInfo] | None] = ContextVar("span_buffer", default=None)
_active_node_ctx: ContextVar[str] = ContextVar("active_node", default="")  # 当前活跃节点名（用于 LLM span 的 parent）

# ── 预览截断长度 ──
_MAX_PREVIEW_CHARS = 500


def _get_span_buffer() -> list[SpanInfo]:
    """获取当前上下文中的 span 缓冲区（懒初始化）。"""
    buf = _span_buffer_ctx.get()
    if buf is None:
        buf = []
        _span_buffer_ctx.set(buf)
    return buf


def set_trace_context(trace_id: str, thread_id: str, streaming: bool = False) -> None:
    """设置当前请求的 trace 上下文。在 API 入口处调用一次。"""
    _trace_id_ctx.set(trace_id)
    _thread_id_ctx.set(thread_id)
    _streaming_mode_ctx.set(streaming)
    _span_buffer_ctx.set([])
    _active_node_ctx.set("")


def clear_trace_context() -> None:
    """清除当前请求的 trace 上下文。请求结束后调用。"""
    _trace_id_ctx.set("")
    _thread_id_ctx.set("")
    _streaming_mode_ctx.set(False)
    _span_buffer_ctx.set(None)
    _active_node_ctx.set("")


def flush_trace() -> None:
    """将内存缓冲区中的所有 span 批量写入 DB（非流式模式）。"""
    spans = _get_span_buffer()
    if not spans:
        return
    thread_id = _thread_id_ctx.get()
    try:
        get_trace_repository().batch_insert_spans(spans, thread_id)
        logger.info("Trace: 批量写入 %d 条 span 完成 (trace_id=%s)", len(spans), _trace_id_ctx.get())
    except Exception as exc:
        logger.warning("Trace: 批量写入 span 失败: %s", exc)
    finally:
        _span_buffer_ctx.set([])


def _persist_span(span: SpanInfo) -> None:
    """根据模式决定 span 的持久化方式。"""
    if _streaming_mode_ctx.get():
        # 流式模式：立即写入 DB
        try:
            get_trace_repository().insert_span(span, _thread_id_ctx.get())
        except Exception as exc:
            logger.warning("Trace: 写入 span 失败 (span_id=%s): %s", span.span_id, exc)
    else:
        # 非流式模式：追加到内存缓冲区
        _get_span_buffer().append(span)


def _truncate(text: str, max_chars: int = _MAX_PREVIEW_CHARS) -> str:
    """截断文本用于预览存储。"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... (截断, 总长 {len(text)})"


def _summarize_state(state: dict[str, Any], keys_to_include: list[str] | None = None) -> dict[str, Any]:
    """从 GraphState 中提取摘要信息。"""
    if keys_to_include is None:
        # 默认提取所有非 messages 字段
        keys_to_include = [k for k in state if k != "messages"]
    summary: dict[str, Any] = {}
    for k in keys_to_include:
        val = state.get(k)
        if val is None:
            continue
        if isinstance(val, str) and len(val) > _MAX_PREVIEW_CHARS:
            summary[k] = _truncate(val)
        elif isinstance(val, list):
            summary[k] = f"[{len(val)} 项]"
        else:
            summary[k] = val
    return summary


def _summarize_output(output: dict[str, Any]) -> dict[str, Any]:
    """从节点返回值中提取摘要信息。"""
    summary: dict[str, Any] = {}
    for k, v in output.items():
        if v is None:
            continue
        if isinstance(v, str) and len(v) > _MAX_PREVIEW_CHARS:
            summary[k] = _truncate(v)
        elif isinstance(v, list):
            if v and isinstance(v[0], str):
                preview = [item if len(str(item)) <= 100 else str(item)[:100] + "..." for item in v[:3]]
                if len(v) > 3:
                    preview.append(f"... 共 {len(v)} 项")
                summary[k] = preview
            else:
                summary[k] = f"[{len(v)} 项]"
        else:
            summary[k] = v
    return summary


# ── trace_node 装饰器 ──


def trace_node(node_name: str, span_type: str = SPAN_TYPE_NODE):
    """装饰器：为 LangGraph 节点函数添加 trace span。

    自动记录：
      - 节点执行耗时 (duration_ms)
      - 输入 state 摘要 (input_json)
      - 输出 dict 摘要 (output_json)
      - 异常信息 (error_text)

    Args:
        node_name: 节点标识名 (intent/retrieval/bfs/schema/sql_gen/safety/execute)
        span_type: span 类型 (默认 "node")
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            trace_id = _trace_id_ctx.get()
            if not trace_id or not settings.trace_enabled:
                return func(state)

            span_id = str(uuid.uuid4())
            span = SpanInfo(
                span_id=span_id,
                trace_id=trace_id,
                node_name=node_name,
                span_type=span_type,
                status=STATUS_RUNNING,
                start_time=time.time(),
                input_data=_summarize_state(state),
            )
            # 设置当前活跃节点
            prev_node = _active_node_ctx.get()
            _active_node_ctx.set(node_name)

            try:
                result = func(state)
                span.status = STATUS_SUCCESS
                span.output_data = _summarize_output(result)
                span.end_time = time.time()
                span.duration_ms = int((span.end_time - span.start_time) * 1000)
                _persist_span(span)
                _active_node_ctx.set(prev_node)
                return result
            except Exception as exc:
                span.status = STATUS_ERROR
                span.error_text = f"{type(exc).__name__}: {exc}"
                span.output_data = {"error": str(exc), "traceback": traceback.format_exc()[-2000:]}
                span.end_time = time.time()
                span.duration_ms = int((span.end_time - span.start_time) * 1000)
                _persist_span(span)
                _active_node_ctx.set(prev_node)
                raise

        return wrapper

    return decorator


# ── trace_llm_call：包裹 LLM 调用 ──


def trace_llm_call(
    prompt: str,
    *,
    node_name: str = "",
    retry_seq: int = 0,
    model: str = "",
) -> Any:
    """包裹 LLM 调用，自动创建 llm_call span 并捕获 token 用量。

    调用方式：
        # 替换原来的 llm.invoke(prompt)
        response = trace_llm_call(prompt, node_name="sql_gen")

    Args:
        prompt: 完整的 prompt 文本
        node_name: 所属节点名（用作 parent_span 关联）
        retry_seq: 重试序号（0=首次）
        model: LLM 模型名（为空则从 settings.llm_model 读取）

    Returns:
        LLM 的 AIMessage 响应对象（与 llm.invoke() 一致）
    """
    trace_id = _trace_id_ctx.get()
    if not trace_id or not settings.trace_enabled:
        llm = get_llm(model or settings.llm_model)
        return llm.invoke(prompt)

    span_id = str(uuid.uuid4())
    actual_node = node_name or _active_node_ctx.get() or "unknown"
    actual_model = model or settings.llm_model

    span = SpanInfo(
        span_id=span_id,
        trace_id=trace_id,
        node_name=actual_node,
        span_type=SPAN_TYPE_LLM,
        parent_span_id="",
        status=STATUS_RUNNING,
        start_time=time.time(),
        input_data={"prompt_length": len(prompt)},
        prompt_preview=_truncate(prompt),
        llm_model=actual_model,
        retry_seq=retry_seq,
    )

    try:
        llm = get_llm(actual_model)
        response = llm.invoke(prompt)

        # 提取 token 用量
        content = response.content if hasattr(response, "content") else str(response)
        token_usage: dict[str, Any] = {}
        try:
            response_metadata = getattr(response, "response_metadata", {}) or {}
            token_usage = response_metadata.get("token_usage", {})
        except Exception:
            pass

        span.status = STATUS_SUCCESS
        span.output_data = {"response_length": len(content)}
        span.response_preview = _truncate(content)
        span.llm_prompt_tokens = int(token_usage.get("prompt_tokens", 0))
        span.llm_completion_tokens = int(token_usage.get("completion_tokens", 0))
        span.llm_total_tokens = int(token_usage.get("total_tokens", 0))
        span.end_time = time.time()
        span.duration_ms = int((span.end_time - span.start_time) * 1000)
        _persist_span(span)

        return response

    except Exception as exc:
        span.status = STATUS_ERROR
        span.error_text = f"{type(exc).__name__}: {exc}"
        span.end_time = time.time()
        span.duration_ms = int((span.end_time - span.start_time) * 1000)
        _persist_span(span)
        raise
