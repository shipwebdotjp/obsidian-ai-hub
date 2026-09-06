import { Person, PersonAlias } from "../../api/types";

export interface PeopleError {
  message: string;
  conflict_type?: string;
  existing_person_id?: string;
  existing_person_name?: string;
}

export interface DeletePersonResponse {
  success: boolean;
  deleted_summary_people: number;
  deleted_aliases: number;
  deleted_assignments: number;
  deleted_subject_relations?: number;
  deleted_object_relations?: number;
  deleted_relation_evidence?: number;
}

export interface AssociatedSummary {
  summary_id: string;
  period_type: string;
  period_key: string;
  note: string | null;
  display_order: number;
}

export interface RelationCounts {
  summaries: number;
  aliases: number;
  assignments: number;
  subject_relations?: number;
  object_relations?: number;
  evidence?: number;
}

export interface PersonDetail extends Person {
  summaries: AssociatedSummary[];
  relation_counts: RelationCounts;
}

export interface PersonCandidate {
  candidate_id: string;
  display_name: string;
  normalized_name: string;
  status: string;
}

export interface PersonCandidateDetail extends PersonCandidate {
  summaries: AssociatedSummary[];
  assigned_summaries_count: number;
}

export interface DuplicateVaultMatch {
  unlinked_person: Person;
  vault_person: {
    id: string;
    name: string;
    path: string;
  };
}

export interface DuplicateSameVaultIdGroup {
  vault_id: string;
  people: Person[];
}

export interface DuplicatesResponse {
  vault_matches: DuplicateVaultMatch[];
  same_vault_id_groups: DuplicateSameVaultIdGroup[];
}

export interface SyncPeopleResponse {
  synced: boolean;
  loader_report: {
    file_deficiencies: Array<{ path: string; message: string }>;
    duplicate_ids: Array<{ id: string; paths: string[] }>;
    normalized_name_collisions: Array<{ normalized_name: string; notes: Array<{ id: string; name: string; path: string }> }>;
    alias_collisions: Array<{ alias: string; notes: Array<{ id: string; name: string; path: string; role: string }> }>;
  };
  db_conflicts: {
    mismatches: Array<{
      alias: string;
      db_person_id: string;
      db_person_name: string;
      db_person_vault_id: string | null;
      vault_note: { id: string; name: string; path: string };
    }>;
    compound_conflicts: Array<{
      alias: string;
      db_person_id: string;
      db_person_name: string;
      db_person_vault_id: string | null;
      vault_claimers: Array<{ id: string; name: string; path: string }>;
    }>;
  };
}

export interface MergedSummaryPreview {
  summary_id: string;
  period_key: string;
  period_type: string;
  from_note: string | null;
  to_note: string | null;
  merged_note: string | null;
  merged_display_order: number | null;
}

export interface AliasTransferPreview {
  normalized_name: string;
  display_name: string;
}

export interface RelationImpactItem {
  relation_id: string;
  other_person_id: string;
  other_person_name: string;
  relation_type_id: string;
  relation_type_slug: string;
  relation_type_forward_label: string;
  relation_type_reverse_label: string;
  started_on: string | null;
  ended_on: string | null;
  result_type: "transferred" | "merged_into_existing" | "self_relation_conflict";
  surviving_relation_id: string | null;
}

export interface PeopleMergePreviewResponse {
  allowed: boolean;
  reason: string | null;
  from_person: Person | null;
  to_person: Person | null;
  transferred_summaries_count: number;
  transferred_aliases_count: number;
  transferred_relations_count?: number;
  merged_relations_count?: number;
  self_relation_conflicts_count?: number;
  alias_transfers: AliasTransferPreview[];
  merged_summaries: MergedSummaryPreview[];
  relation_impacts?: RelationImpactItem[];
}

export interface PersonRelationType {
  relation_type_id: string;
  slug: string;
  forward_label: string;
  reverse_label: string;
  directionality: "directed" | "symmetric";
  description: string | null;
  is_builtin: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PersonRelationTypeCreateRequest {
  slug: string;
  forward_label: string;
  reverse_label: string;
  directionality: "directed" | "symmetric";
  description?: string | null;
}

export interface PersonRelationTypeUpdateRequest {
  forward_label?: string | null;
  reverse_label?: string | null;
  description?: string | null;
  is_active?: boolean | null;
}

export interface PersonRelationEvidence {
  evidence_id: string;
  relation_id: string;
  source_type: "manual";
  source_ref: string | null;
  quote: string | null;
  note: string | null;
  observed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersonRelationEvidenceCreateRequest {
  source_type?: "manual";
  source_ref?: string | null;
  quote?: string | null;
  note?: string | null;
  observed_at?: string | null;
}

export interface PersonRelationEvidenceUpdateRequest {
  source_ref?: string | null;
  quote?: string | null;
  note?: string | null;
  observed_at?: string | null;
}

export type RelationStatus = "upcoming" | "active" | "ended" | "undated";

export interface PersonRelation {
  relation_id: string;
  subject_person_id: string;
  object_person_id: string;
  relation_type_id: string;
  started_on: string | null;
  ended_on: string | null;
  note: string | null;
  status: RelationStatus;
  created_at: string;
  updated_at: string;
  relation_type?: PersonRelationType;
  evidence: PersonRelationEvidence[];
}

export interface PersonRelationCreateRequest {
  subject_person_id: string;
  object_person_id: string;
  relation_type_id: string;
  started_on?: string | null;
  ended_on?: string | null;
  note?: string | null;
  initial_evidence?: PersonRelationEvidenceCreateRequest[];
}

export interface PersonRelationUpdateRequest {
  started_on?: string | null;
  ended_on?: string | null;
  note?: string | null;
}

export interface RelationDuplicateMergeResponse {
  action: "created" | "updated" | "merged_into_existing";
  relation: PersonRelation;
}
