import {
  ArrowUpRight,
  BarChart3,
  Bot,
  Database,
  MessageCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { CodeBlock } from "@/components/CodeBlock";
import { MetricCard } from "@/components/MetricCard";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { analyzeFailures, listCandidates, listFailureCases, publishApproved, runNl2Sql } from "@/lib/api";
import type { ActivityItem, HarnessCandidate, HarnessFailureCase, Nl2SqlResponse } from "@/types";

const presetQueries = [
  "查询工作站对应的工序、产线信息",
  "查询工单关联的编码规则组、标签组和包装规则",
  "查询 SN 状态关联的料号信息",
];

function makeActivity(item: Omit<ActivityItem, "id" | "createdAt">): ActivityItem {
  return {
    id: crypto.randomUUID(),
    createdAt: new Date().toLocaleString(),
    ...item,
  };
}

export default function Home() {
  const [query, setQuery] = useState(presetQueries[0]);
  const [versionInput, setVersionInput] = useState(`web-release-${new Date().toISOString().slice(0, 10)}`);
  const [running, setRunning] = useState(false);
  const [adminBusy, setAdminBusy] = useState<"" | "failures" | "candidates" | "analyze" | "publish">("");
  const [nl2sqlResult, setNl2sqlResult] = useState<Nl2SqlResponse | null>(null);
  const [failures, setFailures] = useState<HarnessFailureCase[]>([]);
  const [candidates, setCandidates] = useState<HarnessCandidate[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);

  const successCount = useMemo(() => activity.filter((item) => item.status === "success").length, [activity]);
  const errorCount = useMemo(() => activity.filter((item) => item.status === "error").length, [activity]);

  function pushActivity(item: Omit<ActivityItem, "id" | "createdAt">) {
    setActivity((current) => [makeActivity(item), ...current].slice(0, 8));
  }

  async function refreshFailures() {
    setAdminBusy("failures");
    try {
      const items = await listFailureCases();
      setFailures(items);
      pushActivity({
        title: "刷新失败案例",
        endpoint: "/admin/harness/failure-cases",
        method: "GET",
        status: "success",
        summary: `读取 ${items.length} 条失败案例`,
        payload: items,
      });
    } catch (error) {
      pushActivity({
        title: "刷新失败案例",
        endpoint: "/admin/harness/failure-cases",
        method: "GET",
        status: "error",
        summary: error instanceof Error ? error.message : "未知错误",
      });
    } finally {
      setAdminBusy("");
    }
  }

  async function refreshCandidates() {
    setAdminBusy("candidates");
    try {
      const items = await listCandidates();
      setCandidates(items);
      pushActivity({
        title: "刷新候选规则",
        endpoint: "/admin/harness/candidates",
        method: "GET",
        status: "success",
        summary: `读取 ${items.length} 条候选规则`,
        payload: items,
      });
    } catch (error) {
      pushActivity({
        title: "刷新候选规则",
        endpoint: "/admin/harness/candidates",
        method: "GET",
        status: "error",
        summary: error instanceof Error ? error.message : "未知错误",
      });
    } finally {
      setAdminBusy("");
    }
  }

  useEffect(() => {
    void refreshFailures();
    void refreshCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleRun() {
    setRunning(true);
    pushActivity({
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
      pushActivity({
        title: "执行 NL2SQL",
        endpoint: "/nl2sql",
        method: "POST",
        status: result.safe ? "success" : "error",
        summary: result.safe ? "已生成可执行 SQL" : result.error || "SQL 未通过校验",
        payload: result,
      });
      void refreshFailures();
    } catch (error) {
      pushActivity({
        title: "执行 NL2SQL",
        endpoint: "/nl2sql",
        method: "POST",
        status: "error",
        summary: error instanceof Error ? error.message : "未知错误",
      });
    } finally {
      setRunning(false);
    }
  }

  async function handleAnalyze() {
    setAdminBusy("analyze");
    try {
      const result = await analyzeFailures();
      pushActivity({
        title: "分析失败案例",
        endpoint: "/admin/harness/analyze-failures",
        method: "POST",
        status: "success",
        summary: "已完成失败分析",
        payload: result,
      });
      await refreshCandidates();
    } catch (error) {
      pushActivity({
        title: "分析失败案例",
        endpoint: "/admin/harness/analyze-failures",
        method: "POST",
        status: "error",
        summary: error instanceof Error ? error.message : "未知错误",
      });
    } finally {
      setAdminBusy("");
    }
  }

  async function handlePublish() {
    setAdminBusy("publish");
    try {
      const result = await publishApproved(versionInput);
      pushActivity({
        title: "发布知识版本",
        endpoint: "/admin/harness/publish",
        method: "POST",
        status: "success",
        summary: `发布版本 ${versionInput}`,
        payload: result,
      });
      await refreshCandidates();
    } catch (error) {
      pushActivity({
        title: "发布知识版本",
        endpoint: "/admin/harness/publish",
        method: "POST",
        status: "error",
        summary: error instanceof Error ? error.message : "未知错误",
      });
    } finally {
      setAdminBusy("");
    }
  }

  return (
    <main className="min-h-screen bg-[#0a0a0a] text-text-primary">
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6 lg:px-8">
        {/* ── Hero Section ── */}
        <section className="rounded-xl border border-white/[0.06] bg-[#111] p-6 sm:p-8">
          <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
            <div>
              <StatusBadge tone="success">Online</StatusBadge>
              <h1 className="mt-4 text-[28px] font-bold tracking-tight text-white sm:text-[32px]">
                MES NL2SQL <span className="text-text-tertiary font-normal">Test Console</span>
              </h1>
              <p className="mt-3 max-w-lg text-[14px] leading-relaxed text-text-tertiary">
                面向研发与测试的调试工具。左侧执行自然语言查询，右侧管理 Harness 规则。
              </p>
              <div className="mt-5 flex flex-wrap items-center gap-2">
                <Link
                  to="/chat"
                  className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-[13px] text-text-secondary transition-colors duration-150 hover:border-accent-border hover:text-white"
                >
                  <MessageCircle className="h-3.5 w-3.5" />
                  对话助手
                </Link>
                {presetQueries.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setQuery(item)}
                    className="rounded-md border border-white/[0.06] bg-white/[0.02] px-3 py-1.5 text-[12px] text-text-tertiary transition-colors duration-150 hover:border-accent-border hover:text-text-secondary"
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <MetricCard label="成功" value={successCount} hint="最近 8 次" icon={<ShieldCheck className="h-4 w-4" />} />
              <MetricCard label="失败" value={errorCount} hint="接口异常" icon={<BarChart3 className="h-4 w-4" />} />
              <MetricCard label="失败案例" value={failures.length} hint="当前列表" icon={<Database className="h-4 w-4" />} />
              <MetricCard label="候选规则" value={candidates.length} hint="当前列表" icon={<Sparkles className="h-4 w-4" />} />
            </div>
          </div>
        </section>

        {/* ── Main Content Grid ── */}
        <div className="grid gap-6 xl:grid-cols-[1.35fr_0.95fr]">
          {/* NL2SQL Panel */}
          <Panel
            title="NL2SQL 调试"
            subtitle="输入自然语言问题，调用 /nl2sql 接口并查看 SQL 与执行结果。"
            action={<StatusBadge tone={running ? "loading" : "neutral"}>{running ? "Running" : "Ready"}</StatusBadge>}
          >
            <div className="space-y-4">
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                rows={4}
                className="w-full rounded-lg border border-white/[0.08] bg-[#0d0d0d] px-4 py-3 text-[14px] text-text-primary outline-none transition-colors placeholder:text-text-tertiary/60 focus:border-accent-border focus:ring-1 focus:ring-accent/20"
                placeholder="输入要测试的自然语言问题..."
              />
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={handleRun}
                  disabled={running || !query.trim()}
                  className="inline-flex items-center gap-1.5 rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-white transition-colors duration-150 hover:bg-accent-600 active:bg-accent-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Search className="h-3.5 w-3.5" />
                  执行查询
                </button>
                {nl2sqlResult ? (
                  <StatusBadge tone={nl2sqlResult.safe ? "success" : "error"}>
                    {nl2sqlResult.safe ? "Safe SQL" : "Unsafe"}
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

          {/* Harness Panel */}
          <Panel
            title="Harness 控制台"
            subtitle="查看失败案例与候选规则，触发分析或发布。"
            action={<StatusBadge tone={adminBusy ? "loading" : "neutral"}>{adminBusy || "Idle"}</StatusBadge>}
          >
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void refreshFailures()}
                  className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.02] px-3 py-1.5 text-[12px] text-text-secondary transition-colors duration-150 hover:border-white/15 hover:text-white"
                >
                  <RefreshCw className="h-3 w-3" />
                  失败案例
                </button>
                <button
                  type="button"
                  onClick={() => void refreshCandidates()}
                  className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.02] px-3 py-1.5 text-[12px] text-text-secondary transition-colors duration-150 hover:border-white/15 hover:text-white"
                >
                  <RefreshCw className="h-3 w-3" />
                  候选规则
                </button>
                <button
                  type="button"
                  onClick={() => void handleAnalyze()}
                  className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-[12px] font-medium text-white transition-colors duration-150 hover:bg-emerald-500"
                >
                  <Bot className="h-3 w-3" />
                  分析失败
                </button>
              </div>

              <div className="space-y-3 rounded-lg border border-white/[0.06] bg-[#0d0d0d] p-4">
                <label className="text-[11px] font-medium tracking-[0.04em] text-text-tertiary uppercase">发布版本</label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    value={versionInput}
                    onChange={(event) => setVersionInput(event.target.value)}
                    className="flex-1 rounded-md border border-white/[0.08] bg-[#111] px-3 py-2 text-[13px] text-text-primary outline-none transition-colors focus:border-accent-border"
                  />
                  <button
                    type="button"
                    onClick={() => void handlePublish()}
                    className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 px-4 py-2 text-[13px] font-medium text-white transition-colors duration-150 hover:bg-amber-500"
                  >
                    <ArrowUpRight className="h-3.5 w-3.5" />
                    发布
                  </button>
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <MiniTable title="失败案例" count={failures.length} rows={failures.map((item) => [String(item.id), item.query_text, item.status, item.failure_type])} />
                <MiniTable
                  title="候选规则"
                  count={candidates.length}
                  rows={candidates.map((item) => [String(item.id), item.question_example, item.status, item.candidate_type])}
                />
              </div>
            </div>
          </Panel>
        </div>

        {/* ── Activity Log ── */}
        <Panel title="接口执行回放" subtitle="每次调用记录与响应详情。">
          <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
            <div className="space-y-2">
              {activity.length === 0 ? (
                <div className="rounded-lg border border-dashed border-white/[0.06] py-10 text-center text-[13px] text-text-tertiary">
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
                    className="w-full rounded-lg border border-white/[0.06] bg-[#0d0d0d] p-4 text-left transition-colors duration-150 hover:border-accent-border"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-medium text-white">{item.title}</span>
                      <StatusBadge
                        tone={
                          item.status === "loading"
                            ? "loading"
                            : item.status === "error"
                              ? "error"
                              : "success"
                        }
                      >
                        {item.status}
                      </StatusBadge>
                    </div>
                    <div className="mt-1.5 text-[12px] text-text-secondary">{item.summary}</div>
                    <div className="mt-2 flex items-center gap-3 font-mono text-[10px] text-text-tertiary/60">
                      <span>{item.method}</span>
                      <span>{item.endpoint}</span>
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

/* ── Mini Table ── */

interface MiniTableProps {
  title: string;
  count: number;
  rows: string[][];
}

function MiniTable({ title, count, rows }: MiniTableProps) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-[#0d0d0d] overflow-hidden">
      <div className="flex items-center justify-between border-b border-white/[0.05] px-3 py-2.5">
        <span className="text-[11px] font-medium tracking-[0.04em] text-text-tertiary uppercase">{title}</span>
        <span className="font-mono text-[11px] text-text-tertiary/60">{count}</span>
      </div>
      <div className="max-h-56 overflow-auto">
        <table className="w-full text-left">
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="px-3 py-8 text-center text-[12px] text-text-tertiary/50">暂无数据</td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={`${title}-${row[0]}`} className="border-b border-white/[0.03] last:border-b-0 hover:bg-white/[0.02]">
                  {row.map((cell, i) => (
                    <td key={`${row[0]}-${i}`} className="max-w-[10rem] truncate px-3 py-2 text-[11px] leading-relaxed text-text-tertiary">
                      {cell || "-"}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
