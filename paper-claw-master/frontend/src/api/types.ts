export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = Record<string, JsonValue>;

export type RunStatus = 'pending' | 'waiting_for_user' | 'running' | 'succeeded' | 'partial' | 'failed' | 'cancelled';
export type ThreadStatus = 'active' | 'archived';
export type RunDecisionType = 'approve' | 'edit' | 'reject' | 'respond';
export type ArtifactUploadRole = 'pdf' | 'source';

export interface AgentMessageRequest {
  thread_id?: number | null;
  message: string;
  active_paper_id?: number | null;
  model?: string | null;
  api_key?: string | null;
  base_url?: string | null;
  temperature?: number;
  max_tokens?: number;
  timeout?: number;
  max_retries?: number;
  chat_provider_name?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AgentMessageResponse {
  thread_id: number;
  run_id: number;
  assistant_message_id: number | null;
  status: RunStatus | string;
  message: string | null;
  error: string | null;
}

export interface AgentStreamEvent {
  type: string;
  thread_id: number;
  run_id: number;
  sequence?: number | null;
  event_type?: string | null;
  status?: RunStatus | string | null;
  message?: string | null;
  assistant_message_id?: number | null;
  error?: string | null;
  payload: Record<string, unknown>;
}

export interface MessageRead {
  id: number;
  thread_id: number;
  role: string;
  content_text: string | null;
  content_json: JsonObject | null;
  source: string;
  run_id: number | null;
  created_at: string;
}

export interface RunEventRead {
  id: number;
  run_id: number;
  sequence: number;
  event_type: string;
  level: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RunRead {
  id: number;
  thread_id: number | null;
  workflow: string;
  status: RunStatus | string;
  error_message: string | null;
  input_json: JsonObject | null;
  output_json: JsonObject | null;
  events: RunEventRead[];
  created_at: string;
  updated_at: string;
}

export interface ThreadSummary {
  id: number;
  title: string;
  surface: string;
  status: ThreadStatus | string;
  current_focus_paper_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ThreadDetail extends ThreadSummary {
  messages: MessageRead[];
  runs: RunRead[];
}

export interface MemoryRead {
  id: number;
  path: string;
  title: string | null;
  memory_type: string;
  scope_type: string;
  scope_id: string | null;
  paper_id: number | null;
  content_text: string;
  content_json: JsonObject | null;
  source: string;
  status: string;
  source_thread_id: number | null;
  source_paper_id: number | null;
  last_accessed_at: string | null;
  metadata: JsonObject;
  created_at: string;
  updated_at: string;
}

export interface RuntimeSettingsRead {
  environment: string;
  data_dir: string;
  storage_root: string | null;
  database_configured: boolean;
  chat: JsonObject;
  embedding: JsonObject;
  arxiv: JsonObject;
  openalex: JsonObject;
  parsing: JsonObject;
}

export interface ArtifactRead {
  id: number;
  kind: string;
  status: string;
  storage_backend: string;
  storage_uri: string | null;
  original_filename: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  checksum_sha256: string | null;
}

export interface PaperSummary {
  id: number;
  title: string;
  abstract: string | null;
  year: number | null;
  venue: string | null;
  status: string;
  current_pdf_url: string | null;
}

export interface PaperDetail extends PaperSummary {
  authors: unknown[];
  identifiers: Record<string, unknown>[];
  source_records: Record<string, unknown>[];
  artifacts: Record<string, unknown>[];
  parse_jobs: Record<string, unknown>[];
  processed_documents: Record<string, unknown>[];
  reports: Record<string, unknown>[];
}

export interface SearchCandidateRead {
  id: number;
  rank: number;
  source: string;
  source_record_id: string | null;
  paper_id: number | null;
  title: string;
  abstract: string | null;
  authors: unknown[];
  year: number | null;
  doi: string | null;
  arxiv_id: string | null;
  openalex_id: string | null;
  landing_page_url: string | null;
  pdf_url: string | null;
  score: number | null;
}

export interface SearchSessionRead {
  id: number;
  thread_id: number | null;
  run_id: number | null;
  query_text: string;
  status: string;
  selected_candidate_id: number | null;
  candidates: SearchCandidateRead[];
}

export interface RunDecision {
  type: RunDecisionType;
  args?: Record<string, unknown> | null;
  edited_action?: { name: string; args: Record<string, unknown> } | null;
  message?: string | null;
}

export interface ApprovalRequest {
  decisions?: RunDecision[];
  decision?: 'approve' | 'reject' | 'revise' | 'cancel' | null;
  comment?: string | null;
}

export interface ReportSummary {
  id: number;
  title: string;
  paper_id: number | null;
  processed_document_id: number | null;
  report_type: string;
  status: string;
  source_scope: string;
  created_at: string;
  updated_at: string;
}

export interface ReportRead extends ReportSummary {
  paper_title: string | null;
  markdown_content: string | null;
  json_content: JsonObject | null;
  source_refs: unknown[];
  evidence: Record<string, unknown>[];
}

export interface UploadArtifactRequest {
  file: File;
  role: ArtifactUploadRole;
  runId?: number | null;
}

export interface ArxivTaskDailyConfigRead {
  id: number;
  enabled: boolean;
  run_time: string;
  last_started_at: string | null;
  last_finished_at: string | null;
  metadata: JsonObject;
  created_at: string;
  updated_at: string;
}

export interface ArxivTaskDailyConfigUpdateRequest {
  enabled: boolean;
  run_time: string;
}

export interface ArxivTaskSubscriptionRead {
  id: number;
  name: string;
  query: string;
  description: string | null;
  enabled: boolean;
  last_refreshed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArxivTaskSubscriptionCreateRequest {
  name: string;
  query: string;
  description?: string | null;
  enabled: boolean;
}

export interface ArxivTaskSubscriptionUpdateRequest {
  name: string;
  query: string;
  description?: string | null;
  enabled: boolean;
}

export interface ArxivTaskSubscriptionTestRequest {
  query: string;
  max_results?: number;
}

export interface ArxivTaskSubscriptionTestPaperRead {
  arxiv_id: string;
  title: string;
  abstract: string | null;
  authors: string[];
  primary_category: string | null;
  categories: string[];
  published_at: string | null;
  updated_at_source: string | null;
  landing_page_url: string | null;
  pdf_url: string | null;
}

export interface ArxivTaskSubscriptionTestRead {
  query: string;
  total_results: number;
  papers: ArxivTaskSubscriptionTestPaperRead[];
}

export interface ArxivTaskPaperRead {
  id: number;
  arxiv_id: string;
  arxiv_base_id: string;
  title: string;
  abstract: string | null;
  authors: unknown[];
  primary_category: string | null;
  categories: unknown[];
  published_at: string | null;
  updated_at_source: string | null;
  landing_page_url: string | null;
  pdf_url: string | null;
  comment: string | null;
  journal_ref: string | null;
  doi: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArxivTaskQueryWindowRead {
  id: number;
  subscription_id: number;
  query_snapshot: string;
  job_id: number | null;
  kind: string;
  window_start: string;
  window_end: string;
  status: string;
  total_results: number | null;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  page_size: number;
  page_count: number;
  error_message: string | null;
  warning_code: string | null;
  parent_window_id: number | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArxivTaskHarvestJobRead {
  id: number;
  kind: string;
  status: string;
  subscription_ids: number[];
  requested_start: string | null;
  requested_end: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  stats: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export interface ArxivTaskHistoryJobCreateRequest {
  subscription_ids: number[];
  start_time: string;
  end_time: string;
}

export interface ArxivTaskStatusRead {
  daily_config: ArxivTaskDailyConfigRead;
  subscriptions: ArxivTaskSubscriptionRead[];
  enabled_subscription_ids: number[];
  coverage_subscription_ids: number[];
  active_job: ArxivTaskHarvestJobRead | null;
  recent_jobs: ArxivTaskHarvestJobRead[];
  recent_windows: ArxivTaskQueryWindowRead[];
  recent_papers: ArxivTaskPaperRead[];
  total_papers: number;
}
