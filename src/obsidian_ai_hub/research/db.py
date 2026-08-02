from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from contextlib import contextmanager

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.research import feedback
from obsidian_ai_hub.utils.embeddings import cosine_similarity

logger = logging.getLogger(__name__)


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

RESEARCH_THEME_COLUMNS = [
    "schema_version",
    "theme_id",
    "theme",
    "direction",
    "kind",
    "why_now",
    "confidence",
    "normalized_key",
    "status",
    "duplicate_of_theme_id",
    "duplicate_reason",
    "related_theme_ids",
    "created_at",
    "updated_at",
    "reviewed_at",
    "reviewed_by",
    "origin",
    "hitl_run_id",
    "feedback_decision",
    "feedback_reason",
    "feedback_comment",
    "feedback_at",
]

RESEARCH_JOB_COLUMNS = [
    "schema_version",
    "job_id",
    "theme_id",
    "status",
    "generated_title",
    "mode",
    "markdown",
    "error",
    "started_at",
    "finished_at",
    "output_path",
    "is_published",
]

ALLOWED_THEME_STATUS = frozenset({"candidate", "approved", "rejected", "duplicate"})
ALLOWED_JOB_STATUS = frozenset({"pending", "running", "succeeded", "failed"})
ALLOWED_KINDS = frozenset({"deep", "adjacent", "explore"})
ALLOWED_FEEDBACK_DECISIONS = frozenset({"approved", "rejected"})
ALLOWED_FEEDBACK_REASONS = feedback.ALLOWED_FEEDBACK_REASONS


def _get_db():
    return get_db_connection()


def get_current_timestamp() -> str:
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).isoformat(timespec="seconds")


def generate_theme_id() -> str:
    today = date.today().strftime("%Y%m%d")
    rand = uuid.uuid4().hex[:6]
    return f"rth_{today}_{rand}"


def generate_job_id() -> str:
    return f"rjob_{uuid.uuid4().hex[:12]}"


def normalize_theme_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.casefold()
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def serialize_theme(t: dict) -> dict:
    row = dict(t)
    if "related_theme_ids" in row and row["related_theme_ids"] is not None:
        row["related_theme_ids"] = json.dumps(
            row["related_theme_ids"], ensure_ascii=False
        )
    return row


