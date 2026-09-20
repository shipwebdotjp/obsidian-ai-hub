import type { QuestionItem } from "../components/InConversationQuestionCard";

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

export interface MemoryPersonRef {
  person_id: string;
  display_name: string;
}

export interface Memory {
  memory_id: string;
  status: MemoryStatus;
  scope?: "user" | "person";
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
  people?: MemoryPersonRef[];
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
  person_ids?: string[];
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
export type ResearchMode = "auto" | "internal" | "web" | "deep" | "project";

export interface ResearchJob {
  job_id: string;
  status: ResearchJobStatus;
  generated_title?: string;
  mode?: string;
  markdown?: string;
  error?: string;
  started_at?: string;
  finished_at?: string;
  project_id?: number | null;
}

export interface ResearchThemeReference {
  theme_id: string;
  theme: string;
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
  duplicate_of_theme?: ResearchThemeReference | null;
  duplicate_reason?: string;
  related_theme_ids: string[];
  created_at?: string;
  updated_at?: string;
  reviewed_at?: string;
  reviewed_by?: string;
  latest_job?: ResearchJob | null;
  origin?: string;
  hitl_run_id?: string;
  project_id?: number | null;
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

export interface Project {
  project_id: number;
  normalized_name: string;
  display_name: string;
  domain: "work" | "personal";
  status: "inquiry" | "active" | "paused" | "completed" | "cancelled";
  goal?: string | null;
  description?: string | null;
  keywords: string[];
  start_date?: string | null;
  target_date?: string | null;
  completed_date?: string | null;
  project_path?: string | null;
  reference_url?: string | null;
  created_at: string;
  updated_at: string;
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

export interface HealthcareImportStats {
  records: number;
  workouts: number;
  activity_summaries: number;
  ecg_files: number;
  ignored_duplicates: number;
  metadata_entries: number;
  hrv_beats: number;
  records_inserted: number;
  workouts_inserted: number;
  activity_summaries_inserted: number;
}

export interface HealthcareImportResponse {
  import_id: string;
  status: "succeeded";
  source: string;
  stats: HealthcareImportStats;
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

// --- Scheduler Job Types ---

export type RecurringJobScheduleType =
  | "minutely"
  | "hourly"
  | "daily"
  | "weekly"
  | "monthly";

export type CronFieldValue = number | string | Array<number | string>;

export interface RecurringJobSchedule {
  type: RecurringJobScheduleType;
  second?: CronFieldValue;
  minute?: CronFieldValue;
  hour?: CronFieldValue;
  weekday?: CronFieldValue;
  day?: CronFieldValue;
}

export interface AgentJobSource {
  agent_id: string;
  session_id?: string | null;
  run_id?: string | null;
  registered_at?: string | null;
}

export interface RecurringJob {
  id: string;
  enabled: boolean;
  schedule: RecurringJobSchedule;
  command: string;
  is_preset: boolean;
  preset_flag?: string | null;
  preset_name?: string | null;
  next_run?: string | null;
  agent_source?: AgentJobSource | null;
}

export interface SchedulerJobConfigResponse {
  jobs: RecurringJob[];
  filepath: string;
  revision: string;
}

export interface SchedulerJobConfigUpdateResponse {
  success: boolean;
  revision: string;
}

export type RecurringJobUpdate = Pick<
  RecurringJob,
  "id" | "enabled" | "schedule" | "command" | "agent_source"
>;

export type OneShotJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface OneShotJobSummary {
  job_id: string;
  command: string;
  run_at_utc: string;
  status: OneShotJobStatus;
  agent_id?: string | null;
  session_id?: string | null;
  run_id?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  output_truncated: boolean;
  error_summary?: string | null;
}

export interface OneShotJobSegment {
  cwd?: string | null;
  args: string[];
  exit_code?: number | null;
  stdout: string;
  stderr: string;
  truncated_stdout: boolean;
  truncated_stderr: boolean;
}

export interface OneShotJobDetail extends OneShotJobSummary {
  segments: OneShotJobSegment[];
}

export interface OneShotJobListResponse {
  items: OneShotJobSummary[];
  total: number;
}

export interface JobState {
  job_id: string;
  last_check_at: string;
  consecutive_empty_count: number;
  last_processed_at: string | null;
  last_error_at: string | null;
  last_error_message: string | null;
  last_error_type: string | null;
  processed_count: number;
  skipped_count: number;
  failed_count: number;
  updated_at: string;
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
  rejection_reason: string | null;
  rejection_comment: string | null;
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

export interface PlannerRejectPayload {
  reason?: string | null;
  comment?: string | null;
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
  delegate_agent_ids?: string[];
  advanced_params?: AgentAdvancedParams | null;
  pinned_at?: string | null;
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
  pinned_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentMessageSearchResult {
  agent_id: string;
  agent_name: string;
  session_id: string;
  session_title: string;
  session_updated_at: string;
  message_id: string;
  role: "user" | "assistant";
  snippet: string;
  created_at: string;
}

export interface AgentMessageAttachment {
  name: string;
  mime_type: string;
  data: string;
}

export interface AgentMessage {
  message_id: string;
  session_id: string;
  sequence: number;
  role: "user" | "assistant";
  content: string;
  attachments?: AgentMessageAttachment[];
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

export type AgentRunStatus =
  | "queued"
  | "running"
  | "cancelling"
  | "waiting_user"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface SlashInvocation {
  kind: "skill";
  name: string;
}

export interface SlashCandidate {
  kind: "skill" | "template";
  name: string;
  description: string;
  template_id?: string;
  content?: string;
}

export interface AgentSlashCandidatesResponse {
  candidates: SlashCandidate[];
  has_skills_tool: boolean;
}

export interface AgentRun {
  run_id: string;
  session_id: string;
  user_message_id: string;
  assistant_message_id: string | null;
  status: AgentRunStatus;
  hitl_run_id: string | null;
  slash_invocation?: SlashInvocation | null;
  used_tools: string[];
  created_hitl_run_ids: string[];
  tool_calls?: AgentToolCall[];
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  idempotency_key?: string | null;
}

export interface AskUserAnswerItem {
  question_id: string;
  question: string;
  selected_value: string;
  selected_label: string;
  text?: string | null;
}

export interface AskUserAnswerRound {
  user_message_id: string;
  hitl_run_id: string;
  tool_call_id: string;
  items: AskUserAnswerItem[];
}

export interface AgentSessionDetailResponse {
  session: AgentSession;
  agent: Agent;
  messages: AgentMessage[];
  runs: AgentRun[];
  active_run?: AgentRun | null;
  ask_user_answer_history?: AskUserAnswerRound[];
}

export type AgentRunEventType =
  | "thinking"
  | "tool_call_detected"
  | "tool_call_start"
  | "tool_call_end"
  | "text_append"
  | "user_question"
  | "done"
  | "error"
  | "cancelled";

export interface AgentRunEvent {
  event_id: number;
  event_type: AgentRunEventType;
  payload: Record<string, unknown>;
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
  | { type: "user_question"; hitl_run_id: string; question_set_id: string; questions: QuestionItem[] }
  | { type: "done"; message: AgentMessage; run: AgentRun; hitl_run_ids: string[]; tool_calls?: AgentToolCall[]; session_title?: string }
  | { type: "error"; error: string; run_id?: string };

// --- Task Agent types ---

export type TaskAgentApprovalPolicy = "auto" | "plan_required";

export interface TaskAgentTask {
  task_id: string;
  prompt_text: string;
  status: string;
  current_plan_id: string | null;
  worker_instance_id: string | null;
  active_child_kind: string | null;
  active_child_run_id: string | null;
  result_summary: string | null;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface TaskAgentPlan {
  plan_id: string;
  task_id: string;
  version: number;
  plan: Record<string, unknown>;
  approval_policy_snapshot: Record<string, unknown>;
  status: string;
  rejection_reason: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface TaskAgentEvent {
  event_id: number;
  task_id: string;
  seq: number;
  event_type: string;
  payload: Record<string, any>;
  created_at: string;
}

export interface TaskAgentTaskDetail {
  task: TaskAgentTask;
  plans: TaskAgentPlan[];
  events: TaskAgentEvent[];
}

export interface TaskAgentListResponse {
  items: TaskAgentTask[];
  total: number;
}

export interface TaskAgentCreateRequest {
  prompt_text: string;
}

export interface TaskAgentCapability {
  capability_key: string;
  adapter_kind: string;
  enabled: boolean;
  approval_policy: TaskAgentApprovalPolicy;
  updated_at: string;
}

export type TaskAgentCapabilityUpdate =
  | { enabled: boolean; approval_policy?: TaskAgentApprovalPolicy }
  | { enabled?: boolean; approval_policy: TaskAgentApprovalPolicy };

export interface TaskAgentTargetOption {
  project_id: number;
  name: string;
  git_root: string;
  keywords: string[];
}

export interface TaskAgentTargetOptionsResponse {
  items: TaskAgentTargetOption[];
}

export type TaskAgentProjectResolutionBody =
  | { kind: "project"; project_id: number }
  | { kind: "general" };

export interface TaskAgentProjectResolution {
  kind: "project" | "general";
  project_id: number | null;
  display_name: string;
  confidence: number | null;
  rationale: string;
  source: "inferred" | "user";
}


// --- Workflow --------------------------------------------------------------

export interface WorkflowCapabilityRecord {
  capability_key: string;
  label: string;
  description: string;
  enabled: boolean;
  approval_policy: string;
  workflow_only: boolean;
}

export interface WorkflowCapabilityListResponse {
  items: WorkflowCapabilityRecord[];
}

export type WorkflowNodeType =
  | "capability"
  | "agent"
  | "loop"
  | "terminal"
  | "loop_result";

export interface WorkflowUIPosition {
  x: number;
  y: number;
}

export interface WorkflowNode {
  node_id: string;
  node_type: WorkflowNodeType;
  label?: string | null;
  config: Record<string, unknown>;
  parent_loop_node_id?: string | null;
  ui_position?: WorkflowUIPosition | null;
}

export interface WorkflowEdge {
  edge_id: string;
  source_node_id: string;
  target_node_id: string;
  edge_kind: "normal" | "error";
  condition: Record<string, unknown> | null;
  order_index: number;
}

export interface WorkflowRevision {
  revision_id: string;
  workflow_id: string;
  version: number;
  status: "draft" | "published" | "superseded";
  inputs_schema: Record<string, unknown>;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  created_at: string;
  updated_at: string;
}

export type WorkflowRunStatus =
  | "queued"
  | "waiting_approval"
  | "running"
  | "waiting_hitl"
  | "waiting_attention"
  | "cancelling"
  | "interrupted"
  | "completed"
  | "incomplete"
  | "failed"
  | "cancelled";

export type WorkflowNodeStatus =
  | "pending"
  | "running"
  | "waiting_hitl"
  | "succeeded"
  | "skipped"
  | "failed"
  | "needs_attention"
  | "cancelled";

export interface WorkflowRunNode {
  run_id: string;
  node_id: string;
  activation_id: string;
  attempt: number;
  status: WorkflowNodeStatus;
  inputs_json?: string | null;
  output_json?: string | null;
  output_summary?: string | null;
  error_summary?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface WorkflowEvent {
  event_id: string;
  run_id: string;
  seq: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface WorkflowRun {
  run_id: string;
  workflow_id: string;
  revision_id: string;
  status: WorkflowRunStatus;
  inputs: Record<string, unknown>;
  result_summary?: string | null;
  error_summary?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  nodes?: WorkflowRunNode[];
  events?: WorkflowEvent[];
}

export interface WorkflowSummary {
  workflow_id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowDetail extends WorkflowSummary {
  revisions?: WorkflowRevision[];
  runs?: WorkflowRun[];
  revision?: WorkflowRevision;
}

export interface WorkflowListResponse {
  items: WorkflowSummary[];
  total: number;
}

export interface WorkflowValidationResponse {
  valid: boolean;
  errors: string[];
}
