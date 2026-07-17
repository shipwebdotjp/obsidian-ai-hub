import json
import logging
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from obsidian_ai_hub.memory import get_db_connection
from obsidian_ai_hub.utils.topics import TOPIC_ENUM, normalize_topics

logger = logging.getLogger(__name__)

SUMMARY_COLUMNS = [
    "schema_version",
    "summary_id",
    "period_type",
    "period_key",
    "period_start",
    "period_end",
    "generated_at",
    "summary",
    "keywords",
    "mood",
    "sleep_raw",
    "sleep_hours",
]

SUMMARY_ITEM_COLUMNS = [
    "summary_item_id",
    "summary_id",
    "kind",
    "body",
    "display_order",
]

DAY_ITEM_KINDS = ["highlights", "activities", "learnings", "reflections", "gratitude"]
WEEK_ITEM_KINDS = ["highlights", "progress", "learnings", "reflections", "patterns", "gratitude"]
MONTH_ITEM_KINDS = ["highlights", "progress", "changes", "learnings", "reflections", "patterns", "gratitude"]

ALLOWED_PERIOD_TYPES = {"day", "week", "month"}


def generate_summary_id() -> str:
    """Generate a unique ID for a summary record."""
    return f"sum_{uuid.uuid4().hex}"


def normalize_entity_name(name: str) -> str:
    """Unicode-normalize, trim, and casefold an entity name for deduplication."""
    if not isinstance(name, str):
        name = str(name)
    return unicodedata.normalize("NFKC", name).strip().casefold()


def parse_sleep_hours(sleep_raw: Optional[str]) -> Optional[float]:
    """
    Parse a free-form sleep string into hours.
    Returns None if the value cannot be interpreted as a number of hours.
    """
    if sleep_raw is None:
        return None
    raw = unicodedata.normalize("NFKC", str(sleep_raw)).strip()
    if not raw:
        return None

    # Japanese: "7時間", "7時間30分"
    match = re.search(r"(\d+(?:\.\d+)?)\s*時間(?:\s*(\d+)\s*分?)?", raw)
    if match:
        hours = float(match.group(1))
        minutes = match.group(2)
        if minutes:
            hours += float(minutes) / 60.0
        return round(hours, 2)

    # English-ish: "7h", "7h30m", "7.5h"
    match = re.search(r"(\d+(?:\.\d+)?)\s*h(?:\s*(\d+)\s*m?)?", raw, re.IGNORECASE)
    if match:
        hours = float(match.group(1))
        minutes = match.group(2)
        if minutes:
            hours += float(minutes) / 60.0
        return round(hours, 2)

    # Bare number: "7", "7.5"
    match = re.search(r"^(\d+(?:\.\d+)?)$", raw)
    if match:
        return round(float(match.group(1)), 2)

    return None


