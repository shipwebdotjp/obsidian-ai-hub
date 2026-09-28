export type CoachGoalStatus = "active" | "paused" | "ended";
export type CoachFocusStatus = "candidate" | "active" | "paused";
export type CoachDecisionType = "continue" | "narrow" | "change" | "pause";

export interface CoachFocus {
  focus_id: string;
  goal_id: string;
  name: string;
  status: CoachFocusStatus;
  created_at: string;
  updated_at: string;
}

export interface CoachGoal {
  goal_id: string;
  statement: string;
  reason: string;
  status: CoachGoalStatus;
  created_at: string;
  updated_at: string;
  active_focus?: CoachFocus | null;
}

export interface CoachGoalDetail extends CoachGoal {
  focuses: CoachFocus[];
}

export interface CoachGoalCreateRequest {
  statement: string;
  reason: string;
  initial_focuses: string[];
}

export interface CoachGoalUpdateRequest {
  statement?: string;
  reason?: string;
}

export interface CoachFocusCreateRequest {
  name: string;
}

export interface CoachFocusUpdateRequest {
  name: string;
}

export interface CoachWeeklyReflection {
  reflection_id: string;
  focus_id: string;
  iso_week_monday: string;
  worked_well?: string | null;
  difficult_reason?: string | null;
  learnings?: string | null;
  next_week_scope?: string | null;
  decision_type: CoachDecisionType;
  target_focus_id?: string | null;
  created_at: string;
  updated_at: string;
  focus_name?: string | null;
  target_focus_name?: string | null;
}

export interface CoachWeeklyReflectionCreateRequest {
  focus_id: string;
  iso_week_monday: string;
  worked_well?: string;
  difficult_reason?: string;
  learnings?: string;
  next_week_scope?: string;
  decision_type: CoachDecisionType;
  target_focus_id?: string;
}

export interface CoachWeeklyReflectionUpdateRequest {
  worked_well?: string;
  difficult_reason?: string;
  learnings?: string;
  next_week_scope?: string;
}

export interface CoachThreadEvent {
  event_id: string;
  goal_id: string;
  focus_id?: string | null;
  reflection_id?: string | null;
  event_type: string;
  payload: Record<string, any>;
  created_at: string;
}

export interface CoachThreadResponse {
  items: CoachThreadEvent[];
  total: number;
}
