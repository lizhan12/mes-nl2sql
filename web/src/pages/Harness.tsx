import {
  ArrowUpRight,
  Beaker,
  Bot,
  Brain,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Database,
  Eye,
  MessageCircle,
  RefreshCw,
  Search,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { CodeBlock } from "@/components/CodeBlock";
import Empty from "@/components/Empty";
import { MetricCard } from "@/components/MetricCard";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import {
  analyzeFailures,
  autoLabelFailures,
  evolveOnline,
  labelFailureCase,
  listCandidates,
  listFailureCases,
  publishApproved,
  reviewCandidate,
} from "@/lib/api";
import type {
  HarnessCandidate,
  HarnessFailureCase,
} from "@/types";

const STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "open", label: "Open" },
  { value: "labeled", label: "Labeled" },
  { value: "auto_labeled", label: "Auto-Labeled" },
  { value: "promoted", label: "Promoted" },
];

const CANDIDATE_STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "published", label: "Published" },
];

export default function Harness() {
  // ── State ──
  const [failures, setFailures] = useState<HarnessFailureCase[]>([]);
  const [candidates, setCandidates] = useState<HarnessCandidate[]>([]);
  const [failureStatus, setFailureStatus] = useState("");
  const [candidateStatus, setCandidateStatus] = useState("");
  const [busy, setBusy] = useState("");

  // Label modal
  const [labelModalOpen, setLabelModalOpen] = useState(false);
  const [labelingCase, setLabelingCase] = useState<HarnessFailureCase | null>(null);
  const [labelSql, setLabelSql] = useState("");
  const [labelNote, setLabelNote] = useState("");

  // Review modal
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewingCandidate, setReviewingCandidate] = useState<HarnessCandidate | null>(null);
  const [reviewNote, setReviewNote] = useState("");

  // Publish
  const [publishVersion, setPublishVersion] = useState(`web-${new Date().toISOString().slice(0, 10)}`);

  // Auto-label config
  const [autoLabelLimit, setAutoLabelLimit] = useState(50);
  const [autoLabelGenModel, setAutoLabelGenModel] = useState("");
  const [autoLabelEvalModel, setAutoLabelEvalModel] = useState("");

  // Evolve online config
  const [evolveOnlineLimit, setEvolveOnlineLimit] = useState(200);

  // Analyze config
  const [analyzeLimit, setAnalyzeLimit] = useState(200);

  // Expanded states
  const [expandedFailure, setExpandedFailure] = useState<number | null>(null);
  const [expandedCandidate, setExpandedCandidate] = useState<number | null>(null);

  // Last operation result
  const [lastResult, setLastResult] = useState<Record<string, unknown> | null>(null);
  const [lastResultTitle, setLastResultTitle] = useState("");

  // ── Stats ──
  const openCount = useMemo(() => failures.filter((f) => f.status === "open").length, [failures]);
  const labeledCount = useMemo(() => failures.filter((f) => f.status === "labeled").length, [failures]);
  const pendingCount = useMemo(() => candidates.filter((c) => c.status === "pending").length, [candidates]);
  const approvedCount = useMemo(() => candidates.filter((c) => c.status === "approved").length, [candidates]);

  // ── Effects ──
  useEffect(() => {
    void refreshFailures();
    void refreshCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Actions ──
  async function refreshFailures() {
    setBusy("failures");
    try {
      const items = await listFailureCases(failureStatus || undefined);
      setFailures(items);
    } catch {
      // ignore
    } finally {
      setBusy("");
    }
  }

  async function refreshCandidates() {
    setBusy("candidates");
    try {
      const items = await listCandidates(candidateStatus || undefined);
      setCandidates(items);
    } catch {
      // ignore
    } finally {
      setBusy("");
    }
  }

  useEffect(() => {
    void refreshFailures();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [failureStatus]);

  useEffect(() => {
    void refreshCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateStatus]);

  async function handleAnalyze() {
    setBusy("analyze");
    try {
      const result = await analyzeFailures(analyzeLimit);
      setLastResult(result);
      setLastResultTitle("分析失败案例");
      await refreshCandidates();
      await refreshFailures();
    } catch {
      // ignore
    } finally {
      setBusy("");
    }
  }

  async function handleAutoLabel() {
    setBusy("auto-label");
    try {
      const result = await autoLabelFailures(autoLabelLimit, autoLabelGenModel, autoLabelEvalModel);
      setLastResult(result as unknown as Record<string, unknown>);
      setLastResultTitle("LLM 自动标注");
      await refreshCandidates();
      await refreshFailures();
    } catch {
      // ignore
    } finally {
      setBusy("");
    }
  }

  async function handleEvolveOnline() {
    setBusy("evolve");
    try {
      const result = await evolveOnline(evolveOnlineLimit);
      setLastResult(result as unknown as Record<string, unknown>);
      setLastResultTitle("线上进化");
      await refreshCandidates();
      await refreshFailures();
    } catch {
      // ignore
    } finally {
      setBusy("");
    }
  }

  async function handlePublish() {
    setBusy("publish");
    try {
      const result = await publishApproved(publishVersion);
      setLastResult(result);
      setLastResultTitle("发布版本");
      await refreshCandidates();
    } catch {
      // ignore
    } finally {
      setBusy("");
    }
  }

  async function handleLabel() {
    if (!labelingCase || !labelSql.trim()) return;
    setBusy("label");
    try {
      await labelFailureCase(labelingCase.id, labelSql.trim(), labelNote);
      setLabelModalOpen(false);
      setLabelingCase(null);
      setLabelSql("");
      setLabelNote("");
      await refreshFailures();
    } catch {
      // ignore
    } finally {
      setBusy("");
    }
  }

  async function handleReview(action: "approve" | "reject") {
    if (!reviewingCandidate) return;
    setBusy("review");
    try {
      await reviewCandidate(reviewingCandidate.id, action, reviewNote);
      setReviewModalOpen(false);
      setReviewingCandidate(null);
      setReviewNote("");
      await refreshCandidates();
    } catch {
      // ignore
    } finally {
      setBusy("");
    }
  }

  function openLabelModal(fc: HarnessFailureCase) {
    setLabelingCase(fc);
    setLabelSql(fc.correct_sql || "");
    setLabelNote(fc.label_note || "");
    setLabelModalOpen(true);
  }

  function openReviewModal(c: HarnessCandidate) {
    setReviewingCandidate(c);
    setReviewNote("");
    setReviewModalOpen(true);
  }

  function statusTone(s: string): "success" | "error" | "warning" | "loading" | "neutral" {
    const map: Record<string, "success" | "error" | "warning" | "loading" | "neutral"> = {
      open: "error",
      labeled: "success",
      auto_labeled: "warning",
      promoted: "neutral",
      pending: "warning",
      approved: "success",
      rejected: "error",
      published: "neutral",
    };
    return map[s] || "neutral";
  }

  function statusLabel(s: string) {
    const map: Record<string, string> = {
      open: "Open",
      labeled: "Labeled",
      auto_labeled: "Auto",
      promoted: "Promoted",
      pending: "Pending",
      approved: "Approved",
      rejected: "Rejected",
      published: "Published",
    };
    return map[s] || s;
  }

  // ── Render ──
  return (
    <main className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="mx-auto max-w-7xl space-y-9 px-4 py-8 sm:px-6 lg:px-8">
        {/* ── Header ── */}
        <section className="corner-accent rounded-lg border border-[var(--border-default)] bg-[var(--bg-raised)] p-6 sm:p-8">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div className="flex-1">
              <StatusBadge tone="success">Online</StatusBadge>
              <h1 className="mt-4 font-display text-[32px] font-semibold leading-none tracking-[0.02em] text-[var(--text-primary)] sm:text-[38px]">
                Harness{" "}
                <span className="font-sans text-[var(--text-tertiary)] font-normal tracking-normal">
                  知识进化
                </span>
              </h1>
              <p className="mt-3 max-w-lg font-mono text-[12px] leading-relaxed text-[var(--text-tertiary)]">
                管理 NL2SQL 运行时知识闭环：查看失败案例、审核候选规则、自动标注、进化发布。
              </p>
              <div className="mt-5 flex flex-wrap items-center gap-2">
                <Link
                  to="/"
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-accent)] hover:text-[var(--text-primary)] hover:shadow-[var(--shadow-glow)]"
                >
                  <MessageCircle className="h-3.5 w-3.5" />
                  对话助手
                </Link>
                <Link
                  to="/home"
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-accent)] hover:text-[var(--text-primary)] hover:shadow-[var(--shadow-glow)]"
                >
                  <Beaker className="h-3.5 w-3.5" />
                  调试控制台
                </Link>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MetricCard
                label="Open 失败"
                value={openCount}
                hint="待处理"
                icon={<XCircle className="h-4 w-4" />}
              />
              <MetricCard
                label="已标注"
                value={labeledCount}
                hint="已补SQL"
                icon={<CheckCircle className="h-4 w-4" />}
              />
              <MetricCard
                label="待审核"
                value={pendingCount}
                hint="候选规则"
                icon={<Eye className="h-4 w-4" />}
              />
              <MetricCard
                label="已批准"
                value={approvedCount}
                hint="待发布"
                icon={<ThumbsUp className="h-4 w-4" />}
              />
            </div>
          </div>
        </section>

        {/* ── Operations ── */}
        <Panel
          title="操作面板"
          subtitle="触发分析、自动标注、进化与发布等核心闭环操作。"
          action={<StatusBadge tone={busy ? "loading" : "neutral"}>{busy || "Idle"}</StatusBadge>}
        >
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Analyze Failures */}
            <div className="corner-accent rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-4 transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)]">
              <div className="flex items-center gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--text-primary)]">
                <Search className="h-4 w-4 text-[var(--accent)]" />
                分析失败案例
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                从线上失败案例和已标注案例生成候选规则
              </p>
              <div className="mt-3 flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <label className="font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                    Limit:
                  </label>
                  <input
                    type="number"
                    value={analyzeLimit}
                    onChange={(e) => setAnalyzeLimit(Number(e.target.value) || 200)}
                    className="w-20 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-1 font-mono text-[12px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleAnalyze}
                  disabled={busy === "analyze"}
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-3 py-1.5 font-mono text-[11px] font-medium uppercase tracking-[0.04em] text-[#080c0f] transition-all duration-[var(--duration-fast)] hover:shadow-[var(--shadow-glow)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  <Bot className="h-3.5 w-3.5" />
                  {busy === "analyze" ? "分析中..." : "分析"}
                </button>
              </div>
            </div>

            {/* Auto-Label */}
            <div className="corner-accent rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-4 transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)]">
              <div className="flex items-center gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--text-primary)]">
                <Brain className="h-4 w-4 text-[var(--success)]" />
                LLM 自动标注
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                LLM 对失败案例生成修正 SQL + 多维度置信度评估
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2">
                  <label className="font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                    Limit:
                  </label>
                  <input
                    type="number"
                    value={autoLabelLimit}
                    onChange={(e) => setAutoLabelLimit(Number(e.target.value) || 50)}
                    className="w-16 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-1 font-mono text-[12px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <label className="font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                    生成模型:
                  </label>
                  <input
                    value={autoLabelGenModel}
                    onChange={(e) => setAutoLabelGenModel(e.target.value)}
                    placeholder="默认"
                    className="w-28 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-1 font-mono text-[12px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <label className="font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                    评估模型:
                  </label>
                  <input
                    value={autoLabelEvalModel}
                    onChange={(e) => setAutoLabelEvalModel(e.target.value)}
                    placeholder="默认"
                    className="w-28 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-1 font-mono text-[12px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleAutoLabel}
                  disabled={busy === "auto-label"}
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--success)] px-3 py-1.5 font-mono text-[11px] font-medium uppercase tracking-[0.04em] text-[#080c0f] transition-all duration-[var(--duration-fast)] hover:shadow-[0_0_20px_var(--success-glow)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {busy === "auto-label" ? "标注中..." : "自动标注"}
                </button>
              </div>
            </div>

            {/* Evolve Online */}
            <div className="corner-accent rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-4 transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)]">
              <div className="flex items-center gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--text-primary)]">
                <ArrowUpRight className="h-4 w-4 text-[var(--warning)]" />
                线上进化
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                从线上高成本成功请求中提炼规则并直接发布
              </p>
              <div className="mt-3 flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <label className="font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                    Limit:
                  </label>
                  <input
                    type="number"
                    value={evolveOnlineLimit}
                    onChange={(e) => setEvolveOnlineLimit(Number(e.target.value) || 200)}
                    className="w-20 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-1 font-mono text-[12px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleEvolveOnline}
                  disabled={busy === "evolve"}
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--warning)] px-3 py-1.5 font-mono text-[11px] font-medium uppercase tracking-[0.04em] text-[#080c0f] transition-all duration-[var(--duration-fast)] hover:shadow-[0_0_20px_var(--warning-glow)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  <Database className="h-3.5 w-3.5" />
                  {busy === "evolve" ? "进化中..." : "执行进化"}
                </button>
              </div>
            </div>

            {/* Publish */}
            <div className="corner-accent rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-4 transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)]">
              <div className="flex items-center gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--text-primary)]">
                <ArrowUpRight className="h-4 w-4 text-[var(--warning)]" />
                发布版本
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                将已审核通过的候选规则发布为运行时知识
              </p>
              <div className="mt-3 flex items-center gap-3">
                <input
                  value={publishVersion}
                  onChange={(e) => setPublishVersion(e.target.value)}
                  className="flex-1 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-raised)] px-3 py-1.5 font-mono text-[13px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                />
                <button
                  type="button"
                  onClick={handlePublish}
                  disabled={busy === "publish"}
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-3 py-1.5 font-mono text-[11px] font-medium uppercase tracking-[0.04em] text-[#080c0f] transition-all duration-[var(--duration-fast)] hover:shadow-[var(--shadow-glow)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  <ArrowUpRight className="h-3.5 w-3.5" />
                  {busy === "publish" ? "发布中..." : "发布"}
                </button>
              </div>
            </div>
          </div>
        </Panel>

        {/* ── Last Result (if any) ── */}
        {lastResult ? (
          <Panel
            title={`结果：${lastResultTitle}`}
            subtitle="最近一次操作的返回值"
          >
            <CodeBlock title="结果" value={lastResult} language="json" maxHeightClassName="max-h-64" />
          </Panel>
        ) : null}

        {/* ── Failure Cases ── */}
        <Panel
          title="失败案例"
          subtitle={`共 ${failures.length} 条`}
          action={
            <div className="flex items-center gap-2">
              <select
                value={failureStatus}
                onChange={(e) => setFailureStatus(e.target.value)}
                className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-2 py-1 font-mono text-[11px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] focus:border-[var(--border-accent)]"
              >
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={refreshFailures}
                className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
              >
                <RefreshCw className="h-3 w-3" />
                刷新
              </button>
            </div>
          }
        >
          {failures.length === 0 ? (
            <Empty />
          ) : (
            <div className="max-h-[600px] space-y-1 overflow-auto">
              {failures.map((fc) => (
                <div
                  key={fc.id}
                  className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-accent)]"
                >
                  <div
                    className="flex cursor-pointer items-center gap-3 p-3 transition-colors duration-[var(--duration-fast)] hover:bg-[var(--accent-surface)]"
                    onClick={() => setExpandedFailure(expandedFailure === fc.id ? null : fc.id)}
                  >
                    <span className="font-mono text-[11px] text-[var(--text-tertiary)]/60 tabular-nums">
                      #{fc.id}
                    </span>
                    <StatusBadge tone={statusTone(fc.status)}>{statusLabel(fc.status)}</StatusBadge>
                    <StatusBadge tone="neutral">{fc.failure_type}</StatusBadge>
                    <span className="flex-1 truncate text-[12px] text-[var(--text-secondary)]">
                      {fc.query_text}
                    </span>
                    <span className="font-mono text-[10px] text-[var(--text-tertiary)]/50 tabular-nums">
                      重试 {fc.retry_count}
                    </span>
                    {expandedFailure === fc.id ? (
                      <ChevronUp className="h-4 w-4 text-[var(--text-tertiary)]/40 transition-colors duration-[var(--duration-fast)]" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-[var(--text-tertiary)]/40 transition-colors duration-[var(--duration-fast)]" />
                    )}
                  </div>
                  {expandedFailure === fc.id ? (
                    <div className="border-t border-[var(--border-default)] p-4 space-y-3">
                      <CodeBlock
                        title="生成的 SQL"
                        value={fc.final_sql || fc.generated_sql || "(无)"}
                        language="sql"
                        maxHeightClassName="max-h-48"
                      />
                      {fc.error_text ? (
                        <CodeBlock
                          title="错误信息"
                          value={fc.error_text}
                          language="text"
                          maxHeightClassName="max-h-32"
                        />
                      ) : null}
                      {fc.correct_sql ? (
                        <CodeBlock
                          title="正确 SQL (已标注)"
                          value={fc.correct_sql}
                          language="sql"
                          maxHeightClassName="max-h-48"
                        />
                      ) : null}
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => openLabelModal(fc)}
                          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-accent)] hover:text-[var(--accent)] hover:bg-[var(--accent-surface)]"
                        >
                          {fc.correct_sql ? "修改标注" : "补充 SQL"}
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </Panel>

        {/* ── Candidate Rules ── */}
        <Panel
          title="候选规则"
          subtitle={`共 ${candidates.length} 条`}
          action={
            <div className="flex items-center gap-2">
              <select
                value={candidateStatus}
                onChange={(e) => setCandidateStatus(e.target.value)}
                className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-2 py-1 font-mono text-[11px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] focus:border-[var(--border-accent)]"
              >
                {CANDIDATE_STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={refreshCandidates}
                className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
              >
                <RefreshCw className="h-3 w-3" />
                刷新
              </button>
            </div>
          }
        >
          {candidates.length === 0 ? (
            <Empty />
          ) : (
            <div className="max-h-[600px] space-y-1 overflow-auto">
              {candidates.map((c) => (
                <div
                  key={c.id}
                  className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-accent)]"
                >
                  <div
                    className="flex cursor-pointer items-center gap-3 p-3 transition-colors duration-[var(--duration-fast)] hover:bg-[var(--accent-surface)]"
                    onClick={() => setExpandedCandidate(expandedCandidate === c.id ? null : c.id)}
                  >
                    <span className="font-mono text-[11px] text-[var(--text-tertiary)]/60 tabular-nums">
                      #{c.id}
                    </span>
                    <StatusBadge tone={statusTone(c.status)}>{statusLabel(c.status)}</StatusBadge>
                    <StatusBadge tone="neutral">{c.candidate_type}</StatusBadge>
                    <span className="flex-1 truncate text-[12px] text-[var(--text-secondary)]">
                      {c.question_example}
                    </span>
                    {c.confidence > 0 ? (
                      <div className="flex items-center gap-2">
                        {/* Confidence gradient bar */}
                        <div className="h-1.5 w-14 overflow-hidden rounded-full bg-[var(--border-default)]">
                          <div
                            className="h-full rounded-full transition-all duration-[var(--duration-slow)]"
                            style={{
                              width: `${Math.round(c.confidence * 100)}%`,
                              background:
                                "linear-gradient(90deg, var(--accent) 0%, var(--accent-soft) 100%)",
                            }}
                          />
                        </div>
                        <span className="font-mono text-[10px] tabular-nums text-[var(--text-tertiary)]/70">
                          {(c.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    ) : null}
                    {expandedCandidate === c.id ? (
                      <ChevronUp className="h-4 w-4 text-[var(--text-tertiary)]/40 transition-colors duration-[var(--duration-fast)]" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-[var(--text-tertiary)]/40 transition-colors duration-[var(--duration-fast)]" />
                    )}
                  </div>
                  {expandedCandidate === c.id ? (
                    <div className="border-t border-[var(--border-default)] p-4 space-y-3">
                      <CodeBlock
                        title="候选规则 (JSON)"
                        value={c.proposed_rule_json || {}}
                        language="json"
                        maxHeightClassName="max-h-48"
                      />
                      {c.proposed_few_shot_text ? (
                        <CodeBlock
                          title="候选 Few-Shot"
                          value={c.proposed_few_shot_text}
                          language="text"
                          maxHeightClassName="max-h-32"
                        />
                      ) : null}
                      {c.evidence_json && Object.keys(c.evidence_json).length > 0 ? (
                        <CodeBlock
                          title="证据"
                          value={c.evidence_json}
                          language="json"
                          maxHeightClassName="max-h-32"
                        />
                      ) : null}
                      {c.review_note ? (
                        <div className="text-[12px] text-[var(--text-tertiary)]">
                          <span className="text-[var(--text-tertiary)]/60">审核备注：</span>
                          {c.review_note}
                        </div>
                      ) : null}
                      {c.published_version ? (
                        <div className="text-[12px] text-[var(--text-tertiary)]">
                          <span className="text-[var(--text-tertiary)]/60">已发布版本：</span>
                          {c.published_version}
                        </div>
                      ) : null}
                      {c.status === "pending" || c.status === "approved" ? (
                        <div className="flex items-center gap-2 pt-1">
                          <button
                            type="button"
                            onClick={() => openReviewModal(c)}
                            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-accent)] hover:text-[var(--accent)] hover:bg-[var(--accent-surface)]"
                          >
                            审核
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </Panel>

        {/* ── Label Modal ── */}
        {labelModalOpen && labelingCase ? (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
            <div className="w-full max-w-2xl rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--bg-raised)] p-6 shadow-[0_0_40px_rgba(0,0,0,0.5)]">
              <h3 className="font-mono text-[14px] font-medium uppercase tracking-[0.04em] text-[var(--text-primary)]">
                标注失败案例 #{labelingCase.id}
              </h3>
              <p className="mt-2 font-mono text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                {labelingCase.query_text}
              </p>
              <div className="mt-3">
                <CodeBlock
                  title="原生成 SQL"
                  value={labelingCase.final_sql || labelingCase.generated_sql}
                  language="sql"
                  maxHeightClassName="max-h-32"
                />
              </div>
              <div className="mt-4 space-y-3">
                <div>
                  <label className="font-mono text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                    正确 SQL
                  </label>
                  <textarea
                    value={labelSql}
                    onChange={(e) => setLabelSql(e.target.value)}
                    rows={6}
                    className="mt-1 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-2 font-mono text-[12px] leading-relaxed text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                    placeholder="输入正确的 SQL 语句..."
                  />
                </div>
                <div>
                  <label className="font-mono text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                    备注
                  </label>
                  <input
                    value={labelNote}
                    onChange={(e) => setLabelNote(e.target.value)}
                    className="mt-1 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-2 font-mono text-[13px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                    placeholder="可选备注"
                  />
                </div>
              </div>
              <div className="mt-5 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setLabelModalOpen(false);
                    setLabelingCase(null);
                  }}
                  className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-4 py-2 font-mono text-[12px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleLabel}
                  disabled={!labelSql.trim() || busy === "label"}
                  className="rounded-[var(--radius-sm)] bg-[var(--accent)] px-4 py-2 font-mono text-[12px] font-medium uppercase tracking-[0.04em] text-[#080c0f] transition-all duration-[var(--duration-fast)] hover:shadow-[var(--shadow-glow)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  {busy === "label" ? "保存中..." : "保存标注"}
                </button>
              </div>
            </div>
          </div>
        ) : null}

        {/* ── Review Modal ── */}
        {reviewModalOpen && reviewingCandidate ? (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
            <div className="w-full max-w-2xl rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--bg-raised)] p-6 shadow-[0_0_40px_rgba(0,0,0,0.5)]">
              <h3 className="font-mono text-[14px] font-medium uppercase tracking-[0.04em] text-[var(--text-primary)]">
                审核候选规则 #{reviewingCandidate.id}
              </h3>
              <p className="mt-2 font-mono text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                {reviewingCandidate.question_example}
              </p>
              <div className="mt-3 space-y-3">
                <CodeBlock
                  title="候选规则"
                  value={reviewingCandidate.proposed_rule_json || {}}
                  language="json"
                  maxHeightClassName="max-h-40"
                />
                {reviewingCandidate.proposed_few_shot_text ? (
                  <CodeBlock
                    title="候选 Few-Shot"
                    value={reviewingCandidate.proposed_few_shot_text}
                    language="text"
                    maxHeightClassName="max-h-32"
                  />
                ) : null}
              </div>
              <div className="mt-4">
                <label className="font-mono text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                  审核备注
                </label>
                <input
                  value={reviewNote}
                  onChange={(e) => setReviewNote(e.target.value)}
                  className="mt-1 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-2 font-mono text-[13px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                  placeholder="可选备注"
                />
              </div>
              <div className="mt-5 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setReviewModalOpen(false);
                    setReviewingCandidate(null);
                  }}
                  className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-4 py-2 font-mono text-[12px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={() => handleReview("reject")}
                  disabled={busy === "review"}
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--error)]/30 bg-[var(--error)]/10 px-4 py-2 font-mono text-[12px] font-medium uppercase tracking-[0.04em] text-[var(--error)] transition-all duration-[var(--duration-fast)] hover:bg-[var(--error)]/20 hover:shadow-[0_0_20px_var(--error-glow)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  <ThumbsDown className="h-3.5 w-3.5" />
                  驳回
                </button>
                <button
                  type="button"
                  onClick={() => handleReview("approve")}
                  disabled={busy === "review"}
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--success)] px-4 py-2 font-mono text-[12px] font-medium uppercase tracking-[0.04em] text-[#080c0f] transition-all duration-[var(--duration-fast)] hover:shadow-[0_0_20px_var(--success-glow)] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  <ThumbsUp className="h-3.5 w-3.5" />
                  批准
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </main>
  );
}
