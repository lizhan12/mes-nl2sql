import { Bot, ChevronLeft, ChevronRight, Clock, GitBranch, MessageCircle, Moon, Plus, Send, Sun, ThumbsDown, ThumbsUp, X, Zap } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { CodeBlock } from "@/components/CodeBlock";
import { PaginationBar } from "@/components/PaginationBar";
import { StatusBadge } from "@/components/StatusBadge";
import { TracePanel } from "@/components/TracePanel";
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
  metric: "指标直达",
  clarify: "术语澄清",
};

/** 查询超时时间（毫秒），超时后自动取消并提示用户 */
const QUERY_TIMEOUT_MS = 60_000;

let _msgId = 1;

function makeId(): string {
  return String(_msgId++);
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
      className="group inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-2.5 py-1.5 text-[13px] font-mono text-[var(--text-secondary)] transition-all duration-150 hover:border-[var(--accent)] hover:text-[var(--accent)] hover:shadow-[var(--shadow-glow)]"
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

  // 查询超时控制
  const abortRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 绕过 React 状态时序问题：SSE 事件(done)可能先于通道事件(multi_metric/clarify等)在状态中被应用
  // 用 ref 作为可靠数据源，done 事件到达时直接读取 ref 而非依赖 prev 状态
  const channelDataRef = useRef<{
    type: string;
    content: string;
    // clarify/ask
    candidates?: Array<{ metric_id: string; name: string; description: string; category: string }>;
    prompt?: string;
    metricId?: string;
    metricName?: string;
    // metric
    sql?: string;
    explain?: string;
    // multi_metric
    multiMetricIds?: string[];
    multiSqls?: Array<{ metric_id: string; metric_name: string; sql: string; explain: string }>;
  } | null>(null);

  // 反馈状态
  const [ratedMessages, setRatedMessages] = useState<Set<string>>(new Set());
  const [feedbackModal, setFeedbackModal] = useState<{ msgId: string; requestId: string } | null>(null);
  const [feedbackReason, setFeedbackReason] = useState("");

  // Trace 面板
  const [tracePanelTraceId, setTracePanelTraceId] = useState<string | null>(null);

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
          thread.messages.map((m) => {
            const typeFromBackend: string = m.type || "";
            const role: "user" | "assistant" =
              typeFromBackend === "HumanMessage" || typeFromBackend === "human"
                ? "user"
                : typeFromBackend === "AIMessage" || typeFromBackend === "ai"
                  ? "assistant"
                  : "user";
            return {
              id: makeId(),
              role,
              content: m.content || "",
              type: "text" as const,
              timestamp: Date.now(),
            };
          }),
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

    channelDataRef.current = null;

    // 超时控制：创建 AbortController，60 秒后自动取消
    if (abortRef.current) {
      abortRef.current.abort();
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    const abortController = new AbortController();
    abortRef.current = abortController;
    let timedOut = false;

    timeoutRef.current = setTimeout(() => {
      timedOut = true;
      abortController.abort();
      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.id === assistantMsg.id) {
            return {
              ...msg,
              content: `查询超时（超过 ${QUERY_TIMEOUT_MS / 1000} 秒），请简化问题后重试`,
              type: "error",
              nodeStatus: Object.fromEntries(
                ["intent", "retrieval", "bfs", "schema", "sql_gen", "safety", "execute"].map((n) => [n, "error"])
              ),
            };
          }
          return msg;
        }),
      );
    }, QUERY_TIMEOUT_MS);

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
            const channel = (event.data?.channel as string) || "";

            const execData = execResults.length > 0 ? (execResults[0] as unknown as Record<string, JsonValue>) : null;
            const requestId = (event.request_id as string) || "";
            const traceId = (event.trace_id as string) || requestId;
            const finalSqlFromEvent = finalSqls.length > 0 ? finalSqls[0] : (event.data?.final_sql as string) || (event.data?.generated_sql as string) || "";
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
                  // 优先用 ref 判断通道类型，绕过 React 状态时序问题
                  const cd = channelDataRef.current;
                  const hasChannelData = cd !== null;
                  const finalType = hasChannelData
                    ? cd!.type
                    : (status === "error" ? "error" : "text");
                  // content：有通道数据用 ref，否则用 computed content
                  const finalContent = hasChannelData
                    ? cd!.content
                    : content;
                  // metric 通道兜底
                  const finalMetricId = (event.data?.metric_id as string) || cd?.metricId || undefined;
                  const finalMetricName = (event.data?.metric_name as string) || cd?.metricName || undefined;
                  const finalSql = cd?.sql || finalSqlFromEvent;
                  // multi_metric 通道兜底
                  const finalMultiMetricIds = cd?.multiMetricIds || (msg as Message).multiMetricIds;
                  const finalMultiSqls = cd?.multiSqls || (msg as Message).multiSqls;
                  return {
                    ...msg,
                    content: finalContent,
                    type: finalType as Message["type"],
                    nodeStatus: { ...currentNodeStatus } as Record<string, "pending" | "running" | "done" | "error">,
                    sql: finalSql,
                    executionResult: execData,
                    requestId,
                    traceId,
                    multiSql,
                    finalSqls,
                    executionResults: enrichedResults,
                    subQueries,
                    steps: [...stepAcc],
                    channel: channel ? (channel as "metric" | "nl2sql" | "clarify" | "multi_metric" | "ask") : undefined,
                    metricId: finalMetricId,
                    metricName: finalMetricName,
                    emptyResult: (event.data?.empty_result as boolean) || false,
                    emptyMessage: (event.data?.empty_message as string) || "",
                    // clarify 特有字段
                    clarifyCandidates: cd?.candidates || (msg as Message & { clarifyCandidates?: unknown }).clarifyCandidates,
                    clarifyPrompt: cd?.prompt || (msg as Message & { clarifyPrompt?: string }).clarifyPrompt,
                    // ask 特有字段
                    ...(cd?.type === "ask" ? {
                      askPrompt: cd.prompt,
                      askMetricId: cd.metricId,
                    } : {}),
                    // multi_metric 特有字段
                    multiMetricIds: finalMultiMetricIds,
                    multiSqls: finalMultiSqls,
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

          // 处理指标路由事件
          if (nodeName === "clarify") {
            const candidates = (event.data?.candidates as Array<{ metric_id: string; name: string; description: string; category: string }>) || [];
            const prompt = (event.data?.clarification_prompt as string) || "";
            channelDataRef.current = { type: "clarify", content: prompt || "请选择要查询的指标", candidates, prompt };
            setMessages((prev) =>
              prev.map((msg) => {
                if (msg.id === assistantMsg.id) {
                  return {
                    ...msg,
                    content: prompt || "请选择要查询的指标",
                    type: "clarify",
                    clarifyCandidates: candidates,
                    clarifyPrompt: prompt,
                    originalQuery: query,
                    nodeStatus: { ...currentNodeStatus },
                  };
                }
                return msg;
              }),
            );
            return;
          }

          if (nodeName === "ask") {
            const prompt = (event.data?.clarification_prompt as string) || "";
            const metricId = (event.data?.metric_id as string) || "";
            const metricName = (event.data?.metric_name as string) || "";
            channelDataRef.current = { type: "ask", content: prompt || "请确认参数", prompt, metricId, metricName };
            setMessages((prev) =>
              prev.map((msg) => {
                if (msg.id === assistantMsg.id) {
                  return {
                    ...msg,
                    content: prompt || "请确认参数",
                    type: "ask",
                    askPrompt: prompt,
                    askMetricId: metricId,
                    metricName,
                    originalQuery: query,
                    nodeStatus: { ...currentNodeStatus },
                  };
                }
                return msg;
              }),
            );
            return;
          }

          if (nodeName === "metric") {
            const sql = (event.data?.sql as string) || "";
            const metricName = (event.data?.metric_name as string) || "";
            const explain = (event.data?.explain as string) || "";
            const metricId = (event.data?.metric_id as string) || "";
            channelDataRef.current = { type: "metric", content: `指标直达: ${metricName}`, metricId, metricName, sql, explain };
            setMessages((prev) =>
              prev.map((msg) => {
                if (msg.id === assistantMsg.id) {
                  return {
                    ...msg,
                    content: `指标直达: ${metricName}`,
                    type: "progress",
                    sql,
                    metricName,
                    nodeStatus: { ...currentNodeStatus, metric: "done" },
                    steps: [...stepAcc, { node: "metric", label: "指标直达", textPreview: explain, status: "done" }],
                  };
                }
                return msg;
              }),
            );
          }

          if (nodeName === "multi_metric") {
            const multiMetricIds = (event.data?.multi_metric_ids as string[]) || [];
            const multiSqls = (event.data?.multi_sqls as Array<{ metric_id: string; metric_name: string; sql: string; explain: string }>) || [];
            channelDataRef.current = { type: "multi_metric", content: `多指标查询完成（共 ${multiMetricIds.length} 个指标）`, multiMetricIds, multiSqls };
            setMessages((prev) =>
              prev.map((msg) => {
                if (msg.id === assistantMsg.id) {
                  return {
                    ...msg,
                    content: `多指标查询完成（共 ${multiMetricIds.length} 个指标）`,
                    type: "progress",
                    multiMetricIds,
                    multiSqls,
                    nodeStatus: { ...currentNodeStatus, multi_metric: "done" },
                    steps: [...stepAcc, { node: "multi_metric", label: "多指标直达", textPreview: multiMetricIds.join(", "), status: "done" }],
                  };
                }
                return msg;
              }),
            );
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
          if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
            timeoutRef.current = null;
          }
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
          if (timeoutRef.current) {
            clearTimeout(timeoutRef.current);
            timeoutRef.current = null;
          }
          setRunning(false);
          refreshHistory();
          inputRef.current?.focus();
        },
        abortController.signal,
      );
    } catch {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
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

  const handleSendMetric = useCallback(
    async (query: string, metricId: string, displayText: string) => {
      if (running) return;

      setRunning(true);

      const userMsg = userMessage(displayText);
      const assistantMsg = assistantProgress("正在查询...");
      setMessages((prev) => [...prev, userMsg, assistantMsg]);

      const currentNodeStatus: Record<string, "pending" | "running" | "done" | "error"> = {};
      const allNodes = ["intent", "retrieval", "bfs", "schema", "sql_gen", "safety", "execute"];

      // 超时控制
      if (abortRef.current) {
        abortRef.current.abort();
      }
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      const abortController = new AbortController();
      abortRef.current = abortController;

      timeoutRef.current = setTimeout(() => {
        abortController.abort();
        setMessages((prev) =>
          prev.map((msg) => {
            if (msg.id === assistantMsg.id) {
              return {
                ...msg,
                content: `查询超时（超过 ${QUERY_TIMEOUT_MS / 1000} 秒），请简化问题后重试`,
                type: "error",
                nodeStatus: Object.fromEntries(allNodes.map((n) => [n, "error"])),
              };
            }
            return msg;
          }),
        );
      }, QUERY_TIMEOUT_MS);

      try {
        const stepAcc: Array<{ node: string; label: string; textPreview: string; status: "running" | "done" | "error" }> = [];
        await fetchSSE(
          "/chat/stream",
          { query, thread_id: threadId, user_id: userId, metric_id: metricId },
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
              const channel = (event.data?.channel as string) || "";

              const execData = execResults.length > 0 ? (execResults[0] as unknown as Record<string, JsonValue>) : null;
              const requestId = (event.request_id as string) || "";
              const traceId = (event.trace_id as string) || requestId;
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
                      nodeStatus: { ...currentNodeStatus } as Record<string, "pending" | "running" | "done" | "error">,
                      sql: finalSql,
                      executionResult: execData,
                      requestId,
                      traceId,
                      multiSql,
                      finalSqls,
                      executionResults: enrichedResults,
                      subQueries,
                      steps: [...stepAcc],
                      channel: channel ? (channel as "metric" | "nl2sql" | "clarify" | "multi_metric" | "ask") : undefined,
                      metricId: (event.data?.metric_id as string) || undefined,
                      metricName: (event.data?.metric_name as string) || undefined,
                      emptyResult: (event.data?.empty_result as boolean) || false,
                      emptyMessage: (event.data?.empty_message as string) || "",
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

            if (nodeName === "metric") {
              const sql = (event.data?.sql as string) || "";
              const metricName = (event.data?.metric_name as string) || "";
              const explain = (event.data?.explain as string) || "";
              setMessages((prev) =>
                prev.map((msg) => {
                  if (msg.id === assistantMsg.id) {
                    return {
                      ...msg,
                      content: `指标直达: ${metricName}`,
                      type: "progress",
                      sql,
                      metricName,
                      nodeStatus: { ...currentNodeStatus, metric: "done" },
                      steps: [...stepAcc, { node: "metric", label: "指标直达", textPreview: explain, status: "done" }],
                    };
                  }
                  return msg;
                }),
              );
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

            setMessages((prev) =>
              prev.map((msg) => {
                if (msg.id === assistantMsg.id) {
                  return {
                    ...msg,
                    content: textPreview || `${label}...`,
                    type: "progress" as const,
                    nodeStatus: { ...currentNodeStatus },
                  };
                }
                return msg;
              }),
            );
          },
          (error: Error) => {
            if (timeoutRef.current) {
              clearTimeout(timeoutRef.current);
              timeoutRef.current = null;
            }
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
            if (timeoutRef.current) {
              clearTimeout(timeoutRef.current);
              timeoutRef.current = null;
            }
            setRunning(false);
            refreshHistory();
          },
          abortController.signal,
        );
      } catch {
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current);
          timeoutRef.current = null;
        }
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
    },
    [running, threadId, userId, refreshHistory],
  );

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
      <header className="flex shrink-0 items-center justify-between border-b border-[var(--border-default)] bg-[var(--bg-raised)] px-4 py-3 shadow-[0_2px_0_0_var(--accent)] sm:px-6">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            title={showHistory ? "隐藏历史" : "显示历史"}
            className="inline-flex items-center rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-1.5 text-[var(--text-secondary)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
          >
            {showHistory ? <ChevronLeft className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
          <Bot className="h-5 w-5 text-[var(--accent)]" />
          <h1 className="font-display text-[18px] font-semibold tracking-wide text-[var(--text-primary)]">
            NL2SQL <span className="font-normal text-[var(--text-secondary)]">智能查询</span>
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
            className="group inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-1.5 font-mono text-[13px] text-[var(--text-secondary)] transition-all duration-150 hover:border-[var(--accent)] hover:text-[var(--accent)] hover:shadow-[var(--shadow-glow)] disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
            新对话
          </button>
          <Link
            to="/home"
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-1.5 font-mono text-[13px] text-[var(--text-secondary)] transition-all duration-150 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
          >
            <X className="h-3.5 w-3.5" />
            调试
          </Link>
          <Link
            to="/graph"
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-1.5 font-mono text-[13px] text-[var(--text-secondary)] transition-all duration-150 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
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
            <div className="border-b border-[var(--border-default)] px-3 py-3">
              <h2 className="flex items-center gap-1.5 font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
                <Clock className="h-3 w-3" />
                对话历史
              </h2>
            </div>
            {historyLoading && historySessions.length === 0 ? (
              <div className="px-3 py-6 text-center font-mono text-[12px] text-[var(--text-tertiary)] opacity-50">加载中...</div>
            ) : historySessions.length === 0 ? (
              <div className="px-3 py-6 text-center font-mono text-[12px] text-[var(--text-tertiary)] opacity-50">暂无对话记录</div>
            ) : (
              <div className="space-y-px px-2 py-2">
                {historySessions.map((s) => (
                  <button
                    key={s.thread_id}
                    type="button"
                    onClick={() => loadSession(s.thread_id)}
                    className={`group relative w-full rounded-[var(--radius-sm)] px-3 py-2 text-left transition-all duration-150 ${
                      s.thread_id === threadId
                        ? "border-l-2 border-l-[var(--accent)] bg-[var(--accent-surface)] text-[var(--accent)]"
                        : "border-l-2 border-l-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-subtle)] hover:text-[var(--text-primary)]"
                    }`}
                  >
                    <div className="truncate font-mono text-[12px] leading-tight">{s.first_query || "空对话"}</div>
                    <div className="mt-0.5 flex items-center gap-2 font-mono text-[10px] text-[var(--text-tertiary)] opacity-50">
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
              <div className="flex h-14 w-14 items-center justify-center rounded-[var(--radius-lg)] border border-[var(--border-default)] bg-[var(--bg-raised)]">
                <MessageCircle className="h-6 w-6 text-[var(--text-tertiary)] opacity-40" />
              </div>
              <p className="font-display text-[17px] text-[var(--text-secondary)]">用自然语言查询 MES 数据</p>
              <p className="font-mono text-[13px] text-[var(--text-tertiary)] opacity-50">支持多轮记忆，可连续追问</p>
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
                  onTraceView={(traceId) => setTracePanelTraceId(traceId)}
                  onSendMetric={handleSendMetric}
                />
              ))}
              {running && (
                <div className="flex justify-center py-1">
                  <div className="flex items-center gap-2 font-mono text-[13px] text-[var(--text-tertiary)]">
                    <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--accent)] shadow-[0_0_6px_var(--accent-glow)]" />
                    <span className="animate-pulse">处理中...</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Side Panel ── */}
        <div className="hidden w-72 shrink-0 overflow-y-auto border-l border-[var(--border-default)] bg-[var(--bg-raised)] px-4 py-4 xl:block">
          <h2 className="mb-4 font-mono text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
            上下文信息
          </h2>
          {threadId ? (
            <div className="space-y-3 text-sm">
              <div className="rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-3">
                <div className="font-mono text-[11px] text-[var(--text-tertiary)] opacity-60">会话 ID</div>
                <div className="mt-1 font-mono text-[13px] text-[var(--accent)]">{threadId.slice(0, 16)}...</div>
              </div>
              <div className="rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-3">
                <div className="font-mono text-[11px] text-[var(--text-tertiary)] opacity-60">消息</div>
                <div className="mt-1 font-mono text-[17px] font-semibold tabular-nums text-[var(--text-primary)]">{messages.length}</div>
              </div>
              {(() => {
                const lastAssistantMsg = [...messages].reverse().find((m) => m.role === "assistant");
                if (!lastAssistantMsg?.nodeStatus) return null;
                return (
                  <div className="rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] p-3">
                    <div className="mb-2 font-mono text-[11px] text-[var(--text-tertiary)] opacity-60">节点进度</div>
                    <div className="space-y-1.5">
                      {Object.entries(lastAssistantMsg.nodeStatus).map(([node, status]) => (
                        <div key={node} className="flex items-center gap-2 font-mono text-[12px]">
                          <span
                            className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                              status === "done"
                                ? "bg-[var(--success)]"
                                : status === "running"
                                  ? "bg-[var(--accent)]"
                                  : status === "error"
                                    ? "bg-[var(--error)]"
                                    : "bg-[var(--text-primary)] opacity-20"
                            }`}
                          />
                          <span className="text-[var(--text-secondary)]">{NODE_LABELS[node] || node}</span>
                          <span className="ml-auto text-[var(--text-tertiary)] opacity-50">{status}</span>
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
                    <div className="mb-2 font-mono text-[11px] text-[var(--text-tertiary)] opacity-60">
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
            <p className="font-mono text-[12px] text-[var(--text-tertiary)] opacity-50">发送第一条消息后显示</p>
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
            className="flex-1 rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-4 py-2.5 font-mono text-[15px] text-[var(--text-primary)] outline-none transition-all duration-150 placeholder:font-mono placeholder:text-[var(--text-tertiary)] placeholder:opacity-50 focus:border-[var(--accent)] focus:shadow-[0_0_0_1px_var(--accent)] disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void handleSend()}
            disabled={running || !input.trim()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-4 py-2.5 font-mono text-[14px] font-medium text-white transition-all duration-150 hover:brightness-110 hover:shadow-[var(--shadow-glow)] active:brightness-90 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:shadow-none"
          >
            <Send className="h-4 w-4" />
            发送
          </button>
        </div>
        <p className="mx-auto mt-3 max-w-3xl font-mono text-[12px] text-[var(--text-tertiary)] opacity-50">
          支持多轮记忆，可连续追问。例如："上一条 SQL 查出的工单有哪些产线？"
        </p>
      </div>

      {/* ── Feedback Modal ── */}
      {feedbackModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-md rounded-[var(--radius-lg)] border border-[var(--border-default)] bg-[var(--bg-raised)] p-6">
            <h3 className="font-mono text-[17px] font-medium text-[var(--text-primary)]">告诉我们哪里有问题</h3>
            <p className="mt-1 font-mono text-[13px] text-[var(--text-tertiary)]">你的反馈将帮助我们改进 SQL 生成质量</p>
            <textarea
              value={feedbackReason}
              onChange={(e) => setFeedbackReason(e.target.value)}
              rows={4}
              className="mt-4 w-full rounded-[var(--radius-md)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-3 py-2 font-mono text-[14px] text-[var(--text-primary)] outline-none transition-all duration-150 placeholder:font-mono placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:shadow-[0_0_0_1px_var(--accent)]"
              placeholder="例如：表关联错误、字段名不对、条件遗漏..."
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setFeedbackModal(null);
                  setFeedbackReason("");
                }}
                className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-4 py-2 font-mono text-[14px] text-[var(--text-secondary)] transition-all duration-150 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void handleSubmitFeedback()}
                disabled={!feedbackReason.trim()}
                className="rounded-[var(--radius-sm)] bg-[var(--accent)] px-4 py-2 font-mono text-[13px] font-medium text-white transition-all duration-150 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                提交
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {tracePanelTraceId ? (
        <TracePanel traceId={tracePanelTraceId} onClose={() => setTracePanelTraceId(null)} />
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
      {/* Tab Bar — monospace labels, accent underline for active */}
      <div className="flex gap-0 overflow-x-auto border-b border-[var(--border-default)]">
        {results.map((result, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => setActiveTab(idx)}
            className={`relative shrink-0 px-3.5 py-2 font-mono text-[12px] font-medium tracking-wide transition-all duration-150 ${
              activeTab === idx
                ? "text-[var(--accent)]"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
            }`}
          >
            {result.description || `SQL ${idx + 1}`}
            <span
              className={`ml-1.5 inline-block h-1.5 w-1.5 rounded-full ${
                result.success ? "bg-[var(--success)]" : "bg-[var(--error)]"
              }`}
            />
            {activeTab === idx && (
              <span className="absolute inset-x-0 bottom-0 h-0.5 bg-[var(--accent)]" />
            )}
          </button>
        ))}
      </div>

      {currentResult && (
        <div className="space-y-3">
          {currentResult.question && (
            <div className="font-mono text-[13px] text-[var(--text-secondary)]">{currentResult.question}</div>
          )}

          {/* Terminal-style SQL card */}
          {currentResult.sql && (
            <CodeBlock title="SQL" value={currentResult.sql} language="sql" maxHeightClassName="max-h-52" />
          )}

          {/* Error display — prominent red */}
          {!currentResult.success && currentResult.error && (
            <div className="rounded-[var(--radius-md)] border border-[var(--error)] bg-[var(--error)] px-3 py-2.5" style={{ backgroundColor: "color-mix(in srgb, var(--error) 8%, transparent)" }}>
              <div className="flex items-center gap-2">
                <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-[var(--error)]" />
                <span className="font-mono text-[13px] font-medium text-[var(--error)]">{currentResult.error}</span>
              </div>
            </div>
          )}

          {/* Success status line */}
          {currentResult.success && (
            <div className="flex items-center gap-2">
              <StatusBadge tone="success">执行成功</StatusBadge>
              <span className="font-mono text-[12px] text-[var(--success)]">
                SQL 执行成功
                {currentResult.repaired && (
                  <span style={{ color: "var(--warning)" }} className="ml-2">
                    （已修复）
                  </span>
                )}
              </span>
            </div>
          )}

          {/* 空结果友好提示 */}
          {currentResult.success && currentResult.empty_result && currentResult.empty_message && (
            <div className="rounded-[var(--radius-md)] border border-[var(--warning)] px-3 py-2.5" style={{ backgroundColor: "color-mix(in srgb, var(--warning) 8%, transparent)" }}>
              <span className="font-mono text-[13px] text-[var(--warning)]">{currentResult.empty_message}</span>
            </div>
          )}

          {currentResult.success && (
            <div className="space-y-2">
              {pState.loading && !tableData && (
                <div className="py-4 text-center font-mono text-[13px] text-[var(--text-tertiary)]">加载中...</div>
              )}
              {tableData && tableData.length > 0 && tableColumns && (
                <div className="overflow-x-auto rounded-[var(--radius-md)] border border-[var(--border-default)]">
                  <table className="w-full text-[14px]">
                    <thead>
                      <tr className="border-b border-[var(--border-default)] bg-[var(--bg-overlay)]">
                        {tableColumns.map((col: string) => (
                          <th key={col} className="whitespace-nowrap px-3 py-2 text-left font-mono text-[12px] font-medium text-[var(--text-secondary)]">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-default)]">
                      {tableData.map((row, ri) => (
                        <tr key={ri} className="hover:bg-[var(--bg-overlay)]">
                          {tableColumns!.map((col: string) => (
                            <td key={col} className="whitespace-nowrap px-3 py-1.5 font-mono text-[12px] text-[var(--text-secondary)]">
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
  onTraceView,
  onSendMetric,
}: {
  message: Message;
  rated: boolean;
  onThumbsUp: (requestId: string) => void;
  onThumbsDown: (requestId: string) => void;
  onTraceView: (traceId: string) => void;
  onSendMetric: (query: string, metricId: string, displayText: string) => void;
}) {
  const isUser = message.role === "user";
  const isError = message.type === "error";
  const isClarify = message.type === "clarify";
  const isAsk = message.type === "ask";

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
    if (hasSingleSql && message.sql && !er?.error) {
      fetchData(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message.sql, hasSingleSql, er?.error]);

  const handlePageChange = (targetPage: number) => {
    if (targetPage < 1 || targetPage > totalPages) return;
    fetchData(targetPage);
  };

  const tableData = pageData?.rows;
  const tableColumns = pageData?.columns;

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      {/* Avatar */}
      <div
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] text-[13px] ${
          isUser
            ? "bg-[var(--accent)] text-white"
            : isError
              ? "bg-[var(--error)] text-white"
              : "bg-[var(--accent-surface)] text-[var(--accent)]"
        }`}
      >
        {isUser ? <UserMsgIcon /> : isError ? <Bot className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>

      <div className={`max-w-[80%] space-y-2.5 ${isUser ? "items-end" : ""}`}>
        {/* Text content bubble */}
        {showContent && (
          <div
            className={`rounded-[var(--radius-md)] px-4 py-3 text-[15px] leading-relaxed ${
              isUser
                ? "bg-[var(--accent)] text-white"
                : isError
                  ? "border border-[var(--error)] text-[var(--error)] font-mono text-[14px]"
                  : "border border-[var(--border-default)] bg-[var(--bg-overlay)] font-mono text-[14px] text-[var(--text-secondary)]"
            }`}
            style={
              isError
                ? { backgroundColor: "color-mix(in srgb, var(--error) 8%, transparent)" }
                : undefined
            }
          >
            {isClarify ? (
              <ClarifySelector message={message} onSendMetric={onSendMetric} />
            ) : isAsk ? (
              <AskConfirmer message={message} onSendMetric={onSendMetric} />
            ) : (
              message.content
            )}
          </div>
        )}

        {/* 指标通道标签 */}
        {message.channel === "metric" && message.metricName && (
          <div className="flex items-center gap-2">
            <StatusBadge tone="success">指标直达</StatusBadge>
            <span className="font-mono text-[12px] text-[var(--success)]">{message.metricName}</span>
          </div>
        )}

        {/* 多指标通道 */}
        {message.channel === "multi_metric" && message.multiSqls && message.multiSqls.length > 0 && (
          <div className="space-y-3">
            <StatusBadge tone="success">多指标直达</StatusBadge>
            {message.multiSqls.map((ms) => (
              <div key={ms.metric_id} className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[12px] font-medium text-[var(--text-primary)]">
                    {ms.metric_name} ({ms.metric_id})
                  </span>
                </div>
                <CodeBlock title="SQL" value={ms.sql} language="sql" maxHeightClassName="max-h-36" />
              </div>
            ))}
          </div>
        )}

        {/* Single SQL — Terminal-style card */}
        {hasSingleSql && (
          <CodeBlock title="SQL" value={message.sql} language="sql" maxHeightClassName="max-h-52" />
        )}

        {/* Single SQL success status */}
        {hasSingleSql &&
          message.executionResult &&
          !(message.executionResult as Record<string, JsonValue>).error && (
            <div className="flex items-center gap-2">
              <StatusBadge tone="success">执行成功</StatusBadge>
              <span className="font-mono text-[12px] text-[var(--success)]">SQL 执行成功</span>
            </div>
          )}

        {/* 空结果友好提示 */}
        {!isUser && message.emptyResult && message.emptyMessage && (
          <div className="rounded-[var(--radius-md)] border border-[var(--warning)] px-3 py-2.5" style={{ backgroundColor: "color-mix(in srgb, var(--warning) 8%, transparent)" }}>
            <span className="font-mono text-[13px] text-[var(--warning)]">{message.emptyMessage}</span>
          </div>
        )}

        {/* Single SQL error display */}
        {hasSingleSql &&
          message.executionResult &&
          (message.executionResult as Record<string, JsonValue>).error && (
            <div className="rounded-[var(--radius-md)] border border-[var(--error)] bg-[var(--error)] px-3 py-2.5" style={{ backgroundColor: "color-mix(in srgb, var(--error) 8%, transparent)" }}>
              <div className="flex items-center gap-2">
                <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-[var(--error)]" />
                <span className="font-mono text-[13px] font-medium text-[var(--error)]">
                  {(message.executionResult as Record<string, JsonValue>).error as string}
                </span>
              </div>
            </div>
          )}

        {/* Single SQL data table */}
        {hasSingleSql && (
          <div className="space-y-2">
            {pageLoading && !tableData && (
              <div className="py-3 text-center font-mono text-[13px] text-[var(--text-tertiary)]">加载中...</div>
            )}
            {tableData && tableData.length > 0 && tableColumns && (
              <div className="overflow-x-auto rounded-[var(--radius-md)] border border-[var(--border-default)]">
                <table className="w-full text-[14px]">
                  <thead>
                    <tr className="border-b border-[var(--border-default)] bg-[var(--bg-overlay)]">
                      {tableColumns.map((col: string) => (
                        <th key={col} className="whitespace-nowrap px-3 py-2 text-left font-mono text-[12px] font-medium text-[var(--text-secondary)]">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-default)]">
                    {tableData.map((row, ri) => (
                      <tr key={ri} className="hover:bg-[var(--bg-overlay)]">
                        {tableColumns!.map((col: string) => (
                          <td key={col} className="whitespace-nowrap px-3 py-1.5 font-mono text-[12px] text-[var(--text-secondary)]">
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

        {/* Multi SQL Tabs */}
        {hasMultiSql && <MultiSqlTabs message={message} />}

        {/* 反馈按钮 — small, subtle, hover reveals accent */}
        {!isUser && (hasSingleSql || hasMultiSql) ? (
          <div className="flex items-center gap-0.5 pt-0.5">
            <button
              type="button"
              onClick={() => onThumbsUp(message.requestId || "")}
              disabled={rated}
              title="回答正确"
              className={`inline-flex items-center rounded-[var(--radius-sm)] p-1 transition-all duration-150 ${
                rated
                  ? "cursor-default text-[var(--text-tertiary)] opacity-30"
                  : "text-[var(--text-tertiary)] hover:text-[var(--success)]"
              }`}
            >
              <ThumbsUp className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => onThumbsDown(message.requestId || "")}
              disabled={rated}
              title="回答有误"
              className={`inline-flex items-center rounded-[var(--radius-sm)] p-1 transition-all duration-150 ${
                rated
                  ? "cursor-default text-[var(--text-tertiary)] opacity-30"
                  : "text-[var(--text-tertiary)] hover:text-[var(--error)]"
              }`}
            >
              <ThumbsDown className="h-3.5 w-3.5" />
            </button>
            {rated ? (
              <span className="ml-1 font-mono text-[11px] text-[var(--text-tertiary)] opacity-40">已反馈</span>
            ) : null}
            <button
              type="button"
              onClick={() => onTraceView(message.traceId || message.requestId || "")}
              title="查看执行链路"
              className="inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-[var(--text-tertiary)] hover:text-[var(--brand)] hover:bg-[var(--brand)]/5 transition-all duration-150"
            >
              <Zap className="h-3 w-3" />
              <span className="font-mono text-[11px]">链路</span>
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ClarifySelector({ message, onSendMetric }: { message: Message; onSendMetric: (query: string, metricId: string, displayText: string) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!message.clarifyCandidates || message.clarifyCandidates.length === 0) {
    return <p className="text-[var(--text-secondary)]">{message.content}</p>;
  }

  const handleSelect = async (metricId: string, metricName: string) => {
    setSelected(metricId);
    setLoading(true);
    onSendMetric(message.originalQuery || message.content || "", metricId, metricName);
  };

  const categoryLabel: Record<string, string> = {
    production: "生产",
    quality: "质量",
    warehouse: "仓储",
    equipment: "设备",
  };

  return (
    <div className="space-y-2">
      <p className="text-[14px] text-[var(--text-primary)]">
        「{message.content}」在不同部门有不同口径，请选择你要查询的指标：
      </p>
      <div className="space-y-1.5">
        {message.clarifyCandidates.map((c) => (
          <button
            key={c.metric_id}
            type="button"
            onClick={() => handleSelect(c.metric_id, c.name)}
            disabled={loading}
            className="w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-2 text-left transition-all duration-150 hover:border-[var(--accent)] hover:bg-[var(--accent-surface)] disabled:opacity-50"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-[13px] font-medium text-[var(--text-primary)]">
                {c.name}
              </span>
              <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                {categoryLabel[c.category] || c.category}
              </span>
            </div>
            <p className="mt-0.5 font-mono text-[12px] text-[var(--text-secondary)]">{c.description}</p>
          </button>
        ))}
      </div>
      {selected && loading && (
        <p className="font-mono text-[12px] text-[var(--text-tertiary)]">正在查询 {selected}...</p>
      )}
    </div>
  );
}

function AskConfirmer({ message, onSendMetric }: { message: Message; onSendMetric: (query: string, metricId: string, displayText: string) => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);

  const prompt = message.askPrompt || "请确认参数";
  const metricId = message.askMetricId || message.metricId || "";
  const metricName = message.metricName || "";

  const handleConfirm = async () => {
    setConfirmed(true);
    setLoading(true);
    onSendMetric(message.originalQuery || message.content || "", metricId, metricName || "确认查询");
  };

  return (
    <div className="space-y-2">
      <p className="text-[14px] text-[var(--text-primary)]">{prompt}</p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleConfirm}
          disabled={loading || confirmed}
          className="rounded-[var(--radius-sm)] border border-[var(--accent)] bg-[var(--accent)] px-4 py-1.5 font-mono text-[13px] font-medium text-white transition-all duration-150 hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "确认中..." : "是"}
        </button>
        <span className="font-mono text-[12px] text-[var(--text-tertiary)]">
          确认后系统将直接查询指标
        </span>
      </div>
      {confirmed && loading && (
        <p className="font-mono text-[12px] text-[var(--text-tertiary)]">正在查询...</p>
      )}
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
