import { Bot, MessageCircle, PlusCircle, Send, User, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { CodeBlock } from "@/components/CodeBlock";
import { StatusBadge } from "@/components/StatusBadge";
import { fetchSSE } from "@/lib/stream";
import type { ChatStreamEvent, JsonValue, Message } from "@/types";

const NODE_LABELS: Record<string, string> = {
  intent: "意图理解",
  retrieval: "检索表结构",
  bfs: "分析关联表",
  schema: "组装上下文",
  sql_gen: "生成 SQL",
  safety: "安全校验",
  execute: "执行查询",
};

function makeId(): string {
  return crypto.randomUUID();
}

function userMessage(content: string): Message {
  return {
    id: makeId(),
    role: "user",
    content,
    type: "text",
    timestamp: Date.now(),
  };
}

function assistantProgress(msg: string): Message {
  return {
    id: makeId(),
    role: "assistant",
    content: msg,
    type: "progress",
    timestamp: Date.now(),
    nodeStatus: {},
  };
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [threadId, setThreadId] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(async () => {
    const query = input.trim();
    if (!query || running) return;

    setInput("");
    setRunning(true);

    const userMsg = userMessage(query);
    const assistantMsg = assistantProgress("正在理解您的问题...");
    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    let currentNodeStatus: Record<string, "pending" | "running" | "done" | "error"> = {};
    const allNodes = ["intent", "retrieval", "bfs", "schema", "sql_gen", "safety", "execute"];

    try {
      const stepAcc: Array<{ node: string; label: string; textPreview: string; status: "running" | "done" | "error" }> = [];
      await fetchSSE(
        "/chat/stream",
        { query, thread_id: threadId },
        (event: ChatStreamEvent) => {
          if (event.thread_id && !threadId) {
            setThreadId(event.thread_id);
          }

          const nodeName = event.node;
          if (nodeName === "done" || nodeName === "error") {
            // 更新为完成状态
            allNodes.forEach((n) => {
              if (currentNodeStatus[n] !== "error") currentNodeStatus[n] = "done";
            });
            const textPreview = (event.data?.text_preview as string) || "";
            const execData = (event.data?.execution_result as Record<string, JsonValue>) || null;
            const finalSql = (event.data?.final_sql as string) || (event.data?.generated_sql as string) || "";
            const status = event.status === "error" ? "error" : "success";
            const content = status === "error"
              ? `错误: ${(event.data?.error as string) || "未知错误"}`
              : `查询完成 ✓`;

            setMessages((prev) =>
              prev.map((msg) => {
                if (msg.id === assistantMsg.id) {
                  return {
                    ...msg,
                    content,
                    type: status === "error" ? "error" : "text",
                    nodeStatus: currentNodeStatus as Record<string, "pending" | "running" | "done" | "error">,
                    sql: finalSql,
                    executionResult: execData,
                    steps: [...stepAcc],
                  };
                }
                return msg;
              }),
            );
            return;
          }

          // 进度事件：更新节点状态
          if (currentNodeStatus[nodeName] !== "error") {
            currentNodeStatus[nodeName] = "done";
          }
          const label = NODE_LABELS[nodeName] || nodeName;
          const textPreview = (event.data?.text_preview as string) || "";

          // 收集步骤信息
          const existing = stepAcc.find((s) => s.node === nodeName);
          if (existing) {
            existing.textPreview = textPreview || existing.textPreview;
            existing.status = "done";
          } else {
            stepAcc.push({ node: nodeName, label, textPreview, status: "running" });
          }
          // 标记当前步骤之前的为 done
          stepAcc.forEach((s) => {
            if (s.node !== nodeName && s.status === "running") s.status = "done";
          });

          const pendingNodes = allNodes.filter(
            (n) => currentNodeStatus[n] !== "done" && currentNodeStatus[n] !== "error",
          );
          const progressText =
            pendingNodes.length > 0
              ? `正在: ${label}（剩余 ${pendingNodes.length - 1} 步）...`
              : `已完成: ${label}`;
          setMessages((prev) =>
            prev.map((msg) => {
              if (msg.id === assistantMsg.id) {
                return {
                  ...msg,
                  content: textPreview || progressText,
                  type: "progress" as const,
                  nodeStatus: { ...currentNodeStatus },
                };
              }
              return msg;
            }),
          );
        },
        (error: Error) => {
          setMessages((prev) =>
            prev.map((msg) => {
              if (msg.id === assistantMsg.id) {
                return {
                  ...msg,
                  content: `请求失败: ${error.message}`,
                  type: "error",
                  nodeStatus: Object.fromEntries(allNodes.map((n) => [n, "error"])),
                };
              }
              return msg;
            }),
          );
        },
        () => {
          setRunning(false);
          inputRef.current?.focus();
        },
      );
    } catch {
      setRunning(false);
      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.id === assistantMsg.id) {
            return { ...msg, content: "请求异常，请重试", type: "error" };
          }
          return msg;
        }),
      );
    }
  }, [input, running, threadId]);

  function handleNewChat() {
    setMessages([]);
    setThreadId("");
    setInput("");
    inputRef.current?.focus();
  }

  return (
    <main className="flex h-screen flex-col bg-[radial-gradient(circle_at_top,rgba(34,211,238,0.12),transparent_26%),linear-gradient(180deg,#020617_0%,#0f172a_55%,#020617_100%)] text-slate-100">
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between border-b border-white/10 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <Bot className="h-6 w-6 text-cyan-300" />
          <h1 className="font-['Rajdhani'] text-xl font-semibold tracking-[0.1em] text-white uppercase">MES 对话助手</h1>
          {threadId ? <StatusBadge tone="warning">{threadId.slice(0, 8)}</StatusBadge> : null}
          {running ? <StatusBadge tone="loading">处理中</StatusBadge> : null}
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleNewChat}
            disabled={running}
            className="inline-flex items-center gap-2 rounded-full border border-white/10 px-4 py-2 text-sm text-slate-300 transition hover:border-cyan-300/30 hover:bg-cyan-300/10 disabled:opacity-50"
          >
            <PlusCircle className="h-4 w-4" />
            新对话
          </button>
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-full border border-white/10 px-4 py-2 text-sm text-slate-300 transition hover:border-cyan-300/30 hover:bg-cyan-300/10"
          >
            <XCircle className="h-4 w-4" />
            返回调试
          </Link>
        </div>
      </header>

      {/* Chat Area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-slate-400">
              <MessageCircle className="h-16 w-16 text-cyan-300/30" />
              <p className="text-lg">开始对话，用自然语言查询 MES 数据</p>
              <p className="text-sm">支持多轮记忆，可连续追问</p>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-4">
              {messages.map((msg) => (
                <ChatBubble key={msg.id} message={msg} />
              ))}
              {running && (
                <div className="flex justify-center py-2">
                  <div className="flex items-center gap-2 text-sm text-slate-500">
                    <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-300" />
                    处理中...
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Context Panel */}
        <div className="hidden w-80 shrink-0 overflow-y-auto border-l border-white/10 bg-slate-950/60 px-4 py-4 xl:block">
          <h2 className="mb-4 font-['Rajdhani'] text-sm tracking-[0.16em] text-slate-400 uppercase">上下文信息</h2>
          {threadId ? (
            <div className="space-y-3 text-sm">
              <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3">
                <div className="text-xs text-slate-500">会话 ID</div>
                <div className="font-mono text-cyan-200">{threadId.slice(0, 16)}...</div>
              </div>
              <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3">
                <div className="text-xs text-slate-500">消息数</div>
                <div className="text-white">{messages.length}</div>
              </div>
              {(() => {
                const lastAssistantMsg = [...messages].reverse().find((m) => m.role === "assistant");
                if (!lastAssistantMsg?.nodeStatus) return null;
                return (
                  <div className="rounded-xl border border-white/10 bg-white/[0.04] p-3">
                    <div className="mb-2 text-xs text-slate-500">节点进度</div>
                    <div className="space-y-1">
                      {Object.entries(lastAssistantMsg.nodeStatus).map(([node, status]) => (
                        <div key={node} className="flex items-center gap-2 text-xs">
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${
                              status === "done" ? "bg-emerald-400" : status === "running" ? "bg-cyan-400" : status === "error" ? "bg-red-400" : "bg-slate-600"
                            }`}
                          />
                          <span className="text-slate-300">{NODE_LABELS[node] || node}</span>
                          <span className="text-slate-500">{status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })()}
              {(() => {
                const lastAssistantMsg = [...messages].reverse().find((m) => m.role === "assistant" && m.sql);
                if (!lastAssistantMsg?.sql) return null;
                return (
                  <div>
                    <div className="mb-2 text-xs text-slate-500">生成的 SQL</div>
                    <CodeBlock title="SQL" value={lastAssistantMsg.sql} language="sql" maxHeightClassName="max-h-48" />
                  </div>
                );
              })()}
            </div>
          ) : (
            <p className="text-sm text-slate-500">发送第一条消息后显示</p>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-white/10 bg-slate-950/80 px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
            disabled={running}
            placeholder="输入查询问题，例如：查询所有工单及其对应的料号信息"
            className="flex-1 rounded-2xl border border-white/10 bg-slate-900/80 px-5 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/20 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void handleSend()}
            disabled={running || !input.trim()}
            className="inline-flex items-center gap-2 rounded-2xl bg-cyan-300 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
            发送
          </button>
        </div>
        <p className="mx-auto mt-3 max-w-3xl text-xs text-slate-500">
          试试："上一条 SQL 查出的工单有哪些产线？"  — 支持多轮记忆，可连续追问
        </p>
      </div>
    </main>
  );
}

function ChatBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const isError = message.type === "error";
  const hasProgress = message.type === "progress" && message.nodeStatus;
  const hasSteps = !isUser && message.steps && message.steps.length > 0;

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          isUser ? "bg-cyan-300/20" : isError ? "bg-red-400/20" : "bg-cyan-300/20"
        }`}
      >
        {isUser ? <User className="h-4 w-4 text-cyan-300" /> : <Bot className="h-4 w-4 text-cyan-300" />}
      </div>
      <div className={`max-w-[80%] space-y-2 ${isUser ? "items-end" : ""}`}>
        {/* 进度指示器 */}
        {hasProgress && message.nodeStatus && (
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(message.nodeStatus).map(([node, status]) => (
              <span
                key={node}
                className={`rounded-full px-2.5 py-0.5 text-[10px] ${
                  status === "done"
                    ? "bg-emerald-400/15 text-emerald-300"
                    : status === "running"
                      ? "bg-cyan-400/15 text-cyan-300"
                      : status === "error"
                        ? "bg-red-400/15 text-red-300"
                        : "bg-slate-600/15 text-slate-400"
                }`}
              >
                {NODE_LABELS[node] || node}
              </span>
            ))}
          </div>
        )}
        {/* 文本内容 */}
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
            isUser
              ? "bg-cyan-300 text-slate-950"
              : isError
                ? "border border-red-400/30 bg-red-400/10 text-red-200"
                : message.type === "progress"
                  ? "border border-white/10 bg-white/[0.04] text-slate-300"
                  : "border border-white/10 bg-white/[0.06] text-slate-200"
          }`}
        >
          {message.content}
        </div>
        {/* 步骤详情 */}
        {hasSteps && (
          <div className="space-y-1.5 pt-1">
            {message.steps!.map((step, i) => (
              <div
                key={step.node}
                className="flex items-start gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2"
              >
                <span
                  className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                    step.status === "done"
                      ? "bg-emerald-400"
                      : step.status === "error"
                        ? "bg-red-400"
                        : "bg-cyan-400"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <div className="text-xs text-slate-400">
                    {step.label}
                    {i === 0 && step.status !== "done" && (
                      <span className="ml-2 text-cyan-400">进行中...</span>
                    )}
                  </div>
                  {step.textPreview && (
                    <div className="mt-1 text-xs leading-relaxed text-slate-300 whitespace-pre-wrap break-all">
                      {step.textPreview}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        {/* SQL 代码块 */}
        {message.sql && (
          <div className="pt-1">
            <CodeBlock title="SQL" value={message.sql} language="sql" maxHeightClassName="max-h-64" />
          </div>
        )}
        {/* 执行结果简要 */}
        {message.executionResult && !(message.executionResult as Record<string, JsonValue>).error && (
          <div className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-400">
            <span className="text-emerald-300">✓</span> 查询成功
            {typeof (message.executionResult as Record<string, JsonValue>).rows === "number" &&
              `，返回 ${(message.executionResult as Record<string, JsonValue>).rows} 行`}
          </div>
        )}
        {/* 数据预览表格 */}
        {(() => {
          const er = message.executionResult as Record<string, JsonValue> | null | undefined;
          const preview = er?.preview as Array<Record<string, JsonValue>> | undefined;
          const columns = er?.columns as string[] | undefined;
          if (!preview || preview.length === 0 || !columns) return null;
          return (
            <div className="overflow-x-auto rounded-xl border border-white/10">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-white/10 bg-white/[0.04]">
                    {columns.map((col: string) => (
                      <th key={col} className="whitespace-nowrap px-3 py-2 text-left font-medium text-slate-300">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {preview.map((row, ri) => (
                    <tr key={ri} className="hover:bg-white/[0.04]">
                      {columns!.map((col: string) => (
                        <td key={col} className="whitespace-nowrap px-3 py-1.5 text-slate-400">
                          {String(row[col] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
