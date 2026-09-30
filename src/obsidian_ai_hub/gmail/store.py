from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from obsidian_ai_hub.database import get_db_connection


class DraftRequestExistsError(Exception):
    """Raised when an identical request already succeeded or failed unexpectedly."""
    pass


def get_draft_request(request_key: str, conn: sqlite3.Connection | None = None) -> dict[str, str | None] | None:
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT request_key, input_sha256, status, gmail_draft_id, gmail_message_id, gmail_thread_id, created_at, updated_at
            FROM gmail_draft_requests
            WHERE request_key = ?
            """,
            (request_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "request_key": row["request_key"],
            "input_sha256": row["input_sha256"],
            "status": row["status"],
            "gmail_draft_id": row["gmail_draft_id"],
            "gmail_message_id": row["gmail_message_id"],
            "gmail_thread_id": row["gmail_thread_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        if close_conn:
            conn.close()


def mark_draft_request_creating(
    request_key: str,
    input_sha256: str,
    conn: sqlite3.Connection | None = None,
) -> dict[str, str | None] | None:
    """Persist status 'creating' before making Gmail API call.

    Attempts atomic INSERT with ON CONFLICT(request_key) DO NOTHING first.
    If rowcount is 0, re-reads existing record:
    - If status == 'created', return existing record (caller reuses stored receipt without API call).
    - If status in ('creating', 'unknown'), raise RuntimeError blocking automatic retry.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    now = datetime.now(timezone.utc).isoformat()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO gmail_draft_requests (
                request_key, input_sha256, status, created_at, updated_at
            ) VALUES (?, ?, 'creating', ?, ?)
            ON CONFLICT(request_key) DO NOTHING
            """,
            (request_key, input_sha256, now, now),
        )
        if cur.rowcount == 0:
            existing = get_draft_request(request_key, conn=conn)
            if existing:
                if existing["status"] == "created":
                    return existing
                raise RuntimeError(
                    f"Draft request '{request_key}' is in status '{existing['status']}'. "
                    "Automatic retry blocked to prevent duplicate drafts in Gmail. "
                    "Please inspect Gmail Drafts before resubmitting."
                )
        conn.commit()
        return None
    finally:
        if close_conn:
            conn.close()


def delete_draft_request(
    request_key: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Remove draft request row on pre-dispatch validation or auth failures."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM gmail_draft_requests WHERE request_key = ?", (request_key,))
        conn.commit()
    finally:
        if close_conn:
            conn.close()


def mark_draft_request_created(
    request_key: str,
    gmail_draft_id: str,
    gmail_message_id: str,
    gmail_thread_id: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Update status to 'created' after Gmail receipt is received."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    now = datetime.now(timezone.utc).isoformat()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE gmail_draft_requests
            SET status = 'created',
                gmail_draft_id = ?,
                gmail_message_id = ?,
                gmail_thread_id = ?,
                updated_at = ?
            WHERE request_key = ?
            """,
            (gmail_draft_id, gmail_message_id, gmail_thread_id, now, request_key),
        )
        conn.commit()
    finally:
        if close_conn:
            conn.close()


def mark_draft_request_unknown(
    request_key: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Mark status as 'unknown' when Gmail call outcome is uncertain (crash or transport error)."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    now = datetime.now(timezone.utc).isoformat()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE gmail_draft_requests
            SET status = 'unknown',
                updated_at = ?
            WHERE request_key = ?
            """,
            (now, request_key),
        )
        conn.commit()
    finally:
        if close_conn:
            conn.close()
