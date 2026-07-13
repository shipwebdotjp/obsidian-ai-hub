export type Stability = "stable" | "tentative" | "explicitly_settled";

export type MemoryStatus = "candidate" | "approved" | "rejected" | "expired";

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
