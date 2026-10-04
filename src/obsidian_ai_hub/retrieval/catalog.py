"""SQLite ``retrieval_documents`` catalog: the retrieval source of truth.

Every indexed document has one catalog row keyed by
``(source_type, source_id)`` holding the content hash, the embedding model
fingerprint, and the indexed_at timestamp. Search results whose catalog row
is missing, hash-mismatched, or model-mismatched are never returned.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from obsidian_ai_hub.database import get_db_connection

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_entry(
    source_type: str,
    source_id: str,
    conn: sqlite3.Connection | None = None,
) -> dict | None:
    """Return the catalog row for a source, or None when not indexed."""
    own = conn is None
    c = conn if conn is not None else get_db_connection()
    try:
        row = c.execute(
            "SELECT source_type, source_id, content_hash, model, indexed_at "
            "FROM retrieval_documents WHERE source_type = ? AND source_id = ?",
            (source_type, source_id),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        if own:
            c.close()


def list_entries(
    source_type: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    """List catalog rows, optionally filtered by source type."""
    own = conn is None
    c = conn if conn is not None else get_db_connection()
    try:
        if source_type is None:
            rows = c.execute(
                "SELECT source_type, source_id, content_hash, model, indexed_at "
                "FROM retrieval_documents"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT source_type, source_id, content_hash, model, indexed_at "
                "FROM retrieval_documents WHERE source_type = ?",
                (source_type,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            c.close()


def upsert_entry(
    source_type: str,
    source_id: str,
    content_hash: str,
    model: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Insert or replace the catalog row. Must run inside the source DB write."""
    own = conn is None
    c = conn if conn is not None else get_db_connection()
    try:
        if own:
            with c:
                c.execute(
                    "INSERT INTO retrieval_documents "
                    "(source_type, source_id, content_hash, model, indexed_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(source_type, source_id) DO UPDATE SET "
                    "content_hash = excluded.content_hash, "
                    "model = excluded.model, "
                    "indexed_at = excluded.indexed_at",
                    (source_type, source_id, content_hash, model, _now_iso()),
                )
        else:
            c.execute(
                "INSERT INTO retrieval_documents "
                "(source_type, source_id, content_hash, model, indexed_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(source_type, source_id) DO UPDATE SET "
                "content_hash = excluded.content_hash, "
                "model = excluded.model, "
                "indexed_at = excluded.indexed_at",
                (source_type, source_id, content_hash, model, _now_iso()),
            )
    finally:
        if own:
            c.close()


def delete_entry(
    source_type: str,
    source_id: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Remove the catalog row. Must run inside the source DB write."""
    own = conn is None
    c = conn if conn is not None else get_db_connection()
    try:
        if own:
            with c:
                c.execute(
                    "DELETE FROM retrieval_documents "
                    "WHERE source_type = ? AND source_id = ?",
                    (source_type, source_id),
                )
        else:
            c.execute(
                "DELETE FROM retrieval_documents "
                "WHERE source_type = ? AND source_id = ?",
                (source_type, source_id),
            )
    finally:
        if own:
            c.close()
