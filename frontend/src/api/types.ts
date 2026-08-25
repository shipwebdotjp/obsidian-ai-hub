export type Stability = "stable" | "tentative" | "explicitly_settled";

export type MemoryStatus = "candidate" | "approved" | "rejected" | "expired" | "superseded";

export interface Evidence {
  path: string;
  quote?: string;
  observed_at?: string;
}

export interface DedupSuggestion {
  target_memory_id: string;
  relation: string;
  reason?: string;
  score?: number;
}

export interface DedupAssessment {
  decision: "merge" | "new" | "supersede" | "failed";
  target_memory_id?: string;
  similarity_score?: number;
  reason?: string;
  integrated_content?: string;
  failure_kind?: "request_failed" | "response_invalid";
}

export interface MemoryEvent {
  event_id: string;
  occurred_at: string;
  actor?: string;
  event_type: string;
  memory_id: string;
  previous_status?: string;
  new_status?: string;
  changes?: Record<string, unknown>;
  reason?: string;
}

export interface Memory {
  memory_id: string;
  status: MemoryStatus;
  kind?: string;
  memory_key?: string;
  content: string;
  topics: string[];
  tags: string[];
  evidence: Evidence[];
  valid_from?: string;
  valid_until?: string;
  review_due_at?: string;
  stability?: Stability;
  sensitivity?: string;
  extraction_confidence?: number;
  supersedes?: string;
  contradicts: string[];
  dedup_suggestions: DedupSuggestion[];
  dedup_assessment?: DedupAssessment | null;
  provenance?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  reviewed_by?: string;
  reviewed_at?: string;
}

export interface MemoryDetail extends Memory {
  events: MemoryEvent[];
}

export interface MemoryListResponse {
  items: Memory[];
  total: number;
}

export interface EditPayload {
  content?: string;
  topics?: string[];
  tags?: string[];
  valid_from?: string | null;
  valid_until?: string | null;
  review_due_at?: string | null;
  stability?: Stability;
}

export interface BatchReviewRequest {
  memory_ids: string[];
  action: "approve" | "reject";
}

export interface BatchReviewResponse {
  updated: string[];
  not_found: string[];
  events: number;
}

export interface DeleteResponse {
  found: boolean;
  deleted: boolean;
  events_deleted: number;
  memory?: Memory | null;
}

export interface BatchDeleteResponse {
  deleted: string[];
  not_found: string[];
  events_deleted: number;
}

export interface BatchDeleteRequest {
  memory_ids: string[];
}

export interface MemoryOptionsResponse {
  kinds: string[];
  topics: string[];
}

export interface RenderCopilotProfileResponse {
  updated_files: string[];
}

export type ResearchStatus = "candidate" | "approved" | "rejected" | "duplicate";
export type ResearchJobStatus = "pending" | "running" | "succeeded" | "failed";

export interface ResearchJob {
  job_id: string;
  status: ResearchJobStatus;
  generated_title?: string;
  mode?: string;
  markdown?: string;
  error?: string;
  started_at?: string;
  finished_at?: string;
}

export interface ResearchTheme {
  theme_id: string;
  status: ResearchStatus;
  theme: string;
  direction?: string;
  kind?: string;
  why_now?: string;
  confidence?: number;
  normalized_key: string;
  duplicate_of_theme_id?: string;
  duplicate_reason?: string;
  related_theme_ids: string[];
  created_at?: string;
  updated_at?: string;
  reviewed_at?: string;
  reviewed_by?: string;
  latest_job?: ResearchJob | null;
  origin?: string;
  hitl_run_id?: string;
}

export interface ResearchListResponse {
  items: ResearchTheme[];
  total: number;
}

export interface ResearchReviewRequest {
  action: "approve" | "reject";
  reason?: string;
}

export interface ResearchRunAcceptedResponse {
  theme: ResearchTheme;
  job: ResearchJob;
}

// Vault Search

export interface VaultSearchHitMetadata {
  collection_name?: string;
  source_path?: string;
  file_path?: string;
  relative_path?: string;
  vault_name?: string;
  chunk_index?: number;
  mtime?: number;
  content_hash?: string;
}

