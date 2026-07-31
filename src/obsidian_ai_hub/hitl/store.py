from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from obsidian_ai_hub.database import get_db_connection

logger = logging.getLogger(__name__)

RUN_COLUMNS = [
    "run_id",
    "handler",
    "status",
    "checkpoint",
    "active_question_set_id",
    "lease_owner",
    "lease_expires_at",
    "retry_count",
    "error_message",
    "created_at",
    "updated_at",
    "title",
    "description",
    "display_type",
]

QUESTION_COLUMNS = [
    "question_id",
    "run_id",
    "question_set_id",
    "question_key",
    "status",
    "question_type",
    "display_text",
    "choices",
    "answer",
    "is_required",
    "expires_at",
    "answered_at",
    "created_at",
    "updated_at",
    "sequence",
    "title",
    "prompt",
    "context_json",
]


def generate_question_id() -> str:
    """Generate a unique ID for a question."""
    return f"q_{uuid.uuid4().hex}"


def get_current_iso() -> str:
    """Get the current JST time in ISO-8601 format."""
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).isoformat()


@contextmanager
def auto_connection(conn: Optional[sqlite3.Connection] = None):
    """Context manager to reuse passed connection or open and close a new one."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True
    try:
        yield conn, close_conn
    finally:
        if close_conn:
            conn.close()


def serialize_question(q: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize Python objects/lists/dicts inside a question for DB storage."""
    row = dict(q)
    for col in ["choices", "answer", "context_json"]:
        val = row.get(col)
        if val is not None:
            row[col] = json.dumps(val, ensure_ascii=False)
        else:
            row[col] = None
    return row


def deserialize_question(row: sqlite3.Row) -> Dict[str, Any]:
    """Deserialize SQLite row for a question and restore its JSON fields."""
    q = dict(row)
    for col in ["choices", "answer", "context_json"]:
        val = q.get(col)
        if val is not None and isinstance(val, str):
            q[col] = json.loads(val)
        else:
            q[col] = val
    return q


