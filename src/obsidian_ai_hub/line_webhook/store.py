from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from obsidian_ai_hub.database import get_db_connection

logger = logging.getLogger(__name__)


def record_webhook_event(
    dedup_key: str,
    webhook_event_id: Optional[str],
    event_type: Optional[str],
    status: str,
    payload_json: Optional[str],
    received_at: str,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Record a received LINE Webhook event or update delivery_count if deduplicated.

    Returns dict representing the saved or updated event record.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT event_id, delivery_count FROM line_webhook_events WHERE dedup_key = ?",
            (dedup_key,),
        )
        row = cur.fetchone()

        if row:
            event_id = row["event_id"]
            new_count = row["delivery_count"] + 1
            cur.execute(
                """
                UPDATE line_webhook_events
                SET delivery_count = ?, last_received_at = ?
                WHERE event_id = ?
                """,
                (new_count, received_at, event_id),
            )
            conn.commit()
            return {
                "event_id": event_id,
                "dedup_key": dedup_key,
                "delivery_count": new_count,
                "duplicate": True,
            }

        event_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO line_webhook_events (
                event_id, dedup_key, webhook_event_id, event_type, status,
                payload_json, delivery_count, received_at, last_received_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                event_id,
                dedup_key,
                webhook_event_id,
                event_type,
                status,
                payload_json,
                received_at,
                received_at,
            ),
        )
        conn.commit()
        return {
            "event_id": event_id,
            "dedup_key": dedup_key,
            "delivery_count": 1,
            "duplicate": False,
        }
    finally:
        if close_conn:
            conn.close()


def cleanup_old_events(
    days: int = 30,
    conn: Optional[sqlite3.Connection] = None,
    now_dt: Optional[datetime] = None,
) -> int:
    """Delete webhook event records older than specified number of days based on received_at.

    Returns the number of deleted records.
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    if now_dt is None:
        now_dt = datetime.now(timezone.utc)

    from datetime import timedelta

    cutoff_dt = now_dt - timedelta(days=days)
    cutoff_iso = cutoff_dt.isoformat()

    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM line_webhook_events WHERE received_at < ?",
            (cutoff_iso,),
        )
        deleted_count = cur.rowcount
        conn.commit()
        logger.info("Cleaned up %d LINE webhook events older than %s", deleted_count, cutoff_iso)
        return deleted_count
    finally:
        if close_conn:
            conn.close()
