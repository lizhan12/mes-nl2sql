"""Trace Span 数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Span 类型常量 ──
SPAN_TYPE_NODE = "node"
SPAN_TYPE_LLM = "llm_call"
SPAN_TYPE_EMBEDDING = "embedding"
SPAN_TYPE_DB = "db_query"

# ── 状态常量 ──
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"

# ── 节点中文名映射 ──
NODE_NAME_MAP: dict[str, str] = {
    "intent": "意图理解",
    "retrieval": "并行检索",
    "bfs": "BFS图扩展",
    "schema": "Schema组装",
    "sql_gen": "SQL生成",
    "safety": "安全校验",
    "execute": "执行与修复",
}

# ── Token 费用定价 (USD / 1K tokens) ──
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0015, 0.002),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """估算 LLM 调用费用（USD）。"""
    pricing = _MODEL_PRICING.get(model, (0, 0))
    prompt_cost = (prompt_tokens / 1000) * pricing[0]
    completion_cost = (completion_tokens / 1000) * pricing[1]
    return round(prompt_cost + completion_cost, 6)


@dataclass
class SpanInfo:
    """单个 trace span 的信息。"""

    span_id: str
    trace_id: str
    node_name: str
    span_type: str = SPAN_TYPE_NODE
    parent_span_id: str = ""
    status: str = STATUS_RUNNING
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: int = 0
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    error_text: str = ""
    # LLM 专属
    llm_model: str = ""
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0
    prompt_preview: str = ""
    response_preview: str = ""
    # 元数据
    retry_seq: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def estimated_cost_usd(self) -> float:
        """估算本次 LLM 调用的费用。"""
        if self.span_type != SPAN_TYPE_LLM or not self.llm_model:
            return 0.0
        return estimate_cost(self.llm_model, self.llm_prompt_tokens, self.llm_completion_tokens)


@dataclass
class TraceSummary:
    """单次请求的 trace 摘要。"""

    trace_id: str
    thread_id: str
    query_text: str = ""
    total_duration_ms: int = 0
    node_count: int = 0
    llm_call_count: int = 0
    status: str = STATUS_SUCCESS
    spans: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
