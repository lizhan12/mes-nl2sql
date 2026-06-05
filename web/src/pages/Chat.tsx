import { Bot, ChevronLeft, ChevronRight, Clock, GitBranch, MessageCircle, Moon, Plus, Send, Sun, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { CodeBlock } from "@/components/CodeBlock";
import { PaginationBar } from "@/components/PaginationBar";
import { StatusBadge } from "@/components/StatusBadge";
import { fetchPage, fetchChatHistory, loadChatThread, submitFeedback } from "@/lib/api";
import type { ChatHistoryItem as ChatHistoryItemType } from "@/lib/api";
import { fetchSSE } from "@/lib/stream";
import { useTheme } from "@/hooks/useTheme";
import { useUser } from "@/hooks/useUser";
import type { ChatStreamEvent, JsonValue, Message, PageResponse, SqlResult } from "@/types";

function parseSqlLimit(sql: string): { limit: number } {
  const match = sql.match(/\bLIMIT\s+(\d+)\s*;?\s*$/i);
  return { limit: match ? parseInt(match[1], 10) : 0 };
}

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

function ThemeToggle() {
  const { isDark, toggleTheme } = useTheme();
  return (
    <button
      type="button"
      onClick={toggleTheme}
      title={isDark ? "切换到亮色模式" : "切换到暗色模式"}
      className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border-default)] bg-[var(--bg-overlay)] px-2.5 py-1.5 text-[15px] text-[var(--text-secondary)] transition-colors duration-150 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
    >
      {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
    </button>
  );
}

