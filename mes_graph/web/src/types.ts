export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface Nl2SqlResponse {
  query: string;
  sql: string;
  safe: boolean;
  error: string;
  tables_used: string[];
  join_hints: string;
  execution_result?: Record<string, JsonValue> | null;
  retry_count: number;
  request_id: string;
  knowledge_version: string;
}

export interface HarnessFailureCase {
  id: number;
  query_text: string;
  failure_type: string;
  status: string;
  generated_sql: string;
  final_sql: string;
  error_text: string;
  retry_count: number;
  correct_sql?: string;
  label_note?: string;
}

export interface HarnessCandidate {
  id: number;
  candidate_type: string;
  status: string;
  question_example: string;
  confidence: number;
  review_note: string;
  published_version: string;
}

export interface HarnessListResponse<T> {
  items: T[];
  error?: string;
}

export interface HarnessActionResponse {
  [key: string]: JsonValue;
}

export interface ActivityItem {
  id: string;
  title: string;
  endpoint: string;
  method: "GET" | "POST";
  status: "idle" | "loading" | "success" | "error";
  summary: string;
  createdAt: string;
  payload?: unknown;
}

export interface StepInfo {
  node: string;
  label: string;
  textPreview: string;
  status: "running" | "done" | "error";
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  type: "text" | "sql" | "progress" | "error";
  timestamp: number;
  nodeStatus?: Record<string, "pending" | "running" | "done" | "error">;
  sql?: string;
  executionResult?: Record<string, JsonValue> | null;
  steps?: StepInfo[];
}

export interface ChatStreamEvent {
  node: string;
  status: "progress" | "complete" | "error";
  thread_id: string;
  data: Record<string, JsonValue>;
}
