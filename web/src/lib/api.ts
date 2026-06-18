import type {
  AutoLabelResponse,
  DedupSimilarItem,
  EvolveOnlineResponse,
  EvolvedFewShotItem,
  FeedbackRecord,
  FeedbackResponse,
  FewShotItem,
  HarnessActionResponse,
  HarnessCandidate,
  HarnessFailureCase,
  HarnessListResponse,
  KnowledgeSearchResult,
  Nl2SqlResponse,
  PrePublishCheckResponse,
  RuntimeRuleItem,
  SyncFromNeo4jResult,
  TableFieldInfo,
  TableKnowledgeSummary,
  TableKnowledgeDetail,
  TableKnowledgeUpdate,
} from "@/types";

const TOKEN_KEY = "nl2sql_auth_token";

/** 读取本地 token，用于请求头注入 */
function getAuthToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

/** 401 时清除 token 并跳转登录页 */
function handleUnauthorized(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem("nl2sql_user_info");
  // 仅在非登录页时跳转，避免循环
  if (!window.location.pathname.endsWith("/login")) {
    window.location.href = "/console/login";
  }
}

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(input, { ...init, headers });

  if (response.status === 401) {
    handleUnauthorized();
    throw new Error("认证已失效，请重新登录");
  }

  const text = await response.text();
  const data = text ? (JSON.parse(text) as T) : ({} as T);
  if (!response.ok) {
    const detail = (data as { detail?: string }).detail ?? `请求失败(${response.status})`;
    throw new Error(detail);
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

export function prePublishCheck(): Promise<PrePublishCheckResponse> {
  return requestJson<PrePublishCheckResponse>("/admin/harness/pre-publish-check", {
    method: "POST",
  });
}

export function publishApproved(version: string, force = false): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>("/admin/harness/publish", {
    method: "POST",
    body: JSON.stringify({ version, force }),
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

export function listFeedback(limit = 100): Promise<FeedbackRecord[]> {
  return requestJson<{ items: FeedbackRecord[] }>(
    `/admin/harness/feedback?limit=${limit}`,
  ).then((data) => data.items);
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

// ── Trace API ──────────────────────────────────────────────────────

import type { RecentTrace, TraceSpan, TraceStats } from "@/types";

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

interface RecentTracesResponse {
  traces: RecentTrace[];
  count: number;
}

export function fetchRecentTraces(limit = 50): Promise<RecentTracesResponse> {
  return requestJson<RecentTracesResponse>(`/api/trace/recent?limit=${limit}`);
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

// ── 知识库管理 API ─────────────────────────────────────────────────

export function fetchKnowledgeTables(module?: string, search?: string): Promise<TableKnowledgeSummary[]> {
  const params = new URLSearchParams();
  if (module) params.set("module", module);
  if (search) params.set("search", search);
  return requestJson<TableKnowledgeSummary[]>(`/api/knowledge/tables?${params}`);
}

export function fetchKnowledgeTable(tableName: string): Promise<TableKnowledgeDetail> {
  return requestJson<TableKnowledgeDetail>(`/api/knowledge/tables/${encodeURIComponent(tableName)}`);
}

export function updateKnowledgeTable(
  tableName: string,
  data: TableKnowledgeUpdate,
): Promise<{ message: string; table_name: string }> {
  return requestJson<{ message: string; table_name: string }>(
    `/api/knowledge/tables/${encodeURIComponent(tableName)}`,
    {
      method: "PUT",
      body: JSON.stringify(data),
    },
  );
}

export function fetchTableColumnsFromDB(tableName: string): Promise<TableFieldInfo[]> {
  return requestJson<TableFieldInfo[]>(
    `/api/knowledge/tables/${encodeURIComponent(tableName)}/columns`,
  );
}

// ── 知识库表抽取与批量添加 ──────────────────────────────────────────

export interface TableExtractResponse {
  tables: TableKnowledgeUpdate[];
  relations: GraphEdgeCreate[];
}

export interface TableBatchAddResponse {
  table_names: string[];
  relation_count: number;
  message: string;
}

export function extractTableStructure(rawText: string): Promise<TableExtractResponse> {
  return requestJson<TableExtractResponse>("/api/knowledge/tables/extract", {
    method: "POST",
    body: JSON.stringify({ raw_text: rawText }),
  });
}

export function batchAddKnowledgeTables(
  tables: TableKnowledgeUpdate[],
  relations: GraphEdgeCreate[],
): Promise<TableBatchAddResponse> {
  return requestJson<TableBatchAddResponse>("/api/knowledge/tables/batch-add", {
    method: "POST",
    body: JSON.stringify({ tables, relations }),
  });
}

export function deleteGraphEdgeByTables(fromTable: string, toTable: string): Promise<{ message: string; version: number }> {
  const params = new URLSearchParams({ from_table: fromTable, to_table: toTable });
  return requestJson<{ message: string; version: number }>(`/api/graph/edges?${params}`, {
    method: "DELETE",
  });
}

// ── 知识库检索 API ─────────────────────────────────────────────────

export function searchKnowledge(
  query: string,
  searchTypes: string[] = ["schema", "few_shot", "fields"],
  topK = 10,
  similarityThreshold = 0.55,
): Promise<KnowledgeSearchResult> {
  return requestJson<KnowledgeSearchResult>("/api/knowledge/search", {
    method: "POST",
    body: JSON.stringify({
      query,
      search_types: searchTypes,
      top_k: topK,
      similarity_threshold: similarityThreshold,
    }),
  });
}

// ── 知识库删除与同步 API ────────────────────────────────────────────

export function deleteKnowledgeTable(tableName: string): Promise<{ message: string }> {
  return requestJson<{ message: string }>(
    `/api/knowledge/tables/${encodeURIComponent(tableName)}`,
    { method: "DELETE" },
  );
}

export function syncKnowledgeFromNeo4j(): Promise<SyncFromNeo4jResult> {
  return requestJson<SyncFromNeo4jResult>("/api/knowledge/sync-from-neo4j", {
    method: "POST",
  });
}

export function downloadSyncedFiles(): Promise<{ files: Record<string, string> }> {
  return requestJson<{ files: Record<string, string> }>("/api/knowledge/download-synced-files");
}

// ── FewShot 管理 API ───────────────────────────────────────────────

export function fetchFewShots(): Promise<FewShotItem[]> {
  return requestJson<FewShotItem[]>("/api/knowledge/few-shots");
}

export function createFewShot(
  scenario: string,
  question: string,
  sql: string,
  force = false,
): Promise<FewShotItem> {
  const params = force ? "?force=true" : "";
  return requestJson<FewShotItem>(`/api/knowledge/few-shots${params}`, {
    method: "POST",
    body: JSON.stringify({ scenario, question, sql }),
  });
}

export function updateFewShot(
  fewShotId: string,
  scenario: string,
  question: string,
  sql: string,
): Promise<{ message: string; id: string }> {
  return requestJson<{ message: string; id: string }>(
    `/api/knowledge/few-shots/${encodeURIComponent(fewShotId)}`,
    {
      method: "PUT",
      body: JSON.stringify({ scenario, question, sql }),
    },
  );
}

export function deleteFewShot(fewShotId: string): Promise<{ message: string; id: string }> {
  return requestJson<{ message: string; id: string }>(
    `/api/knowledge/few-shots/${encodeURIComponent(fewShotId)}`,
    { method: "DELETE" },
  );
}

// ── EvolvedFewShot 管理 API ────────────────────────────────────────

export function fetchEvolvedFewShots(): Promise<EvolvedFewShotItem[]> {
  return requestJson<EvolvedFewShotItem[]>("/api/knowledge/evolved-few-shots");
}

export function createEvolvedFewShot(
  scenario: string,
  question: string,
  sql: string,
  force = false,
): Promise<EvolvedFewShotItem> {
  const params = force ? "?force=true" : "";
  return requestJson<EvolvedFewShotItem>(`/api/knowledge/evolved-few-shots${params}`, {
    method: "POST",
    body: JSON.stringify({ scenario, question, sql }),
  });
}

export function updateEvolvedFewShot(
  evolvedId: string,
  scenario: string,
  question: string,
  sql: string,
): Promise<{ message: string; id: string }> {
  return requestJson<{ message: string; id: string }>(
    `/api/knowledge/evolved-few-shots/${encodeURIComponent(evolvedId)}`,
    {
      method: "PUT",
      body: JSON.stringify({ scenario, question, sql }),
    },
  );
}

export function deleteEvolvedFewShot(
  evolvedId: string,
): Promise<{ message: string; id: string }> {
  return requestJson<{ message: string; id: string }>(
    `/api/knowledge/evolved-few-shots/${encodeURIComponent(evolvedId)}`,
    { method: "DELETE" },
  );
}

// ── RuntimeRule 管理 API ──────────────────────────────────────────

export function fetchRuntimeRules(): Promise<RuntimeRuleItem[]> {
  return requestJson<RuntimeRuleItem[]>("/api/knowledge/runtime-rules");
}

export function createRuntimeRule(
  question: string,
  normalized_question: string,
  preferred_main_table: string,
  required_tables: string[],
  required_joins: string[],
  source: string,
  force = false,
): Promise<RuntimeRuleItem> {
  const params = force ? "?force=true" : "";
  return requestJson<RuntimeRuleItem>(`/api/knowledge/runtime-rules${params}`, {
    method: "POST",
    body: JSON.stringify({
      question,
      normalized_question,
      preferred_main_table,
      required_tables,
      required_joins,
      source,
    }),
  });
}

export function updateRuntimeRule(
  normalizedQuestion: string,
  question: string,
  preferred_main_table: string,
  required_tables: string[],
  required_joins: string[],
  source: string,
): Promise<{ message: string }> {
  return requestJson<{ message: string }>(
    `/api/knowledge/runtime-rules/${encodeURIComponent(normalizedQuestion)}`,
    {
      method: "PUT",
      body: JSON.stringify({
        question,
        preferred_main_table,
        required_tables,
        required_joins,
        source,
      }),
    },
  );
}

export function deleteRuntimeRule(
  normalizedQuestion: string,
): Promise<{ message: string; normalized_question: string }> {
  return requestJson<{ message: string; normalized_question: string }>(
    `/api/knowledge/runtime-rules/${encodeURIComponent(normalizedQuestion)}`,
    { method: "DELETE" },
  );
}

// ── 认证 API ──────────────────────────────────────────────────────

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  created_at?: string;
  last_login_at?: string;
}

export interface LoginResponse {
  token: string;
  user: AuthUser;
}

export function login(username: string, password: string): Promise<LoginResponse> {
  return requestJson<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function logout(): Promise<{ message: string }> {
  return requestJson<{ message: string }>("/auth/logout", { method: "POST" });
}

export function fetchCurrentUser(): Promise<AuthUser> {
  return requestJson<AuthUser>("/auth/me");
}

// ── 用户管理 API（admin） ─────────────────────────────────────────

export interface UserListResponse {
  items: AuthUser[];
  total_rows: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface UserCreatePayload {
  username: string;
  password: string;
  display_name?: string;
  role?: "admin" | "user";
}

export interface UserUpdatePayload {
  display_name?: string;
  role?: "admin" | "user";
}

export function fetchUsers(
  page = 1,
  pageSize = 20,
  search = "",
): Promise<UserListResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (search) params.set("search", search);
  return requestJson<UserListResponse>(`/api/users?${params}`);
}

export function createUser(payload: UserCreatePayload): Promise<AuthUser> {
  return requestJson<AuthUser>("/api/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateUser(userId: number, payload: UserUpdatePayload): Promise<AuthUser> {
  return requestJson<AuthUser>(`/api/users/${userId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function resetUserPassword(userId: number, newPassword: string): Promise<{ message: string }> {
  return requestJson<{ message: string }>(`/api/users/${userId}/reset-password`, {
    method: "POST",
    body: JSON.stringify({ new_password: newPassword }),
  });
}

export function deleteUser(userId: number): Promise<{ message: string }> {
  return requestJson<{ message: string }>(`/api/users/${userId}`, { method: "DELETE" });
}