def deserialize_theme(row: dict) -> dict:
    t = dict(row)
    raw = t.get("related_theme_ids")
    if raw is not None and raw != "":
        if isinstance(raw, str):
            try:
                t["related_theme_ids"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                t["related_theme_ids"] = []
        elif isinstance(raw, list):
            pass
        else:
            t["related_theme_ids"] = []
    else:
        t["related_theme_ids"] = []
    return t


def create_theme(
    *,
    theme: str,
    direction: Optional[str] = None,
    kind: Optional[str] = None,
    why_now: Optional[str] = None,
    confidence: float = 0.0,
    status: str = "candidate",
    duplicate_of_theme_id: Optional[str] = None,
    duplicate_reason: Optional[str] = None,
    related_theme_ids: Optional[list[str]] = None,
    origin: Optional[str] = None,
    hitl_run_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    now = get_current_timestamp()
    theme_id = generate_theme_id()
    normalized = normalize_theme_key(theme)
    if kind and kind not in ALLOWED_KINDS:
        kind = "explore"
    if status not in ALLOWED_THEME_STATUS:
        status = "candidate"
    rec = {
        "schema_version": 3,
        "theme_id": theme_id,
        "theme": theme,
        "direction": direction,
        "kind": kind,
        "why_now": why_now,
        "confidence": confidence,
        "normalized_key": normalized,
        "status": status,
        "duplicate_of_theme_id": duplicate_of_theme_id,
        "duplicate_reason": duplicate_reason,
        "related_theme_ids": related_theme_ids or [],
        "created_at": now,
        "updated_at": now,
        "reviewed_at": None,
        "reviewed_by": None,
        "origin": origin,
        "hitl_run_id": hitl_run_id,
        "feedback_decision": None,
        "feedback_reason": None,
        "feedback_comment": None,
        "feedback_at": None,
    }
    db_row = serialize_theme(rec)
    columns = ", ".join(RESEARCH_THEME_COLUMNS)
    placeholders = ", ".join("?" for _ in RESEARCH_THEME_COLUMNS)

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                active_conn.execute(
                    f"INSERT INTO research_themes ({columns}) VALUES ({placeholders})",
                    tuple(db_row.get(c) for c in RESEARCH_THEME_COLUMNS),
                )
        else:
            active_conn.execute(
                f"INSERT INTO research_themes ({columns}) VALUES ({placeholders})",
                tuple(db_row.get(c) for c in RESEARCH_THEME_COLUMNS),
            )
    return rec


def get_theme(theme_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute("SELECT * FROM research_themes WHERE theme_id = ?", (theme_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return deserialize_theme(dict(row))


def list_themes(
    *,
    status: Optional[str] = None,
    job_status: Optional[str] = None,
    q: Optional[str] = None,
) -> list[dict]:
    where_clauses = []
    params: list = []

    if status:
        if status not in ALLOWED_THEME_STATUS:
            return []
        where_clauses.append("rt.status = ?")
        params.append(status)

    if q:
        where_clauses.append(
            "(rt.theme LIKE ? OR rt.direction LIKE ? OR rt.why_now LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT rt.*, rj.job_id AS latest_job_id, rj.status AS job_status,
                   rj.generated_title, rj.mode, rj.error,
                   rj.started_at AS job_started_at, rj.finished_at AS job_finished_at
            FROM research_themes rt
            LEFT JOIN research_jobs rj ON rj.job_id = (
                SELECT rj2.job_id FROM research_jobs rj2
                WHERE rj2.theme_id = rt.theme_id
                ORDER BY rj2.started_at DESC
                LIMIT 1
            )
            {where_sql}
            ORDER BY rt.created_at DESC
        """,
            params,
        )
        rows = [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

    if job_status:
        rows = [r for r in rows if r.get("job_status") == job_status]

    out = []
    for r in rows:
        theme = deserialize_theme(r)
        job = None
        if r.get("latest_job_id"):
            job = {
                "job_id": r["latest_job_id"],
                "status": r["job_status"],
                "generated_title": r["generated_title"],
                "mode": r["mode"],
                "error": r["error"],
                "started_at": r["job_started_at"],
                "finished_at": r["job_finished_at"],
            }
        theme["latest_job"] = job
        out.append(theme)
    return out


def set_status(
    theme_id: str,
    status: str,
    *,
    reviewed_by: str = "user",
    reason: Optional[str] = None,
    duplicate_of: Optional[str] = None,
    related_ids: Optional[list[str]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict]:
    if status not in ALLOWED_THEME_STATUS:
        raise ValueError(f"Invalid status: {status}")
    now = get_current_timestamp()

    def _execute_update(c_conn):
        cursor = c_conn.cursor()
        cursor.execute(
            "SELECT * FROM research_themes WHERE theme_id = ?", (theme_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        t = deserialize_theme(dict(row))
        t["status"] = status
        t["updated_at"] = now
        if status in ("approved", "rejected", "duplicate"):
            t["reviewed_at"] = now
            t["reviewed_by"] = reviewed_by
        if reason:
            t["duplicate_reason"] = reason
        if duplicate_of:
            t["duplicate_of_theme_id"] = duplicate_of
        if related_ids is not None:
            t["related_theme_ids"] = related_ids
        db_row = serialize_theme(t)
        set_clause = ", ".join(
            f"{c} = ?" for c in RESEARCH_THEME_COLUMNS if c != "theme_id"
        )
        values = [
            db_row.get(c) for c in RESEARCH_THEME_COLUMNS if c != "theme_id"
        ] + [theme_id]
        c_conn.execute(
            f"UPDATE research_themes SET {set_clause} WHERE theme_id = ?", values
        )
        return t

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                return _execute_update(active_conn)
        else:
            return _execute_update(active_conn)


def set_theme_feedback(
    theme_id: str,
    *,
    status: str,
    decision: str,
    reason: Optional[str] = None,
    comment: Optional[str] = None,
    reviewed_by: str = "user",
    feedback_at: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict]:
    """Update a theme's status and persist HITL feedback in a single DB operation.

    `decision` is "approved" or "rejected"; `reason` is one of
    ALLOWED_FEEDBACK_REASONS when the theme was rejected. This is only invoked
    for auto-suggestion themes processed through the HITL confirmation.
    """
    if status not in ALLOWED_THEME_STATUS:
        raise ValueError(f"Invalid status: {status}")
    if decision not in ALLOWED_FEEDBACK_DECISIONS:
        raise ValueError(f"Invalid feedback decision: {decision}")
    expected_status = "approved" if decision == "approved" else "rejected"
    if status != expected_status:
        raise ValueError(f"Status {status} does not match decision {decision}")
    if decision == "approved" and reason is not None:
        raise ValueError("Feedback reason is only allowed for rejected themes")
    if reason is not None and reason not in ALLOWED_FEEDBACK_REASONS:
        raise ValueError(f"Invalid feedback reason: {reason}")
    now = get_current_timestamp()
    feedback_at = feedback_at or now

    def _execute_update(c_conn):
        cursor = c_conn.cursor()
        cursor.execute(
            "SELECT * FROM research_themes WHERE theme_id = ?", (theme_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        t = deserialize_theme(dict(row))
        t["status"] = status
        t["updated_at"] = now
        t["reviewed_at"] = now
        t["reviewed_by"] = reviewed_by
        t["feedback_decision"] = decision
        t["feedback_reason"] = reason
        t["feedback_comment"] = comment
        t["feedback_at"] = feedback_at
        db_row = serialize_theme(t)
        set_clause = ", ".join(
            f"{c} = ?" for c in RESEARCH_THEME_COLUMNS if c != "theme_id"
        )
        values = [
            db_row.get(c) for c in RESEARCH_THEME_COLUMNS if c != "theme_id"
        ] + [theme_id]
        c_conn.execute(
            f"UPDATE research_themes SET {set_clause} WHERE theme_id = ?", values
        )
        return t

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                return _execute_update(active_conn)
        else:
            return _execute_update(active_conn)


def list_theme_feedback(
    limit: int = 20,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """Return the most recent themes carrying HITL feedback (newest first)."""
    if limit < 1:
        raise ValueError(f"Invalid limit: {limit}")
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(
            """
            SELECT theme, direction, feedback_decision, feedback_reason,
                   feedback_comment, feedback_at
            FROM research_themes
            WHERE feedback_decision IS NOT NULL AND feedback_decision != ''
            ORDER BY feedback_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def create_job(theme_id: str, conn: Optional[sqlite3.Connection] = None) -> dict:
    now = get_current_timestamp()
    job_id = generate_job_id()
    rec = {
        "schema_version": 1,
        "job_id": job_id,
        "theme_id": theme_id,
        "status": "pending",
        "generated_title": None,
        "mode": None,
        "markdown": None,
        "error": None,
        "started_at": now,
        "finished_at": None,
        "output_path": None,
        "is_published": 0,
    }
    columns = ", ".join(RESEARCH_JOB_COLUMNS)
    placeholders = ", ".join("?" for _ in RESEARCH_JOB_COLUMNS)

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                active_conn.execute(
                    f"INSERT INTO research_jobs ({columns}) VALUES ({placeholders})",
                    tuple(rec.get(c) for c in RESEARCH_JOB_COLUMNS),
                )
        else:
            active_conn.execute(
                f"INSERT INTO research_jobs ({columns}) VALUES ({placeholders})",
                tuple(rec.get(c) for c in RESEARCH_JOB_COLUMNS),
            )
    return rec


def update_job(
    job_id: str,
    *,
    status: Optional[str] = None,
    generated_title: Optional[str] = None,
    mode: Optional[str] = None,
    markdown: Optional[str] = None,
    error: Optional[str] = None,
    finished_at: Optional[str] = None,
    output_path: Optional[str] = None,
    is_published: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict]:
    def _execute_update(c_conn):
        cursor = c_conn.cursor()
        cursor.execute("SELECT * FROM research_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        j = dict(row)
        if status is not None:
            if status not in ALLOWED_JOB_STATUS:
                raise ValueError(f"Invalid job status: {status}")
            j["status"] = status
        if generated_title is not None:
            j["generated_title"] = generated_title
        if mode is not None:
            j["mode"] = mode
        if markdown is not None:
            j["markdown"] = markdown
        if error is not None:
            j["error"] = error
        if finished_at is not None:
            j["finished_at"] = finished_at
        elif status in ("succeeded", "failed"):
            j["finished_at"] = get_current_timestamp()
        if output_path is not None:
            j["output_path"] = output_path
        if is_published is not None:
            j["is_published"] = is_published

        set_clause = ", ".join(
            f"{c} = ?" for c in RESEARCH_JOB_COLUMNS if c != "job_id"
        )
        values = [j.get(c) for c in RESEARCH_JOB_COLUMNS if c != "job_id"] + [
            job_id
        ]
        c_conn.execute(
            f"UPDATE research_jobs SET {set_clause} WHERE job_id = ?", values
        )
        return j

    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                return _execute_update(active_conn)
        else:
            return _execute_update(active_conn)


def latest_job(theme_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(
            "SELECT * FROM research_jobs WHERE theme_id = ? ORDER BY started_at DESC LIMIT 1",
            (theme_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)


def get_job(job_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute("SELECT * FROM research_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)


def find_exact_duplicate(normalized_key: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(
            "SELECT * FROM research_themes WHERE normalized_key = ? LIMIT 1",
            (normalized_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return deserialize_theme(dict(row))


def find_top_similar(theme: str, embedder, k: int = 5, conn: Optional[sqlite3.Connection] = None) -> list[tuple[str, float]]:
    try:
        with auto_connection(conn) as (active_conn, _):
            cursor = active_conn.cursor()
            cursor.execute("SELECT theme_id, theme FROM research_themes")
            rows = cursor.fetchall()

        if not rows:
            return []

        try:
            query_vec = embedder.embed_query(theme)
        except Exception:
            logger.warning("embed_query failed for theme dedup")
            return []

        scored: list[tuple[str, float]] = []
        for r in rows:
            try:
                doc_vec = embedder.embed_query(r["theme"])
            except Exception:
                continue
            sim = cosine_similarity(query_vec, doc_vec)
            if sim >= 0.7:
                scored.append((r["theme_id"], sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]
    except Exception as exc:
        logger.warning("find_top_similar failed: %s", exc)
        return []


def list_recent_activity_days(days: int = 30) -> list[dict]:
    from obsidian_ai_hub.activity.store import get_recent_activities

    try:
        db_activities = get_recent_activities(days=days)
    except Exception as e:
        logger.error(f"Failed to fetch recent activities from SQLite: {e}")
        return []

    # Sort: occurred_at ASC (chronological) first
    db_activities = sorted(db_activities, key=lambda x: x.get("occurred_at") or "")
    # Sort: activity_date DESC (newest first) next.
    # Because python's sort is stable, occurred_at ASC ordering is preserved within each date.
    db_activities = sorted(
        db_activities, key=lambda x: x.get("activity_date") or "", reverse=True
    )

    entries = []
    for e in db_activities:
        summary = e.get("summary") or ""
        if not summary.strip():
            continue
        category = e.get("category") or ""
        keywords = e.get("keywords") or []
        entries.append(
            {
                "activity_date": e.get("activity_date"),
                "summary": summary.strip(),
                "category": category.strip() if isinstance(category, str) else "",
                "keywords": [str(k).strip() for k in keywords if k],
            }
        )

    seen_summaries: set[str] = set()
    deduped: list[dict] = []
    for e in entries:
        key = normalize_theme_key(e["summary"])
        if key in seen_summaries:
            continue
        seen_summaries.add(key)
        deduped.append(e)

    return deduped


def list_approved_themes_by_date(date_str: str) -> list[dict]:
    """指定日（YYYY-MM-DD）に承認されたリサーチテーマを返す。"""
    conn = _get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT theme_id, theme, direction
            FROM research_themes
            WHERE status = 'approved'
              AND substr(reviewed_at, 1, 10) = ?
            ORDER BY reviewed_at ASC
            """,
            (date_str,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def _set_theme_field(theme_id: str, field: str, value: Any, conn: Optional[sqlite3.Connection] = None) -> None:
    """Update a single field on a research theme."""
    if field not in RESEARCH_THEME_COLUMNS:
        raise ValueError(f"Unsupported research theme field: {field}")
    with auto_connection(conn) as (active_conn, is_generated):
        if is_generated:
            with active_conn:
                active_conn.execute(
                    f"UPDATE research_themes SET {field} = ?, updated_at = ? WHERE theme_id = ?",
                    (value, get_current_timestamp(), theme_id)
                )
        else:
            active_conn.execute(
                f"UPDATE research_themes SET {field} = ?, updated_at = ? WHERE theme_id = ?",
                (value, get_current_timestamp(), theme_id)
            )
