import { Loader2, Search, Sparkles } from "lucide-react";
import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";

import Empty from "@/components/Empty";
import { Panel } from "@/components/Panel";
import { searchKnowledge } from "@/lib/api";
import type {
  FewShotSearchItem,
  KnowledgeSearchResult,
  SchemaSearchItem,
} from "@/types";

// ── 模块颜色 ──────────────────────────────────────────────────────
const MODULE_COLORS: Record<string, string> = {
  "条码管理": "bg-cyan-100 text-cyan-800 border-cyan-200",
  "基础数据": "bg-red-100 text-red-800 border-red-200",
  "生产执行": "bg-blue-100 text-blue-800 border-blue-200",
  "质量管理": "bg-green-100 text-green-800 border-green-200",
  "仓储管理": "bg-amber-100 text-amber-800 border-amber-200",
  "设备管理": "bg-purple-100 text-purple-800 border-purple-200",
};

function getModuleColor(mod: string): string {
  return MODULE_COLORS[mod] || "bg-gray-100 text-gray-700 border-gray-200";
}

// ── 检索结果子组件 ──────────────────────────────────────────────────

function SchemaResultCard({
  item,
  expanded,
  onToggle,
}: {
  item: SchemaSearchItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  const navigate = useNavigate();

  return (
    <div className="rounded border border-[var(--border-default)] p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate(`/knowledge?table=${encodeURIComponent(item.table_name)}`)}
            className="font-mono text-xs font-medium text-[var(--accent)] hover:underline"
            title="跳转到表管理查看详情"
          >
            {item.table_name}
          </button>
          {item.module && (
            <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${getModuleColor(item.module)}`}>
              {item.module}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
            相似度: {item.score.toFixed(4)}
          </span>
          <button
            onClick={onToggle}
            className="rounded px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            {expanded ? "收起" : "展开"}
          </button>
        </div>
      </div>
      {item.business_meaning && (
        <p className="text-[11px] text-[var(--text-secondary)]">{item.business_meaning}</p>
      )}
      {expanded && (
        <pre className="whitespace-pre-wrap rounded border border-[var(--border-subtle)] bg-[var(--bg-subtle)] p-3 font-mono text-[11px] text-[var(--text-secondary)] overflow-x-auto">
          {item.full_text}
        </pre>
      )}
    </div>
  );
}

function FewShotResultCard({
  item,
  expanded,
  onToggle,
}: {
  item: FewShotSearchItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="rounded border border-[var(--border-default)] p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {item.scenario && (
            <span className="rounded border border-[var(--border-default)] bg-[var(--bg-raised)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-secondary)]">
              {item.scenario}
            </span>
          )}
          <span className="text-[11px] text-[var(--text-primary)] truncate max-w-md">
            {item.question}
          </span>
        </div>
        <button
          onClick={onToggle}
          className="rounded px-1.5 py-0.5 text-[10px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
        >
          {expanded ? "收起" : "展开"}
        </button>
      </div>
      {expanded && (
        <pre className="whitespace-pre-wrap rounded border border-[var(--border-subtle)] bg-[var(--bg-subtle)] p-3 font-mono text-[11px] text-[var(--text-secondary)] overflow-x-auto">
          {item.full_text}
        </pre>
      )}
    </div>
  );
}

// ── 主组件 ──────────────────────────────────────────────────────────

export default function KnowledgeSearchPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTypes, setSearchTypes] = useState<string[]>(["schema", "few_shot", "fields"]);
  const [useRerank, setUseRerank] = useState(false);
  const [rerankTopN, setRerankTopN] = useState<number | "">("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchResult, setSearchResult] = useState<KnowledgeSearchResult | null>(null);
  const [expandedSchemaIdx, setExpandedSchemaIdx] = useState<Set<number>>(new Set());
  const [expandedFewShotIdx, setExpandedFewShotIdx] = useState<Set<number>>(new Set());

  // ── 检索查询 ──
  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    setSearchLoading(true);
    setSearchError("");
    setSearchResult(null);
    setExpandedSchemaIdx(new Set());
    setExpandedFewShotIdx(new Set());
    try {
      const result = await searchKnowledge(
        searchQuery,
        searchTypes,
        10,
        0.55,
        useRerank,
        useRerank && typeof rerankTopN === "number" && rerankTopN > 0 ? rerankTopN : null,
      );
      setSearchResult(result);
    } catch (e) {
      setSearchError(String(e));
    } finally {
      setSearchLoading(false);
    }
  }, [searchQuery, searchTypes, useRerank, rerankTopN]);

  const toggleSearchType = (type: string) => {
    setSearchTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  };

  const toggleSchemaExpand = (idx: number) => {
    setExpandedSchemaIdx((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleFewShotExpand = (idx: number) => {
    setExpandedFewShotIdx((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  return (
    <div className="flex h-full flex-col">
      {/* 页面标题 */}
      <div className="flex shrink-0 items-center gap-3 border-b border-[var(--border-default)] px-6 py-3">
        <Search size={18} className="text-[var(--accent)]" />
        <h1 className="font-display text-sm font-semibold uppercase tracking-[0.06em] text-[var(--text-primary)]">
          检索查询
        </h1>
      </div>

      {/* 搜索区域 */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-5xl space-y-5">
          {/* 搜索栏 */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="输入查询文本，如：查询工单的过站记录..."
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] py-2 pl-9 pr-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            <button
              onClick={handleSearch}
              disabled={searchLoading || !searchQuery.trim() || searchTypes.length === 0}
              className="inline-flex items-center gap-1.5 rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {searchLoading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
              检索
            </button>
          </div>

          {/* 检索类型选择 */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[11px] font-medium text-[var(--text-tertiary)]">检索类型：</span>
            {[
              { key: "schema", label: "表结构" },
              { key: "few_shot", label: "SQL 示例" },
              { key: "fields", label: "字段级" },
              { key: "runtime_rule", label: "运行时规则" },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => toggleSearchType(key)}
                className={`rounded border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  searchTypes.includes(key)
                    ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                    : "border-[var(--border-default)] text-[var(--text-tertiary)] hover:border-[var(--text-tertiary)]"
                }`}
              >
                {label}
              </button>
            ))}

            {/* Rerank 开关 */}
            <div className="ml-2 flex items-center gap-2 border-l border-[var(--border-default)] pl-3">
              <button
                onClick={() => setUseRerank((v) => !v)}
                className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  useRerank
                    ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                    : "border-[var(--border-default)] text-[var(--text-tertiary)] hover:border-[var(--text-tertiary)]"
                }`}
                title="启用硅基流动 Rerank 模型（Qwen3-Reranker-4B）进行二次精排"
              >
                <Sparkles size={11} className={useRerank ? "" : "opacity-60"} />
                Rerank
              </button>
              {useRerank && (
                <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-tertiary)]">
                  <span>Top-N</span>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={rerankTopN}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === "") {
                        setRerankTopN("");
                      } else {
                        const n = Number(v);
                        setRerankTopN(Number.isFinite(n) && n > 0 ? n : "");
                      }
                    }}
                    placeholder="默认"
                    className="w-16 rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-1.5 py-0.5 text-center text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>
              )}
            </div>
          </div>

          {/* 错误提示 */}
          {searchError && (
            <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
              {searchError}
            </div>
          )}

          {/* 模型信息 */}
          {searchResult && (
            <div className="flex items-center gap-3 text-[11px] text-[var(--text-tertiary)]">
              <span>
                Embedding: <span className="font-mono text-[var(--text-secondary)]">{searchResult.embedding_model || "—"}</span>
              </span>
              {searchResult.rerank_model && (
                <span>
                  Rerank: <span className="font-mono text-[var(--text-secondary)]">{searchResult.rerank_model}</span>
                </span>
              )}
            </div>
          )}

          {/* 检索结果 */}
          {searchResult && (
            <div className="space-y-5">
              {/* 关键词匹配表 */}
              {searchResult.keyword_tables.length > 0 && (
                <Panel title={`关键词匹配表（${searchResult.keyword_tables.length}）`}>
                  <div className="flex flex-wrap gap-2">
                    {searchResult.keyword_tables.map((t) => (
                      <span
                        key={t}
                        className="rounded border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-0.5 font-mono text-[11px] text-[var(--text-primary)]"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </Panel>
              )}

              {/* 表结构检索结果 */}
              {searchResult.schema_results.length > 0 && (
                <Panel title={`表结构检索（${searchResult.schema_results.length}）`}>
                  <div className="space-y-3">
                    {searchResult.schema_results.map((item, idx) => (
                      <SchemaResultCard
                        key={item.table_name}
                        item={item}
                        expanded={expandedSchemaIdx.has(idx)}
                        onToggle={() => toggleSchemaExpand(idx)}
                      />
                    ))}
                  </div>
                </Panel>
              )}

              {/* SQL 示例检索结果 */}
              {searchResult.few_shot_results.length > 0 && (
                <Panel title={`SQL 示例检索（${searchResult.few_shot_results.length}）`}>
                  <div className="space-y-3">
                    {searchResult.few_shot_results.map((item, idx) => (
                      <FewShotResultCard
                        key={idx}
                        item={item}
                        expanded={expandedFewShotIdx.has(idx)}
                        onToggle={() => toggleFewShotExpand(idx)}
                      />
                    ))}
                  </div>
                </Panel>
              )}

              {/* 字段级检索结果 */}
              {searchResult.field_results.length > 0 && (
                <Panel title={`字段级检索（${searchResult.field_results.length}）`}>
                  <div className="overflow-x-auto rounded border border-[var(--border-default)]">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-[var(--border-default)] bg-[var(--bg-raised)]">
                          <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">表名</th>
                          <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">字段名</th>
                          <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">类型</th>
                          <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">注释</th>
                          <th className="px-3 py-2 text-right font-medium text-[var(--text-secondary)]">相似度</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[var(--border-subtle)]">
                        {searchResult.field_results.map((f, idx) => (
                          <tr key={idx} className="hover:bg-[var(--bg-hover)]">
                            <td className="px-3 py-1.5 font-mono text-[var(--accent)]">{f.table_name}</td>
                            <td className="px-3 py-1.5 font-mono text-[var(--text-primary)]">{f.field_name}</td>
                            <td className="px-3 py-1.5 font-mono text-[var(--text-tertiary)]">{f.type}</td>
                            <td className="px-3 py-1.5 text-[var(--text-secondary)]">{f.comment}</td>
                            <td className="px-3 py-1.5 text-right font-mono text-[var(--text-tertiary)]">{f.score.toFixed(4)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              )}

              {/* 运行时规则检索结果 */}
              {searchResult.runtime_rule_results.length > 0 && (
                <Panel title={`运行时规则检索（${searchResult.runtime_rule_results.length}）`}>
                  <div className="space-y-3">
                    {searchResult.runtime_rule_results.map((item, idx) => (
                      <div
                        key={idx}
                        className="rounded border border-[var(--border-default)] bg-[var(--bg-raised)] p-3"
                      >
                        <div className="mb-2 flex items-start justify-between">
                          <div className="flex-1">
                            <div className="mb-1 text-xs font-medium text-[var(--text-primary)]">
                              {item.question}
                            </div>
                            <div className="text-[11px] text-[var(--text-tertiary)]">
                              归一化：{item.normalized_question}
                            </div>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                              相似度: {item.score.toFixed(4)}
                            </span>
                            <span className="rounded bg-[var(--accent)]/10 px-2 py-0.5 text-[10px] text-[var(--accent)]">
                              {item.source}
                            </span>
                          </div>
                        </div>
                        <div className="mb-2 text-[11px]">
                          <span className="font-medium text-[var(--text-secondary)]">主表：</span>
                          <span className="font-mono text-[var(--accent)]">{item.preferred_main_table}</span>
                        </div>
                        <div className="mb-2 text-[11px]">
                          <span className="font-medium text-[var(--text-secondary)]">必需表：</span>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {item.required_tables.map((t, i) => (
                              <span
                                key={i}
                                className="rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-primary)]"
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                        </div>
                        {item.required_joins.length > 0 && (
                          <div className="text-[11px]">
                            <span className="font-medium text-[var(--text-secondary)]">必需 JOIN：</span>
                            <div className="mt-1 space-y-1">
                              {item.required_joins.map((j, i) => (
                                <div
                                  key={i}
                                  className="rounded bg-[var(--bg-subtle)] px-2 py-1 font-mono text-[10px] text-[var(--text-primary)]"
                                >
                                  {j}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </Panel>
              )}

              {/* 无结果 */}
              {searchResult.schema_results.length === 0 &&
                searchResult.few_shot_results.length === 0 &&
                searchResult.field_results.length === 0 &&
                searchResult.keyword_tables.length === 0 &&
                searchResult.runtime_rule_results.length === 0 && (
                  <Empty message="未检索到相关结果，请尝试其他查询" />
                )}
            </div>
          )}

          {/* 初始空状态 */}
          {!searchResult && !searchLoading && !searchError && (
            <Empty message="输入查询文本后点击检索，查看并行检索结果" />
          )}
        </div>
      </div>
    </div>
  );
}
