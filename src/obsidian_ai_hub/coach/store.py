from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from obsidian_ai_hub.database import get_db_connection


class CoachStore:
    def __init__(self, conn: Optional[sqlite3.Connection] = None) -> None:
        self._external_conn = conn

    def _get_conn(self) -> sqlite3.Connection:
        if self._external_conn is not None:
            return self._external_conn
        return get_db_connection()

    # --- Goals ---

    def create_goal(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
        statement: str,
        reason: str,
        status: str,
        created_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO coach_goals (goal_id, statement, reason, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (goal_id, statement, reason, status, created_at, updated_at),
        )
        return {
            "goal_id": goal_id,
            "statement": statement,
            "reason": reason,
            "status": status,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def get_goal(self, conn: sqlite3.Connection, goal_id: str) -> Optional[dict[str, Any]]:
        row = conn.execute(
            "SELECT goal_id, statement, reason, status, created_at, updated_at FROM coach_goals WHERE goal_id = ?",
            (goal_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def list_goals(
        self, conn: sqlite3.Connection, status: Optional[str] = None
    ) -> list[dict[str, Any]]:
        if status:
            rows = conn.execute(
                "SELECT goal_id, statement, reason, status, created_at, updated_at "
                "FROM coach_goals WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT goal_id, statement, reason, status, created_at, updated_at "
                "FROM coach_goals ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_goal(
        self,
        conn: sqlite3.Connection,
        goal_id: str,
        statement: Optional[str] = None,
        reason: Optional[str] = None,
        status: Optional[str] = None,
        updated_at: Optional[str] = None,
    ) -> None:
        fields = []
        params = []
        if statement is not None:
            fields.append("statement = ?")
            params.append(statement)
        if reason is not None:
            fields.append("reason = ?")
            params.append(reason)
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if updated_at is not None:
            fields.append("updated_at = ?")
            params.append(updated_at)

        if not fields:
            return

        params.append(goal_id)
        sql = f"UPDATE coach_goals SET {', '.join(fields)} WHERE goal_id = ?"
        conn.execute(sql, params)

    # --- Focuses ---

    def create_focus(
        self,
        conn: sqlite3.Connection,
        focus_id: str,
        goal_id: str,
        name: str,
        status: str,
        created_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO coach_focuses (focus_id, goal_id, name, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (focus_id, goal_id, name, status, created_at, updated_at),
        )
        return {
            "focus_id": focus_id,
            "goal_id": goal_id,
            "name": name,
            "status": status,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def get_focus(self, conn: sqlite3.Connection, focus_id: str) -> Optional[dict[str, Any]]:
        row = conn.execute(
            "SELECT focus_id, goal_id, name, status, created_at, updated_at FROM coach_focuses WHERE focus_id = ?",
            (focus_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def list_focuses_by_goal(
        self, conn: sqlite3.Connection, goal_id: str
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT focus_id, goal_id, name, status, created_at, updated_at "
            "FROM coach_focuses WHERE goal_id = ? ORDER BY created_at ASC",
            (goal_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_active_focus_for_goal(
        self, conn: sqlite3.Connection, goal_id: str
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            "SELECT focus_id, goal_id, name, status, created_at, updated_at "
            "FROM coach_focuses WHERE goal_id = ? AND status = 'active'",
            (goal_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def update_focus(
        self,
        conn: sqlite3.Connection,
        focus_id: str,
        name: Optional[str] = None,
        status: Optional[str] = None,
        updated_at: Optional[str] = None,
    ) -> None:
        fields = []
        params = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if updated_at is not None:
            fields.append("updated_at = ?")
            params.append(updated_at)

        if not fields:
            return

        params.append(focus_id)
        sql = f"UPDATE coach_focuses SET {', '.join(fields)} WHERE focus_id = ?"
        conn.execute(sql, params)

    # --- Reflections ---

    def create_reflection(
        self,
        conn: sqlite3.Connection,
        reflection_id: str,
        focus_id: str,
        iso_week_monday: str,
        worked_well: Optional[str],
        difficult_reason: Optional[str],
        learnings: Optional[str],
        next_week_scope: Optional[str],
        decision_type: str,
        target_focus_id: Optional[str],
        created_at: str,
        updated_at: str,
    ) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO coach_weekly_reflections (
                reflection_id, focus_id, iso_week_monday, worked_well, difficult_reason,
                learnings, next_week_scope, decision_type, target_focus_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reflection_id,
                focus_id,
                iso_week_monday,
                worked_well,
                difficult_reason,
                learnings,
                next_week_scope,
                decision_type,
                target_focus_id,
                created_at,
                updated_at,
            ),
        )
        return {
            "reflection_id": reflection_id,
            "focus_id": focus_id,
            "iso_week_monday": iso_week_monday,
            "worked_well": worked_well,
            "difficult_reason": difficult_reason,
            "learnings": learnings,
            "next_week_scope": next_week_scope,
            "decision_type": decision_type,
            "target_focus_id": target_focus_id,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def get_reflection(
        self, conn: sqlite3.Connection, reflection_id: str
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            """
            SELECT r.reflection_id, r.focus_id, r.iso_week_monday, r.worked_well,
                   r.difficult_reason, r.learnings, r.next_week_scope, r.decision_type,
                   r.target_focus_id, r.created_at, r.updated_at,
                   f.name AS focus_name, tf.name AS target_focus_name
            FROM coach_weekly_reflections r
            JOIN coach_focuses f ON r.focus_id = f.focus_id
            LEFT JOIN coach_focuses tf ON r.target_focus_id = tf.focus_id
            WHERE r.reflection_id = ?
            """,
            (reflection_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def get_reflection_by_focus_and_week(
        self, conn: sqlite3.Connection, focus_id: str, iso_week_monday: str
    ) -> Optional[dict[str, Any]]:
        row = conn.execute(
            """
            SELECT r.reflection_id, r.focus_id, r.iso_week_monday, r.worked_well,
                   r.difficult_reason, r.learnings, r.next_week_scope, r.decision_type,
                   r.target_focus_id, r.created_at, r.updated_at,
                   f.name AS focus_name, tf.name AS target_focus_name
            FROM coach_weekly_reflections r
            JOIN coach_focuses f ON r.focus_id = f.focus_id
            LEFT JOIN coach_focuses tf ON r.target_focus_id = tf.focus_id
            WHERE r.focus_id = ? AND r.iso_week_monday = ?
            """,
            (focus_id, iso_week_monday),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def list_reflections_by_focus(
        self, conn: sqlite3.Connection, focus_id: str
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT r.reflection_id, r.focus_id, r.iso_week_monday, r.worked_well,
                   r.difficult_reason, r.learnings, r.next_week_scope, r.decision_type,
                   r.target_focus_id, r.created_at, r.updated_at,
                   f.name AS focus_name, tf.name AS target_focus_name
            FROM coach_weekly_reflections r
            JOIN coach_focuses f ON r.focus_id = f.focus_id
            LEFT JOIN coach_focuses tf ON r.target_focus_id = tf.focus_id
            WHERE r.focus_id = ?
            ORDER BY r.iso_week_monday DESC
            """,
            (focus_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_reflection(
        self,
        conn: sqlite3.Connection,
        reflection_id: str,
        worked_well: Optional[str] = None,
        difficult_reason: Optional[str] = None,
        learnings: Optional[str] = None,
        next_week_scope: Optional[str] = None,
        updated_at: Optional[str] = None,
    ) -> None:
        fields = []
        params = []
        if worked_well is not None:
            fields.append("worked_well = ?")
            params.append(worked_well)
        if difficult_reason is not None:
            fields.append("difficult_reason = ?")
            params.append(difficult_reason)
        if learnings is not None:
            fields.append("learnings = ?")
            params.append(learnings)
        if next_week_scope is not None:
            fields.append("next_week_scope = ?")
            params.append(next_week_scope)
        if updated_at is not None:
            fields.append("updated_at = ?")
            params.append(updated_at)

        if not fields:
            return

        params.append(reflection_id)
        sql = f"UPDATE coach_weekly_reflections SET {', '.join(fields)} WHERE reflection_id = ?"
        conn.execute(sql, params)

    # --- Thread Events ---

    def create_thread_event(
        self,
        conn: sqlite3.Connection,
        event_id: str,
        goal_id: str,
        focus_id: Optional[str],
        reflection_id: Optional[str],
        event_type: str,
        payload_json: str,
        created_at: str,
    ) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO coach_thread_events (
                event_id, goal_id, focus_id, reflection_id, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, goal_id, focus_id, reflection_id, event_type, payload_json, created_at),
        )
        return {
            "event_id": event_id,
            "goal_id": goal_id,
            "focus_id": focus_id,
            "reflection_id": reflection_id,
            "event_type": event_type,
            "payload_json": payload_json,
            "created_at": created_at,
        }

    def list_thread_events_by_goal(
        self, conn: sqlite3.Connection, goal_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        total_row = conn.execute(
            "SELECT COUNT(*) FROM coach_thread_events WHERE goal_id = ?", (goal_id,)
        ).fetchone()
        total = total_row[0] if total_row else 0

        rows = conn.execute(
            """
            SELECT event_id, goal_id, focus_id, reflection_id, event_type, payload_json, created_at
            FROM coach_thread_events
            WHERE goal_id = ?
            ORDER BY created_at DESC, event_id DESC
            LIMIT ? OFFSET ?
            """,
            (goal_id, limit, offset),
        ).fetchall()

        events = []
        for r in rows:
            item = dict(r)
            try:
                item["payload"] = json.loads(item["payload_json"])
            except Exception:
                item["payload"] = {}
            events.append(item)

        return events, total
