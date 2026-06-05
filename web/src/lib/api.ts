import type {
  AutoLabelResponse,
  EvolveOnlineResponse,
  FeedbackResponse,
  HarnessActionResponse,
  HarnessCandidate,
  HarnessFailureCase,
  HarnessListResponse,
  Nl2SqlResponse,
  PageResponse,
  Message,
} from "@/types";

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const text = await response.text();
  const data = text ? (JSON.parse(text) as T) : ({} as T);
  if (!response.ok) {
    throw new Error(`请求失败(${response.status})`);
  }
  return data;
}

export function runNl2Sql(query: string): Promise<Nl2SqlResponse> {
  return requestJson<Nl2SqlResponse>("/nl2sql", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

export async function listFailureCases(status?: string, limit = 50): Promise<HarnessFailureCase[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  const result = await requestJson<HarnessListResponse<HarnessFailureCase>>(`/admin/harness/failure-cases?${params}`);
  return result.items ?? [];
}

export async function listCandidates(status?: string, limit = 50): Promise<HarnessCandidate[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  const result = await requestJson<HarnessListResponse<HarnessCandidate>>(`/admin/harness/candidates?${params}`);
  return result.items ?? [];
}

export function labelFailureCase(failureCaseId: number, correctSql: string, note = "", labelType = "correct_sql"): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>(`/admin/harness/failure-cases/${failureCaseId}/label`, {
    method: "POST",
    body: JSON.stringify({ correct_sql: correctSql, note, label_type: labelType }),
  });
}

export function analyzeFailures(limit = 200): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>(`/admin/harness/analyze-failures?limit=${limit}&sync_failures=true`, {
    method: "POST",
  });
}

export function autoLabelFailures(limit = 50, generateModel = "", evalModel = ""): Promise<AutoLabelResponse> {
  const params = new URLSearchParams({ limit: String(limit), sync_failures: "true" });
  if (generateModel) params.set("generate_model", generateModel);
  if (evalModel) params.set("eval_model", evalModel);
  return requestJson<AutoLabelResponse>(`/admin/harness/auto-label-failures?${params}`, {
    method: "POST",
  });
}

export function evolveOnline(limit = 200): Promise<EvolveOnlineResponse> {
  const params = new URLSearchParams({ limit: String(limit), sync_failures: "true" });
  return requestJson<EvolveOnlineResponse>(`/admin/harness/evolve-online?${params}`, {
    method: "POST",
  });
}

export function reviewCandidate(candidateId: number, action: "approve" | "reject", note = ""): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>(`/admin/harness/candidates/${candidateId}/review`, {
    method: "POST",
    body: JSON.stringify({ action, note }),
  });
}

export function publishApproved(version: string): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>("/admin/harness/publish", {
    method: "POST",
    body: JSON.stringify({ version }),
  });
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function submitFeedback(requestId: string, rating: "up" | "down", reason = ""): Promise<FeedbackResponse> {
  if (!UUID_RE.test(requestId)) {
    // 无效 UUID，静默跳过，避免 500
    return Promise.resolve({ request_id: requestId, rating: rating === "up" ? 1 : -1, failure_case_created: false });
  }
  return requestJson<FeedbackResponse>("/admin/harness/feedback", {
    method: "POST",
    body: JSON.stringify({ request_id: requestId, rating, reason }),
  });
}

export function fetchPage(sql: string, page: number, pageSize = 20): Promise<PageResponse> {
  return requestJson<PageResponse>("/execute/page", {
    method: "POST",
    body: JSON.stringify({ sql, page, page_size: pageSize }),
  });
}

export interface GraphEdge {
  to: string;
  from_field: string;
  to_field: string;
  join: string;
  join_type: string;
  desc: string;
  confidence: string;
  note: string;
}

export interface GraphData {
  graph: Record<string, GraphEdge[]>;
}

export function fetchRelationGraph(): Promise<GraphData> {
  return requestJson<GraphData>("/api/graph");
}

// ── 关系图 PG 边 CRUD ──────────────────────────────────────────────

