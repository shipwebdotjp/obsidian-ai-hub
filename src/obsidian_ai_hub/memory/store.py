from __future__ import annotations

import json
import logging
import sqlite3
from typing import Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.memory.models import (
    EVENT_COLUMNS,
    MEMORY_COLUMNS,
    deserialize_event,
    deserialize_memory,
    generate_event_id,
    get_current_timestamp,
    serialize_event,
    serialize_memory,
)

logger = logging.getLogger(__name__)


def load_all_memories() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories")
            rows = cursor.fetchall()
            return [deserialize_memory(dict(row)) for row in rows]
    finally:
        conn.close()


def save_all_memories(memories: list[dict]):
    """Replace the memories table with the provided list using upsert semantics.

    The full-table delete-and-insert approach causes FOREIGN KEY constraint
    failures once `memory_events` rows exist for the memories being kept. We
    instead insert/update the new rows and remove the surplus rows after
    detaching their event log so the cascade is safe.
    """
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            for m in memories:
                db_row = serialize_memory(m)
                columns = ", ".join(MEMORY_COLUMNS)
                placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
                update_clause = ", ".join(
                    f"{col}=excluded.{col}"
                    for col in MEMORY_COLUMNS
                    if col != "memory_id"
                )
                cursor.execute(
                    f"INSERT INTO memories ({columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT(memory_id) DO UPDATE SET {update_clause}",
                    tuple(db_row.get(col) for col in MEMORY_COLUMNS),
                )

            keep_ids = [m.get("memory_id") for m in memories if m.get("memory_id")]
            cursor.execute("SELECT memory_id FROM memories")
            existing_ids = [row["memory_id"] for row in cursor.fetchall()]
            surplus_ids = [eid for eid in existing_ids if eid not in set(keep_ids)]
            if surplus_ids:
                placeholders = ", ".join("?" for _ in surplus_ids)
                # Drop event log for the surplus IDs first so that
                # `DELETE FROM memories` does not violate the FK.
                cursor.execute(
                    f"DELETE FROM memory_events WHERE memory_id IN ({placeholders})",
                    surplus_ids,
                )
                cursor.execute(
                    f"DELETE FROM memories WHERE memory_id IN ({placeholders})",
                    surplus_ids,
                )
    finally:
        conn.close()


def log_memory_event(
    event_type: str,
    memory_id: str,
    previous_status: Optional[str],
    new_status: str,
    changes: Optional[dict] = None,
    reason: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    actor: str = "user",
):
    event_record = {
        "schema_version": 1,
        "event_id": generate_event_id(),
        "occurred_at": get_current_timestamp(),
        "actor": actor,
        "event_type": event_type,
        "memory_id": memory_id,
        "previous_status": previous_status,
        "new_status": new_status,
        "changes": changes or {},
        "reason": reason,
    }
    db_row = serialize_event(event_record)
    columns = ", ".join(EVENT_COLUMNS)
    placeholders = ", ".join("?" for _ in EVENT_COLUMNS)

    sql = f"INSERT INTO memory_events ({columns}) VALUES ({placeholders})"
    values = tuple(db_row.get(col) for col in EVENT_COLUMNS)

    if conn is not None:
        conn.execute(sql, values)
    else:
        c = get_db_connection()
        try:
            with c:
                c.execute(sql, values)
        finally:
            c.close()


def get_memory_events(memory_id: str) -> list:
    """Return event history for a memory_id in chronological order."""
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM memory_events WHERE memory_id = ? ORDER BY occurred_at ASC",
                (memory_id,),
            )
            rows = cursor.fetchall()
            return [deserialize_event(dict(row)) for row in rows]
    finally:
        conn.close()


def _prune_dedup_suggestions(cursor, memory_id: str) -> None:
    cursor.execute(
        "SELECT memory_id, dedup_suggestions FROM memories WHERE dedup_suggestions IS NOT NULL"
    )
    rows = cursor.fetchall()
    for row in rows:
        mid = row["memory_id"]
        raw = row["dedup_suggestions"]
        if raw is None:
            continue
        try:
            suggestions = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(suggestions, list):
            continue
        filtered = [s for s in suggestions if s.get("target_memory_id") != memory_id]
        if len(filtered) != len(suggestions):
            new_val = json.dumps(filtered, ensure_ascii=False) if filtered else None
            cursor.execute(
                "UPDATE memories SET dedup_suggestions = ? WHERE memory_id = ?",
                (new_val, mid),
            )
