import {
  BarChart3,
  Database,
  MessageCircle,
  Moon,
  Search,
  ShieldCheck,
  Sparkles,
  Sun,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useTheme } from "@/hooks/useTheme";

import { CodeBlock } from "@/components/CodeBlock";
import { MetricCard } from "@/components/MetricCard";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { listCandidates, listFailureCases, runNl2Sql } from "@/lib/api";
import type { ActivityItem, HarnessCandidate, HarnessFailureCase, Nl2SqlResponse } from "@/types";

const presetQueries = [
  "查询工作站对应的工序、产线信息",
  "查询工单关联的编码规则组、标签组和包装规则",
  "查询 SN 状态关联的料号信息",
];

export default function Home() {
  const [query, setQuery] = useState(presetQueries[0]);
  const [running, setRunning] = useState(false);
  const [nl2sqlResult, setNl2sqlResult] = useState<Nl2SqlResponse | null>(null);
  const [failures, setFailures] = useState<HarnessFailureCase[]>([]);
  const [candidates, setCandidates] = useState<HarnessCandidate[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);

  const successCount = useMemo(() => activity.filter((item) => item.status === "success").length, [activity]);
  const errorCount = useMemo(() => activity.filter((item) => item.status === "error").length, [activity]);

  let _nextId = 1;

  function pushActivity(item: Omit<ActivityItem, "id" | "createdAt">): string {
    const id = String(_nextId++);
    setActivity((current) => [{ id, createdAt: new Date().toLocaleString(), ...item }, ...current].slice(0, 8));
    return id;
  }

  function updateActivity(id: string, updates: Partial<Omit<ActivityItem, "id" | "createdAt">>) {
    setActivity((current) =>
      current.map((entry) => (entry.id === id ? { ...entry, ...updates } : entry)),
    );
  }

  async function refreshFailures() {
    try {
      const items = await listFailureCases();
      setFailures(items);
    } catch {
      // silent — preview only
    }
  }

  async function refreshCandidates() {
    try {
      const items = await listCandidates();
      setCandidates(items);
    } catch {
      // silent — preview only
    }
  }

  useEffect(() => {
    void refreshFailures();
    void refreshCandidates();
  }, []);

  async function handleRun() {
    setRunning(true);
    const activityId = pushActivity({
      title: "执行 NL2SQL",
      endpoint: "/nl2sql",
      method: "POST",
      status: "loading",
      summary: query,
      payload: { query },
    });
    try {
      const result = await runNl2Sql(query);
      setNl2sqlResult(result);
      updateActivity(activityId, {
        status: result.safe ? "success" : "error",
        summary: result.safe ? "已生成可执行 SQL" : result.error || "SQL 未通过校验",
        payload: result,
      });
      void refreshFailures();
    } catch (error) {
      updateActivity(activityId, {
        status: "error",
        summary: error instanceof Error ? error.message : "未知错误",
      });
    } finally {
      setRunning(false);
    }
  }

  const { isDark, toggleTheme } = useTheme();

  return (
    <main className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
      <div className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
        {/* ── Top bar ── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              to="/"
              className="font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--text-tertiary)] transition-colors hover:text-[var(--accent)]"
            >
              ← 对话
            </Link>
            <Link
              to="/harness"
              className="font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--text-tertiary)] transition-colors hover:text-[var(--accent)]"
            >
              Harness
            </Link>
            <Link
              to="/graph"
              className="font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--text-tertiary)] transition-colors hover:text-[var(--accent)]"
            >
              关系图
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

        {/* ── Hero Section ── */}
        <section className="relative overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--bg-raised)] p-6 sm:p-8">
          {/* Corner accent */}
          <div
            className="pointer-events-none absolute inset-0 rounded-lg opacity-[0.06]"
            style={{
              border: "1px solid transparent",
              borderImage: "linear-gradient(135deg, var(--accent) 0%, transparent 40%, transparent 60%, var(--accent) 100%) 1",
            }}
          />
          <div className="relative z-10 grid gap-6 lg:grid-cols-[1.2fr_1fr]">
            <div>
              <StatusBadge tone="success">ONLINE</StatusBadge>
              <h1 className="mt-4 font-display text-[32px] font-bold uppercase leading-none tracking-tight text-[var(--text-primary)] sm:text-[36px]">
                MES NL2SQL
              </h1>
              <h2 className="font-display text-[18px] font-medium uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                Test Console
              </h2>
              <p className="mt-3 max-w-lg font-mono text-[12px] leading-relaxed text-[var(--text-tertiary)]">
                面向研发与测试的 NL2SQL 调试工具。执行自然语言查询，查看 SQL 生成与执行结果。知识管理请前往{" "}
                <Link to="/harness" className="text-[var(--accent)] transition-colors hover:underline">
                  Harness
                </Link>
                。
              </p>
              <div className="mt-5 flex flex-wrap items-center gap-2">
                <Link
                  to="/"
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--text-secondary)] transition-all duration-150 hover:border-[var(--border-accent)] hover:text-[var(--accent)]"
                >
                  <MessageCircle className="h-3.5 w-3.5" />
                  对话助手
                </Link>
                {presetQueries.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setQuery(item)}
                    className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 text-[11px] text-[var(--text-tertiary)] transition-all duration-150 hover:border-[var(--border-accent)] hover:text-[var(--text-secondary)]"
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <MetricCard label="成功" value={successCount} hint="最近 8 次" icon={<ShieldCheck className="h-4 w-4" />} />
              <MetricCard label="失败" value={errorCount} hint="接口异常" icon={<BarChart3 className="h-4 w-4" />} />
              <MetricCard label="失败案例" value={failures.length} hint="前往 Harness 处理" icon={<Database className="h-4 w-4" />} />
              <MetricCard label="候选规则" value={candidates.length} hint="前往 Harness 审核" icon={<Sparkles className="h-4 w-4" />} />
            </div>
          </div>
        </section>

        {/* ── NL2SQL Panel ── */}
        <Panel
          title="NL2SQL 调试"
          subtitle="输入自然语言问题，调用 /nl2sql 接口并查看 SQL 与执行结果。"
          action={<StatusBadge tone={running ? "loading" : "neutral"}>{running ? "RUNNING" : "READY"}</StatusBadge>}
        >
          <div className="space-y-4">
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              rows={4}
              className="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-4 py-3 font-mono text-[13px] text-[var(--text-primary)] outline-none transition-colors placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]/20"
              placeholder="输入要测试的自然语言问题..."
            />
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleRun}
                disabled={running || !query.trim()}
                className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-4 py-2 font-mono text-[11px] font-medium uppercase tracking-[0.04em] text-white transition-all duration-150 hover:shadow-[var(--shadow-glow)] active:opacity-80 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <Search className="h-3.5 w-3.5" />
                执行查询
              </button>
              {nl2sqlResult ? (
                <StatusBadge tone={nl2sqlResult.safe ? "success" : "error"}>
                  {nl2sqlResult.safe ? "SAFE SQL" : "UNSAFE"}
                </StatusBadge>
              ) : null}
              {nl2sqlResult?.knowledge_version ? (
                <StatusBadge tone="warning">{nl2sqlResult.knowledge_version}</StatusBadge>
              ) : null}
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              <CodeBlock title="SQL" value={nl2sqlResult?.sql ?? ""} language="sql" />
              <CodeBlock
                title="Result"
                value={nl2sqlResult?.execution_result ?? { message: "尚未执行" }}
                language="json"
              />
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              <CodeBlock title="Join Hints" value={nl2sqlResult?.join_hints ?? ""} language="text" maxHeightClassName="max-h-48" />
              <CodeBlock
                title="Summary"
                value={{
                  request_id: nl2sqlResult?.request_id ?? "",
                  retry_count: nl2sqlResult?.retry_count ?? 0,
                  tables_used: nl2sqlResult?.tables_used ?? [],
                  error: nl2sqlResult?.error ?? "",
                }}
                language="json"
                maxHeightClassName="max-h-48"
              />
            </div>
          </div>
        </Panel>

        {/* ── Activity Log ── */}
        <Panel title="接口执行回放" subtitle="每次调用记录与响应详情。">
          <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
            <div className="space-y-2">
              {activity.length === 0 ? (
                <div className="rounded-[var(--radius-md)] border border-dashed border-[var(--border-default)] py-10 text-center font-mono text-[12px] text-[var(--text-tertiary)]">
                  暂无记录，请先执行查询或刷新数据。
                </div>
              ) : (
                activity.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() =>
                      setActivity((current) => [item, ...current.filter((entry) => entry.id !== item.id)])
                    }
                    className="w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-4 text-left transition-all duration-150 hover:border-[var(--border-accent)]"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[12px] font-medium uppercase tracking-[0.04em] text-[var(--text-primary)]">
                        {item.title}
                      </span>
                      <StatusBadge
                        tone={
                          item.status === "loading"
                            ? "loading"
                            : item.status === "error"
                              ? "error"
                              : "success"
                        }
                      >
                        {item.status.toUpperCase()}
                      </StatusBadge>
                    </div>
                    <div className="mt-1.5 text-[11px] text-[var(--text-secondary)]">{item.summary}</div>
                    <div className="mt-2 flex items-center gap-3 font-mono text-[10px] text-[var(--text-tertiary)] opacity-60">
                      <span>{item.method}</span>
                      <span className="opacity-40">|</span>
                      <span>{item.endpoint}</span>
                      <span className="opacity-40">|</span>
                      <span>{item.createdAt}</span>
                    </div>
                  </button>
                ))
              )}
            </div>
            <CodeBlock
              title="Payload / Response"
              value={activity[0]?.payload ?? { message: "暂无数据" }}
              language="json"
              maxHeightClassName="max-h-[28rem]"
            />
          </div>
        </Panel>
      </div>
    </main>
  );
}
