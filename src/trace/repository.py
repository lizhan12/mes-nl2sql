"""Trace Span 数据库仓储。

使用 AppPool 连接池，按 psycopg 原生 SQL 模式操作 nl2sql_trace_span 表。
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Any

from src.services.db_pool import app_connection
from src.trace.models import STATUS_SUCCESS, SpanInfo, TraceSummary


class TraceRepository:
    """Trace span 的数据库存取。"""

    def ensure_tables(self) -> None:
        """创建 trace span 表及索引。"""
        ddl = """
        CREATE TABLE IF NOT EXISTS nl2sql_trace_span (
            id BIGSERIAL PRIMARY KEY,
            span_id UUID NOT NULL,
            trace_id UUID NOT NULL,
            thread_id TEXT NOT NULL DEFAULT '',
            parent_span_id UUID,
            node_name TEXT NOT NULL,
            span_type TEXT NOT NULL DEFAULT 'node',
            status TEXT NOT NULL DEFAULT 'running',
            start_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            end_time TIMESTAMPTZ,
            duration_ms INTEGER,
            input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_text TEXT NOT NULL DEFAULT '',
            llm_model TEXT NOT NULL DEFAULT '',
            llm_prompt_tokens INTEGER,
            llm_completion_tokens INTEGER,
            llm_total_tokens INTEGER,
            prompt_preview TEXT NOT NULL DEFAULT '',
            response_preview TEXT NOT NULL DEFAULT '',
            retry_seq INTEGER NOT NULL DEFAULT 0,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_trace_span_trace_id
            ON nl2sql_trace_span(trace_id);
        CREATE INDEX IF NOT EXISTS idx_trace_span_thread_id
            ON nl2sql_trace_span(thread_id);
        CREATE INDEX IF NOT EXISTS idx_trace_span_node_name
            ON nl2sql_trace_span(node_name);
        CREATE INDEX IF NOT EXISTS idx_trace_span_parent
            ON nl2sql_trace_span(parent_span_id);
        CREATE INDEX IF NOT EXISTS idx_trace_span_start_time
            ON nl2sql_trace_span(start_time DESC);
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(ddl)
            conn.commit()

    def insert_span(self, span: SpanInfo, thread_id: str) -> None:
        """插入单条 span 记录。"""
        sql = """
        INSERT INTO nl2sql_trace_span (
            span_id, trace_id, thread_id, parent_span_id, node_name, span_type,
            status, start_time, end_time, duration_ms,
            input_json, output_json, error_text,
            llm_model, llm_prompt_tokens, llm_completion_tokens, llm_total_tokens,
            prompt_preview, response_preview, retry_seq, metadata_json
        ) VALUES (
            %(span_id)s, %(trace_id)s, %(thread_id)s, %(parent_span_id)s,
            %(node_name)s, %(span_type)s, %(status)s,
            %(start_time)s, %(end_time)s, %(duration_ms)s,
            %(input_json)s::jsonb, %(output_json)s::jsonb, %(error_text)s,
            %(llm_model)s, %(llm_prompt_tokens)s, %(llm_completion_tokens)s, %(llm_total_tokens)s,
            %(prompt_preview)s, %(response_preview)s, %(retry_seq)s, %(metadata_json)s::jsonb
        )
        """
        end_time = _ts_or_none(span.end_time)
        start_time = _ts_or_none(span.start_time)
        params = {
            "span_id": span.span_id,
            "trace_id": span.trace_id,
            "thread_id": thread_id,
            "parent_span_id": span.parent_span_id or None,
            "node_name": span.node_name,
            "span_type": span.span_type,
            "status": span.status,
            "start_time": start_time,
            "end_time": end_time,
            "duration_ms": span.duration_ms or None,
            "input_json": json.dumps(span.input_data, ensure_ascii=False, default=str),
            "output_json": json.dumps(span.output_data, ensure_ascii=False, default=str),
            "error_text": span.error_text,
            "llm_model": span.llm_model,
            "llm_prompt_tokens": span.llm_prompt_tokens or None,
            "llm_completion_tokens": span.llm_completion_tokens or None,
            "llm_total_tokens": span.llm_total_tokens or None,
            "prompt_preview": span.prompt_preview,
            "response_preview": span.response_preview,
            "retry_seq": span.retry_seq,
            "metadata_json": json.dumps(span.metadata, ensure_ascii=False, default=str),
        }
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()

    def batch_insert_spans(self, spans: list[SpanInfo], thread_id: str) -> None:
        """批量插入 span 记录。"""
        if not spans:
            return
        for span in spans:
            self.insert_span(span, thread_id)

    def query_by_trace_id(self, trace_id: str) -> list[dict[str, Any]]:
        """根据 trace_id 查询所有 span，按 start_time 排序。"""
        sql = """
        SELECT span_id, trace_id, thread_id, parent_span_id, node_name, span_type,
               status, start_time, end_time, duration_ms,
               input_json, output_json, error_text,
               llm_model, llm_prompt_tokens, llm_completion_tokens, llm_total_tokens,
               prompt_preview, response_preview, retry_seq, metadata_json, created_at
        FROM nl2sql_trace_span
        WHERE trace_id = %(trace_id)s
        ORDER BY start_time ASC
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"trace_id": trace_id})
            rows = cur.fetchall()
        return [_row_to_dict(row) for row in rows]

    def query_by_thread_id(self, thread_id: str) -> list[dict[str, Any]]:
        """根据 thread_id 查询所有 span，按 start_time 排序。"""
        sql = """
        SELECT span_id, trace_id, thread_id, parent_span_id, node_name, span_type,
               status, start_time, end_time, duration_ms,
               input_json, output_json, error_text,
               llm_model, llm_prompt_tokens, llm_completion_tokens, llm_total_tokens,
               prompt_preview, response_preview, retry_seq, metadata_json, created_at
        FROM nl2sql_trace_span
        WHERE thread_id = %(thread_id)s
        ORDER BY start_time ASC
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"thread_id": thread_id})
            rows = cur.fetchall()
        return [_row_to_dict(row) for row in rows]

    def query_recent_traces(self, limit: int = 50) -> list[TraceSummary]:
        """查询最近的 trace 摘要列表。"""
        sql = """
        SELECT
            trace_id,
            thread_id,
            MIN(start_time) AS start_time,
            MAX(COALESCE(duration_ms, 0)) AS max_duration,
            COUNT(*) AS node_count,
            COUNT(*) FILTER (WHERE span_type = 'llm_call') AS llm_call_count,
            BOOL_AND(status = 'success') AS all_success,
            SUM(COALESCE(llm_total_tokens, 0)) AS total_tokens,
            (SELECT input_json->>'query'
             FROM nl2sql_trace_span AS s2
             WHERE s2.trace_id = nl2sql_trace_span.trace_id
               AND s2.node_name = 'intent'
               AND s2.span_type = 'node'
             LIMIT 1) AS query_text
        FROM nl2sql_trace_span
        GROUP BY trace_id, thread_id
        ORDER BY start_time DESC
        LIMIT %(limit)s
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"limit": limit})
            rows = cur.fetchall()

        summaries: list[TraceSummary] = []
        for row in rows:
            query_text = str(row["query_text"] or "")
            summaries.append(
                TraceSummary(
                    trace_id=str(row["trace_id"]),
                    thread_id=str(row["thread_id"]),
                    query_text=query_text,
                    total_duration_ms=int(row["max_duration"] or 0),
                    node_count=int(row["node_count"] or 0),
                    llm_call_count=int(row["llm_call_count"] or 0),
                    status=STATUS_SUCCESS if row["all_success"] else "error",
                    created_at=str(row["start_time"] or ""),
                    total_tokens=int(row["total_tokens"] or 0),
                )
            )
        return summaries

    def get_trace_stats(self, node_name: str = "", days: int = 7) -> dict[str, Any]:
        """获取 trace 统计信息：各节点平均耗时、P50/P95/P99、token 消耗等。"""
        node_filter = "AND node_name = %(node_name)s" if node_name else ""

        stats_sql = f"""
        SELECT
            node_name,
            COUNT(*) AS cnt,
            AVG(duration_ms)::INTEGER AS avg_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms)::INTEGER AS p50_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::INTEGER AS p95_ms,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms)::INTEGER AS p99_ms,
            COUNT(*) FILTER (WHERE status = 'error') AS error_cnt,
            AVG(llm_total_tokens)::NUMERIC(10,1) AS avg_tokens,
            SUM(llm_total_tokens)::BIGINT AS total_tokens
        FROM nl2sql_trace_span
        WHERE start_time >= NOW() - INTERVAL '{days} days'
          {node_filter}
        GROUP BY node_name
        ORDER BY node_name
        """
        params: dict = {"node_name": node_name, "days": days}

        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(stats_sql, params)
            rows = cur.fetchall()

        nodes_stats = {}
        for row in rows:
            nodes_stats[str(row["node_name"])] = {
                "count": int(row["cnt"]),
                "avg_ms": int(row["avg_ms"] or 0),
                "p50_ms": int(row["p50_ms"] or 0),
                "p95_ms": int(row["p95_ms"] or 0),
                "p99_ms": int(row["p99_ms"] or 0),
                "error_count": int(row["error_cnt"]),
                "avg_tokens": float(row["avg_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
            }

        return {"nodes": nodes_stats, "days": days}

    def cleanup_old_spans(self, retention_days: int = 30) -> int:
        """删除超过保留期限的 span 数据。"""
        sql = """
        DELETE FROM nl2sql_trace_span
        WHERE start_time < NOW() - INTERVAL '%s days'
        """
        with app_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (retention_days,))
            deleted = cur.rowcount
            conn.commit()
        return deleted


def _ts_or_none(ts: float) -> str | None:
    """将 Unix 时间戳转为 ISO 字符串，0 表示 NULL。"""
    if ts <= 0:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将 psycopg 查询行转为 plain dict，处理 JSONB 字段。"""
    d = dict(row)
    for json_field in ("input_json", "output_json", "metadata_json"):
        val = d.get(json_field)
        if isinstance(val, str):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                d[json_field] = json.loads(val)
    # 时间戳转字符串
    for ts_field in ("start_time", "end_time", "created_at"):
        val = d.get(ts_field)
        if val is not None and not isinstance(val, str):
            d[ts_field] = str(val)
    return d


_repository: TraceRepository | None = None


def get_trace_repository() -> TraceRepository:
    """获取全局 TraceRepository 单例。"""
    global _repository
    if _repository is None:
        _repository = TraceRepository()
    return _repository
