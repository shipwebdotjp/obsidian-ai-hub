import type { ProjectCandidate } from "../../api/types";

export type ProjectDomain = "work" | "personal";

export type ProjectStatus = "inquiry" | "active" | "paused" | "completed" | "cancelled";

export type ResolveMode = "approve_new" | "link_existing" | "reject";

export type Tab = "inbox" | "projects" | "archive";

export interface Project {
  project_id: number;
  normalized_name: string;
  display_name: string;
  domain: ProjectDomain;
  status: ProjectStatus;
  goal: string | null;
  description: string | null;
  keywords: string[];
  start_date: string | null;
  target_date: string | null;
  completed_date: string | null;
  project_path: string | null;
  reference_url: string | null;
  created_at: string;
  updated_at: string;
  summary_count: number;
}

export interface AssociatedSummary {
  summary_id: string;
  period_type: string;
  period_key: string;
  note?: string | null;
  display_order?: number | null;
}

export interface ProjectDetail extends Project {
  summaries: AssociatedSummary[];
}

export interface ProjectCandidateDetail extends ProjectCandidate {
  summaries: AssociatedSummary[];
  assigned_summaries_count: number;
}
