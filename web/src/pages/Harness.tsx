import { CheckCircle, FlaskConical, Loader2, Play, RefreshCw, Search, ThumbsDown, ThumbsUp, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  analyzeFailures,
  autoLabelFailures,
  evolveOnline,
  labelFailureCase,
  listCandidates,
  listFailureCases,
  listFeedback,
  reviewCandidate,
} from "@/lib/api";
import type { FeedbackRecord, HarnessCandidate, HarnessFailureCase } from "@/types";

export default function Harness() {
  const [tab, setTab] = useState<"cases" | "candidates" | "feedback">("cases");

  // 失败案例
  const [cases, setCases] = useState<HarnessFailureCase[]>([]);
  const [casesStatus, setCasesStatus] = useState("");
  const [casesLoading, setCasesLoading] = useState(true);
  const [casesError, setCasesError] = useState("");

  // 候选规则
  const [candidates, setCandidates] = useState<HarnessCandidate[]>([]);
  const [candStatus, setCandStatus] = useState("");
  const [candLoading, setCandLoading] = useState(true);

  // 反馈
  const [feedbacks, setFeedbacks] = useState<FeedbackRecord[]>([]);
  const [fbLoading, setFbLoading] = useState(true);

  // 操作状态
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState("");

  // 标注弹窗
  const [labelId, setLabelId] = useState<number | null>(null);
  const [correctSql, setCorrectSql] = useState("");
  const [labelNote, setLabelNote] = useState("");
  const [labelSubmitting, setLabelSubmitting] = useState(false);

  const loadCases = useCallback(async () => {
    setCasesLoading(true);
    setCasesError("");
    try {
      const data = await listFailureCases(casesStatus || undefined, 100);
      setCases(data);
    } catch (err) {
      setCasesError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setCasesLoading(false);
    }
  }, [casesStatus]);

  const loadCandidates = useCallback(async () => {
    setCandLoading(true);
    try {
      const data = await listCandidates(candStatus || undefined, 100);
      setCandidates(data);
    } catch {
      // ignore
    } finally {
      setCandLoading(false);
    }
  }, [candStatus]);

  const loadFeedback = useCallback(async () => {
    setFbLoading(true);
    try {
      const data = await listFeedback(100);
      setFeedbacks(data);
    } catch {
      // ignore
    } finally {
      setFbLoading(false);
    }
  }, []);

  useEffect(() => { loadCases(); }, [loadCases]);
  useEffect(() => { loadCandidates(); }, [loadCandidates]);
  useEffect(() => { loadFeedback(); }, [loadFeedback]);

  async function handleAction(label: string, fn: () => Promise<unknown>) {
    setActionLoading(label);
    setActionMsg("");
    try {
      const result = await fn();
      setActionMsg(JSON.stringify(result));
      loadCases();
      loadCandidates();
    } catch (err) {
      setActionMsg(err instanceof Error ? err.message : "操作失败");
    } finally {
      setActionLoading(null);
    }
  }

  async function submitLabel() {
    if (!labelId) return;
    setLabelSubmitting(true);
    try {
      await labelFailureCase(labelId, correctSql, labelNote);
      setLabelId(null);
      setCorrectSql("");
      setLabelNote("");
      loadCases();
    } catch (err) {
      alert(err instanceof Error ? err.message : "标注失败");
    } finally {
      setLabelSubmitting(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border-default)] px-4 py-3">
        <h2 className="font-display text-sm font-semibold text-[var(--text-primary)]">数据飞轮</h2>
        <div className="flex gap-1">
          <button type="button" onClick={() => handleAction("同步", () => analyzeFailures(200))} disabled={actionLoading !== null} className="inline-flex items-center gap-1 rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-2 py-1 text-[11px] text-[var(--text-secondary)] transition-colors hover:text-[var(--accent)] disabled:opacity-50">
            {actionLoading === "同步" ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            同步
          </button>
          <button type="button" onClick={() => handleAction("自动标注", () => autoLabelFailures(50))} disabled={actionLoading !== null} className="inline-flex items-center gap-1 rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-2 py-1 text-[11px] text-[var(--text-secondary)] transition-colors hover:text-[var(--accent)] disabled:opacity-50">
            {actionLoading === "自动标注" ? <Loader2 className="h-3 w-3 animate-spin" /> : <FlaskConical className="h-3 w-3" />}
            自动标注
          </button>
          <button type="button" onClick={() => handleAction("进化", () => evolveOnline(200))} disabled={actionLoading !== null} className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-2 py-1 text-[11px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50">
            {actionLoading === "进化" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            进化
          </button>
        </div>
      </div>

      {actionMsg && (
        <div className="mx-4 mt-3 rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-3 py-2 font-mono text-[10px] whitespace-pre-wrap text-[var(--text-secondary)]">
          {actionMsg}
        </div>
      )}

      {/* Tab 切换 */}
      <div className="flex border-b border-[var(--border-default)] px-4">
        {[
          ["cases", "失败案例"],
          ["candidates", "候选规则"],
          ["feedback", "用户反馈"],
        ].map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key as typeof tab)}
            className={`border-b-2 px-3 py-2 text-xs transition-colors ${
              tab === key ? "border-[var(--accent)] text-[var(--accent)]" : "border-transparent text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto px-4 py-3">
        {tab === "cases" && (
          <>
            <div className="mb-2 flex items-center gap-2">
              <select value={casesStatus} onChange={(e) => setCasesStatus(e.target.value)} className="rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1 text-[11px] text-[var(--text-primary)]">
                <option value="">全部状态</option>
                <option value="unlabeled">未标注</option>
                <option value="labeled">已标注</option>
                <option value="ignored">已忽略</option>
              </select>
              <button type="button" onClick={loadCases} className="rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] p-1 text-[var(--text-tertiary)] hover:text-[var(--accent)]">
                <Search className="h-3.5 w-3.5" />
              </button>
            </div>
            {casesLoading ? (
              <div className="py-4 text-center text-xs text-[var(--text-tertiary)]">加载中...</div>
            ) : casesError ? (
              <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">{casesError}</div>
            ) : cases.length === 0 ? (
              <div className="py-4 text-center text-xs text-[var(--text-tertiary)]">暂无数据</div>
            ) : (
              <div className="space-y-2">
                {cases.map((c) => (
                  <div key={c.id} className="rounded border border-[var(--border-default)] bg-[var(--bg-default)] p-3">
                    <div className="mb-1 flex items-start justify-between gap-2">
                      <span className="text-[11px] font-medium text-[var(--text-primary)]">{c.query_text || "(无查询)"}</span>
                      <div className="flex shrink-0 items-center gap-1">
                        <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
                          c.status === "labeled" ? "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300" :
                          c.status === "ignored" ? "bg-gray-100 text-gray-500" :
                          "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                        }`}>
                          {c.status === "labeled" ? "已标注" : c.status === "ignored" ? "已忽略" : "未标注"}
                        </span>
                        <button type="button" onClick={() => { setLabelId(c.id); setCorrectSql(""); setLabelNote(""); }} className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-subtle)] hover:text-[var(--accent)]">标注</button>
                      </div>
                    </div>
                    {c.generated_sql && <code className="mt-1 block text-[10px] text-[var(--text-tertiary)]">{c.generated_sql}</code>}
                    {c.correct_sql && (
                      <div className="mt-1 rounded bg-green-50 px-2 py-1 dark:bg-green-950">
                        <code className="text-[10px] text-green-700 dark:text-green-300">{c.correct_sql}</code>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {tab === "candidates" && (
          <>
            <div className="mb-2 flex items-center gap-2">
              <select value={candStatus} onChange={(e) => setCandStatus(e.target.value)} className="rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1 text-[11px] text-[var(--text-primary)]">
                <option value="">全部状态</option>
                <option value="pending">待审核</option>
                <option value="approved">已通过</option>
                <option value="rejected">已拒绝</option>
              </select>
            </div>
            {candLoading ? (
              <div className="py-4 text-center text-xs text-[var(--text-tertiary)]">加载中...</div>
            ) : candidates.length === 0 ? (
              <div className="py-4 text-center text-xs text-[var(--text-tertiary)]">暂无数据</div>
            ) : (
              <div className="space-y-2">
                {candidates.map((c) => (
                  <div key={c.id} className="rounded border border-[var(--border-default)] bg-[var(--bg-default)] p-3">
                    <div className="mb-1 flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <span className="text-[11px] font-medium text-[var(--text-primary)]">{c.question_example || "(无问题)"}</span>
                        <span className={`ml-2 rounded px-1.5 py-0.5 font-mono text-[10px] ${
                          c.status === "approved" ? "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300" :
                          c.status === "rejected" ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300" :
                          "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                        }`}>
                          {c.status === "approved" ? "已通过" : c.status === "rejected" ? "已拒绝" : "待审核"}
                        </span>
                      </div>
                      {c.status === "pending" && (
                        <div className="flex shrink-0 gap-1">
                          <button type="button" onClick={() => handleAction("通过", () => reviewCandidate(c.id, "approve"))} disabled={actionLoading !== null} className="rounded p-1 text-[var(--success)] hover:bg-[var(--bg-subtle)]" title="通过">
                            <CheckCircle className="h-3.5 w-3.5" />
                          </button>
                          <button type="button" onClick={() => handleAction("拒绝", () => reviewCandidate(c.id, "reject"))} disabled={actionLoading !== null} className="rounded p-1 text-[var(--error)] hover:bg-[var(--error-glow)]" title="拒绝">
                            <XCircle className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      )}
                    </div>
                    {c.proposed_rule_json && (
                      <span className="rounded bg-[var(--accent-surface)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--accent)]">
                        {String(c.proposed_rule_json.preferred_main_table || c.candidate_type)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {tab === "feedback" && (
          fbLoading ? (
            <div className="py-4 text-center text-xs text-[var(--text-tertiary)]">加载中...</div>
          ) : feedbacks.length === 0 ? (
            <div className="py-4 text-center text-xs text-[var(--text-tertiary)]">暂无数据</div>
          ) : (
            <div className="space-y-2">
              {feedbacks.map((f) => (
                <div key={f.request_id} className="rounded border border-[var(--border-default)] bg-[var(--bg-default)] p-3">
                  <div className="flex items-center gap-2">
                    {f.user_rating === 1 ? <ThumbsUp className="h-3.5 w-3.5 text-[var(--success)]" /> : <ThumbsDown className="h-3.5 w-3.5 text-[var(--error)]" />}
                    <span className="font-mono text-[10px] text-[var(--text-tertiary)]">{f.request_id}</span>
                    <span className="text-[11px] text-[var(--text-primary)]">{f.user_feedback}</span>
                  </div>
                </div>
              ))}
            </div>
          )
        )}
      </div>

      {/* 标注弹窗 */}
      {labelId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-96 rounded border border-[var(--border-default)] bg-[var(--bg-raised)] p-4 shadow-xl">
            <h3 className="mb-3 text-xs font-semibold text-[var(--text-primary)]">标注失败案例</h3>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">正确 SQL</label>
                <textarea rows={4} value={correctSql} onChange={(e) => setCorrectSql(e.target.value)} className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 font-mono text-xs focus:border-[var(--accent)] focus:outline-none" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">备注</label>
                <input type="text" value={labelNote} onChange={(e) => setLabelNote(e.target.value)} className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none" />
              </div>
              <div className="flex gap-2">
                <button type="button" disabled={labelSubmitting} onClick={submitLabel} className="rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">{labelSubmitting ? "提交中..." : "提交"}</button>
                <button type="button" onClick={() => setLabelId(null)} className="rounded border border-[var(--border-default)] px-3 py-1.5 text-xs text-[var(--text-secondary)]">取消</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
