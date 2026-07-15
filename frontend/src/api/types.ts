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
