import {
  Activity,
  ArrowUpRight,
  Bot,
  Database,
  DatabaseZap,
  MessageCircle,
  RefreshCw,
  SearchCode,
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
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.16),transparent_26%),linear-gradient(180deg,#020617_0%,#0f172a_55%,#020617_100%)] px-4 py-8 text-slate-100 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="relative overflow-hidden rounded-[2rem] border border-cyan-300/15 bg-slate-950/80 px-6 py-8 shadow-[0_40px_120px_rgba(8,15,34,0.65)] sm:px-8">
          <div className="absolute inset-0 bg-[linear-gradient(120deg,rgba(34,211,238,0.08),transparent_38%,rgba(59,130,246,0.08))]" />
          <div className="relative grid gap-6 lg:grid-cols-[1.4fr_1fr]">
            <div>
              <StatusBadge tone="success">Online Harness</StatusBadge>
              <h1 className="mt-4 font-['Rajdhani'] text-4xl font-semibold tracking-[0.12em] text-white uppercase sm:text-5xl">
                MES NL2SQL Test Console
              </h1>
              <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300">
                一个给研发和测试直接使用的调试页。左边跑查询，右边看 Harness，底部看每次接口执行返回。
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <Link
                  to="/chat"
                  className="inline-flex items-center gap-2 rounded-full border border-cyan-300/30 bg-cyan-300/10 px-4 py-2 text-sm text-cyan-200 transition hover:border-cyan-300/50 hover:bg-cyan-300/20"
                >
                  <MessageCircle className="h-4 w-4" />
                  对话助手
                </Link>
                {presetQueries.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setQuery(item)}
                    className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:border-cyan-300/30 hover:bg-cyan-300/10"
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <MetricCard label="成功请求" value={successCount} hint="最近 8 次操作" icon={<ShieldCheck className="h-5 w-5" />} />
              <MetricCard label="失败请求" value={errorCount} hint="包含接口异常和校验失败" icon={<DatabaseZap className="h-5 w-5" />} />
              <MetricCard label="失败案例" value={failures.length} hint="当前列表条数" icon={<Database className="h-5 w-5" />} />
              <MetricCard label="候选规则" value={candidates.length} hint="当前列表条数" icon={<Sparkles className="h-5 w-5" />} />
            </div>
          </div>
        </section>

        <div className="grid gap-6 xl:grid-cols-[1.35fr_0.95fr]">
          <Panel
            title="NL2SQL 调试"
            subtitle="输入问题，直接调用 /nl2sql，并实时展示 SQL、执行结果和知识版本。"
            action={<StatusBadge tone={running ? "loading" : "neutral"}>{running ? "执行中" : "Ready"}</StatusBadge>}
          >
            <div className="space-y-4">
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                rows={5}
                className="w-full rounded-3xl border border-white/10 bg-slate-900/80 px-4 py-4 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20"
                placeholder="输入要测试的自然语言问题..."
              />
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={handleRun}
                  disabled={running || !query.trim()}
                  className="inline-flex items-center gap-2 rounded-full bg-cyan-300 px-5 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <SearchCode className="h-4 w-4" />
                  执行查询
                </button>
                {nl2sqlResult ? <StatusBadge tone={nl2sqlResult.safe ? "success" : "error"}>{nl2sqlResult.safe ? "Safe SQL" : "Unsafe"}</StatusBadge> : null}
                {nl2sqlResult?.knowledge_version ? <StatusBadge tone="warning">{nl2sqlResult.knowledge_version}</StatusBadge> : null}
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <CodeBlock title="生成 SQL" value={nl2sqlResult?.sql ?? ""} language="sql" />
                <CodeBlock title="执行结果 JSON" value={nl2sqlResult?.execution_result ?? { message: "尚未执行" }} language="json" />
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <CodeBlock title="JOIN 提示" value={nl2sqlResult?.join_hints ?? ""} language="text" maxHeightClassName="max-h-56" />
                <CodeBlock
                  title="响应摘要"
                  value={{
                    request_id: nl2sqlResult?.request_id ?? "",
                    retry_count: nl2sqlResult?.retry_count ?? 0,
                    tables_used: nl2sqlResult?.tables_used ?? [],
                    error: nl2sqlResult?.error ?? "",
                  }}
                  language="json"
                  maxHeightClassName="max-h-56"
                />
              </div>
            </div>
          </Panel>

          <Panel
            title="Harness 控制台"
            subtitle="查看失败案例与候选规则，直接触发分析和发布。"
            action={<StatusBadge tone={adminBusy ? "loading" : "neutral"}>{adminBusy || "idle"}</StatusBadge>}
          >
            <div className="space-y-4">
              <div className="flex flex-wrap gap-3">
                <button type="button" onClick={() => void refreshFailures()} className="rounded-full border border-white/10 px-4 py-2 text-sm transition hover:border-cyan-300/30 hover:bg-cyan-300/10">
                  <RefreshCw className="mr-2 inline h-4 w-4" />
                  刷新失败案例
                </button>
                <button type="button" onClick={() => void refreshCandidates()} className="rounded-full border border-white/10 px-4 py-2 text-sm transition hover:border-cyan-300/30 hover:bg-cyan-300/10">
                  <RefreshCw className="mr-2 inline h-4 w-4" />
                  刷新候选规则
                </button>
                <button type="button" onClick={() => void handleAnalyze()} className="rounded-full bg-emerald-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-emerald-200">
                  <Bot className="mr-2 inline h-4 w-4" />
                  分析失败
                </button>
              </div>
              <div className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                <label className="text-xs tracking-[0.16em] text-slate-400 uppercase">发布版本号</label>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <input
                    value={versionInput}
                    onChange={(event) => setVersionInput(event.target.value)}
                    className="flex-1 rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 text-sm outline-none focus:border-cyan-300/40"
                  />
                  <button type="button" onClick={() => void handlePublish()} className="rounded-2xl bg-amber-300 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-amber-200">
                    <ArrowUpRight className="mr-2 inline h-4 w-4" />
                    发布已审核候选
                  </button>
                </div>
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <DataTable title="失败案例" count={failures.length} rows={failures.map((item) => [String(item.id), item.query_text, item.status, item.failure_type])} />
                <DataTable
                  title="候选规则"
                  count={candidates.length}
                  rows={candidates.map((item) => [String(item.id), item.question_example, item.status, item.candidate_type])}
                />
              </div>
            </div>
          </Panel>
        </div>

        <Panel title="接口执行回放" subtitle="最近一次调用结果和管理接口响应都会在这里留下记录。">
          <div className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
            <div className="space-y-3">
              {activity.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-400">
                  还没有接口调用记录，先执行一次查询或刷新 Harness 数据。
                </div>
              ) : (
                activity.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setActivity((current) => [item, ...current.filter((entry) => entry.id !== item.id)])}
                    className="w-full rounded-2xl border border-white/10 bg-white/[0.04] p-4 text-left transition hover:border-cyan-300/30 hover:bg-cyan-300/10"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium text-white">{item.title}</div>
                      <StatusBadge tone={item.status === "loading" ? "loading" : item.status === "error" ? "error" : "success"}>
                        {item.status}
                      </StatusBadge>
                    </div>
                    <div className="mt-2 text-sm text-slate-300">{item.summary}</div>
                    <div className="mt-3 flex items-center gap-3 text-xs text-slate-500">
                      <span>{item.method}</span>
                      <span>{item.endpoint}</span>
                      <span>{item.createdAt}</span>
                    </div>
                  </button>
                ))
              )}
            </div>
            <CodeBlock title="最近一次接口 Payload / Response" value={activity[0]?.payload ?? { message: "暂无数据" }} language="json" maxHeightClassName="max-h-[32rem]" />
          </div>
        </Panel>
      </div>
    </main>
  );
}

interface DataTableProps {
  title: string;
  count: number;
  rows: string[][];
}

function DataTable({ title, count, rows }: DataTableProps) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/70">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <div className="font-['Rajdhani'] text-sm tracking-[0.18em] text-slate-300 uppercase">{title}</div>
        <div className="text-xs text-slate-400">{count} 条</div>
      </div>
      <div className="max-h-72 overflow-auto">
        <table className="min-w-full text-left text-sm text-slate-300">
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="px-4 py-6 text-slate-500" colSpan={4}>
                  暂无数据
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={`${title}-${row[0]}`} className="border-b border-white/5 last:border-b-0">
                  {row.map((cell, index) => (
                    <td key={`${row[0]}-${index}`} className="max-w-[12rem] px-4 py-3 align-top text-xs leading-6 text-slate-300">
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
