import { apiGet, apiPost, apiPatch, withQuery } from "../../api/client";
import {
  CoachGoal,
  CoachGoalDetail,
  CoachGoalCreateRequest,
  CoachGoalUpdateRequest,
  CoachFocus,
  CoachFocusCreateRequest,
  CoachFocusUpdateRequest,
  CoachWeeklyReflection,
  CoachWeeklyReflectionCreateRequest,
  CoachWeeklyReflectionUpdateRequest,
  CoachThreadResponse,
} from "./types";

const COACH_API = "/api/v1/coach";

export async function fetchCoachGoals(status?: string): Promise<{ items: CoachGoalDetail[]; total: number }> {
  const query: Record<string, string> = {};
  if (status) query.status = status;
  return apiGet<{ items: CoachGoalDetail[]; total: number }>(withQuery(`${COACH_API}/goals`, query));
}

export async function createCoachGoal(req: CoachGoalCreateRequest): Promise<CoachGoalDetail> {
  return apiPost<CoachGoalDetail>(`${COACH_API}/goals`, req);
}

export async function fetchCoachGoalDetail(goalId: string): Promise<CoachGoalDetail> {
  return apiGet<CoachGoalDetail>(`${COACH_API}/goals/${encodeURIComponent(goalId)}`);
}

export async function updateCoachGoal(
  goalId: string,
  req: CoachGoalUpdateRequest
): Promise<CoachGoalDetail> {
  return apiPatch<CoachGoalDetail>(`${COACH_API}/goals/${encodeURIComponent(goalId)}`, req);
}

export async function pauseCoachGoal(goalId: string): Promise<CoachGoalDetail> {
  return apiPost<CoachGoalDetail>(`${COACH_API}/goals/${encodeURIComponent(goalId)}/pause`, {});
}

export async function resumeCoachGoal(goalId: string): Promise<CoachGoalDetail> {
  return apiPost<CoachGoalDetail>(`${COACH_API}/goals/${encodeURIComponent(goalId)}/resume`, {});
}

export async function endCoachGoal(goalId: string): Promise<CoachGoalDetail> {
  return apiPost<CoachGoalDetail>(`${COACH_API}/goals/${encodeURIComponent(goalId)}/end`, {});
}

export async function createCoachFocus(
  goalId: string,
  req: CoachFocusCreateRequest
): Promise<CoachFocus> {
  return apiPost<CoachFocus>(`${COACH_API}/goals/${encodeURIComponent(goalId)}/focuses`, req);
}

export async function updateCoachFocus(
  focusId: string,
  req: CoachFocusUpdateRequest
): Promise<CoachFocus> {
  return apiPatch<CoachFocus>(`${COACH_API}/focuses/${encodeURIComponent(focusId)}`, req);
}

export async function activateCoachFocus(focusId: string): Promise<CoachFocus> {
  return apiPost<CoachFocus>(`${COACH_API}/focuses/${encodeURIComponent(focusId)}/activate`, {});
}

export async function pauseCoachFocus(focusId: string): Promise<CoachFocus> {
  return apiPost<CoachFocus>(`${COACH_API}/focuses/${encodeURIComponent(focusId)}/pause`, {});
}

export async function createCoachReflection(
  focusId: string,
  req: CoachWeeklyReflectionCreateRequest
): Promise<CoachWeeklyReflection> {
  return apiPost<CoachWeeklyReflection>(
    `${COACH_API}/focuses/${encodeURIComponent(focusId)}/reflections`,
    req
  );
}

export async function fetchCoachReflectionsByFocus(
  focusId: string
): Promise<CoachWeeklyReflection[]> {
  return apiGet<CoachWeeklyReflection[]>(
    `${COACH_API}/focuses/${encodeURIComponent(focusId)}/reflections`
  );
}

export async function fetchCoachReflectionDetail(
  reflectionId: string
): Promise<CoachWeeklyReflection> {
  return apiGet<CoachWeeklyReflection>(
    `${COACH_API}/reflections/${encodeURIComponent(reflectionId)}`
  );
}

export async function updateCoachReflection(
  reflectionId: string,
  req: CoachWeeklyReflectionUpdateRequest
): Promise<CoachWeeklyReflection> {
  return apiPatch<CoachWeeklyReflection>(
    `${COACH_API}/reflections/${encodeURIComponent(reflectionId)}`,
    req
  );
}

export async function fetchCoachThreadEvents(
  goalId: string,
  limit: number = 50,
  offset: number = 0
): Promise<CoachThreadResponse> {
  return apiGet<CoachThreadResponse>(
    withQuery(`${COACH_API}/goals/${encodeURIComponent(goalId)}/thread`, {
      limit,
      offset,
    })
  );
}
