import { useEffect, useState } from "react";
import { Clock, Cpu, AlertCircle, X, ChevronDown, ChevronUp, ExternalLink } from "lucide-react";
import { fetchTrace } from "@/lib/api";
import type { TraceSpan } from "@/types";

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

interface Props {
  traceId: string;
  onClose: () => void;
}

export function TracePanel({ traceId, onClose }: Props) {
  const [spans, setSpans] = useState<TraceSpan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedSpan, setExpandedSpan] = useState<string | null>(null);
  const [showLlmDetail, setShowLlmDetail] = useState<string | null>(null);

  useEffect(() => {
    if (!traceId) return;
    fetchTrace(traceId)
      .then((res) => setSpans(res.spans))
      .catch((e) => setError(e.message || "加载失败"))
      .finally(() => setLoading(false));
  }, [traceId]);

  // Group spans by node_name (node spans) and llm_call spans
  const nodeSpans = spans.filter((s) => s.span_type === "node").sort(
    (a, b) => NODE_ORDER.indexOf(a.node_name) - NODE_ORDER.indexOf(b.node_name)
  );
  const llmSpans = spans.filter((s) => s.span_type === "llm_call");

  // Calculate overall timing
  const allDurations = spans.map((s) => s.duration_ms).filter((d) => d > 0);
  const maxDuration = Math.max(...allDurations, 1);
  const totalDuration = nodeSpans.reduce((sum, s) => sum + s.duration_ms, 0);

  const formatMs = (ms: number) => {
    if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
    return `${ms}ms`;
  };

  const getBarWidth = (ms: number) => `${Math.max((ms / maxDuration) * 100, 2)}%`;

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center" onClick={onClose}>
        <div className="bg-white rounded-xl shadow-2xl w-[640px] max-h-[80vh] p-6" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-center py-12 text-gray-400">
            <Clock className="animate-spin mr-2" size={20} />
            加载 Trace 数据...
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center" onClick={onClose}>
        <div className="bg-white rounded-xl shadow-2xl w-[640px] p-6" onClick={(e) => e.stopPropagation()}>
          <div className="text-red-500">{error}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-2xl w-[720px] max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 shrink-0">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">执行链路追踪</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              总耗时: {formatMs(totalDuration)} · {nodeSpans.length} 个节点 · {llmSpans.length} 次 LLM 调用
            </p>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600">
            <X size={20} />
          </button>
        </div>

        {/* Timeline */}
        <div className="overflow-y-auto p-4 space-y-2">
          {NODE_ORDER.map((nodeName) => {
            const span = nodeSpans.find((s) => s.node_name === nodeName);
            const nodeLlms = llmSpans.filter((s) => s.node_name === nodeName);
            if (!span) return null;

            const isExpanded = expandedSpan === span.span_id;
            const isError = span.status === "error";
            const hasLlm = nodeLlms.length > 0;

            return (
              <div key={span.span_id}>
                {/* Node bar */}
                <button
                  onClick={() => setExpandedSpan(isExpanded ? null : span.span_id)}
                  className={`w-full text-left rounded-lg border transition-colors ${
                    isError
                      ? "border-red-200 bg-red-50 hover:bg-red-100"
                      : "border-gray-200 bg-gray-50 hover:bg-gray-100"
                  }`}
                >
                  <div className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      {isError ? (
                        <AlertCircle size={16} className="text-red-500" />
                      ) : (
                        <Cpu size={16} className="text-blue-500" />
                      )}
                      <span className={`text-sm font-medium ${isError ? "text-red-700" : "text-gray-700"}`}>
                        {NODE_LABELS[nodeName] || nodeName}
                      </span>
                      <span className="text-xs text-gray-400 ml-auto">{formatMs(span.duration_ms)}</span>
                      {hasLlm && (
                        <span className="text-xs bg-purple-100 text-purple-600 px-1.5 py-0.5 rounded">
                          {nodeLlms.length} LLM
                        </span>
                      )}
                      {isExpanded ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
                    </div>
                    {/* Duration bar */}
                    <div className="mt-1.5 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${isError ? "bg-red-400" : "bg-blue-400"}`}
                        style={{ width: getBarWidth(span.duration_ms) }}
                      />
                    </div>
                  </div>
                </button>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="mt-1 ml-4 pl-4 border-l-2 border-blue-200 space-y-1 py-1">
                    {span.input_json && Object.keys(span.input_json).length > 0 && (
                      <div className="text-xs text-gray-500">
                        <span className="font-medium">输入: </span>
                        {JSON.stringify(span.input_json).slice(0, 200)}
                      </div>
                    )}
                    {span.output_json && Object.keys(span.output_json).length > 0 && (
                      <div className="text-xs text-gray-500">
                        <span className="font-medium">输出: </span>
                        {JSON.stringify(span.output_json).slice(0, 200)}
                      </div>
                    )}
                    {isError && span.error_text && (
                      <div className="text-xs text-red-500">{span.error_text}</div>
                    )}
                    {/* LLM calls nested */}
                    {nodeLlms.map((llm) => (
                      <div key={llm.span_id} className="bg-purple-50 rounded px-2 py-1">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setShowLlmDetail(showLlmDetail === llm.span_id ? null : llm.span_id);
                          }}
                          className="flex items-center gap-2 w-full text-left"
                        >
                          <ExternalLink size={12} className="text-purple-400" />
                          <span className="text-xs text-purple-700">
                            LLM: {llm.llm_model}
                            {llm.retry_seq > 0 && ` (重试 #${llm.retry_seq})`}
                          </span>
                          <span className="text-xs text-purple-400 ml-auto">{formatMs(llm.duration_ms)}</span>
                          {llm.llm_total_tokens > 0 && (
                            <span className="text-xs text-purple-500">{llm.llm_total_tokens} tokens</span>
                          )}
                        </button>
                        {showLlmDetail === llm.span_id && (
                          <div className="mt-1 text-xs text-gray-600 space-y-1">
                            <div>
                              Prompt: {llm.llm_prompt_tokens}t · Completion: {llm.llm_completion_tokens}t
                              · Total: {llm.llm_total_tokens}t
                            </div>
                            {llm.prompt_preview && (
                              <div className="bg-white rounded p-1 text-xs font-mono text-gray-500 max-h-20 overflow-y-auto">
                                {llm.prompt_preview}
                              </div>
                            )}
                            {llm.response_preview && (
                              <div className="bg-white rounded p-1 text-xs font-mono text-gray-500 max-h-20 overflow-y-auto">
                                {llm.response_preview}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-200 shrink-0 flex items-center gap-4 text-xs text-gray-400">
          <span>Trace ID: {traceId.slice(0, 8)}...</span>
          {llmSpans.reduce((sum, s) => sum + s.llm_total_tokens, 0) > 0 && (
            <span>总 Token: {llmSpans.reduce((sum, s) => sum + s.llm_total_tokens, 0)}</span>
          )}
        </div>
      </div>
    </div>
  );
}
