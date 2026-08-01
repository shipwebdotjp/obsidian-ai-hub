import { apiGet, apiPost, apiPatch, apiDelete } from "../../api/client";
import { Person } from "../../api/types";
import {
  PersonCandidate,
  PersonCandidateDetail,
  PersonDetail,
  DuplicatesResponse,
  SyncPeopleResponse,
  PeopleMergePreviewResponse,
  DeletePersonResponse
} from "./types";

const PEOPLE_API = "/api/v1/people";

export async function fetchCandidates(): Promise<PersonCandidate[]> {
  return apiGet<PersonCandidate[]>(`${PEOPLE_API}/candidates`);
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