export default function Chat() {
  const { userId } = useUser();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [threadId, setThreadId] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 反馈状态
  const [ratedMessages, setRatedMessages] = useState<Set<string>>(new Set());
  const [feedbackModal, setFeedbackModal] = useState<{ msgId: string; requestId: string } | null>(null);
  const [feedbackReason, setFeedbackReason] = useState("");

  // 历史会话
  const [historySessions, setHistorySessions] = useState<ChatHistoryItemType[]>([]);
  const [showHistory, setShowHistory] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // 加载用户历史会话列表
  useEffect(() => {
    if (userId) {
      setHistoryLoading(true);
      fetchChatHistory(userId)
        .then(setHistorySessions)
        .catch(() => {})
        .finally(() => setHistoryLoading(false));
    }
  }, [userId]);

  async function loadSession(targetThreadId: string) {
    setHistoryLoading(true);
    try {
      const thread = await loadChatThread(userId, targetThreadId);
      if (thread && thread.messages) {
        setMessages(
          thread.messages.map((m) => ({
            id: makeId(),
            role: (m.role as "user" | "assistant") || "user",
            content: m.content || "",
            type: "text" as const,
            timestamp: Date.now(),
          })),
        );
        setThreadId(targetThreadId);
      }
    } catch {
      // ignore
    } finally {
      setHistoryLoading(false);
    }
  }

  const refreshHistory = useCallback(() => {
    if (userId) {
      fetchChatHistory(userId).then(setHistorySessions).catch(() => {});
    }
  }, [userId]);

  const handleSend = useCallback(async () => {
    const query = input.trim();
    if (!query || running) return;

    setInput("");
    setRunning(true);

    const userMsg = userMessage(query);
    const assistantMsg = assistantProgress("正在理解您的问题...");
    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    const currentNodeStatus: Record<string, "pending" | "running" | "done" | "error"> = {};
    const allNodes = ["intent", "retrieval", "bfs", "schema", "sql_gen", "safety", "execute"];

    try {
      const stepAcc: Array<{ node: string; label: string; textPreview: string; status: "running" | "done" | "error" }> = [];
      await fetchSSE(
        "/chat/stream",
        { query, thread_id: threadId, user_id: userId },
        (event: ChatStreamEvent) => {
          if (event.thread_id && !threadId) {
            setThreadId(event.thread_id);
          }

          const nodeName = event.node;
          if (nodeName === "done" || nodeName === "error") {
            allNodes.forEach((n) => {
              if (currentNodeStatus[n] !== "error") currentNodeStatus[n] = "done";
            });
            const status = event.status === "error" ? "error" : "success";

            const multiSql = (event.data?.multi_sql as boolean) || false;
            const subQueries = (event.data?.sub_queries as Array<{ question: string; description: string }>) || [];
            const finalSqls = (event.data?.final_sqls as string[]) || [];
            const execResults = (event.data?.execution_results as SqlResult[]) || [];

            const execData = execResults.length > 0 ? (execResults[0] as unknown as Record<string, JsonValue>) : null;
            const requestId = (event.request_id as string) || "";
            const finalSql = finalSqls.length > 0 ? finalSqls[0] : (event.data?.final_sql as string) || (event.data?.generated_sql as string) || "";
            const content = status === "error"
              ? `错误: ${(event.data?.error as string) || "未知错误"}`
              : multiSql
                ? `查询完成（共 ${finalSqls.length} 条查询）`
                : `查询完成`;

            const enrichedResults: SqlResult[] = execResults.map((r, i) => ({
              ...r,
              sql: finalSqls[i] || "",
            }));

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
                    requestId,
                    multiSql,
                    finalSqls,
                    executionResults: enrichedResults,
                    subQueries,
                    steps: [...stepAcc],
                  };
                }
                return msg;
              }),
            );
            return;
          }

          if (currentNodeStatus[nodeName] !== "error") {
            currentNodeStatus[nodeName] = "done";
          }
          const label = NODE_LABELS[nodeName] || nodeName;
          const textPreview = (event.data?.text_preview as string) || "";

          const existing = stepAcc.find((s) => s.node === nodeName);
          if (existing) {
            existing.textPreview = textPreview || existing.textPreview;
            existing.status = "done";
          } else {
            stepAcc.push({ node: nodeName, label, textPreview, status: "running" });
          }
          stepAcc.forEach((s) => {
            if (s.node !== nodeName && s.status === "running") s.status = "done";
          });

          const pendingNodes = allNodes.filter(
            (n) => currentNodeStatus[n] !== "done" && currentNodeStatus[n] !== "error",
          );
          const progressText =
            pendingNodes.length > 0
              ? `${label}（剩余 ${pendingNodes.length - 1} 步）...`
              : `${label} 完成`;

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
          refreshHistory();
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
  }, [input, running, threadId, userId, refreshHistory]);

  function handleNewChat() {
    setMessages([]);
    setThreadId("");
    setInput("");
    setRatedMessages(new Set());
    inputRef.current?.focus();
  }

  function handleThumbsUp(msgId: string, requestId: string) {
    if (ratedMessages.has(msgId)) return;
    setRatedMessages((prev) => new Set(prev).add(msgId));
    submitFeedback(requestId, "up").catch(() => {});
  }

  function handleThumbsDown(msgId: string, requestId: string) {
    if (ratedMessages.has(msgId)) return;
    setFeedbackModal({ msgId, requestId });
  }

  async function handleSubmitFeedback() {
    if (!feedbackModal) return;
    const { msgId, requestId } = feedbackModal;
    setRatedMessages((prev) => new Set(prev).add(msgId));
    await submitFeedback(requestId, "down", feedbackReason);
    setFeedbackModal(null);
    setFeedbackReason("");
  }

  return (
    <main className="flex h-screen flex-col bg-[var(--bg-base)] text-[var(--text-primary)]">
      {/* ── Header ── */}
      <header className="flex shrink-0 items-center justify-between border-b border-[var(--border-default)] bg-[var(--bg-raised)] px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            title={showHistory ? "隐藏历史" : "显示历史"}
            className="inline-flex items-center rounded-md border border-[var(--border-default)] bg-[var(--bg-overlay)] p-1.5 text-[var(--text-secondary)] transition-colors hover:border-[var(--border-strong)]"
          >
            {showHistory ? <ChevronLeft className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
          <Bot className="h-5 w-5 text-accent-500" />
          <h1 className="text-[18px] font-semibold tracking-tight text-[var(--text-primary)]">
            MES <span className="font-normal text-text-tertiary">对话助手</span>
          </h1>
          <StatusBadge tone="neutral">{userId.slice(0, 8)}</StatusBadge>
          {threadId ? <StatusBadge tone="warning">{threadId.slice(0, 8)}</StatusBadge> : null}
          {running ? <StatusBadge tone="loading">处理中</StatusBadge> : null}
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button
            type="button"
            onClick={handleNewChat}
            disabled={running}
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-1.5 text-[15px] text-[var(--text-secondary)] transition-colors duration-150 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
            新对话
          </button>
          <Link
            to="/home"
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-1.5 text-[15px] text-[var(--text-secondary)] transition-colors duration-150 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
          >
            <X className="h-3.5 w-3.5" />
            调试
          </Link>
          <Link
            to="/graph"
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-1.5 text-[15px] text-[var(--text-secondary)] transition-colors duration-150 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
          >
            <GitBranch className="h-3.5 w-3.5" />
            关系图
          </Link>
        </div>
      </header>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── History Sidebar ── */}
        {showHistory ? (
          <div className="w-64 shrink-0 overflow-y-auto border-r border-[var(--border-default)] bg-[var(--bg-raised)]">
            <div className="px-3 py-3">
              <h2 className="flex items-center gap-1.5 text-[12px] font-medium tracking-[0.04em] text-[var(--text-secondary)] uppercase">
                <Clock className="h-3 w-3" />
                对话历史
              </h2>
            </div>
            {historyLoading && historySessions.length === 0 ? (
              <div className="px-3 py-6 text-center text-[13px] text-text-tertiary/50">加载中...</div>
            ) : historySessions.length === 0 ? (
              <div className="px-3 py-6 text-center text-[13px] text-text-tertiary/50">暂无对话记录</div>
            ) : (
              <div className="space-y-0.5 px-2 pb-3">
                {historySessions.map((s) => (
                  <button
                    key={s.thread_id}
                    type="button"
                    onClick={() => loadSession(s.thread_id)}
                    className={`w-full rounded-md px-3 py-2 text-left transition-colors ${
                      s.thread_id === threadId
                        ? "bg-accent/10 text-accent-500"
                        : "text-[var(--text-secondary)] hover:bg-[var(--bg-overlay)]"
                    }`}
                  >
                    <div className="truncate text-[13px]">{s.first_query || "空对话"}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-text-tertiary/50">
                      <span>{s.message_count} 条消息</span>
                      <span>
                        {s.updated_at
                          ? new Date(s.updated_at).toLocaleDateString("zh-CN", {
                              month: "short",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : ""}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : null}

        {/* Messages Area */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-3">
              <div className="flex h-14 w-14 items-center justify-center rounded-xl border border-[var(--border-default)] bg-[var(--bg-raised)]">
                <MessageCircle className="h-6 w-6 text-text-tertiary/40" />
              </div>
              <p className="text-[17px] text-text-tertiary">用自然语言查询 MES 数据</p>
              <p className="text-[14px] text-text-tertiary/50">支持多轮记忆，可连续追问</p>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-5">
              {messages.map((msg) => (
                <ChatBubble
                  key={msg.id}
                  message={msg}
                  rated={ratedMessages.has(msg.id)}
                  onThumbsUp={(requestId) => handleThumbsUp(msg.id, requestId)}
                  onThumbsDown={(requestId) => handleThumbsDown(msg.id, requestId)}
                />
              ))}
              {running && (
                <div className="flex justify-center py-1">
                  <div className="flex items-center gap-2 text-[14px] text-text-tertiary">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                    处理中...
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Side Panel ── */}
        <div className="hidden w-72 shrink-0 overflow-y-auto border-l border-[var(--border-default)] bg-[var(--bg-raised)] px-4 py-4 xl:block">
          <h2 className="mb-4 text-[13px] font-medium tracking-[0.04em] text-[var(--text-secondary)] uppercase">
            上下文信息
          </h2>
          {threadId ? (
            <div className="space-y-3 text-sm">
              <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-overlay)] p-3">
                <div className="text-[13px] text-text-tertiary/60">会话 ID</div>
                <div className="mt-1 font-mono text-[13px] text-accent-500">{threadId.slice(0, 16)}...</div>
              </div>
              <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-overlay)] p-3">
                <div className="text-[13px] text-text-tertiary/60">消息</div>
                <div className="mt-1 text-[17px] font-semibold tabular-nums text-[var(--text-primary)]">{messages.length}</div>
              </div>
              {(() => {
                const lastAssistantMsg = [...messages].reverse().find((m) => m.role === "assistant");
                if (!lastAssistantMsg?.nodeStatus) return null;
                return (
                  <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-overlay)] p-3">
                    <div className="mb-2 text-[13px] text-text-tertiary/60">节点进度</div>
                    <div className="space-y-1.5">
                      {Object.entries(lastAssistantMsg.nodeStatus).map(([node, status]) => (
                        <div key={node} className="flex items-center gap-2 text-[13px]">
                          <span
                            className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                              status === "done"
                                ? "bg-emerald-500"
                                : status === "running"
                                  ? "bg-accent"
                                  : status === "error"
                                    ? "bg-red-500"
                                    : "bg-white/20"
                            }`}
                          />
                          <span className="text-text-secondary">{NODE_LABELS[node] || node}</span>
                          <span className="ml-auto font-mono text-[12px] text-text-tertiary/50">{status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })()}
              {(() => {
                const lastAssistantMsg = [...messages]
                  .reverse()
                  .find((m) => m.role === "assistant" && (m.sql || (m.finalSqls && m.finalSqls.length > 0)));
                if (!lastAssistantMsg) return null;
                const sqls =
                  lastAssistantMsg.multiSql && lastAssistantMsg.finalSqls
                    ? lastAssistantMsg.finalSqls
                    : lastAssistantMsg.sql
                      ? [lastAssistantMsg.sql]
                      : [];
                return (
                  <div>
                    <div className="mb-2 text-[13px] text-text-tertiary/60">
                      SQL{sqls.length > 1 ? ` (${sqls.length})` : ""}
                    </div>
                    <div className="space-y-2">
                      {sqls.map((s, i) => (
                        <CodeBlock
                          key={i}
                          title={sqls.length > 1 ? `SQL ${i + 1}` : "SQL"}
                          value={s}
                          language="sql"
                          maxHeightClassName="max-h-40"
                        />
                      ))}
                    </div>
                  </div>
                );
              })()}
            </div>
          ) : (
            <p className="text-[12px] text-text-tertiary/50">发送第一条消息后显示</p>
          )}
        </div>
      </div>

      {/* ── Input ── */}
      <div className="shrink-0 border-t border-[var(--border-default)] bg-[var(--bg-raised)] px-4 py-4 sm:px-8">
        <div className="mx-auto flex max-w-3xl items-center gap-2">
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
            className="flex-1 rounded-lg border border-[var(--border-default)] bg-[var(--bg-overlay)] px-4 py-2.5 text-[16px] text-[var(--text-primary)] outline-none transition-colors placeholder:text-[var(--text-tertiary)] focus:border-accent-border focus:ring-1 focus:ring-accent/20 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void handleSend()}
            disabled={running || !input.trim()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-4 py-2.5 text-[15px] font-medium text-white transition-colors duration-150 hover:bg-accent-600 active:bg-accent-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Send className="h-4 w-4" />
            发送
          </button>
        </div>
        <p className="mx-auto mt-3 max-w-3xl text-[13px] text-text-tertiary/50">
          支持多轮记忆，可连续追问。例如："上一条 SQL 查出的工单有哪些产线？"
        </p>
      </div>

      {/* ── Feedback Modal ── */}
      {feedbackModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-md rounded-xl border border-[var(--border-default)] bg-[var(--bg-raised)] p-6">
            <h3 className="text-[17px] font-medium text-[var(--text-primary)]">告诉我们哪里有问题</h3>
            <p className="mt-1 text-[13px] text-text-tertiary">你的反馈将帮助我们改进 SQL 生成质量</p>
            <textarea
              value={feedbackReason}
              onChange={(e) => setFeedbackReason(e.target.value)}
              rows={4}
              className="mt-4 w-full rounded-lg border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-2 text-[15px] text-[var(--text-primary)] outline-none focus:border-accent-border placeholder:text-[var(--text-tertiary)]"
              placeholder="例如：表关联错误、字段名不对、条件遗漏..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setFeedbackModal(null);
                  setFeedbackReason("");
                }}
                className="rounded-md border border-[var(--border-default)] bg-[var(--bg-overlay)] px-4 py-2 text-[15px] text-[var(--text-secondary)] transition-colors hover:border-[var(--border-strong)]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void handleSubmitFeedback()}
                disabled={!feedbackReason.trim()}
                className="rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-accent-600 disabled:cursor-not-allowed disabled:opacity-40"
              >
                提交
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}

/* ── Multi SQL Tabs ── */

function MultiSqlTabs({ message }: { message: Message }) {
  const [activeTab, setActiveTab] = useState(0);
  const results = message.executionResults!;
  const [pageStates, setPageStates] = useState<Record<number, { page: number; data: PageResponse | null; loading: boolean }>>({});

  const currentResult = results[activeTab];
  const pState = pageStates[activeTab] || { page: 1, data: null, loading: false };

  const sqlLimit = currentResult?.sql ? parseSqlLimit(currentResult.sql).limit : 0;
  const pageSize = sqlLimit > 0 ? sqlLimit : 20;
  const totalRows = pState.data
    ? pState.data.total_rows
    : ((typeof currentResult?.rows === "number" ? currentResult.rows : 0) as number);
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));

  const fetchData = async (targetPage: number) => {
    const sql = currentResult?.sql || "";
    if (!sql) return;

    setPageStates((prev) => ({
      ...prev,
      [activeTab]: { ...(prev[activeTab] || { page: 1, data: null, loading: false }), loading: true },
    }));

    try {
      const data = await fetchPage(sql, targetPage, pageSize);
      setPageStates((prev) => ({
        ...prev,
        [activeTab]: { page: targetPage, data, loading: false },
      }));
    } catch {
      setPageStates((prev) => ({
        ...prev,
        [activeTab]: { ...(prev[activeTab] || { page: 1, data: null, loading: false }), loading: false },
      }));
    }
  };

  useEffect(() => {
    if (currentResult?.success && currentResult?.sql && !pageStates[activeTab]?.data) {
      fetchData(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, currentResult?.sql]);

  const handlePageChange = (targetPage: number) => {
    if (targetPage < 1 || targetPage > totalPages) return;
    fetchData(targetPage);
  };

  const tableData = pState.data?.rows;
  const tableColumns = pState.data?.columns;

  return (
    <div className="space-y-3 pt-1">
      <div className="flex gap-1 overflow-x-auto rounded-lg border border-[var(--border-default)] bg-[var(--bg-overlay)] p-1">
        {results.map((result, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => setActiveTab(idx)}
            className={`shrink-0 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors duration-150 ${
              activeTab === idx ? "bg-accent/15 text-accent-500" : "text-text-tertiary hover:text-text-secondary"
            }`}
          >
            {result.description || `SQL ${idx + 1}`}
            <span
              className={`ml-1.5 inline-block h-1.5 w-1.5 rounded-full ${result.success ? "bg-emerald-500" : "bg-red-500"}`}
            />
          </button>
        ))}
      </div>

      {currentResult && (
        <div className="space-y-3">
          {currentResult.question && <div className="text-[13px] text-text-tertiary">{currentResult.question}</div>}
          {!currentResult.success && currentResult.error && (
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-[13px] text-red-400">
              {currentResult.error}
            </div>
          )}
          {currentResult.success && (
            <div className="rounded-lg border border-emerald-500/10 bg-emerald-500/5 px-3 py-2 text-[13px] text-emerald-400">
              SQL 执行成功
              {currentResult.repaired && <span className="ml-2 text-amber-400">（已修复）</span>}
            </div>
          )}
          {currentResult.sql && (
            <CodeBlock title="SQL" value={currentResult.sql} language="sql" maxHeightClassName="max-h-52" />
          )}
          {currentResult.success && (
            <div className="space-y-2">
              {pState.loading && !tableData && (
                <div className="py-4 text-center text-[13px] text-text-tertiary">加载中...</div>
              )}
              {tableData && tableData.length > 0 && tableColumns && (
                <div className="overflow-x-auto rounded-lg border border-[var(--border-default)]">
                  <table className="w-full text-[14px]">
                    <thead>
                      <tr className="border-b border-[var(--border-default)] bg-[var(--bg-overlay)]">
                        {tableColumns.map((col: string) => (
                          <th key={col} className="whitespace-nowrap px-3 py-2 text-left font-medium text-text-secondary">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-default)]">
                      {tableData.map((row, ri) => (
                        <tr key={ri} className="hover:bg-[var(--bg-overlay)]">
                          {tableColumns!.map((col: string) => (
                            <td key={col} className="whitespace-nowrap px-3 py-1.5 text-text-tertiary text-[13px]">
                              {String(row[col] ?? "")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <PaginationBar
                page={pState.page}
                totalPages={totalPages}
                totalRows={totalRows}
                loading={pState.loading}
                onPageChange={handlePageChange}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Chat Bubble ── */

function ChatBubble({
  message,
  rated,
  onThumbsUp,
  onThumbsDown,
}: {
  message: Message;
  rated: boolean;
  onThumbsUp: (requestId: string) => void;
  onThumbsDown: (requestId: string) => void;
}) {
  const isUser = message.role === "user";
  const isError = message.type === "error";

  const hasSqlResult =
    !isUser &&
    (message.sql || (message.multiSql && message.executionResults && message.executionResults.length > 0));
  const showContent = isUser || isError || !hasSqlResult;

  const hasSingleSql = !isUser && message.sql && !message.multiSql;
  const hasMultiSql =
    !isUser && message.multiSql && message.executionResults && message.executionResults.length > 0;

  const [pageData, setPageData] = useState<PageResponse | null>(null);
  const [pageLoading, setPageLoading] = useState(false);

  const sqlLimit = message.sql ? parseSqlLimit(message.sql).limit : 0;
  const pageSize = sqlLimit > 0 ? sqlLimit : 20;
  const er = message.executionResult as Record<string, JsonValue> | null | undefined;
  const totalRows = pageData ? pageData.total_rows : (typeof er?.rows === "number" ? (er.rows as number) : 0);
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));

  const fetchData = async (targetPage: number) => {
    const sql = message.sql || "";
    if (!sql) return;
    setPageLoading(true);
    try {
      const data = await fetchPage(sql, targetPage, pageSize);
      setPageData(data);
    } catch {
      // keep current state
    } finally {
      setPageLoading(false);
    }
  };

  useEffect(() => {
    if (hasSingleSql && message.sql) {
      fetchData(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message.sql, hasSingleSql]);

  const handlePageChange = (targetPage: number) => {
    if (targetPage < 1 || targetPage > totalPages) return;
    fetchData(targetPage);
  };

  const tableData = pageData?.rows;
  const tableColumns = pageData?.columns;

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[13px] ${
          isUser
            ? "bg-accent text-white"
            : isError
              ? "bg-red-500/20 text-red-400"
              : "bg-accent/10 text-accent-500"
        }`}
      >
        {isUser ? <UserMsgIcon /> : isError ? <Bot className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>
      <div className={`max-w-[80%] space-y-2.5 ${isUser ? "items-end" : ""}`}>
        {showContent && (
          <div
            className={`rounded-lg px-4 py-3 text-[15px] leading-relaxed ${
              isUser
                ? "bg-accent text-white"
                : isError
                  ? "border border-red-500/20 bg-red-500/5 text-red-300"
                  : "border border-[var(--border-default)] bg-[var(--bg-overlay)] text-[var(--text-secondary)]"
            }`}
          >
            {message.content}
          </div>
        )}

        {hasSingleSql && (
          <div className="pt-1">
            <CodeBlock title="SQL" value={message.sql} language="sql" maxHeightClassName="max-h-52" />
          </div>
        )}

        {hasSingleSql &&
          message.executionResult &&
          !(message.executionResult as Record<string, JsonValue>).error && (
            <div className="rounded-lg border border-emerald-500/10 bg-emerald-500/5 px-3 py-1.5 text-[13px] text-emerald-400">
              SQL 执行成功
            </div>
          )}

        {hasSingleSql && (
          <div className="space-y-2">
            {pageLoading && !tableData && (
              <div className="py-3 text-center text-[13px] text-text-tertiary">加载中...</div>
            )}
            {tableData && tableData.length > 0 && tableColumns && (
              <div className="overflow-x-auto rounded-lg border border-[var(--border-default)]">
                <table className="w-full text-[14px]">
                  <thead>
                    <tr className="border-b border-[var(--border-default)] bg-[var(--bg-overlay)]">
                      {tableColumns.map((col: string) => (
                        <th key={col} className="whitespace-nowrap px-3 py-2 text-left font-medium text-text-secondary">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-default)]">
                    {tableData.map((row, ri) => (
                      <tr key={ri} className="hover:bg-[var(--bg-overlay)]">
                        {tableColumns!.map((col: string) => (
                          <td key={col} className="whitespace-nowrap px-3 py-1.5 text-text-tertiary text-[13px]">
                            {String(row[col] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <PaginationBar
              page={pageData?.page || 1}
              totalPages={totalPages}
              totalRows={totalRows}
              loading={pageLoading}
              onPageChange={handlePageChange}
            />
          </div>
        )}

        {hasMultiSql && <MultiSqlTabs message={message} />}

        {/* 反馈按钮 */}
        {!isUser && (hasSingleSql || hasMultiSql) ? (
          <div className="flex items-center gap-1 pt-1">
            <button
              type="button"
              onClick={() => onThumbsUp(message.requestId || "")}
              disabled={rated}
              title="回答正确"
              className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[13px] transition-colors ${
                rated
                  ? "cursor-default text-text-tertiary/30"
                  : "text-text-tertiary hover:text-emerald-400 hover:bg-emerald-500/10"
              }`}
            >
              <ThumbsUp className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => onThumbsDown(message.requestId || "")}
              disabled={rated}
              title="回答有误"
              className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[13px] transition-colors ${
                rated
                  ? "cursor-default text-text-tertiary/30"
                  : "text-text-tertiary hover:text-red-400 hover:bg-red-500/10"
              }`}
            >
              <ThumbsDown className="h-4 w-4" />
            </button>
            {rated ? (
              <span className="text-[12px] text-text-tertiary/40">已反馈</span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function UserMsgIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="5" r="3" stroke="currentColor" strokeWidth="1.3" />
      <path d="M2 12c0-2.2 2.2-4 5-4s5 1.8 5 4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}