export interface GraphEdgeRecord {
  id: number;
  from_table: string;
  to_table: string;
  from_field: string;
  to_field: string;
  join_condition: string;
  join_type: string;
  description: string;
  confidence: string;
  note: string;
  created_at: string;
  updated_at: string;
}

export interface GraphEdgeCreate {
  from_table: string;
  to_table: string;
  from_field: string;
  to_field: string;
  join_condition: string;
  join_type?: string;
  description?: string;
  confidence?: string;
  note?: string;
}

export interface GraphVersionResponse {
  version: number;
}

export interface GraphSyncResponse {
  message: string;
  count: number;
  version: number;
}

export interface GraphEdgeListResponse {
  edges: GraphEdgeRecord[];
}

export interface GraphEdgeMutationResponse {
  id: number;
  message: string;
  version: number;
}

export function fetchGraphVersion(): Promise<GraphVersionResponse> {
  return requestJson<GraphVersionResponse>("/api/graph/version");
}

export function syncGraphFromJson(): Promise<GraphSyncResponse> {
  return requestJson<GraphSyncResponse>("/api/graph/sync", { method: "POST" });
}

export function listGraphEdges(fromTable?: string, confidence?: string): Promise<GraphEdgeListResponse> {
  const params = new URLSearchParams();
  if (fromTable) params.set("from_table", fromTable);
  if (confidence) params.set("confidence", confidence);
  return requestJson<GraphEdgeListResponse>(`/api/graph/edges?${params}`);
}

export function getGraphEdge(edgeId: number): Promise<GraphEdgeRecord> {
  return requestJson<GraphEdgeRecord>(`/api/graph/edges/${edgeId}`);
}

export function addGraphEdge(edge: GraphEdgeCreate): Promise<GraphEdgeMutationResponse> {
  return requestJson<GraphEdgeMutationResponse>("/api/graph/edges", {
    method: "POST",
    body: JSON.stringify(edge),
  });
}

export function updateGraphEdge(edgeId: number, edge: GraphEdgeCreate): Promise<GraphEdgeMutationResponse> {
  return requestJson<GraphEdgeMutationResponse>(`/api/graph/edges/${edgeId}`, {
    method: "PUT",
    body: JSON.stringify(edge),
  });
}

export function deleteGraphEdge(edgeId: number): Promise<GraphEdgeMutationResponse> {
  return requestJson<GraphEdgeMutationResponse>(`/api/graph/edges/${edgeId}`, {
    method: "DELETE",
  });
}

// ── 聊天历史 ────────────────────────────────────────────────────────

export interface ChatHistoryItem {
  thread_id: string;
  first_query: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

interface ChatHistoryListResponse {
  sessions: ChatHistoryItem[];
}

interface ChatThreadResponse {
  thread_id: string;
  user_id: string;
  messages: Message[];
}

export function fetchChatHistory(userId: string): Promise<ChatHistoryItem[]> {
  return requestJson<ChatHistoryListResponse>(
    `/chat/history?user_id=${encodeURIComponent(userId)}`,
  ).then((r) => r.sessions);
}

export function loadChatThread(userId: string, threadId: string): Promise<ChatThreadResponse> {
  return requestJson<ChatThreadResponse>(
    `/chat/history/${threadId}?user_id=${encodeURIComponent(userId)}`,
  );
}

// ── Trace API ──────────────────────────────────────────────────────

import type { TraceSpan, TraceStats } from "@/types";

interface TraceResponse {
  trace_id: string;
  spans: TraceSpan[];
  count: number;
}

interface ThreadTraceResponse {
  thread_id: string;
  spans: TraceSpan[];
  count: number;
}

export function fetchTrace(traceId: string): Promise<TraceResponse> {
  return requestJson<TraceResponse>(`/api/trace/${traceId}`);
}

export function fetchThreadTraces(threadId: string): Promise<ThreadTraceResponse> {
  return requestJson<ThreadTraceResponse>(`/api/trace/thread/${threadId}`);
}

export function fetchTraceStats(node?: string, days?: number): Promise<TraceStats> {
  const params = new URLSearchParams();
  if (node) params.set("node", node);
  if (days) params.set("days", String(days));
  return requestJson<TraceStats>(`/api/trace/stats?${params}`);
}
