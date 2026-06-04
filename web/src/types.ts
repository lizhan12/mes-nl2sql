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
  label_id?: number;
  label_type?: string;
  created_at?: string;
}

export interface HarnessCandidate {
  id: number;
  candidate_type: string;
  status: string;
  question_example: string;
  confidence: number;
  review_note: string;
  published_version: string;
  pattern_type?: string;
  pattern_key?: string;
  proposed_rule_json?: Record<string, JsonValue>;
  proposed_few_shot_text?: string;
  evidence_json?: Record<string, JsonValue>;
  created_at?: string;
  reviewed_at?: string;
  published_at?: string;
}

export interface HarnessListResponse<T> {
  items: T[];
  error?: string;
}

export interface HarnessActionResponse {
  [key: string]: JsonValue;
}

export interface AutoLabelResponse {
  synced_failures: number;
  open_failures: number;
  auto_approved: number;
  medium_confidence: number;
  low_confidence: number;
  skipped: number;
  total_processed: number;
  marked_auto_labeled?: number;
  details: Array<{
    case_id: number;
    question: string;
    confidence: number;
    level: string;
    needs_review: boolean;
  }>;
}

export interface EvolveOnlineResponse {
  synced_failures: number;
  promotable_requests: number;
  published_rules: number;
  version: string;
}

export interface FeedbackRequest {
  request_id: string;
  rating: "up" | "down";
  reason: string;
}

export interface FeedbackResponse {
  request_id: string;
  rating: number;
  failure_case_created: boolean;
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

export interface SqlResult {
  description?: string;
  question?: string;
  sql?: string;
  success?: boolean;
  rows?: number;
  columns?: string[];
  preview?: Array<Record<string, JsonValue>>;
  error?: string;
  repaired?: boolean;
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
  requestId?: string;
  // 多 SQL 相关
  multiSql?: boolean;
  finalSqls?: string[];
  executionResults?: SqlResult[];
  subQueries?: Array<{ question: string; description: string }>;
  steps?: StepInfo[];
}

export interface ChatStreamEvent {
  node: string;
  status: "progress" | "complete" | "error";
  thread_id: string;
  request_id?: string;
  data: Record<string, JsonValue>;
}

export interface PageRequest {
  sql: string;
  page: number;
  page_size: number;
}

export interface PageResponse {
  success: boolean;
  total_rows: number;
  page: number;
  page_size: number;
  total_pages: number;
  columns: string[];
  rows: Array<Record<string, JsonValue>>;
  error: string;
}
