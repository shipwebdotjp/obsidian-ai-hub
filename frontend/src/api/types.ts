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

export interface DashboardStatsResponse {
  granularity: "day" | "week" | "month";
  buckets: StatsBucket[];
  candidate_topics: string[];
  candidate_keywords: string[];
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
