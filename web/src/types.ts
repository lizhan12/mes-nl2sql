export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

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
  /** 用户评分: 1=点赞, -1=点踩 */
  user_rating?: number;
  /** 用户点踩时填写的反馈原因 */
  user_feedback?: string;
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

export interface FeedbackRecord {
  request_id: string;
  query_text: string;
  generated_sql: string;
  final_sql: string;
  execution_success: boolean;
  user_rating: number;
  user_feedback: string;
  created_at: string;
}

// ── 知识库管理 ────────────────────────────────────────────────────

export interface TableFieldInfo {
  name: string;
  type: string;
  comment: string;
}

export interface TableKnowledgeSummary {
  table_name: string;
  module: string;
  business_meaning: string;
  field_count: number;
}

export interface TableKnowledgeDetail {
  table_name: string;
  module: string;
  business_meaning: string;
  fields: TableFieldInfo[];
  relations: string[];
  scenarios: string[];
}

export interface TableKnowledgeUpdate {
  table_name: string;
  module: string;
  business_meaning: string;
  fields: TableFieldInfo[];
  relations: string[];
  scenarios: string[];
}

// ── 通用知识库 ────────────────────────────────────────────────────

export interface GenericKnowledgeFieldDef {
  name: string;
  value: string;
  embed: boolean;
}

export interface GenericKnowledgeItem {
  item_id: string;
  label: string;
  fields: GenericKnowledgeFieldDef[];
  created_at: string;
}

export interface GenericKBSummary {
  kb_name: string;
  label: string;
  item_count: number;
  field_names: string[];
}

// ── 知识库检索 ────────────────────────────────────────────────────

export interface SchemaSearchItem {
  table_name: string;
  module: string;
  business_meaning: string;
  full_text: string;
  score: number;
}

export interface FewShotSearchItem {
  scenario: string;
  question: string;
  full_text: string;
  score: number;
  type: string;
  match_type: "archive_key_exact" | "vector";
  archive_key: string;
  object_entity: string;
  action_type: string;
  domain: string;
}

export interface FieldSearchItem {
  table_name: string;
  field_name: string;
  type: string;
  comment: string;
  score: number;
}

export interface RuntimeRuleSearchItem {
  question: string;
  normalized_question: string;
  preferred_main_table: string;
  required_tables: string[];
  required_joins: string[];
  source: string;
  score: number;
}

export interface StructuralEntities {
  object_entity: string;
  action_type: string;
  domain: string;
  archive_key: string;
}

export interface KnowledgeSearchResult {
  query: string;
  embedding_model: string;
  rerank_model: string;
  structural_entities: StructuralEntities;
  schema_results: SchemaSearchItem[];
  few_shot_results: FewShotSearchItem[];
  field_results: FieldSearchItem[];
  keyword_tables: string[];
  runtime_rule_results: RuntimeRuleSearchItem[];
}

export interface SyncFromNeo4jResult {
  table_count: number;
  few_shot_count: number;
  relation_count: number;
  message: string;
  synced_files: string[];
}

// ── FewShot 管理 ──────────────────────────────────────────────────

export interface FewShotItem {
  id: string;
  scenario: string;
  question: string;
  full_text: string;
  enabled: boolean;
  type: string;
  archive_key?: string;
  object_entity?: string;
  action_type?: string;
  domain?: string;
}

// ── RuntimeRule 管理 ──────────────────────────────────────────────

export interface RuntimeRuleItem {
  normalized_question: string;
  question: string;
  preferred_main_table: string;
  required_tables: string[];
  required_joins: string[];
  source: string;
  enabled: boolean;
}

export interface DedupSimilarItem {
  key: string;
  question: string;
  score: number;
  match_type: "exact" | "vector";
  existing_item: Record<string, unknown>;
  candidate_id?: number;
}

export interface PrePublishCheckResponse {
  total_candidates: number;
  duplicate_items: DedupSimilarItem[];
  clean_count: number;
}

// ── 实体词典 ──────────────────────────────────────────────────────
export interface EntityLexiconEntry {
  entity: string;
  domain: string;
  tables: string[];
}

export interface ActionPattern {
  keywords: string[];
  action: string;
}

export interface EntityLexiconData {
  entity_lexicon: EntityLexiconEntry[];
  action_patterns: ActionPattern[];
}

export interface EntityExtractPreview {
  query: string;
  structural: {
    object_entity: string;
    action_type: string;
    domain: string;
  };
  archive_key: string;
}
