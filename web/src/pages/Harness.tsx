import {
  ArrowUpRight,
  Beaker,
  Bot,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Eye,
  MessageCircle,
  Moon,
  RefreshCw,
  Search,
  Sun,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useTheme } from "@/hooks/useTheme";

import { CodeBlock } from "@/components/CodeBlock";
import Empty from "@/components/Empty";
import { MetricCard } from "@/components/MetricCard";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import {
  analyzeFailures,
  deleteCandidate,
  deleteFailureCase,
  labelFailureCase,
  listCandidates,
  listFailureCases,
  listFeedback,
  prePublishCheck,
  previewEntityExtract,
  publishApproved,
  reviewCandidate,
} from "@/lib/api";
import type {
  DedupSimilarItem,
  EntityExtractPreview,
  FeedbackRecord,
  HarnessCandidate,
  HarnessFailureCase,
  PrePublishCheckResponse,
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

function FeedbackItem({ fb }: { fb: FeedbackRecord }) {
  const [sqlExpanded, setSqlExpanded] = useState(false);
  const displaySql = fb.final_sql || fb.generated_sql || "";

  return (
    <div className="group relative rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)]">
      <div className={`absolute inset-y-0 left-0 w-[2px] rounded-l-[var(--radius-sm)] transition-opacity duration-[var(--duration-normal)] ${fb.user_rating === 1 ? "bg-[var(--success)]" : "bg-[var(--error)]"} opacity-60`} />
      <div className="relative flex items-center gap-3 p-3">
        <span className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.04em] ${fb.user_rating === 1 ? "bg-[var(--success)]/10 text-[var(--success)] border-[var(--success)]/20" : "bg-[var(--error)]/10 text-[var(--error)] border-[var(--error)]/20"}`}>
          {fb.user_rating === 1 ? (
            <ThumbsUp className="h-3 w-3" />
          ) : (
            <ThumbsDown className="h-3 w-3" />
          )}
          {fb.user_rating === 1 ? "点赞" : "点踩"}
        </span>
        <span className="flex-1 truncate text-[12px] text-[var(--text-secondary)]">
          {fb.query_text || "(无查询文本)"}
        </span>
        <span className="font-mono text-[10px] text-[var(--text-tertiary)]/50 tabular-nums shrink-0">
          {fb.created_at ? new Date(fb.created_at).toLocaleString() : ""}
        </span>
      </div>
      {fb.user_feedback ? (
        <div className="mx-3 mb-3 rounded-[var(--radius-sm)] border border-[var(--warning)]/20 bg-[var(--warning)]/5 px-3 py-2">
          <p className="font-mono text-[12px] leading-relaxed text-[var(--text-secondary)]">
            {fb.user_feedback}
          </p>
        </div>
      ) : null}
      {displaySql ? (
        <div className="mx-3 mb-3">
          <button
            type="button"
            onClick={() => setSqlExpanded(!sqlExpanded)}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-2 py-1 font-mono text-[10px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
          >
            {sqlExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            SQL
            {fb.execution_success ? (
              <CheckCircle className="h-3 w-3 text-[var(--success)]" />
            ) : (
              <XCircle className="h-3 w-3 text-[var(--error)]" />
            )}
          </button>
          {sqlExpanded ? (
            <div className="mt-2">
              <CodeBlock title={fb.final_sql ? "Final SQL" : "Generated SQL"} value={displaySql} language="sql" maxHeightClassName="max-h-48" />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}


function getNum(r: Record<string, unknown>, key: string): number {
  return Number(r[key]) || 0;
}

interface ResultCategoryProps {
  icon: ReactNode;
  label: string;
  tone: "success" | "warning" | "accent" | "neutral";
  lines: string[];
}

function ResultCategory({ icon, label, tone, lines }: ResultCategoryProps) {
  const toneColor = {
    success: "var(--success)",
    warning: "var(--warning)",
    accent: "var(--accent)",
    neutral: "var(--text-tertiary)",
  }[tone];
  return (
    <div className="group relative rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-3 transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)]">
      <div className="absolute inset-y-0 left-0 w-[2px] rounded-l-[var(--radius-sm)] opacity-60" style={{ backgroundColor: toneColor }} />
      <div className="flex items-center gap-2 mb-1.5">
        <span className="flex h-5 w-5 items-center justify-center rounded border border-[var(--border-default)] bg-[var(--bg-subtle)]" style={{ color: toneColor }}>
          {icon}
        </span>
        <span className="font-mono text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--text-primary)]">
          {label}
        </span>
      </div>
      {lines.map((line, i) => (
        <p key={i} className="ml-7 font-mono text-[10px] leading-relaxed text-[var(--text-tertiary)]">
          {line}
        </p>
      ))}
    </div>
  );
}

function AnalyzeResultPanel({ result }: { result: Record<string, unknown> }) {
  const synced = getNum(result, "synced_failures");
  const total = getNum(result, "open_failures") + getNum(result, "liked_requests") + getNum(result, "retry_success_cases");
  const upserted = getNum(result, "candidates_upserted");
  const skipped = getNum(result, "candidates_skipped");

  return (
    <Panel title="分析结果" subtitle={`同步 ${synced} 条失败案例，共处理 ${total} 条，生成 ${upserted} 条候选，跳过 ${skipped} 条`}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {/* 人工标注 */}
        <ResultCategory
          icon={<CheckCircle className="h-3 w-3" />}
          label="人工标注"
          tone="success"
          lines={[
            `生成 ${getNum(result, "labeled_candidates")} 条候选`,
            getNum(result, "labeled_skipped") > 0 ? `跳过 ${getNum(result, "labeled_skipped")} 条（已存在）` : "",
          ].filter(Boolean)}
        />

        {/* SQL 匹配恢复 */}
        <ResultCategory
          icon={<Search className="h-3 w-3" />}
          label="SQL 匹配恢复"
          tone="accent"
          lines={[
            `恢复 ${getNum(result, "recovered_candidates")} 条候选`,
          ]}
        />

        {/* LLM 回退标注 */}
        <ResultCategory
          icon={<Bot className="h-3 w-3" />}
          label="LLM 回退标注"
          tone="warning"
          lines={[
            `生成 ${getNum(result, "llm_generated_candidates")} 条候选`,
            `自动通过 ${getNum(result, "llm_auto_approved")} 条`,
            getNum(result, "llm_medium_confidence") > 0 ? `待确认 ${getNum(result, "llm_medium_confidence")} 条` : "",
            getNum(result, "llm_failed") > 0 ? `失败 ${getNum(result, "llm_failed")} 条` : "",
          ].filter(Boolean)}
        />

        {/* 用户点赞 */}
        <ResultCategory
          icon={<ThumbsUp className="h-3 w-3" />}
          label="用户点赞"
          tone="success"
          lines={[
            `${getNum(result, "liked_requests")} 条请求 → ${getNum(result, "liked_candidates")} 条候选`,
            getNum(result, "liked_skipped") > 0 ? `跳过 ${getNum(result, "liked_skipped")} 条（已存在）` : "",
          ].filter(Boolean)}
        />

        {/* 重试成功评估 */}
        {getNum(result, "retry_success_cases") > 0 ? (
          <ResultCategory
            icon={<RefreshCw className="h-3 w-3" />}
            label="重试成功评估"
            tone="warning"
            lines={[
              `${getNum(result, "retry_success_cases")} 条案例`,
              `自动通过 ${getNum(result, "retry_auto_approved")} 条`,
              getNum(result, "retry_medium_confidence") > 0 ? `待确认 ${getNum(result, "retry_medium_confidence")} 条` : "",
              getNum(result, "retry_low_confidence") > 0 ? `低置信 ${getNum(result, "retry_low_confidence")} 条` : "",
              getNum(result, "retry_skipped") > 0 ? `跳过 ${getNum(result, "retry_skipped")} 条（已由点赞处理）` : "",
            ].filter(Boolean)}
          />
        ) : null}
      </div>
    </Panel>
  );
}

export default function Harness() {
  const { isDark, toggleTheme } = useTheme();

  // ── State ──
  const [failures, setFailures] = useState<HarnessFailureCase[]>([]);
  const [candidates, setCandidates] = useState<HarnessCandidate[]>([]);
  const [feedbacks, setFeedbacks] = useState<FeedbackRecord[]>([]);
  const [failureStatus, setFailureStatus] = useState("");
  const [candidateStatus, setCandidateStatus] = useState("");
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<number>>(new Set());
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
  const [structuralPreview, setStructuralPreview] = useState<EntityExtractPreview | null>(null);

  // Publish
  const [publishVersion, setPublishVersion] = useState(`web-${new Date().toISOString().slice(0, 10)}`);

  // Pre-publish check state
  const [prePublishDialog, setPrePublishDialog] = useState<{
    open: boolean;
    result: PrePublishCheckResponse | null;
  }>({ open: false, result: null });

  // Analyze config（含 LLM 回退参数）
  const [analyzeLimit, setAnalyzeLimit] = useState(200);
  const [analyzeGenModel, setAnalyzeGenModel] = useState("");
  const [analyzeEvalModel, setAnalyzeEvalModel] = useState("");

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
  const upCount = useMemo(() => feedbacks.filter((f) => f.user_rating === 1).length, [feedbacks]);
  const downCount = useMemo(() => feedbacks.filter((f) => f.user_rating === -1).length, [feedbacks]);

  // ── Effects ──
  useEffect(() => {
    void refreshFailures();
    void refreshCandidates();
    void refreshFeedbacks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Actions ──
  async function refreshFeedbacks() {
    try {
      const items = await listFeedback();
      setFeedbacks(items);
    } catch {
      // ignore
    }
  }

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

  // 默认选中所有 approved 候选
  useEffect(() => {
    setSelectedCandidateIds(new Set(candidates.filter((c) => c.status === "approved").map((c) => c.id)));
  }, [candidates]);

  async function handleAnalyze() {
    setBusy("analyze");
    try {
      const result = await analyzeFailures(analyzeLimit, analyzeGenModel, analyzeEvalModel);
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

  async function handlePublish() {
    setBusy("publish");
    const publishIds = [...selectedCandidateIds];
    try {
      // 先做去重检查
      const checkResult = await prePublishCheck();
      if (checkResult.duplicate_items && checkResult.duplicate_items.length > 0) {
        setPrePublishDialog({ open: true, result: checkResult });
        setBusy("");
        return;
      }

      // 无重复，直接发布选中项
      const result = await publishApproved(publishVersion, false, publishIds);
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

  async function handleDeleteCandidate(candidateId: number) {
    if (!window.confirm("确认删除此候选规则？此操作不可撤销。")) return;
    setBusy("delete");
    try {
      await deleteCandidate(candidateId);
      setSelectedCandidateIds((prev) => {
        const next = new Set(prev);
        next.delete(candidateId);
        return next;
      });
      await refreshCandidates();
    } catch {
      // ignore
    } finally {
      setBusy("");
    }
  }

  async function handleDeleteFailureCase(failureCaseId: number) {
    if (!window.confirm("确认删除此失败案例？此操作不可撤销。")) return;
    setBusy("delete");
    try {
      await deleteFailureCase(failureCaseId);
      await refreshFailures();
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

  async function openReviewModal(c: HarnessCandidate) {
    setReviewingCandidate(c);
    setReviewNote("");
    setStructuralPreview(null);
    setReviewModalOpen(true);
    // 获取结构化抽取预览
    if (c.question_example) {
      try {
        const result = await previewEntityExtract(c.question_example);
        setStructuralPreview(result);
      } catch {
        // 预览失败不影响审核
      }
    }
  }

  function statusTone(s: string): "success" | "error" | "warning" | "loading" | "neutral" {
    const map: Record<string, "success" | "error" | "warning" | "loading" | "neutral"> = {
      open: "error",
      labeled: "success",
      auto_labeled: "warning",
      promoted: "warning",
      pending: "warning",
      approved: "success",
      rejected: "error",
      published: "success",
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
      {/* ── Top Navigation Bar ── */}
      <div className="flex items-center justify-between border-b border-[var(--border-default)] bg-[var(--bg-raised)] px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4">
          <Link
            to="/"
            className="font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--text-tertiary)] transition-colors hover:text-[var(--accent)]"
          >
            ← 对话
          </Link>
          <Link
            to="/home"
            className="font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--text-tertiary)] transition-colors hover:text-[var(--accent)]"
          >
            调试
          </Link>
          <Link
            to="/graph"
            className="font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--text-tertiary)] transition-colors hover:text-[var(--accent)]"
          >
            关系图
          </Link>
          <Link
            to="/trace"
            className="font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--text-tertiary)] transition-colors hover:text-[var(--accent)]"
          >
            链路追踪
          </Link>
        </div>
        <button
          type="button"
          onClick={toggleTheme}
          title={isDark ? "切换到亮色模式" : "切换到暗色模式"}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-2.5 py-1.5 font-mono text-[11px] text-[var(--text-secondary)] transition-all duration-150 hover:border-[var(--border-accent)] hover:text-[var(--accent)] hover:shadow-[var(--shadow-glow)]"
        >
          {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
          {isDark ? "LIGHT" : "DARK"}
        </button>
      </div>

      <div className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
        {/* ── Header ── */}
        <section className="relative overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--bg-raised)] p-6 sm:p-8">
          {/* Corner accent decorative border */}
          <div
            className="pointer-events-none absolute inset-0 rounded-lg opacity-[0.06]"
            style={{
              border: "1px solid transparent",
              borderImage: "linear-gradient(135deg, var(--accent) 0%, transparent 40%, transparent 60%, var(--accent) 100%) 1",
            }}
          />
          <div className="relative z-10 flex flex-wrap items-start justify-between gap-6">
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
            <div className="group relative overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-4 transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)] hover:shadow-[0_0_24px_var(--accent-glow)]">
              <div className="absolute inset-x-0 top-0 h-[1px] bg-gradient-to-r from-transparent via-[var(--accent)] to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-30" />
              <div className="mb-2 flex h-8 w-8 items-center justify-center rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] text-[var(--accent)] transition-colors duration-300 group-hover:border-[var(--border-accent)] group-hover:bg-[var(--accent-surface)]">
                <Search className="h-4 w-4" />
              </div>
              <div className="font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--text-primary)]">
                分析失败案例
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                从线上失败案例和用户点赞记录生成候选规则（含 LLM 回退 + 重试成功评估）
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
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
                <div className="flex items-center gap-2">
                  <label className="font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                    生成模型:
                  </label>
                  <input
                    value={analyzeGenModel}
                    onChange={(e) => setAnalyzeGenModel(e.target.value)}
                    placeholder="默认"
                    className="w-28 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-1 font-mono text-[12px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <label className="font-mono text-[10px] uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                    评估模型:
                  </label>
                  <input
                    value={analyzeEvalModel}
                    onChange={(e) => setAnalyzeEvalModel(e.target.value)}
                    placeholder="默认"
                    className="w-28 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-1 font-mono text-[12px] text-[var(--text-primary)] outline-none transition-all duration-[var(--duration-fast)] placeholder:text-[var(--text-tertiary)]/40 focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
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

            {/* Publish */}
            <div className="group relative overflow-hidden rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-4 transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)] hover:shadow-[0_0_24px_var(--accent-glow)]">
              <div className="absolute inset-x-0 top-0 h-[1px] bg-gradient-to-r from-transparent via-[var(--accent)] to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-30" />
              <div className="mb-2 flex h-8 w-8 items-center justify-center rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] text-[var(--accent)] transition-colors duration-300 group-hover:border-[var(--border-accent)] group-hover:bg-[var(--accent-surface)]">
                <ArrowUpRight className="h-4 w-4" />
              </div>
              <div className="font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--text-primary)]">
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
        {lastResult && lastResultTitle === "分析失败案例" ? (
          <AnalyzeResultPanel result={lastResult} />
        ) : lastResult ? (
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
                  className="group relative rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)]"
                >
                  {/* Left accent bar on hover */}
                  <div className="absolute inset-y-0 left-0 w-[2px] rounded-l-[var(--radius-sm)] bg-[var(--accent)] opacity-0 transition-opacity duration-[var(--duration-normal)] group-hover:opacity-50" />
                  <div
                    className="relative flex cursor-pointer items-center gap-3 p-3 transition-colors duration-[var(--duration-fast)] hover:bg-[var(--accent-surface)]"
                    onClick={() => setExpandedFailure(expandedFailure === fc.id ? null : fc.id)}
                  >
                    <span className="font-mono text-[11px] text-[var(--text-tertiary)]/60 tabular-nums">
                      #{fc.id}
                    </span>
                    <StatusBadge tone={statusTone(fc.status)}>{statusLabel(fc.status)}</StatusBadge>
                    <StatusBadge tone="neutral">{fc.failure_type}</StatusBadge>
                    {fc.user_feedback ? (
                      <span className="inline-flex items-center gap-1 rounded border border-[var(--warning)]/20 bg-[var(--warning)]/5 px-1.5 py-0.5 font-mono text-[9px] text-[var(--warning)]" title="用户反馈">
                        <ThumbsDown className="h-2.5 w-2.5" />
                        反馈
                      </span>
                    ) : null}
                    <span className="flex-1 truncate text-[12px] text-[var(--text-secondary)]">
                      {fc.query_text}
                    </span>
                    <span className="font-mono text-[10px] text-[var(--text-tertiary)]/50 tabular-nums">
                      重试 {fc.retry_count}
                    </span>
                    {expandedFailure === fc.id ? (
                      <ChevronUp className="h-4 w-4 text-[var(--text-tertiary)]/40 transition-transform duration-[var(--duration-fast)]" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-[var(--text-tertiary)]/40 transition-transform duration-[var(--duration-fast)] group-hover:text-[var(--text-tertiary)]/70" />
                    )}
                  </div>
                  {expandedFailure === fc.id ? (
                    <div className="animate-fade-slide-in border-t border-[var(--border-default)] p-4 space-y-3">
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
                      {fc.user_feedback ? (
                        <div className="rounded-[var(--radius-sm)] border border-[var(--warning)]/20 bg-[var(--warning)]/5 p-3">
                          <div className="flex items-center gap-2 mb-1.5">
                            <ThumbsDown className="h-3.5 w-3.5 text-[var(--warning)]" />
                            <span className="font-mono text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--warning)]">
                              用户反馈
                            </span>
                          </div>
                          <p className="font-mono text-[12px] leading-relaxed text-[var(--text-secondary)]">
                            {fc.user_feedback}
                          </p>
                        </div>
                      ) : null}
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => openLabelModal(fc)}
                          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-accent)] hover:text-[var(--accent)] hover:bg-[var(--accent-surface)]"
                        >
                          {fc.correct_sql ? "修改标注" : "补充 SQL"}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteFailureCase(fc.id)}
                          className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--error)]/30 bg-[var(--error)]/5 px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--error)] transition-all duration-[var(--duration-fast)] hover:bg-[var(--error)]/15 hover:border-[var(--error)]/50"
                        >
                          删除
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
              <button
                type="button"
                onClick={() => {
                  const allApproved = candidates.filter((c) => c.status === "approved");
                  if (selectedCandidateIds.size === allApproved.length && allApproved.length > 0) {
                    setSelectedCandidateIds(new Set());
                  } else {
                    setSelectedCandidateIds(new Set(allApproved.map((c) => c.id)));
                  }
                }}
                className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-2 py-1 font-mono text-[11px] leading-none text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
              >
                {selectedCandidateIds.size > 0 ? `已选 ${selectedCandidateIds.size}` : "全选"}
              </button>
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
                  className="group relative rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] transition-all duration-[var(--duration-normal)] hover:border-[var(--border-accent)]"
                >
                  {/* Left accent bar on hover — color matches status */}
                  <div className={`absolute inset-y-0 left-0 w-[2px] rounded-l-[var(--radius-sm)] opacity-0 transition-opacity duration-[var(--duration-normal)] group-hover:opacity-50 ${c.status === "approved" ? "bg-[var(--success)]" : c.status === "rejected" ? "bg-[var(--error)]" : "bg-[var(--accent)]"}`} />
                  <div
                    className="relative flex cursor-pointer items-center gap-3 p-3 transition-colors duration-[var(--duration-fast)] hover:bg-[var(--accent-surface)]"
                    onClick={() => setExpandedCandidate(expandedCandidate === c.id ? null : c.id)}
                  >
                    <input
                      type="checkbox"
                      checked={selectedCandidateIds.has(c.id)}
                      onChange={(e) => {
                        e.stopPropagation();
                        setSelectedCandidateIds((prev) => {
                          const next = new Set(prev);
                          if (e.target.checked) {
                            next.add(c.id);
                          } else {
                            next.delete(c.id);
                          }
                          return next;
                        });
                      }}
                      className="h-3.5 w-3.5 cursor-pointer rounded border-[var(--border-default)] accent-[var(--accent)]"
                    />
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
                      <ChevronUp className="h-4 w-4 text-[var(--text-tertiary)]/40 transition-transform duration-[var(--duration-fast)]" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-[var(--text-tertiary)]/40 transition-transform duration-[var(--duration-fast)] group-hover:text-[var(--text-tertiary)]/70" />
                    )}
                  </div>
                  {expandedCandidate === c.id ? (
                    <div className="animate-fade-slide-in border-t border-[var(--border-default)] p-4 space-y-3">
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
                          <button
                            type="button"
                            onClick={() => handleDeleteCandidate(c.id)}
                            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--error)]/30 bg-[var(--error)]/5 px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--error)] transition-all duration-[var(--duration-fast)] hover:bg-[var(--error)]/15 hover:border-[var(--error)]/50"
                          >
                            删除
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

        {/* ── User Feedback Records ── */}
        <Panel
          title="用户反馈记录"
          subtitle={`共 ${feedbacks.length} 条（👍 ${upCount} / 👎 ${downCount}）`}
          action={
            <button
              type="button"
              onClick={refreshFeedbacks}
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
            >
              <RefreshCw className="h-3 w-3" />
              刷新
            </button>
          }
        >
          {feedbacks.length === 0 ? (
            <Empty />
          ) : (
            <div className="max-h-[600px] space-y-1 overflow-auto">
              {feedbacks.map((fb) => (
                <FeedbackItem key={fb.request_id} fb={fb} />
              ))}
            </div>
          )}
        </Panel>

        {/* ── Label Modal ── */}
        {labelModalOpen && labelingCase ? (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm">
            <div className="animate-fade-slide-in w-full max-w-2xl rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--bg-raised)] p-6 shadow-[0_0_60px_rgba(0,0,0,0.6)]">
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
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm">
            <div className="animate-fade-slide-in w-full max-w-2xl rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--bg-raised)] p-6 shadow-[0_0_60px_rgba(0,0,0,0.6)]">
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
                {structuralPreview ? (
                  <div className="rounded border border-[var(--border-default)] bg-[var(--bg-overlay)] p-3 text-xs">
                    <div className="font-medium text-[var(--text-primary)] mb-1.5">结构化抽取预览</div>
                    <div className="grid grid-cols-2 gap-1.5">
                      <div><span className="text-[var(--text-tertiary)]">实体词：</span>{structuralPreview.structural.object_entity || "(无)"}</div>
                      <div><span className="text-[var(--text-tertiary)]">动作：</span>{structuralPreview.structural.action_type}</div>
                      <div><span className="text-[var(--text-tertiary)]">域：</span>{structuralPreview.structural.domain || "(无)"}</div>
                      <div className="font-mono text-[11px]"><span className="text-[var(--text-tertiary)]">Key：</span>{structuralPreview.archive_key}</div>
                    </div>
                  </div>
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

        {/* ── Pre-Publish 去重确认弹窗 ── */}
        {prePublishDialog.open && prePublishDialog.result ? (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm">
            <div className="animate-fade-slide-in w-full max-w-2xl rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--bg-raised)] p-6 shadow-[0_0_60px_rgba(0,0,0,0.6)]">
              <h3 className="font-mono text-[14px] font-medium uppercase tracking-[0.04em] text-[var(--text-primary)]">
                发布前确认 — 发现 {prePublishDialog.result.duplicate_items.length} 个相似条目
              </h3>
              <p className="mt-2 text-[11px] leading-relaxed text-[var(--text-warning)]">
                以下候选项与知识库中已有条目高度相似。重复发布可能导致知识库冗余。无重复的候选 {prePublishDialog.result.clean_count} 项仍会正常发布。
              </p>
              <div className="mt-3 max-h-[300px] space-y-1 overflow-auto">
                {prePublishDialog.result.duplicate_items.map((item, idx) => (
                  <div
                    key={idx}
                    className="rounded border border-[var(--border-default)] bg-[var(--bg-overlay)] p-2 text-xs"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <StatusBadge tone={item.match_type === "exact" ? "error" : "warning"}>
                        {item.match_type === "exact" ? "精确匹配" : "向量相似"}
                      </StatusBadge>
                      <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
                        相似度: {(item.score * 100).toFixed(1)}%
                      </span>
                      {item.candidate_id ? (
                        <span className="font-mono text-[10px] text-[var(--text-tertiary)]/50">
                          候选 #{item.candidate_id}
                        </span>
                      ) : null}
                    </div>
                    <div className="text-[var(--text-primary)]">新增: {item.question}</div>
                    {item.existing_item && Object.keys(item.existing_item).length > 0 ? (
                      <div className="mt-1 text-[10px] text-[var(--text-tertiary)]">
                        已有: {typeof item.existing_item.question === "string" ? item.existing_item.question : JSON.stringify(item.existing_item)}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
              <div className="mt-5 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setPrePublishDialog({ open: false, result: null })}
                  className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-4 py-2 font-mono text-[12px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    setPrePublishDialog({ open: false, result: null });
                    setBusy("publish");
                    const forceIds = [...selectedCandidateIds];
                    try {
                      const result = await publishApproved(publishVersion, true, forceIds);
                      setLastResult(result);
                      setLastResultTitle("发布版本");
                      await refreshCandidates();
                    } catch {
                      // ignore
                    } finally {
                      setBusy("");
                    }
                  }}
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-4 py-2 font-mono text-[12px] font-medium uppercase tracking-[0.04em] text-[#080c0f] transition-all duration-[var(--duration-fast)] hover:shadow-[var(--shadow-glow)]"
                >
                  仍然发布全部
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </main>
  );
}