def get_run(run_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Dict[str, Any]]:
    """Fetch a HITL run by its ID."""
    sql = "SELECT * FROM hitl_runs WHERE run_id = ?"
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(sql, (run_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)


def upsert_run(run: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> None:
    """Insert or update a HITL run."""
    run_id = run["run_id"]
    existing = get_run(run_id, conn)

    now = get_current_iso()
    run_record = dict(run)
    run_record["updated_at"] = now

    if existing is None:
        run_record["created_at"] = run_record.get("created_at") or now
        columns = ", ".join(RUN_COLUMNS)
        placeholders = ", ".join("?" for _ in RUN_COLUMNS)
        sql = f"INSERT INTO hitl_runs ({columns}) VALUES ({placeholders})"
        values = tuple(run_record.get(c) for c in RUN_COLUMNS)
    else:
        run_record["created_at"] = existing["created_at"]
        update_set = ", ".join(f"{c} = ?" for c in RUN_COLUMNS if c != "run_id")
        sql = f"UPDATE hitl_runs SET {update_set} WHERE run_id = ?"
        values = tuple(run_record.get(c) for c in RUN_COLUMNS if c != "run_id") + (run_id,)

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                active_conn.execute(sql, values)
        else:
            active_conn.execute(sql, values)


def list_runs(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[List[Dict[str, Any]], int]:
    """Fetch a paginated list of HITL runs and the total count."""
    sql = "SELECT * FROM hitl_runs"
    count_sql = "SELECT COUNT(*) FROM hitl_runs"
    params = []

    if status:
        sql += " WHERE status = ?"
        count_sql += " WHERE status = ?"
        params.append(status)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    query_params = list(params) + [limit, offset]

    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(count_sql, tuple(params))
        total = cursor.fetchone()[0]

        cursor.execute(sql, tuple(query_params))
        rows = cursor.fetchall()
        return [dict(row) for row in rows], total


def insert_question(q: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> None:
    """Insert a new HITL question."""
    if not q.get("question_id"):
        q = dict(q)
        q["question_id"] = generate_question_id()

    now = get_current_iso()
    q_record = dict(q)
    q_record["created_at"] = q_record.get("created_at") or now
    q_record["updated_at"] = now

    db_row = serialize_question(q_record)

    columns = ", ".join(QUESTION_COLUMNS)
    placeholders = ", ".join("?" for _ in QUESTION_COLUMNS)
    sql = f"INSERT INTO hitl_questions ({columns}) VALUES ({placeholders})"
    values = tuple(db_row.get(c) for c in QUESTION_COLUMNS)

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                active_conn.execute(sql, values)
        else:
            active_conn.execute(sql, values)


def get_question(
    run_id: str, question_set_id: str, question_key: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """Fetch a specific question by run_id, question_set_id, and question_key."""
    sql = "SELECT * FROM hitl_questions WHERE run_id = ? AND question_set_id = ? AND question_key = ?"
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(sql, (run_id, question_set_id, question_key))
        row = cursor.fetchone()
        if row is None:
            return None
        return deserialize_question(row)


def get_questions_by_set(
    run_id: str, question_set_id: str, conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Get all questions in a specific question set for a run."""
    sql = "SELECT * FROM hitl_questions WHERE run_id = ? AND question_set_id = ? ORDER BY sequence ASC, created_at ASC"
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(sql, (run_id, question_set_id))
        rows = cursor.fetchall()
        return [deserialize_question(row) for row in rows]


def get_all_questions_for_run(
    run_id: str, conn: Optional[sqlite3.Connection] = None
) -> List[Dict[str, Any]]:
    """Fetch all questions across all sets for a given run."""
    sql = "SELECT * FROM hitl_questions WHERE run_id = ? ORDER BY question_set_id, created_at ASC"
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(sql, (run_id,))
        rows = cursor.fetchall()
        return [deserialize_question(row) for row in rows]


def update_question_status_and_answer(
    question_id: str, status: str, answer: Any, answered_at: Optional[str] = None, conn: Optional[sqlite3.Connection] = None
) -> None:
    """Update a question's status and answer."""
    now = get_current_iso()
    answered_time = answered_at or now

    q_updates = {
        "status": status,
        "answer": answer,
        "answered_at": answered_time,
        "updated_at": now,
    }
    db_updates = serialize_question(q_updates)

    sql = """
        UPDATE hitl_questions
        SET status = ?, answer = ?, answered_at = ?, updated_at = ?
        WHERE question_id = ?
    """
    values = (
        db_updates["status"],
        db_updates["answer"],
        db_updates["answered_at"],
        db_updates["updated_at"],
        question_id,
    )

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                active_conn.execute(sql, values)
        else:
            active_conn.execute(sql, values)


def update_pending_question_answer(
    question_id: str, answer: Any, answered_at: Optional[str] = None, conn: Optional[sqlite3.Connection] = None
) -> bool:
    """
    Atomically update a pending question to 'answered' with the provided answer.
    Returns True if update succeeded, False if the question was not pending.
    """
    now = get_current_iso()
    answered_time = answered_at or now

    q_updates = {
        "status": "answered",
        "answer": answer,
        "answered_at": answered_time,
        "updated_at": now,
    }
    db_updates = serialize_question(q_updates)

    sql = """
        UPDATE hitl_questions
        SET status = ?, answer = ?, answered_at = ?, updated_at = ?
        WHERE question_id = ? AND status = 'pending'
    """
    values = (
        db_updates["status"],
        db_updates["answer"],
        db_updates["answered_at"],
        db_updates["updated_at"],
        question_id,
    )

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                cursor = active_conn.execute(sql, values)
                return cursor.rowcount > 0
        else:
            cursor = active_conn.execute(sql, values)
            return cursor.rowcount > 0


def bulk_update_questions_status_by_set(
    run_id: str, question_set_id: str, from_status: str, to_status: str, conn: Optional[sqlite3.Connection] = None
) -> None:
    """Update status of all questions in a set that currently match from_status to to_status."""
    now = get_current_iso()
    sql = """
        UPDATE hitl_questions
        SET status = ?, updated_at = ?
        WHERE run_id = ? AND question_set_id = ? AND status = ?
    """
    values = (to_status, now, run_id, question_set_id, from_status)

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                active_conn.execute(sql, values)
        else:
            active_conn.execute(sql, values)