def serialize_summary(record: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize JSON fields (keywords) into string for storage."""
    row = dict(record)
    keywords = row.get("keywords")
    if keywords is not None:
        row["keywords"] = json.dumps(keywords, ensure_ascii=False)
    else:
        row["keywords"] = None
    return row


def deserialize_summary(row: sqlite3.Row) -> Dict[str, Any]:
    """Deserialize SQL row and restore JSON fields (keywords) to lists."""
    record = dict(row)
    val = record.get("keywords")
    if val is not None and isinstance(val, str):
        try:
            record["keywords"] = json.loads(val)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to deserialize keywords for summary {record.get('summary_id')}: {e}")
            record["keywords"] = []
    elif val is None:
        record["keywords"] = []
    return record


_ENTITY_ID_COLUMNS = {
    "topics": "topic_id",
    "projects": "project_id",
    "people": "person_id",
}


def _get_or_create_entity(
    conn: sqlite3.Connection,
    table: str,
    display_name: str,
    normalized_name: str,
) -> str:
    """Return the entity id, inserting with first-seen display name if absent."""
    id_col = _ENTITY_ID_COLUMNS[table]
    cursor = conn.cursor()
    cursor.execute(f"SELECT {id_col} FROM {table} WHERE normalized_name = ?", (normalized_name,))
    row = cursor.fetchone()
    if row is not None:
        return row[0]

    entity_id = f"{table[:3]}_{uuid.uuid4().hex}"
    cursor.execute(
        f"INSERT INTO {table} ({id_col}, normalized_name, display_name) VALUES (?, ?, ?)",
        (entity_id, normalized_name, display_name),
    )
    return entity_id


def _delete_summary_children(conn: sqlite3.Connection, summary_id: str) -> None:
    """Remove child rows before replacing a summary."""
    conn.execute("DELETE FROM summary_items WHERE summary_id = ?", (summary_id,))
    conn.execute("DELETE FROM summary_topics WHERE summary_id = ?", (summary_id,))
    conn.execute("DELETE FROM summary_projects WHERE summary_id = ?", (summary_id,))
    conn.execute("DELETE FROM summary_people WHERE summary_id = ?", (summary_id,))


def upsert_summary(
    record: Dict[str, Any],
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Insert or replace a summary record keyed by (period_type, period_key).
    The record should contain:
      - period_type, period_key, period_start, period_end, generated_at, summary, keywords
      - mood, sleep_raw, sleep_hours (day only; may be None)
      - items: list of {"kind": str, "body": str, "display_order": int}
      - topics: list of topic display names
      - projects: list of project display names
      - people: list of {"name": str, "note": str}
    """
    period_type = record.get("period_type")
    period_key = record.get("period_key")
    if period_type not in ALLOWED_PERIOD_TYPES:
        raise ValueError(f"Invalid period_type: {period_type}")
    if not period_key:
        raise ValueError("period_key is required")

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        if close_conn:
            with conn:
                return _upsert_summary_in_tx(conn, record)
        else:
            return _upsert_summary_in_tx(conn, record)
    finally:
        if close_conn:
            conn.close()


def _upsert_summary_in_tx(conn: sqlite3.Connection, record: Dict[str, Any]) -> Dict[str, Any]:
    period_type = record["period_type"]
    period_key = record["period_key"]

    cursor = conn.cursor()
    cursor.execute(
        "SELECT summary_id FROM summaries WHERE period_type = ? AND period_key = ?",
        (period_type, period_key),
    )
    row = cursor.fetchone()
    summary_id = row[0] if row else generate_summary_id()

    _delete_summary_children(conn, summary_id)

    db_record = {
        "schema_version": 1,
        "summary_id": summary_id,
        "period_type": period_type,
        "period_key": period_key,
        "period_start": record.get("period_start"),
        "period_end": record.get("period_end"),
        "generated_at": record.get("generated_at") or datetime.now().isoformat(),
        "summary": record.get("summary"),
        "keywords": record.get("keywords") or [],
        "mood": record.get("mood"),
        "sleep_raw": record.get("sleep_raw"),
        "sleep_hours": record.get("sleep_hours"),
    }
    db_row = serialize_summary(db_record)

    columns = ", ".join(SUMMARY_COLUMNS)
    placeholders = ", ".join("?" for _ in SUMMARY_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in SUMMARY_COLUMNS if c != "summary_id")
    sql = f"""
        INSERT INTO summaries ({columns}) VALUES ({placeholders})
        ON CONFLICT(period_type, period_key) DO UPDATE SET {updates}
    """
    values = tuple(db_row.get(c) for c in SUMMARY_COLUMNS)
    cursor.execute(sql, values)

    _insert_items(conn, summary_id, record.get("items") or [])
    _insert_topics(conn, summary_id, record.get("topics") or [])
    _insert_projects(conn, summary_id, record.get("projects") or [])
    _insert_people(conn, summary_id, record.get("people") or [])

    return {**db_record, "summary_id": summary_id}


def _insert_items(conn: sqlite3.Connection, summary_id: str, items: List[Dict[str, Any]]) -> None:
    if not items:
        return
    columns = ", ".join(SUMMARY_ITEM_COLUMNS)
    placeholders = ", ".join("?" for _ in SUMMARY_ITEM_COLUMNS)
    sql = f"INSERT INTO summary_items ({columns}) VALUES ({placeholders})"
    for item in items:
        item_id = f"sit_{uuid.uuid4().hex}"
        values = (
            item_id,
            summary_id,
            item.get("kind"),
            item.get("body"),
            item.get("display_order", 0),
        )
        conn.execute(sql, values)


def _insert_topics(conn: sqlite3.Connection, summary_id: str, topics: List[str]) -> None:
    normalized = normalize_topics(topics) if topics else []
    for order, display_name in enumerate(normalized):
        normalized_name = normalize_entity_name(display_name)
        topic_id = _get_or_create_entity(conn, "topics", display_name, normalized_name)
        conn.execute(
            "INSERT INTO summary_topics (summary_id, topic_id, display_order) VALUES (?, ?, ?)",
            (summary_id, topic_id, order),
        )


def _insert_projects(conn: sqlite3.Connection, summary_id: str, projects: List[str]) -> None:
    seen = set()
    order = 0
    for display_name in projects:
        if not isinstance(display_name, str) or not display_name.strip():
            continue
        normalized_name = normalize_entity_name(display_name)
        if normalized_name in seen:
            continue
        seen.add(normalized_name)
        project_id = _get_or_create_entity(conn, "projects", display_name, normalized_name)
        conn.execute(
            "INSERT INTO summary_projects (summary_id, project_id, display_order) VALUES (?, ?, ?)",
            (summary_id, project_id, order),
        )
        order += 1


def _insert_people(conn: sqlite3.Connection, summary_id: str, people: List[Dict[str, Any]]) -> None:
    seen = set()
    order = 0
    for person in people:
        if not isinstance(person, dict):
            continue
        name = person.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        normalized_name = normalize_entity_name(name)
        if normalized_name in seen:
            continue
        seen.add(normalized_name)
        person_id = _get_or_create_entity(conn, "people", name, normalized_name)
        conn.execute(
            "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
            (summary_id, person_id, person.get("note"), order),
        )
        order += 1


def get_summary_by_period(
    period_type: str,
    period_key: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch a single summary with its items and entities by period."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM summaries WHERE period_type = ? AND period_key = ?",
            (period_type, period_key),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return _load_summary_children(conn, deserialize_summary(row))
    finally:
        if close_conn:
            conn.close()


def get_summary_by_id(
    summary_id: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch a single summary with its items and entities by summary_id."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM summaries WHERE summary_id = ?", (summary_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return _load_summary_children(conn, deserialize_summary(row))
    finally:
        if close_conn:
            conn.close()


def _load_summary_children(conn: sqlite3.Connection, record: Dict[str, Any]) -> Dict[str, Any]:
    summary_id = record["summary_id"]
    cursor = conn.cursor()

    cursor.execute(
        "SELECT kind, body, display_order FROM summary_items WHERE summary_id = ? ORDER BY display_order",
        (summary_id,),
    )
    record["items"] = [{"kind": r["kind"], "body": r["body"], "display_order": r["display_order"]} for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT t.display_name, st.display_order
        FROM summary_topics st
        JOIN topics t ON st.topic_id = t.topic_id
        WHERE st.summary_id = ?
        ORDER BY st.display_order
        """,
        (summary_id,),
    )
    record["topics"] = [r["display_name"] for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT p.display_name, sp.display_order
        FROM summary_projects sp
        JOIN projects p ON sp.project_id = p.project_id
        WHERE sp.summary_id = ?
        ORDER BY sp.display_order
        """,
        (summary_id,),
    )
    record["projects"] = [r["display_name"] for r in cursor.fetchall()]

    cursor.execute(
        """
        SELECT p.display_name, sp.note, sp.display_order
        FROM summary_people sp
        JOIN people p ON sp.person_id = p.person_id
        WHERE sp.summary_id = ?
        ORDER BY sp.display_order
        """,
        (summary_id,),
    )
    record["people"] = [{"name": r["display_name"], "note": r["note"], "display_order": r["display_order"]} for r in cursor.fetchall()]

    return record


def list_summaries(
    period_type: Optional[str] = None,
    period: Optional[str] = None,
    topic: Optional[str] = None,
    project: Optional[str] = None,
    person: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """List summaries with optional filters. Returns full records with children."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        sql = "SELECT * FROM summaries WHERE 1=1"
        params: List[Any] = []
        if period_type:
            sql += " AND period_type = ?"
            params.append(period_type)
        if period:
            sql += " AND period_key = ?"
            params.append(period)
        sql += " ORDER BY period_start DESC, period_key DESC"
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        records = [_load_summary_children(conn, deserialize_summary(row)) for row in rows]

        if topic:
            target = normalize_entity_name(topic)
            records = [r for r in records if any(normalize_entity_name(t) == target for t in r.get("topics", []))]
        if project:
            target = normalize_entity_name(project)
            records = [r for r in records if any(normalize_entity_name(p) == target for p in r.get("projects", []))]
        if person:
            target = normalize_entity_name(person)
            records = [r for r in records if any(normalize_entity_name(p["name"]) == target for p in r.get("people", []))]

        return records
    finally:
        if close_conn:
            conn.close()


def get_summary_options(conn: Optional[sqlite3.Connection] = None) -> Dict[str, List[str]]:
    """Return distinct filter candidates for topics, projects, and people."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT display_name FROM topics ORDER BY display_name")
        topics = [r[0] for r in cursor.fetchall()]
        cursor.execute("SELECT display_name FROM projects ORDER BY display_name")
        projects = [r[0] for r in cursor.fetchall()]
        cursor.execute("SELECT display_name FROM people ORDER BY display_name")
        people = [r[0] for r in cursor.fetchall()]
        return {"topics": topics, "projects": projects, "people": people}
    finally:
        if close_conn:
            conn.close()


