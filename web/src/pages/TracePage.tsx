import { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Cpu,
  ExternalLink,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react";
import { fetchRecentTraces, fetchTrace } from "@/lib/api";
import type { RecentTrace, TraceSpan } from "@/types";

const NODE_LABELS: Record<string, string> = {
  intent: "意图理解",
  retrieval: "并行检索",
  bfs: "BFS图扩展",
  schema: "Schema组装",
  sql_gen: "SQL生成",
  safety: "安全校验",
  execute: "执行与修复",
};

const NODE_ORDER = ["intent", "retrieval", "bfs", "schema", "sql_gen", "safety", "execute"];

export default function TracePage() {
  const [traces, setTraces] = useState<RecentTrace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detailSpans, setDetailSpans] = useState<TraceSpan[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [expandedLlmId, setExpandedLlmId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const loadTraces = () => {
    setLoading(true);
    setError("");
    fetchRecentTraces(100)
      .then((res) => setTraces(res.traces))
      .catch((e) => setError(e.message || "加载失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadTraces();
  }, []);

  const loadDetail = (traceId: string) => {
    setDetailLoading(true);
    fetchTrace(traceId)
      .then((res) => setDetailSpans(res.spans))
      .catch(() => setDetailSpans([]))
      .finally(() => setDetailLoading(false));
  };

  const toggleExpand = (traceId: string) => {
    if (expandedId === traceId) {
      setExpandedId(null);
      setDetailSpans([]);
      setExpandedLlmId(null);
    } else {
      setExpandedId(traceId);
      setExpandedLlmId(null);
      loadDetail(traceId);
    }
  };

  const formatMs = (ms: number) => {
    if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
    return `${ms}ms`;
  };

  const formatTokensPerSec = (tokens: number, durationMs: number) => {
    if (!tokens || !durationMs) return "-";
    const tps = tokens / (durationMs / 1000);
    if (tps >= 100) return `${tps.toFixed(0)} tok/s`;
    return `${tps.toFixed(1)} tok/s`;
  };

  const formatTime = (iso: string) => {
    if (!iso) return "-";
    try {
      const d = new Date(iso);
      return d.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  const getBarWidth = (ms: number, maxMs: number) =>
    `${Math.max((ms / Math.max(maxMs, 1)) * 100, 1)}%`;

  const filteredTraces = searchQuery
    ? traces.filter(
        (t) =>
          t.query_text.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.trace_id.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : traces;

  // ── 渲染 ──────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex items-center gap-2 text-gray-400">
          <Clock className="animate-spin" size={20} />
          加载 Trace 数据...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-red-500 flex items-center gap-2">
          <XCircle size={20} />
          {error}
          <button onClick={loadTraces} className="ml-2 text-blue-500 hover:underline text-sm">
            重试
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* 头部 */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">链路追踪</h1>
            <p className="text-sm text-gray-500 mt-1">
              共 {traces.length} 条 Trace 记录 · 每次 NL2SQL 请求的完整执行链路
            </p>
          </div>
          <button
            onClick={loadTraces}
            className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
          >
            <RefreshCw size={14} />
            刷新
          </button>
        </div>

        {/* 搜索框 */}
        <div className="mb-4 relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="搜索查询内容或 Trace ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
        </div>

        {/* Trace 列表 */}
        {filteredTraces.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            {searchQuery ? "无匹配的 Trace 记录" : "暂无 Trace 记录"}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredTraces.map((trace) => {
              const isExpanded = expandedId === trace.trace_id;
              const nodeSpans = detailSpans
                .filter((s) => s.span_type === "node")
                .sort((a, b) => NODE_ORDER.indexOf(a.node_name) - NODE_ORDER.indexOf(b.node_name));
              const llmSpans = detailSpans.filter((s) => s.span_type === "llm_call");
              const allDurations = nodeSpans.map((s) => s.duration_ms).filter((d) => d > 0);
              const maxDuration = Math.max(...allDurations, 1);

              return (
                <div
                  key={trace.trace_id}
                  className={`bg-white rounded-lg border transition-colors ${
                    isExpanded ? "border-blue-300 shadow-sm" : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  {/* 摘要行 */}
                  <button
                    onClick={() => toggleExpand(trace.trace_id)}
                    className="w-full text-left px-4 py-3 flex items-center gap-4"
                  >
                    {/* 状态 */}
                    {trace.status === "success" ? (
                      <CheckCircle size={18} className="text-green-500 shrink-0" />
                    ) : (
                      <AlertCircle size={18} className="text-red-500 shrink-0" />
                    )}

                    {/* 时间 */}
                    <span className="text-xs text-gray-400 w-36 shrink-0">
                      {formatTime(trace.created_at)}
                    </span>

                    {/* 查询文本 */}
                    <span className="text-sm text-gray-800 truncate flex-1 min-w-0">
                      {trace.query_text || "(未记录查询)"}
                    </span>

                    {/* 指标 */}
                    <div className="flex items-center gap-4 text-xs shrink-0">
                      <span className="text-gray-500">
                        <span className="font-medium text-gray-700">{formatMs(trace.total_duration_ms)}</span>
                      </span>
                      <span className="text-gray-400">
                        {trace.node_count} 阶段
                      </span>
                      <span className={`font-medium ${trace.llm_call_count > 0 ? "text-purple-600" : "text-gray-400"}`}>
                        {trace.llm_call_count} 次LLM
                      </span>
                      {trace.total_tokens > 0 && (
                        <span className="text-gray-400">
                          {trace.total_tokens.toLocaleString()} tokens
                        </span>
                      )}
                    </div>

                    {/* Trace ID */}
                    <span className="text-xs text-gray-300 font-mono w-24 shrink-0 truncate">
                      {trace.trace_id.slice(0, 8)}
                    </span>

                    {/* 展开/收起 */}
                    {isExpanded ? (
                      <ChevronUp size={16} className="text-gray-400 shrink-0" />
                    ) : (
                      <ChevronDown size={16} className="text-gray-400 shrink-0" />
                    )}
                  </button>

                  {/* 展开详情：阶段时间线 */}
                  {isExpanded && (
                    <div className="border-t border-gray-100 px-4 py-3">
                      {detailLoading ? (
                        <div className="flex items-center justify-center py-8 text-gray-400 text-sm">
                          <Clock className="animate-spin mr-2" size={14} />
                          加载详情...
                        </div>
                      ) : nodeSpans.length === 0 ? (
                        <div className="text-center py-6 text-gray-400 text-sm">暂无 Span 数据</div>
                      ) : (
                        <div className="space-y-1.5">
                          {/* 阶段时间线总览 */}
                          <div className="text-xs text-gray-400 mb-3 flex items-center gap-2">
                            <Clock size={12} />
                            各阶段耗时分布 · 总耗时 {formatMs(allDurations.reduce((s, d) => s + d, 0))}
                            · {nodeSpans.length} 个阶段 · {llmSpans.length} 次 LLM 调用
                          </div>

                          {NODE_ORDER.map((nodeName) => {
                            const span = nodeSpans.find((s) => s.node_name === nodeName);
                            if (!span) return null;

                            const nodeLlms = llmSpans.filter((s) => s.node_name === nodeName);
                            const isError = span.status === "error";

                            return (
                              <div key={span.span_id} className="flex items-center gap-3 text-sm">
                                {/* 阶段名 */}
                                <div className="w-24 shrink-0 flex items-center gap-1.5">
                                  {isError ? (
                                    <AlertCircle size={14} className="text-red-500" />
                                  ) : (
                                    <Cpu size={14} className="text-blue-500" />
                                  )}
                                  <span className={`text-xs font-medium ${isError ? "text-red-600" : "text-gray-700"}`}>
                                    {NODE_LABELS[nodeName] || nodeName}
                                  </span>
                                </div>

                                {/* 耗时条 */}
                                <div className="flex-1 h-5 bg-gray-100 rounded-full overflow-hidden relative">
                                  <div
                                    className={`h-full rounded-full transition-all ${
                                      isError ? "bg-red-400" : "bg-blue-400"
                                    }`}
                                    style={{ width: getBarWidth(span.duration_ms, maxDuration) }}
                                  />
                                  <span className="absolute inset-0 flex items-center justify-center text-[10px] text-gray-500 font-medium">
                                    {formatMs(span.duration_ms)}
                                  </span>
                                </div>

                                {/* LLM 调用标记 */}
                                {nodeLlms.length > 0 && (
                                  <div className="shrink-0 flex items-center gap-0.5">
                                    {nodeLlms.map((llm, i) => (
                                      <button
                                        key={llm.span_id}
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          setExpandedLlmId(
                                            expandedLlmId === llm.span_id ? null : llm.span_id
                                          );
                                        }}
                                        className={`text-[10px] px-1.5 py-0.5 rounded-full transition-colors ${
                                          expandedLlmId === llm.span_id
                                            ? "bg-purple-200 text-purple-800"
                                            : "bg-purple-100 text-purple-600 hover:bg-purple-200"
                                        }`}
                                        title={`${llm.llm_model} · ${formatMs(llm.duration_ms)} · ${
                                          llm.llm_total_tokens
                                        } tokens`}
                                      >
                                        LLM{i + 1}
                                      </button>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}

                          {/* LLM 调用详情 */}
                          {llmSpans.length > 0 && (
                            <div className="mt-3 pt-3 border-t border-gray-100">
                              <div className="text-xs font-medium text-gray-500 mb-2">
                                大模型调用详情 ({llmSpans.length} 次)
                              </div>
                              <div className="space-y-1.5">
                                {llmSpans.map((llm) => {
                                  const isLlmExpanded = expandedLlmId === llm.span_id;
                                  return (
                                    <div key={llm.span_id} className="bg-gray-50 rounded-lg">
                                      <button
                                        onClick={() =>
                                          setExpandedLlmId(isLlmExpanded ? null : llm.span_id)
                                        }
                                        className="w-full text-left px-3 py-2 flex items-center gap-3 text-xs"
                                      >
                                        <ExternalLink size={12} className="text-purple-400 shrink-0" />
                                        <span className="text-gray-600 font-medium">
                                          {NODE_LABELS[llm.node_name] || llm.node_name}
                                          {llm.retry_seq > 0 && (
                                            <span className="text-orange-500 ml-1">
                                              (重试 #{llm.retry_seq})
                                            </span>
                                          )}
                                        </span>
                                        <span className="text-purple-600">{llm.llm_model}</span>
                                        <span className="text-gray-400 ml-auto">
                                          {formatMs(llm.duration_ms)}
                                        </span>
                                        {llm.llm_total_tokens > 0 && (
                                          <span className="text-gray-500">
                                            prompt: {llm.llm_prompt_tokens.toLocaleString()}
                                            {" · "}
                                            completion: {llm.llm_completion_tokens.toLocaleString()}
                                            {" · "}
                                            合计: {llm.llm_total_tokens.toLocaleString()} tokens
                                          </span>
                                        )}
                                        {llm.llm_total_tokens > 0 && llm.duration_ms > 0 && (
                                          <span className="text-blue-600 font-medium">
                                            {formatTokensPerSec(llm.llm_total_tokens, llm.duration_ms)}
                                          </span>
                                        )}
                                        {isLlmExpanded ? (
                                          <ChevronUp size={12} className="text-gray-400" />
                                        ) : (
                                          <ChevronDown size={12} className="text-gray-400" />
                                        )}
                                      </button>

                                      {isLlmExpanded && (
                                        <div className="px-3 pb-2 text-xs text-gray-500 space-y-1.5">
                                          {llm.prompt_preview && (
                                            <div>
                                              <div className="font-medium text-gray-400 mb-0.5">
                                                Prompt 预览:
                                              </div>
                                              <div className="bg-white rounded p-1.5 font-mono text-[11px] text-gray-500 max-h-60 overflow-y-auto whitespace-pre-wrap">
                                                {llm.prompt_preview}
                                              </div>
                                            </div>
                                          )}
                                          {llm.response_preview && (
                                            <div>
                                              <div className="font-medium text-gray-400 mb-0.5">
                                                Response 预览:
                                              </div>
                                              <div className="bg-white rounded p-1.5 font-mono text-[11px] text-gray-500 max-h-60 overflow-y-auto whitespace-pre-wrap">
                                                {llm.response_preview}
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}