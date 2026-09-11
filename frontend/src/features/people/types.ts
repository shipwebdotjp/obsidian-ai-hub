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
  deleted_property_values?: number;
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

export interface PrincipalPersonResponse {
  principal_person_id: string | null;
  display_name: string | null;
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

export interface SkippedRelationItem {
  relation_id: string;
  relation_type_slug: string;
  other_person_id: string;
  other_person_name: string;
  started_on: string | null;
  ended_on: string | null;
}

export interface SkippedRelationMerge {
  from_person_id: string;
  from_person_name: string;
  to_person_id: string;
  to_person_name: string;
  reason: string;
  skipped_relations: SkippedRelationItem[];
}

export interface InvalidPropertyItem {
  person_id: string;
  person_name: string;
  property_key: string;
  property_display_name: string;
  reason: string;
}

export interface SkippedPropertyMerge {
  from_person_id: string;
  from_person_name: string;
  to_person_id: string;
  to_person_name: string;
  property_key: string;
  property_display_name: string;
  reason: string;
}

export interface PropertySyncReport {
  replaced_properties_count: number;
  replaced_values_count: number;
  deleted_properties_count: number;
  deleted_values_count: number;
  invalid_properties: InvalidPropertyItem[];
  skipped_property_merges: SkippedPropertyMerge[];
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
  skipped_relation_merges?: SkippedRelationMerge[];
  property_report?: PropertySyncReport | null;
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

export interface PropertyImpactItem {
  property_value_id: string;
  property_definition_id: string;
  property_key: string;
  property_display_name: string;
  source_type: PropertySourceType;
  valid_from: string | null;
  valid_until: string | null;
  result_type: "transferred" | "merged_into_existing" | "property_conflict";
  conflict_reason: string | null;
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
  transferred_properties_count?: number;
  merged_properties_count?: number;
  property_conflicts_count?: number;
  alias_transfers: AliasTransferPreview[];
  merged_summaries: MergedSummaryPreview[];
  relation_impacts?: RelationImpactItem[];
  property_impacts?: PropertyImpactItem[];
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

export type PropertyDataType = "text" | "date" | "number" | "boolean" | "select";
export type PropertyCardinality = "single" | "multiple";
export type PropertySourceType = "database" | "vault";

export interface PersonPropertyOption {
  option_id: string;
  option_key: string;
  display_name: string;
  display_order: number;
  aliases: string[];
}

export interface PersonPropertyOptionInput {
  option_key: string;
  display_name: string;
  display_order?: number;
  aliases?: string[];
}

export interface PersonPropertyDefinition {
  property_definition_id: string;
  key: string;
  display_name: string;
  data_type: PropertyDataType;
  cardinality: PropertyCardinality;
  source_type: PropertySourceType;
  aliases: string[];
  options: PersonPropertyOption[];
  created_at: string;
  updated_at: string;
}

export interface PersonPropertyDefinitionCreateRequest {
  key: string;
  display_name: string;
  data_type: PropertyDataType;
  cardinality: PropertyCardinality;
  source_type?: PropertySourceType;
  aliases?: string[];
  options?: PersonPropertyOptionInput[];
}

export interface PersonPropertyDefinitionUpdateRequest {
  display_name?: string;
  aliases?: string[];
  options?: PersonPropertyOptionInput[];
}

export interface PersonPropertyValue {
  property_value_id: string;
  person_id: string;
  property_definition_id: string;
  property_key: string;
  property_display_name: string;
  data_type: PropertyDataType;
  cardinality: PropertyCardinality;
  source_type: PropertySourceType;
  value: any;
  value_text: string | null;
  value_date: string | null;
  value_number: number | null;
  value_boolean: boolean | null;
  option_id: string | null;
  option_key: string | null;
  option_display_name: string | null;
  valid_from: string | null;
  valid_until: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersonPropertyValueCreateRequest {
  property_definition_id: string;
  value: any;
  valid_from?: string | null;
  valid_until?: string | null;
  note?: string | null;
}

export interface PersonPropertyValueUpdateRequest {
  value?: any;
  valid_from?: string | null;
  valid_until?: string | null;
  note?: string | null;
}

export interface PersonPropertyDefinitionDeleteResponse {
  success: boolean;
  deleted_property_definition_id: string;
  deleted_values_count: number;
  deleted_options_count: number;
}

export interface PersonPropertyValueDeleteResponse {
  success: boolean;
  deleted_property_value_id: string;
}