export interface VaultSearchHit {
  content: string;
  metadata: VaultSearchHitMetadata;
  score: number;
}

export interface VaultSearchResponse {
  items: VaultSearchHit[];
  total: number;
}

export interface VaultFileResponse {
  content: string;
  relative_path: string;
}

export type SummaryPeriodType = "day" | "week" | "month";

export interface SummaryPerson {
  name: string;
  note: string;
  person_id?: string | null;
  resolution_status?: string | null;
  candidate_id?: string | null;
}

export interface SummaryItem {
  summary_item_id: string;
  kind: string;
  body: string;
  display_order: number;
}

export interface SummaryProjectNote {
  project_id: number;
  display_name: string;
  note: string;
  display_order: number;
}

export interface SummaryProjectNoteInput {
  project_id: number;
  note: string;
}

export interface ProjectCandidate {
  candidate_id: number;
  display_name: string;
  normalized_name: string;
  domain: "work" | "personal";
  status: "unresolved" | "resolved" | "rejected";
  goal?: string | null;
  description?: string | null;
  keywords: string[];
  start_date?: string | null;
  target_date?: string | null;
  completed_date?: string | null;
  evidence?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SummaryListItem {
  summary_id: string;
  period_type: SummaryPeriodType;
  period_key: string;
  period_start?: string | null;
  period_end?: string | null;
  generated_at?: string | null;
  summary?: string | null;
  keywords: string[];
  mood?: string | null;
  sleep_raw?: string | null;
  sleep_hours?: number | null;
  topics: string[];
  projects: string[];
  project_notes: SummaryProjectNote[];
  project_candidates?: ProjectCandidate[];
  people: SummaryPerson[];
}

export interface SummaryDetail extends SummaryListItem {
  items: SummaryItem[];
}

// --- Dashboard interfaces ---

export interface DashboardActivityLog {
  activity_id: string;
  occurred_at: string;
  app_name: string | null;
  window_title: string | null;
  summary: string | null;
  category: string | null;
  keywords: string[];
  project_id?: number | null;
  project_name?: string | null;
}

export interface TodayActivity {
  date: string;
  active_minutes: number;
  inactive_minutes: number;
  logs: DashboardActivityLog[];
}

export interface DashboardHomeResponse {
  this_month_summary: SummaryDetail | null;
  latest_week_summary: SummaryDetail | null;
  yesterday_summary: SummaryDetail | null;
  today_activity: TodayActivity;
}

export interface BrowseDayItem {
  date: string;
  has_summary: boolean;
  summary_id: string | null;
  summary: string | null;
  topics: string[];
}

export interface DashboardBrowseResponse {
  selectable_years: string[];
  selected_year: string;
  selected_month: string | null;
  months: SummaryDetail[];
  weeks: SummaryDetail[];
  days: BrowseDayItem[];
  missing_summary_targets?: MissingSummaryTarget[];
}

export interface MissingSummaryTarget {
  period_type: SummaryPeriodType;
  period_key: string;
  period_start: string;
  period_end: string;
}

export interface SummaryGenerateRequest {
  period_type: SummaryPeriodType;
  target_date?: string;
  target_month?: string;
}

export interface DashboardDayDetailsResponse {
  date: string;
  summary: SummaryDetail | null;
  active_minutes: number;
  inactive_minutes: number;
  logs: DashboardActivityLog[];
}

export interface StatsBucket {
  key: string;
  display_label: string;
  start_date: string;
  end_date: string;
  active_minutes: number;
  inactive_minutes: number;
  daily_summary_count: number;
  topic_counts: Record<string, number>;
  keyword_counts: Record<string, number>;
}

export interface HourlyCategoryBucket {
  hour: number;
  total_log_count: number;
  category_counts: Record<string, number>;
}

export interface DashboardStatsResponse {
  granularity: "day" | "week" | "month";
  buckets: StatsBucket[];
  candidate_topics: string[];
  candidate_keywords: string[];
  activity_categories: string[];
  hourly_category_buckets: HourlyCategoryBucket[];
}

// --- Healthcare types ---

export interface HealthcareBucket {
  key: string;
  display_label: string;
  start_date: string;
  end_date: string;
  value: number | null;
  avg: number | null;
  min: number | null;
  max: number | null;
  sum: number | null;
  count: number;
}

export interface HealthcareMetricSeries {
  key: string;
  label: string;
  type: string;
  unit: string;
  aggregation: "sum" | "avg";
  latest_value: number | null;
  previous_value: number | null;
  delta_pct: number | null;
  buckets: HealthcareBucket[];
}

export interface HealthcareOverviewResponse {
  start_date: string;
  end_date: string;
  granularity: "day" | "week" | "month";
  metrics: HealthcareMetricSeries[];
}

export interface HealthcareCorrelationPoint {
  date: string;
  x: number;
  y: number;
}

export interface HealthcareCorrelationResponse {
  metric_x: string;
  metric_y: string;
  x_label: string;
  y_label: string;
  x_unit: string;
  y_unit: string;
  x_type: string;
  y_type: string;
  start_date: string;
  end_date: string;
  granularity: "day";
  n: number;
  pearson_r: number | null;
  regression_slope: number | null;
  regression_intercept: number | null;
  points: HealthcareCorrelationPoint[];
}

// --- Summary Edit/Delete types ---

export interface SummaryItemInput {
  kind: string;
  body: string;
  display_order: number;
}

export interface SummaryPersonInput {
  person_id: string;
  note: string;
}

export interface SummaryUpdatePayload {
  summary?: string | null;
  keywords?: string[];
  mood?: string | null;
  sleep_raw?: string | null;
  items?: SummaryItemInput[];
  topics?: string[];
  people?: SummaryPersonInput[];
  project_notes?: SummaryProjectNoteInput[];
}

export interface SummaryDeleteResponse {
  deleted: boolean;
  summary_id: string;
}

export interface EditOptionsResponse {
  topics: string[];
  item_kinds: {
    day: string[];
    week: string[];
    month: string[];
  };
}

// --- People type ---

export interface PersonAlias {
  normalized_name: string;
  display_name: string;
}

export interface Person {
  person_id: string;
  display_name: string;
  normalized_name: string;
  vault_id: string | null;
  aliases: PersonAlias[];
  summary_count: number;
}

// --- Task Config Types ---

export interface TaskItem {
  id: string;
  enabled: boolean;
  schedule: Record<string, any>;
  command: string;
  is_preset: boolean;
  preset_flag?: string | null;
  preset_name?: string | null;
  next_run?: string | null;
}

export interface TaskConfigResponse {
  tasks: TaskItem[];
  filepath: string;
  revision: string;
}

export interface TaskConfigUpdateResponse {
  success: boolean;
  revision: string;
}

export interface CommandSegment {
  cwd?: string | null;
  args: string[];
}

export interface CommandPreviewResponse {
  segments: CommandSegment[];
  is_preset: boolean;
  preset_flag?: string | null;
  preset_name?: string | null;
}

// --- HITL types ---

export interface HitlQuestion {
  question_id: string;
  run_id: string;
  question_set_id: string;
  question_key: string;
  status: string;
  question_type: string;
  display_text: string;
  choices: any[] | null;
  answer: any | null;
  is_required: number;
  expires_at: string | null;
  answered_at: string | null;
  created_at: string;
  updated_at: string;
  sequence: number;
  title: string | null;
  prompt: string | null;
  context: unknown | null;
}

export interface HitlRun {
  run_id: string;
  handler: string;
  status: string;
  checkpoint: string | null;
  active_question_set_id: string | null;
  lease_owner: string | null;
  lease_expires_at: string | null;
  retry_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  title: string | null;
  description: string | null;
  display_type: string | null;
  display_title: string | null;
}

export interface HitlRunDetail extends HitlRun {
  questions: HitlQuestion[];
}

export interface HitlRunListResponse {
  items: HitlRun[];
  total: number;
}

export interface PlannerAppleEvent {
  title: string;
  start_time: string | null;
  end_time: string | null;
  location: string | null;
  all_day: boolean;
  source: string;
}

export interface PlannerAppleReminder {
  title: string;
  due_date: string | null;
  source: string;
}

export interface PlannerRecurringItem {
  title: string;
  date: string;
  category: number;
  source: string;
  start_time: string | null;
  end_time: string | null;
  all_day: boolean;
}

export interface PlannerInboxPending {
  run_id: string;
  handler: string;
  title: string;
  kind: string;
  start_time: string | null;
  end_time: string | null;
  location: string | null;
  due_date: string | null;
}

export type PlannerProposalStatus = "proposed" | "promoted" | "rejected" | "expired";

export interface PlannerProposal {
  proposal_id: string;
  kind: string;
  title: string;
  rationale: string;
  generation_source: string;
  status: PlannerProposalStatus;
  fingerprint: string | null;
  external_result: string | null;
  start_time: string | null;
  end_time: string | null;
  location: string | null;
  due_date: string | null;
  created_at: string;
  updated_at: string;
  expired_at: string | null;
  promoted_at: string | null;
  rejected_at: string | null;
}

export interface PlannerTimelineResponse {
  apple_events: PlannerAppleEvent[];
  apple_reminders: PlannerAppleReminder[];
  apple_error: string | null;
  recurring_events: PlannerRecurringItem[];
  inbox_pending: PlannerInboxPending[];
  ai_proposals: PlannerProposal[];
}

export interface PlannerProposalListResponse {
  items: PlannerProposal[];
  total: number;
}

export interface PlannerProposalUpdatePayload {
  title?: string;
  rationale?: string;
  kind?: string;
  start_time?: string | null;
  end_time?: string | null;
  location?: string | null;
  due_date?: string | null;
}

export interface PlannerGenerateResponse {
  generated: number;
  proposals: PlannerProposal[];
}

// --- AI Agent types ---

export interface AgentAdvancedParams {
  max_tokens?: number | null;
  reasoning?: {
    effort?: string | null;
  } | null;
}

export interface AgentPromptTemplate {
  template_id: string;
  agent_id: string;
  name: string;
  content: string;
  display_order: number;
  created_at: string;
  updated_at: string;
}

export interface Agent {
  agent_id: string;
  name: string;
  system_prompt: string;
  provider: string | null;
  model: string | null;
  tool_ids: string[];
  advanced_params?: AgentAdvancedParams | null;
  created_at: string;
  updated_at: string;
}

export interface AgentTool {
  tool_id: string;
  name: string;
  description: string;
}

export interface AgentSession {
  session_id: string;
  agent_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface AgentMessage {
  message_id: string;
  session_id: string;
  sequence: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface AgentToolCall {
  id: string;
  tool_name: string;
  args: Record<string, unknown>;
  result: string;
  hitl_run_id?: string | null;
  status: "succeeded" | "failed";
  error?: string | null;
  iteration: number;
}

export interface AgentRun {
  run_id: string;
  session_id: string;
  user_message_id: string;
  assistant_message_id: string | null;
  status: "running" | "succeeded" | "failed";
  used_tools: string[];
  created_hitl_run_ids: string[];
  tool_calls?: AgentToolCall[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface AgentSessionDetailResponse {
  session: AgentSession;
  agent: Agent;
  messages: AgentMessage[];
  runs: AgentRun[];
}

export interface AgentLiveToolCall {
  /** Stable identity for the live panel; call_key takes precedence when present. */
  id: string;
  call_id?: string;
  call_key?: string;
  tool_name: string;
  args: Record<string, unknown>;
  result: string;
  hitl_run_id?: string | null;
  status: "preparing" | "running" | "succeeded" | "failed";
  error?: string | null;
  iteration: number;
}

export type AgentStreamEvent =
  | { type: "thinking"; iteration: number }
  | { type: "tool_call_detected"; call_key: string; tool_name: string; iteration: number }
  | { type: "tool_call_start"; call_id: string; call_key?: string; tool_name: string; args: Record<string, unknown>; iteration: number }
  | { type: "tool_call_end"; call_id: string; call_key?: string; tool_name: string; status: "succeeded" | "failed"; result: string; hitl_run_id?: string | null; error?: string | null; iteration: number }
  | { type: "text"; delta: string }
  | { type: "done"; message: AgentMessage; run: AgentRun; hitl_run_ids: string[]; tool_calls?: AgentToolCall[] }
  | { type: "error"; error: string; run_id?: string };
