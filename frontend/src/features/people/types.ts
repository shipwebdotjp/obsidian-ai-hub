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

export interface VaultReportResponse {
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

export interface SyncPeopleResponse extends VaultReportResponse {
  synced: boolean;
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

export interface PeopleMergePreviewResponse {
  allowed: boolean;
  reason: string | null;
  from_person: Person | null;
  to_person: Person | null;
  transferred_summaries_count: number;
  transferred_aliases_count: number;
  alias_transfers: AliasTransferPreview[];
  merged_summaries: MergedSummaryPreview[];
}
