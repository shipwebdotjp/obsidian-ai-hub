import json
import logging
import sqlite3
import uuid
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from obsidian_ai_hub.memory import get_db_connection

logger = logging.getLogger(__name__)

ACTIVITY_LOGS_COLUMNS = [
    "schema_version",
    "activity_id",
    "activity_date",
    "occurred_at",
    "app_name",
    "window_title",
    "summary",
    "category",
    "keywords",
    "screenshots",
    "source_path",
    "source_line",
]


def generate_activity_id() -> str:
    """Generate a unique ID for an activity log."""
    return f"act_{uuid.uuid4().hex}"


def serialize_activity(activity: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize JSON fields (keywords, screenshots) into string for storage."""
    row = dict(activity)
    for col in ["keywords", "screenshots"]:
        val = row.get(col)
        if val is not None:
            row[col] = json.dumps(val, ensure_ascii=False)
        else:
            row[col] = None
    return row


def deserialize_activity(row: sqlite3.Row) -> Dict[str, Any]:
    """Deserialize SQL row and restore JSON fields (keywords, screenshots) to lists."""
    activity = dict(row)
    for col in ["keywords", "screenshots"]:
        val = activity.get(col)
        if val is not None and isinstance(val, str):
            try:
                activity[col] = json.loads(val)
            except json.JSONDecodeError as e:
                logger.warning(
                    f"Failed to deserialize field '{col}' for activity {activity.get('activity_id')}: {e}"
                )
                activity[col] = []
        elif val is None:
            activity[col] = []
    return activity


def add_activity(
    conn: Optional[sqlite3.Connection] = None,
    activity_id: Optional[str] = None,
    activity_date: Optional[str] = None,
    occurred_at: Optional[str] = None,
    app_name: Optional[str] = None,
    window_title: Optional[str] = None,
    summary: Optional[str] = None,
    category: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    screenshots: Optional[List[str]] = None,
    source_path: Optional[str] = None,
    source_line: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Add a new activity log entry to the database.
    If activity_id is not specified, a new UUID is generated automatically.
    """
    if activity_id is None:
        activity_id = generate_activity_id()

    # Fallbacks for dates
    now = datetime.now()
    if activity_date is None:
        activity_date = now.strftime("%Y-%m-%d")
    if occurred_at is None:
        occurred_at = now.isoformat()

    record = {
        "schema_version": 1,
        "activity_id": activity_id,
        "activity_date": activity_date,
        "occurred_at": occurred_at,
        "app_name": app_name,
        "window_title": window_title,
        "summary": summary,
        "category": category,
        "keywords": keywords or [],
        "screenshots": screenshots or [],
        "source_path": source_path,
        "source_line": source_line,
    }

    db_row = serialize_activity(record)

    columns = ", ".join(ACTIVITY_LOGS_COLUMNS)
    placeholders = ", ".join("?" for _ in ACTIVITY_LOGS_COLUMNS)
    sql = f"INSERT INTO activity_logs ({columns}) VALUES ({placeholders})"
    values = tuple(db_row.get(c) for c in ACTIVITY_LOGS_COLUMNS)

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        if close_conn:
            with conn:
                conn.execute(sql, values)
        else:
            conn.execute(sql, values)
    finally:
        if close_conn:
            conn.close()

    return record


def get_activities_by_date(
    activity_date: str,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """
    Get all activities on the specified date, sorted by occurred_at ascending.
    """
    sql = """
        SELECT * FROM activity_logs
        WHERE activity_date = ?
        ORDER BY occurred_at ASC
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute(sql, (activity_date,))
        rows = cursor.fetchall()
        return [deserialize_activity(row) for row in rows]
    finally:
        if close_conn:
            conn.close()


def get_latest_activity_by_date(
    activity_date: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get the latest activity record on the specified date.
    """
    sql = """
        SELECT * FROM activity_logs
        WHERE activity_date = ?
        ORDER BY occurred_at DESC
        LIMIT 1
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute(sql, (activity_date,))
        row = cursor.fetchone()
        if row is None:
            return None
        return deserialize_activity(row)
    finally:
        if close_conn:
            conn.close()


def get_recent_activities(
    days: int = 30,
    base_date: Optional[date] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """
    Get activities from the last N days (including the base_date), where the summary is not empty.
    Returns activities sorted by activity_date DESC, then occurred_at DESC.
    """
    if base_date is None:
        base_date = date.today()

    start_date = base_date - timedelta(days=days - 1)
    start_date_str = start_date.strftime("%Y-%m-%d")
    base_date_str = base_date.strftime("%Y-%m-%d")

    sql = """
        SELECT * FROM activity_logs
        WHERE activity_date >= ? AND activity_date <= ?
          AND summary IS NOT NULL AND trim(summary) != ''
        ORDER BY activity_date DESC, occurred_at DESC
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute(sql, (start_date_str, base_date_str))
        rows = cursor.fetchall()
        return [deserialize_activity(row) for row in rows]
    finally:
        if close_conn:
            conn.close()
