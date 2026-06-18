"""全链路 Trace 追踪模块。

提供 LangGraph 工作流各节点的结构化追踪能力，
包括执行耗时、LLM token 消耗、输入/输出摘要等。
"""

from src.trace.models import (
    NODE_NAME_MAP,
    SPAN_TYPE_DB,
    SPAN_TYPE_EMBEDDING,
    SPAN_TYPE_LLM,
    SPAN_TYPE_NODE,
    STATUS_ERROR,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    SpanInfo,
    TraceSummary,
)
from src.trace.repository import TraceRepository, get_trace_repository
from src.trace.tracer import (
    clear_trace_context,
    flush_trace,
    set_trace_context,
    trace_llm_call,
    trace_node,
)

__all__ = [
    "SpanInfo",
    "TraceSummary",
    "TraceRepository",
    "get_trace_repository",
    "trace_node",
    "trace_llm_call",
    "set_trace_context",
    "clear_trace_context",
    "flush_trace",
    # 常量
    "SPAN_TYPE_NODE",
    "SPAN_TYPE_LLM",
    "SPAN_TYPE_EMBEDDING",
    "SPAN_TYPE_DB",
    "STATUS_RUNNING",
    "STATUS_SUCCESS",
    "STATUS_ERROR",
    "NODE_NAME_MAP",
]
