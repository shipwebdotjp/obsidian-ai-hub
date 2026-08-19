from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from obsidian_ai_hub.database import get_db_connection

ALLOWED_PROPOSAL_STATUS = frozenset({"proposed", "promoted", "rejected", "expired"})
ALLOWED_KINDS = frozenset({"calendar", "reminder"})

JST = timezone(timedelta(hours=9))


class DuplicateActiveProposalError(ValueError):
    """Raised when an active proposal with the same fingerprint already exists."""


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


def get_current_timestamp() -> str:
    """Return the current JST time in ISO-8601 format with second precision."""
    return datetime.now(JST).isoformat(timespec="seconds")


def generate_proposal_id() -> str:
    return f"pp_{uuid.uuid4().hex[:12]}"


def normalize_proposal_title(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.casefold()
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def compute_fingerprint(kind: str, title: str, anchor: Optional[str] = None) -> str:
    """Compute the active-duplicate fingerprint for a proposal.

    The anchor is the date the proposal is tied to (start_time for calendar,
    due_date for reminder). A proposal keeps its fingerprint across edits; a
    rejected/expired proposal releases its fingerprint for future reuse.
    """
    identity = "\x00".join([kind, normalize_proposal_title(title), anchor or ""])
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]


def _validate_proposal_fields(*, kind: str, title: str, rationale: Optional[str] = None) -> None:
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"Invalid proposal kind: {kind}")
    if not title or not title.strip():
        raise ValueError("Proposal title is required")
    if rationale is not None and not rationale.strip():
        raise ValueError("Proposal rationale is required")


