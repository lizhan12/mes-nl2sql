import { Clock, Search, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { fetchRecentTraces, fetchTrace } from "@/lib/api";
import type { RecentTrace, TraceSpan } from "@/types";

export default function TracePage() {
  const [traces, setTraces] = useState<RecentTrace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [spans, setSpans] = useState<TraceSpan[]>([]);
  const [spanLoading, setSpanLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetchRecentTraces(50);
      setTraces(res.traces);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function openTrace(traceId: string) {
    setSelectedTraceId(traceId);
    setSpanLoading(true);
    try {
      const res = await fetchTrace(traceId);
      setSpans(res.spans);
    } catch {
      setSpans([]);
    } finally {
      setSpanLoading(false);
    }
  }

  function formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center border-b border-[var(--border-default)] px-4 py-3">
        <h2 className="font-display text-sm font-semibold text-[var(--text-primary)]">链路追踪</h2>
      </div>

      {error && (
        <div className="mx-4 mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧：最近追踪列表 */}
        <div className="flex w-64 shrink-0 flex-col border-r border-[var(--border-default)]">
          <div className="flex items-center justify-between border-b border-[var(--border-default)] px-3 py-2">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">最近查询</span>
            <button type="button" onClick={load} className="rounded p-0.5 text-[var(--text-tertiary)] hover:text-[var(--accent)]">
              <Clock className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="flex-1 overflow-auto">
            {loading ? (
              <div className="py-4 text-center text-[11px] text-[var(--text-tertiary)]">加载中...</div>
            ) : traces.length === 0 ? (
              <div className="py-4 text-center text-[11px] text-[var(--text-tertiary)]">暂无数据</div>
            ) : (
              traces.map((t) => (
                <button
                  key={t.trace_id}
                  type="button"
                  onClick={() => openTrace(t.trace_id)}
                  className={`w-full border-b border-[var(--border-default)] px-3 py-2 text-left transition-colors hover:bg-[var(--bg-subtle)] ${
                    selectedTraceId === t.trace_id ? "border-l-2 border-l-[var(--accent)] bg-[var(--accent-surface)]" : "border-l-2 border-l-transparent"
                  }`}
                >
                  <div className="truncate text-[11px] text-[var(--text-primary)]">{t.query_text || "(无查询)"}</div>
                  <div className="mt-0.5 flex items-center gap-2">
                    <span className="font-mono text-[10px] text-[var(--text-tertiary)]">{new Date(t.created_at).toLocaleString()}</span>
                    {t.total_duration_ms != null && (
                      <span className="font-mono text-[10px] text-[var(--accent)]">{formatDuration(t.total_duration_ms)}</span>
                    )}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* 右侧：追踪详情 */}
        <div className="flex-1 overflow-auto p-4">
          {!selectedTraceId ? (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <Search className="mx-auto mb-2 h-8 w-8 opacity-20 text-[var(--text-tertiary)]" />
                <span className="text-xs text-[var(--text-tertiary)]">请从左侧选择一条追踪查看详情</span>
              </div>
            </div>
          ) : spanLoading ? (
            <div className="py-8 text-center text-xs text-[var(--text-tertiary)]">加载中...</div>
          ) : spans.length === 0 ? (
            <div className="py-8 text-center text-xs text-[var(--text-tertiary)]">无 span 数据</div>
          ) : (
            <div className="space-y-2">
              {spans.map((span) => (
                <div key={span.span_id} className="rounded border border-[var(--border-default)] bg-[var(--bg-default)] p-3">
                  <div className="mb-1 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-[var(--accent-surface)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--accent)]">
                        {span.node_name || span.span_id}
                      </span>
                      <span className={`rounded-full h-2 w-2 ${span.status === "error" ? "bg-[var(--error)]" : "bg-[var(--success)]"}`} />
                    </div>
                    {span.duration_ms != null && (
                      <span className="font-mono text-[10px] text-[var(--text-tertiary)] flex items-center gap-1">
                        <TrendingUp className="h-3 w-3" />
                        {formatDuration(span.duration_ms)}
                      </span>
                    )}
                  </div>
                  {span.input_json && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-[11px] text-[var(--text-secondary)]">输入</summary>
                      <pre className="mt-1 max-h-32 overflow-auto rounded bg-[var(--bg-subtle)] p-2 font-mono text-[10px] whitespace-pre-wrap text-[var(--text-primary)]">{JSON.stringify(span.input_json, null, 2)}</pre>
                    </details>
                  )}
                  {span.output_json && (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-[11px] text-[var(--text-secondary)]">输出</summary>
                      <pre className="mt-1 max-h-32 overflow-auto rounded bg-[var(--bg-subtle)] p-2 font-mono text-[10px] whitespace-pre-wrap text-[var(--text-primary)]">{JSON.stringify(span.output_json, null, 2)}</pre>
                    </details>
                  )}
                  {span.error_text && (
                    <div className="mt-1 rounded border border-red-300 bg-red-50 px-2 py-1 text-[10px] text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">{span.error_text}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
