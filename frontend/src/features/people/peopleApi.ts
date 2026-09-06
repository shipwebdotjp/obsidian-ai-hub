import { apiGet, apiPost, apiPatch, apiDelete } from "../../api/client";
import { Person } from "../../api/types";
import {
  PersonCandidate,
  PersonCandidateDetail,
  PersonDetail,
  DuplicatesResponse,
  SyncPeopleResponse,
  PeopleMergePreviewResponse,
  DeletePersonResponse,
  PersonRelationType,
  PersonRelationTypeCreateRequest,
  PersonRelationTypeUpdateRequest,
  PersonRelation,
  PersonRelationCreateRequest,
  PersonRelationUpdateRequest,
  PersonRelationEvidenceCreateRequest,
  PersonRelationEvidenceUpdateRequest,
  RelationDuplicateMergeResponse,
  RelationStatus
} from "./types";

const PEOPLE_API = "/api/v1/people";
const RELATION_TYPES_API = "/api/v1/person-relation-types";
const RELATIONS_API = "/api/v1/person-relations";
const EVIDENCE_API = "/api/v1/person-relation-evidence";

export async function fetchCandidates(status: "unresolved" | "rejected" = "unresolved"): Promise<PersonCandidate[]> {
  return apiGet<PersonCandidate[]>(`${PEOPLE_API}/candidates?status=${status}`);
}

export async function rejectCandidate(candidateId: string): Promise<void> {
  await apiPost(`${PEOPLE_API}/candidates/${encodeURIComponent(candidateId)}/reject`, {});
}

export async function reopenCandidate(candidateId: string): Promise<void> {
  await apiPost(`${PEOPLE_API}/candidates/${encodeURIComponent(candidateId)}/reopen`, {});
}

export async function fetchPeople(): Promise<Person[]> {
  return apiGet<Person[]>(PEOPLE_API);
}

export async function fetchDuplicates(): Promise<DuplicatesResponse> {
  return apiGet<DuplicatesResponse>(`${PEOPLE_API}/duplicates`);
}

export async function fetchVaultReport(): Promise<SyncPeopleResponse> {
  return apiGet<SyncPeopleResponse>(`${PEOPLE_API}/vault-report`);
}

export async function fetchCandidateDetail(candidateId: string): Promise<PersonCandidateDetail> {
  return apiGet<PersonCandidateDetail>(`${PEOPLE_API}/candidates/${encodeURIComponent(candidateId)}`);
}

export async function fetchPersonDetail(personId: string): Promise<PersonDetail> {
  return apiGet<PersonDetail>(`${PEOPLE_API}/${encodeURIComponent(personId)}`);
}

export async function assignCandidateSummary(
  candidateId: string,
  summaryId: string,
  targetPersonId: string
): Promise<void> {
  await apiPost(
    `${PEOPLE_API}/candidates/${encodeURIComponent(candidateId)}/summaries/${encodeURIComponent(summaryId)}/assign`,
    {
      target_person_id: targetPersonId,
    }
  );
}

export async function updatePerson(
  personId: string,
  displayName: string,
  aliases: string[]
): Promise<PersonDetail> {
  return apiPatch<PersonDetail>(`${PEOPLE_API}/${encodeURIComponent(personId)}`, {
    display_name: displayName,
    aliases,
  });
}

export async function deletePerson(personId: string): Promise<DeletePersonResponse> {
  return apiDelete<DeletePersonResponse>(`${PEOPLE_API}/${encodeURIComponent(personId)}`);
}

export async function resolveCandidate(
  candidateId: string,
  targetPersonId: string
): Promise<void> {
  await apiPost(`${PEOPLE_API}/candidates/${encodeURIComponent(candidateId)}/resolve`, {
    target_person_id: targetPersonId,
  });
}

export async function getMergePreview(
  fromPersonId: string,
  toPersonId: string
): Promise<PeopleMergePreviewResponse> {
  return apiPost<PeopleMergePreviewResponse>(`${PEOPLE_API}/merge/preview`, {
    from_person_id: fromPersonId,
    to_person_id: toPersonId,
  });
}

export async function executeMerge(fromPersonId: string, toPersonId: string): Promise<void> {
  await apiPost(`${PEOPLE_API}/merge`, {
    from_person_id: fromPersonId,
    to_person_id: toPersonId,
  });
}

export async function deleteAlias(personId: string, normalizedName: string): Promise<PersonDetail> {
  return apiDelete<PersonDetail>(
    `${PEOPLE_API}/${encodeURIComponent(personId)}/aliases?normalized_name=${encodeURIComponent(normalizedName)}`
  );
}

export async function promoteCandidate(
  candidateId: string,
  displayName: string
): Promise<PersonDetail> {
  return apiPost<PersonDetail>(`${PEOPLE_API}/candidates/${encodeURIComponent(candidateId)}/promote`, {
    display_name: displayName,
  });
}

export async function syncPeople(): Promise<SyncPeopleResponse> {
  return apiPost<SyncPeopleResponse>(`${PEOPLE_API}/sync`, {});
}

export async function fetchPersonRelationTypes(): Promise<PersonRelationType[]> {
  return apiGet<PersonRelationType[]>(RELATION_TYPES_API);
}

export async function createPersonRelationType(
  req: PersonRelationTypeCreateRequest
): Promise<PersonRelationType> {
  return apiPost<PersonRelationType>(RELATION_TYPES_API, req);
}

export async function updatePersonRelationType(
  relationTypeId: string,
  req: PersonRelationTypeUpdateRequest
): Promise<PersonRelationType> {
  return apiPatch<PersonRelationType>(`${RELATION_TYPES_API}/${encodeURIComponent(relationTypeId)}`, req);
}

export async function fetchPersonRelations(
  personId: string,
  status?: RelationStatus
): Promise<PersonRelation[]> {
  const url = status
    ? `${PEOPLE_API}/${encodeURIComponent(personId)}/relations?status=${encodeURIComponent(status)}`
    : `${PEOPLE_API}/${encodeURIComponent(personId)}/relations`;
  return apiGet<PersonRelation[]>(url);
}

export async function createPersonRelation(
  personId: string,
  req: PersonRelationCreateRequest
): Promise<RelationDuplicateMergeResponse> {
  return apiPost<RelationDuplicateMergeResponse>(`${PEOPLE_API}/${encodeURIComponent(personId)}/relations`, req);
}

export async function updatePersonRelation(
  relationId: string,
  req: PersonRelationUpdateRequest
): Promise<RelationDuplicateMergeResponse> {
  return apiPatch<RelationDuplicateMergeResponse>(`${RELATIONS_API}/${encodeURIComponent(relationId)}`, req);
}

export async function deletePersonRelation(relationId: string): Promise<void> {
  await apiDelete(`${RELATIONS_API}/${encodeURIComponent(relationId)}`);
}

export async function addRelationEvidence(
  relationId: string,
  req: PersonRelationEvidenceCreateRequest
): Promise<PersonRelation> {
  return apiPost<PersonRelation>(`${RELATIONS_API}/${encodeURIComponent(relationId)}/evidence`, req);
}

export async function updateRelationEvidence(
  evidenceId: string,
  req: PersonRelationEvidenceUpdateRequest
): Promise<PersonRelation> {
  return apiPatch<PersonRelation>(`${EVIDENCE_API}/${encodeURIComponent(evidenceId)}`, req);
}

export async function deleteRelationEvidence(evidenceId: string): Promise<void> {
  await apiDelete(`${EVIDENCE_API}/${encodeURIComponent(evidenceId)}`);
}