def create_proposal(
    *,
    kind: str,
    title: str,
    rationale: Optional[str] = None,
    generation_source: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    due_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Create a new AI proposal in status 'proposed'.

    Raises ValueError for invalid fields and DuplicateActiveProposalError when
    an active proposal with the same fingerprint already exists.
    """
    _validate_proposal_fields(kind=kind, title=title, rationale=rationale)
    if not rationale:
        raise ValueError("Proposal rationale is required")

    anchor = start_time if kind == "calendar" else due_date
    fingerprint = compute_fingerprint(kind, title, anchor)

    proposal_id = generate_proposal_id()
    now = get_current_timestamp()

    with auto_connection(conn) as (active_conn, _):
        active_conn.execute("BEGIN IMMEDIATE")
        try:
            existing = find_active_by_fingerprint(fingerprint, conn=active_conn)
            if existing is not None:
                raise DuplicateActiveProposalError(
                    f"An active proposal with the same fingerprint already exists: {existing['proposal_id']}"
                )
            active_conn.execute(
                """
                INSERT INTO planner_proposals (
                    proposal_id, kind, title, start_time, end_time, location, due_date,
                    rationale, generation_source, status, fingerprint,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?)
                """,
                (
                    proposal_id,
                    kind,
                    title.strip(),
                    start_time,
                    end_time,
                    location,
                    due_date,
                    rationale.strip(),
                    generation_source,
                    fingerprint,
                    now,
                    now,
                ),
            )
            active_conn.commit()
        except sqlite3.IntegrityError:
            active_conn.rollback()
            raise DuplicateActiveProposalError(
                "An active proposal with the same fingerprint already exists"
            )
        except Exception:
            active_conn.rollback()
            raise

    return get_proposal(proposal_id, conn=conn)


def get_proposal(proposal_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    """Fetch a single proposal by its ID, or None if it does not exist."""
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(
            "SELECT * FROM planner_proposals WHERE proposal_id = ?",
            (proposal_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None


def find_active_by_fingerprint(
    fingerprint: str, conn: Optional[sqlite3.Connection] = None
) -> Optional[dict]:
    """Return an active (proposed/promoted) proposal matching the fingerprint."""
    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(
            "SELECT * FROM planner_proposals "
            "WHERE fingerprint = ? AND status IN ('proposed', 'promoted') LIMIT 1",
            (fingerprint,),
        )
        row = cursor.fetchone()
        return dict(row) if row is not None else None


def list_proposals(
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    limit: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[dict]:
    """List proposals, newest first. Optional status/kind filters."""
    if status is not None and status not in ALLOWED_PROPOSAL_STATUS:
        raise ValueError(f"Invalid proposal status: {status}")
    if kind is not None and kind not in ALLOWED_KINDS:
        raise ValueError(f"Invalid proposal kind: {kind}")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    sql = "SELECT * FROM planner_proposals"
    clauses = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, proposal_id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def update_proposal_fields(
    proposal_id: str,
    *,
    kind: Optional[str] = None,
    title: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    due_date: Optional[str] = None,
    rationale: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Update the editable fields of a proposal in status 'proposed'.

    Editing recomputes the fingerprint and refuses an active-fingerprint
    conflict. Raises ValueError when the proposal is not editable or fields are
    invalid, and DuplicateActiveProposalError on fingerprint conflict.
    """
    proposal = get_proposal(proposal_id, conn=conn)
    if proposal is None:
        raise ValueError(f"Proposal not found: {proposal_id}")
    if proposal["status"] != "proposed":
        raise ValueError("Only proposed proposals can be edited")

    new_kind = kind if kind is not None else proposal["kind"]
    new_title = title if title is not None else proposal["title"]
    new_start_time = start_time if start_time is not None else proposal["start_time"]
    new_end_time = end_time if end_time is not None else proposal["end_time"]
    new_location = location if location is not None else proposal["location"]
    new_due_date = due_date if due_date is not None else proposal["due_date"]
    new_rationale = rationale if rationale is not None else proposal["rationale"]

    _validate_proposal_fields(kind=new_kind, title=new_title, rationale=new_rationale)

    new_anchor = new_start_time if new_kind == "calendar" else new_due_date
    new_fingerprint = compute_fingerprint(new_kind, new_title, new_anchor)

    with auto_connection(conn) as (active_conn, _):
        active_conn.execute("BEGIN IMMEDIATE")
        try:
            conflicting = find_active_by_fingerprint(new_fingerprint, conn=active_conn)
            if conflicting is not None and conflicting["proposal_id"] != proposal_id:
                raise DuplicateActiveProposalError(
                    f"An active proposal with the same fingerprint already exists: {conflicting['proposal_id']}"
                )
            active_conn.execute(
                """
                UPDATE planner_proposals
                SET kind = ?, title = ?, start_time = ?, end_time = ?,
                    location = ?, due_date = ?, rationale = ?, fingerprint = ?,
                    updated_at = ?
                WHERE proposal_id = ?
                """,
                (
                    new_kind,
                    new_title.strip(),
                    new_start_time,
                    new_end_time,
                    new_location,
                    new_due_date,
                    new_rationale.strip(),
                    new_fingerprint,
                    get_current_timestamp(),
                    proposal_id,
                ),
            )
            active_conn.commit()
        except sqlite3.IntegrityError:
            active_conn.rollback()
            raise DuplicateActiveProposalError(
                "An active proposal with the same fingerprint already exists"
            )
        except Exception:
            active_conn.rollback()
            raise

    return get_proposal(proposal_id, conn=conn)


def transition_status(
    proposal_id: str,
    *,
    to_status: str,
    external_result: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """Atomically transition a proposal from 'proposed' to a terminal status.

    Only proposed -> promoted | rejected | expired is allowed. Returns False
    when the current status was not 'proposed' (e.g. already promoted).
    """
    if to_status not in ALLOWED_PROPOSAL_STATUS:
        raise ValueError(f"Invalid proposal status: {to_status}")
    if to_status == "proposed":
        raise ValueError("Cannot transition to proposed")

    timestamp_col = {
        "promoted": "promoted_at",
        "rejected": "rejected_at",
        "expired": "expired_at",
    }.get(to_status)
    now = get_current_timestamp()

    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        if timestamp_col is not None:
            cursor.execute(
                f"""
                UPDATE planner_proposals
                SET status = ?, {timestamp_col} = ?, updated_at = ?,
                    external_result = COALESCE(?, external_result)
                WHERE proposal_id = ? AND status = 'proposed'
                """,
                (to_status, now, now, external_result, proposal_id),
            )
        else:
            cursor.execute(
                """
                UPDATE planner_proposals
                SET status = ?, updated_at = ?
                WHERE proposal_id = ? AND status = 'proposed'
                """,
                (to_status, now, proposal_id),
            )
        changed = cursor.rowcount > 0
        active_conn.commit()
    return changed


def cleanup_expired_proposals(
    days: int = 7,
    conn: Optional[sqlite3.Connection] = None,
    now_dt: Optional[datetime] = None,
) -> int:
    """Mark proposals older than 'days' days as expired.

    Only 'proposed' proposals are expired; history is preserved. Returns the
    number of proposals expired.
    """
    if days < 0:
        raise ValueError("days must be non-negative")
    if now_dt is None:
        now_dt = datetime.now(JST)
    elif now_dt.tzinfo is not None:
        now_dt = now_dt.astimezone(JST)
    now = now_dt.isoformat(timespec="seconds")
    cutoff_iso = (now_dt - timedelta(days=days)).isoformat(timespec="seconds")

    with auto_connection(conn) as (active_conn, _):
        cursor = active_conn.cursor()
        cursor.execute(
            """
            UPDATE planner_proposals
            SET status = 'expired', expired_at = ?, updated_at = ?
            WHERE status = 'proposed' AND created_at < ?
            """,
            (now, now, cutoff_iso),
        )
        changed = cursor.rowcount
        active_conn.commit()
    return changed
