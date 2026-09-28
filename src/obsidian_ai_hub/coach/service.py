from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from obsidian_ai_hub.coach.exceptions import (
    CoachDuplicateReflectionError,
    CoachFocusNotFoundError,
    CoachGoalNotFoundError,
    CoachReflectionNotFoundError,
    CoachStateValidationError,
)
from obsidian_ai_hub.coach.store import CoachStore
from obsidian_ai_hub.database import get_db_connection


def get_current_jst_iso_week_monday() -> str:
    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    monday = now_jst.date() - timedelta(days=now_jst.weekday())
    return monday.isoformat()


class CoachService:
    def __init__(self, store: Optional[CoachStore] = None) -> None:
        self.store = store or CoachStore()

    def create_goal(
        self, statement: str, reason: str, initial_focuses: list[str]
    ) -> dict[str, Any]:
        statement = statement.strip()
        reason = reason.strip()
        cleaned_focuses = [f.strip() for f in initial_focuses if f and f.strip()]
        if not statement or not reason:
            raise CoachStateValidationError("Statement and reason must not be blank")
        if not cleaned_focuses:
            raise CoachStateValidationError("At least one initial focus candidate is required")

        conn = get_db_connection()
        now = datetime.now(timezone.utc).isoformat()
        goal_id = f"cgoal_{uuid4().hex[:12]}"

        with conn:
            self.store.create_goal(
                conn,
                goal_id=goal_id,
                statement=statement,
                reason=reason,
                status="active",
                created_at=now,
                updated_at=now,
            )
            event_id = f"cevt_{uuid4().hex[:12]}"
            self.store.create_thread_event(
                conn,
                event_id=event_id,
                goal_id=goal_id,
                focus_id=None,
                reflection_id=None,
                event_type="goal_created",
                payload_json=json.dumps({"goal_statement": statement, "goal_reason": reason}),
                created_at=now,
            )

            focuses = []
            for idx, focus_name in enumerate(cleaned_focuses):
                focus_id = f"cfoc_{uuid4().hex[:12]}"
                status = "active" if idx == 0 else "candidate"
                f_item = self.store.create_focus(
                    conn,
                    focus_id=focus_id,
                    goal_id=goal_id,
                    name=focus_name,
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
                focuses.append(f_item)

                fevt_id = f"cevt_{uuid4().hex[:12]}"
                self.store.create_thread_event(
                    conn,
                    event_id=fevt_id,
                    goal_id=goal_id,
                    focus_id=focus_id,
                    reflection_id=None,
                    event_type="focus_created",
                    payload_json=json.dumps(
                        {
                            "goal_statement": statement,
                            "focus_name": focus_name,
                            "status": status,
                        }
                    ),
                    created_at=now,
                )

        return self.get_goal(goal_id)

    def get_goal(self, goal_id: str) -> dict[str, Any]:
        conn = get_db_connection()
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")

        focuses = self.store.list_focuses_by_goal(conn, goal_id)
        active_focus = self.store.get_active_focus_for_goal(conn, goal_id)

        goal["focuses"] = focuses
        goal["active_focus"] = active_focus
        return goal

    def list_goals(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        conn = get_db_connection()
        goals = self.store.list_goals(conn, status=status)
        result = []
        for g in goals:
            g_id = g["goal_id"]
            g["focuses"] = self.store.list_focuses_by_goal(conn, g_id)
            g["active_focus"] = self.store.get_active_focus_for_goal(conn, g_id)
            result.append(g)
        return result

    def update_goal(
        self, goal_id: str, statement: Optional[str] = None, reason: Optional[str] = None
    ) -> dict[str, Any]:
        conn = get_db_connection()
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")
        if goal["status"] == "ended":
            raise CoachStateValidationError("Ended goal cannot be updated")

        stmt_val = statement.strip() if statement is not None else None
        reason_val = reason.strip() if reason is not None else None
        if statement is not None and not stmt_val:
            raise CoachStateValidationError("Statement must not be blank")
        if reason is not None and not reason_val:
            raise CoachStateValidationError("Reason must not be blank")

        now = datetime.now(timezone.utc).isoformat()
        with conn:
            self.store.update_goal(
                conn,
                goal_id=goal_id,
                statement=stmt_val,
                reason=reason_val,
                updated_at=now,
            )

        return self.get_goal(goal_id)

    def pause_goal(self, goal_id: str) -> dict[str, Any]:
        conn = get_db_connection()
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")
        if goal["status"] == "ended":
            raise CoachStateValidationError("Ended goal cannot be paused")
        if goal["status"] == "paused":
            return self.get_goal(goal_id)

        now = datetime.now(timezone.utc).isoformat()
        with conn:
            self.store.update_goal(conn, goal_id=goal_id, status="paused", updated_at=now)
            event_id = f"cevt_{uuid4().hex[:12]}"
            self.store.create_thread_event(
                conn,
                event_id=event_id,
                goal_id=goal_id,
                focus_id=None,
                reflection_id=None,
                event_type="goal_paused",
                payload_json=json.dumps({"goal_statement": goal["statement"]}),
                created_at=now,
            )

        return self.get_goal(goal_id)

    def resume_goal(self, goal_id: str) -> dict[str, Any]:
        conn = get_db_connection()
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")
        if goal["status"] == "ended":
            raise CoachStateValidationError("Ended goal cannot be resumed")
        if goal["status"] == "active":
            return self.get_goal(goal_id)

        now = datetime.now(timezone.utc).isoformat()
        with conn:
            self.store.update_goal(conn, goal_id=goal_id, status="active", updated_at=now)
            event_id = f"cevt_{uuid4().hex[:12]}"
            self.store.create_thread_event(
                conn,
                event_id=event_id,
                goal_id=goal_id,
                focus_id=None,
                reflection_id=None,
                event_type="goal_resumed",
                payload_json=json.dumps({"goal_statement": goal["statement"]}),
                created_at=now,
            )

        return self.get_goal(goal_id)

    def end_goal(self, goal_id: str) -> dict[str, Any]:
        conn = get_db_connection()
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")
        if goal["status"] == "ended":
            return self.get_goal(goal_id)

        now = datetime.now(timezone.utc).isoformat()
        with conn:
            self.store.update_goal(conn, goal_id=goal_id, status="ended", updated_at=now)
            event_id = f"cevt_{uuid4().hex[:12]}"
            self.store.create_thread_event(
                conn,
                event_id=event_id,
                goal_id=goal_id,
                focus_id=None,
                reflection_id=None,
                event_type="goal_ended",
                payload_json=json.dumps({"goal_statement": goal["statement"]}),
                created_at=now,
            )

        return self.get_goal(goal_id)

    def create_focus(self, goal_id: str, name: str) -> dict[str, Any]:
        name_val = name.strip()
        if not name_val:
            raise CoachStateValidationError("Focus name must not be blank")

        conn = get_db_connection()
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")
        if goal["status"] == "ended":
            raise CoachStateValidationError("Cannot create focus under ended goal")

        focus_id = f"cfoc_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        with conn:
            f_item = self.store.create_focus(
                conn,
                focus_id=focus_id,
                goal_id=goal_id,
                name=name_val,
                status="candidate",
                created_at=now,
                updated_at=now,
            )
            event_id = f"cevt_{uuid4().hex[:12]}"
            self.store.create_thread_event(
                conn,
                event_id=event_id,
                goal_id=goal_id,
                focus_id=focus_id,
                reflection_id=None,
                event_type="focus_created",
                payload_json=json.dumps(
                    {
                        "goal_statement": goal["statement"],
                        "focus_name": name_val,
                        "status": "candidate",
                    }
                ),
                created_at=now,
            )

        return f_item

    def update_focus(self, focus_id: str, name: str) -> dict[str, Any]:
        name_val = name.strip()
        if not name_val:
            raise CoachStateValidationError("Focus name must not be blank")

        conn = get_db_connection()
        focus = self.store.get_focus(conn, focus_id)
        if not focus:
            raise CoachFocusNotFoundError(f"Focus {focus_id} not found")

        goal = self.store.get_goal(conn, focus["goal_id"])
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {focus['goal_id']} not found")
        if goal["status"] == "ended":
            raise CoachStateValidationError("Cannot edit focus on ended goal")

        now = datetime.now(timezone.utc).isoformat()
        with conn:
            self.store.update_focus(conn, focus_id=focus_id, name=name_val, updated_at=now)

        return self.store.get_focus(conn, focus_id)

    def activate_focus(self, focus_id: str) -> dict[str, Any]:
        conn = get_db_connection()
        focus = self.store.get_focus(conn, focus_id)
        if not focus:
            raise CoachFocusNotFoundError(f"Focus {focus_id} not found")

        goal_id = focus["goal_id"]
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")
        if goal["status"] == "ended":
            raise CoachStateValidationError("Cannot activate focus on ended goal")

        if focus["status"] == "active":
            return focus

        now = datetime.now(timezone.utc).isoformat()
        with conn:
            current_active = self.store.get_active_focus_for_goal(conn, goal_id)
            if current_active and current_active["focus_id"] != focus_id:
                self.store.update_focus(
                    conn,
                    focus_id=current_active["focus_id"],
                    status="candidate",
                    updated_at=now,
                )

            self.store.update_focus(
                conn, focus_id=focus_id, status="active", updated_at=now
            )

            event_id = f"cevt_{uuid4().hex[:12]}"
            self.store.create_thread_event(
                conn,
                event_id=event_id,
                goal_id=goal_id,
                focus_id=focus_id,
                reflection_id=None,
                event_type="focus_activated",
                payload_json=json.dumps(
                    {
                        "goal_statement": goal["statement"],
                        "focus_name": focus["name"],
                    }
                ),
                created_at=now,
            )

        return self.store.get_focus(conn, focus_id)

    def pause_focus(self, focus_id: str) -> dict[str, Any]:
        conn = get_db_connection()
        focus = self.store.get_focus(conn, focus_id)
        if not focus:
            raise CoachFocusNotFoundError(f"Focus {focus_id} not found")

        goal_id = focus["goal_id"]
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")
        if goal["status"] == "ended":
            raise CoachStateValidationError("Cannot pause focus on ended goal")

        if focus["status"] == "paused":
            return focus

        now = datetime.now(timezone.utc).isoformat()
        with conn:
            self.store.update_focus(
                conn, focus_id=focus_id, status="paused", updated_at=now
            )

            event_id = f"cevt_{uuid4().hex[:12]}"
            self.store.create_thread_event(
                conn,
                event_id=event_id,
                goal_id=goal_id,
                focus_id=focus_id,
                reflection_id=None,
                event_type="focus_paused",
                payload_json=json.dumps(
                    {
                        "goal_statement": goal["statement"],
                        "focus_name": focus["name"],
                    }
                ),
                created_at=now,
            )

        return self.store.get_focus(conn, focus_id)

    def create_weekly_reflection(
        self,
        focus_id: str,
        iso_week_monday: str,
        worked_well: Optional[str],
        difficult_reason: Optional[str],
        learnings: Optional[str],
        next_week_scope: Optional[str],
        decision_type: str,
        target_focus_id: Optional[str] = None,
    ) -> dict[str, Any]:
        current_monday = get_current_jst_iso_week_monday()
        if iso_week_monday > current_monday:
            raise CoachStateValidationError("Cannot register reflection for future week")

        conn = get_db_connection()
        focus = self.store.get_focus(conn, focus_id)
        if not focus:
            raise CoachFocusNotFoundError(f"Focus {focus_id} not found")

        goal_id = focus["goal_id"]
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")

        if goal["status"] in ("paused", "ended"):
            raise CoachStateValidationError(f"Cannot register reflection on {goal['status']} goal")
        if focus["status"] != "active":
            raise CoachStateValidationError("Cannot register reflection on non-active focus")

        existing = self.store.get_reflection_by_focus_and_week(
            conn, focus_id, iso_week_monday
        )
        if existing:
            raise CoachDuplicateReflectionError("Reflection already exists for this focus and week")

        target_focus = None
        if decision_type == "narrow":
            if not next_week_scope or not next_week_scope.strip():
                raise CoachStateValidationError("next_week_scope is required when decision_type is 'narrow'")
        elif decision_type == "change":
            if not target_focus_id:
                raise CoachStateValidationError("target_focus_id is required when decision_type is 'change'")
            target_focus = self.store.get_focus(conn, target_focus_id)
            if not target_focus or target_focus["goal_id"] != goal_id:
                raise CoachStateValidationError("target_focus_id must belong to the same goal")

        refl_id = f"crefl_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        with conn:
            # Apply focus status transitions according to decision_type
            if decision_type == "change" and target_focus:
                # Current active focus becomes candidate, target candidate becomes active
                self.store.update_focus(
                    conn, focus_id=focus_id, status="candidate", updated_at=now
                )
                self.store.update_focus(
                    conn, focus_id=target_focus_id, status="active", updated_at=now
                )
            elif decision_type == "pause":
                # Current active focus becomes paused
                self.store.update_focus(
                    conn, focus_id=focus_id, status="paused", updated_at=now
                )

            # Create reflection row
            self.store.create_reflection(
                conn,
                reflection_id=refl_id,
                focus_id=focus_id,
                iso_week_monday=iso_week_monday,
                worked_well=worked_well,
                difficult_reason=difficult_reason,
                learnings=learnings,
                next_week_scope=next_week_scope,
                decision_type=decision_type,
                target_focus_id=target_focus_id,
                created_at=now,
                updated_at=now,
            )

            # Build thread event payload with display name snapshots
            payload = {
                "goal_statement": goal["statement"],
                "focus_name": focus["name"],
                "decision_type": decision_type,
                "iso_week_monday": iso_week_monday,
                "worked_well": worked_well,
                "difficult_reason": difficult_reason,
                "learnings": learnings,
                "next_week_scope": next_week_scope,
            }
            if decision_type == "change" and target_focus:
                payload["target_focus_id"] = target_focus_id
                payload["target_focus_name"] = target_focus["name"]

            event_id = f"cevt_{uuid4().hex[:12]}"
            self.store.create_thread_event(
                conn,
                event_id=event_id,
                goal_id=goal_id,
                focus_id=focus_id,
                reflection_id=refl_id,
                event_type="reflection_created",
                payload_json=json.dumps(payload),
                created_at=now,
            )

        return self.store.get_reflection(conn, refl_id)

    def get_reflection(self, reflection_id: str) -> dict[str, Any]:
        conn = get_db_connection()
        refl = self.store.get_reflection(conn, reflection_id)
        if not refl:
            raise CoachReflectionNotFoundError(f"Reflection {reflection_id} not found")
        return refl

    def list_reflections_by_focus(self, focus_id: str) -> list[dict[str, Any]]:
        conn = get_db_connection()
        focus = self.store.get_focus(conn, focus_id)
        if not focus:
            raise CoachFocusNotFoundError(f"Focus {focus_id} not found")
        return self.store.list_reflections_by_focus(conn, focus_id)

    def update_reflection(
        self,
        reflection_id: str,
        worked_well: Optional[str] = None,
        difficult_reason: Optional[str] = None,
        learnings: Optional[str] = None,
        next_week_scope: Optional[str] = None,
    ) -> dict[str, Any]:
        conn = get_db_connection()
        refl = self.store.get_reflection(conn, reflection_id)
        if not refl:
            raise CoachReflectionNotFoundError(f"Reflection {reflection_id} not found")

        focus = self.store.get_focus(conn, refl["focus_id"])
        if focus:
            goal = self.store.get_goal(conn, focus["goal_id"])
            if goal and goal["status"] == "ended":
                raise CoachStateValidationError("Ended goal reflections cannot be edited")

        now = datetime.now(timezone.utc).isoformat()
        with conn:
            self.store.update_reflection(
                conn,
                reflection_id=reflection_id,
                worked_well=worked_well,
                difficult_reason=difficult_reason,
                learnings=learnings,
                next_week_scope=next_week_scope,
                updated_at=now,
            )

        return self.store.get_reflection(conn, reflection_id)

    def list_thread_events(
        self, goal_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        conn = get_db_connection()
        goal = self.store.get_goal(conn, goal_id)
        if not goal:
            raise CoachGoalNotFoundError(f"Goal {goal_id} not found")
        return self.store.list_thread_events_by_goal(conn, goal_id, limit=limit, offset=offset)
