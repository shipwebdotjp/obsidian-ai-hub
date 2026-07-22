import json
import logging
import re
import sqlite3
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils.topics import normalize_topics

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
WEEK_ITEM_KINDS = [
    "highlights",
    "progress",
    "learnings",
    "reflections",
    "patterns",
    "gratitude",
]
MONTH_ITEM_KINDS = [
    "highlights",
    "progress",
    "changes",
    "learnings",
    "reflections",
    "patterns",
    "gratitude",
]

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
            logger.warning(
                f"Failed to deserialize keywords for summary {record.get('summary_id')}: {e}"
            )
            record["keywords"] = []
    elif val is None:
        record["keywords"] = []
    return record


def deserialize_candidate(row: dict | sqlite3.Row) -> dict:
    c = dict(row)
    kw = c.get("keywords")
    if isinstance(kw, str):
        try:
            c["keywords"] = json.loads(kw)
        except (json.JSONDecodeError, TypeError):
            c["keywords"] = []
    elif not isinstance(kw, list):
        c["keywords"] = []
    return c


_ENTITY_ID_COLUMNS = {
    "topics": "topic_id",
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
    cursor.execute(
        f"SELECT {id_col} FROM {table} WHERE normalized_name = ?", (normalized_name,)
    )
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
    conn.execute("DELETE FROM summary_project_candidates WHERE summary_id = ?", (summary_id,))
    conn.execute("DELETE FROM summary_people WHERE summary_id = ?", (summary_id,))
    conn.execute(
        "DELETE FROM summary_person_candidates WHERE summary_id = ?", (summary_id,)
    )


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


def _upsert_summary_in_tx(
    conn: sqlite3.Connection, record: Dict[str, Any]
) -> Dict[str, Any]:
    # Validate and load people notes first so we abort on validation failures before DB changes
    from obsidian_ai_hub.utils.people_loader import load_and_validate_people_notes

    people_notes_map = load_and_validate_people_notes()

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
    updates = ", ".join(
        f"{c} = excluded.{c}" for c in SUMMARY_COLUMNS if c != "summary_id"
    )
    sql = f"""
        INSERT INTO summaries ({columns}) VALUES ({placeholders})
        ON CONFLICT(period_type, period_key) DO UPDATE SET {updates}
    """
    values = tuple(db_row.get(c) for c in SUMMARY_COLUMNS)
    cursor.execute(sql, values)

    _insert_items(conn, summary_id, record.get("items") or [])
    _insert_topics(conn, summary_id, record.get("topics") or [])
    _insert_projects(conn, summary_id, record.get("project_ids") or record.get("projects") or [])
    _insert_project_candidates(conn, summary_id, record.get("project_candidates") or [])
    _insert_people(conn, summary_id, record.get("people") or [], people_notes_map)

    return {**db_record, "summary_id": summary_id}


def _insert_items(
    conn: sqlite3.Connection, summary_id: str, items: List[Dict[str, Any]]
) -> None:
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


def _insert_topics(
    conn: sqlite3.Connection, summary_id: str, topics: List[str]
) -> None:
    normalized = normalize_topics(topics) if topics else []
    for order, display_name in enumerate(normalized):
        normalized_name = normalize_entity_name(display_name)
        topic_id = _get_or_create_entity(conn, "topics", display_name, normalized_name)
        conn.execute(
            "INSERT INTO summary_topics (summary_id, topic_id, display_order) VALUES (?, ?, ?)",
            (summary_id, topic_id, order),
        )


def _insert_projects(
    conn: sqlite3.Connection, summary_id: str, projects_or_ids: List[Any]
) -> None:
    seen = set()
    order = 0
    for item in projects_or_ids:
        if isinstance(item, int):
            project_id = item
            if project_id in seen:
                continue
            seen.add(project_id)
            cursor = conn.cursor()
            cursor.execute("SELECT project_id FROM projects WHERE project_id = ?", (project_id,))
            if cursor.fetchone() is not None:
                conn.execute(
                    "INSERT INTO summary_projects (summary_id, project_id, display_order) VALUES (?, ?, ?)",
                    (summary_id, project_id, order),
                )
                order += 1
        elif isinstance(item, str):
            display_name = item.strip()
            if not display_name:
                continue
            norm_name = normalize_entity_name(display_name)
            cursor = conn.cursor()
            cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ?", (norm_name,))
            row = cursor.fetchone()
            if row is not None:
                project_id = row[0]
                if project_id in seen:
                    continue
                seen.add(project_id)
                conn.execute(
                    "INSERT INTO summary_projects (summary_id, project_id, display_order) VALUES (?, ?, ?)",
                    (summary_id, project_id, order),
                )
                order += 1


def _insert_project_candidates(
    conn: sqlite3.Connection,
    summary_id: str,
    candidates: List[Dict[str, Any]],
) -> None:
    seen = set()
    order = 0
    now_iso = datetime.now().isoformat()

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        display_name = cand.get("display_name") or cand.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            continue
        display_name = display_name.strip()
        norm_name = normalize_entity_name(display_name)

        if norm_name in seen:
            continue
        seen.add(norm_name)

        # "却下済み候補と同じ正規化名は保存しない"
        cursor = conn.cursor()
        cursor.execute("SELECT candidate_id, status FROM project_candidates WHERE normalized_name = ?", (norm_name,))
        existing_row = cursor.fetchone()
        if existing_row is not None:
            cand_id = existing_row["candidate_id"]
            status = existing_row["status"]
            if status == "rejected":
                continue
            elif status == "resolved":
                # Find resolved project and link directly
                cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ?", (norm_name,))
                p_row = cursor.fetchone()
                if p_row is not None:
                    project_id = p_row[0]
                    conn.execute("""
                        INSERT OR IGNORE INTO summary_projects (summary_id, project_id, display_order)
                        VALUES (?, ?, ?)
                    """, (summary_id, project_id, order))
                    order += 1
                continue
            else:
                # 'unresolved'
                conn.execute("""
                    INSERT OR IGNORE INTO summary_project_candidates (summary_id, candidate_id, display_order)
                    VALUES (?, ?, ?)
                """, (summary_id, cand_id, order))
                order += 1
                continue

        domain = cand.get("domain") or "personal"
        if domain not in ("work", "personal"):
            domain = "personal"

        keywords = cand.get("keywords") or []
        kw_json = json.dumps(keywords, ensure_ascii=False)

        cursor.execute("""
            INSERT INTO project_candidates (
                display_name, normalized_name, domain, status, goal, description,
                keywords, start_date, target_date, completed_date, evidence,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            display_name, norm_name, domain, "unresolved", cand.get("goal"),
            cand.get("description"), kw_json, cand.get("start_date"),
            cand.get("target_date"), cand.get("completed_date"), cand.get("evidence"),
            now_iso, now_iso
        ))
        cand_id = cursor.lastrowid

        conn.execute("""
            INSERT INTO summary_project_candidates (summary_id, candidate_id, display_order)
            VALUES (?, ?, ?)
        """, (summary_id, cand_id, order))
        order += 1


def _insert_people(
    conn: sqlite3.Connection,
    summary_id: str,
    people: List[Dict[str, Any]],
    people_notes_map: Dict[str, Any],
) -> None:
    seen = set()
    seen_person_ids = set()
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

        # Priority 0: Manual Assignment (summary_person_assignments)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT person_id FROM summary_person_assignments WHERE summary_id = ? AND normalized_name = ?",
            (summary_id, normalized_name),
        )
        row = cursor.fetchone()
        if row is not None:
            person_id = row[0]
            # Ensure the target person exists in people table
            cursor.execute(
                "SELECT person_id FROM people WHERE person_id = ?", (person_id,)
            )
            if cursor.fetchone() is not None:
                if person_id not in seen_person_ids:
                    seen_person_ids.add(person_id)
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, person_id, person.get("note"), order),
                    )
                else:
                    cursor.execute(
                        "SELECT note FROM summary_people WHERE summary_id = ? AND person_id = ?",
                        (summary_id, person_id),
                    )
                    existing_row = cursor.fetchone()
                    if existing_row:
                        notes_to_join = []
                        existing_note = existing_row[0]
                        if existing_note and existing_note.strip():
                            notes_to_join.append(existing_note.strip())
                        new_note = person.get("note")
                        if new_note and new_note.strip():
                            notes_to_join.append(new_note.strip())
                        merged_note = (
                            "\n".join(notes_to_join) if notes_to_join else None
                        )
                        conn.execute(
                            "UPDATE summary_people SET note = ? WHERE summary_id = ? AND person_id = ?",
                            (merged_note, summary_id, person_id),
                        )
                order += 1
                continue

        # Priority 1: DB Confirmed Alias
        cursor.execute(
            "SELECT person_id FROM person_aliases WHERE normalized_name = ?",
            (normalized_name,),
        )
        row = cursor.fetchone()
        if row is not None:
            person_id = row[0]
            # Ensure the target person exists in people table
            cursor.execute(
                "SELECT person_id FROM people WHERE person_id = ?", (person_id,)
            )
            if cursor.fetchone() is not None:
                if person_id not in seen_person_ids:
                    seen_person_ids.add(person_id)
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, person_id, person.get("note"), order),
                    )
                else:
                    cursor.execute(
                        "SELECT note FROM summary_people WHERE summary_id = ? AND person_id = ?",
                        (summary_id, person_id),
                    )
                    existing_row = cursor.fetchone()
                    if existing_row:
                        notes_to_join = []
                        existing_note = existing_row[0]
                        if existing_note and existing_note.strip():
                            notes_to_join.append(existing_note.strip())
                        new_note = person.get("note")
                        if new_note and new_note.strip():
                            notes_to_join.append(new_note.strip())
                        merged_note = (
                            "\n".join(notes_to_join) if notes_to_join else None
                        )
                        conn.execute(
                            "UPDATE summary_people SET note = ? WHERE summary_id = ? AND person_id = ?",
                            (merged_note, summary_id, person_id),
                        )
                order += 1
                continue

        # Priority 2: Safe Vault Input
        if normalized_name in people_notes_map:
            note_data = people_notes_map[normalized_name]
            vault_id = note_data["id"]
            vault_name = note_data["name"]

            # Check if there is an existing person with this vault_id
            cursor.execute(
                "SELECT person_id FROM people WHERE vault_id = ?", (vault_id,)
            )
            row = cursor.fetchone()
            if row is not None:
                person_id = row[0]
                # Update display_name to vault_name and update normalized_name
                conn.execute(
                    "UPDATE people SET display_name = ?, normalized_name = ? WHERE person_id = ?",
                    (vault_name, normalize_entity_name(vault_name), person_id),
                )
            else:
                # Check if there is an existing person with the same normalized name
                cursor.execute(
                    "SELECT person_id FROM people WHERE normalized_name = ?",
                    (normalize_entity_name(vault_name),),
                )
                row = cursor.fetchone()
                if row is not None:
                    person_id = row[0]
                    conn.execute(
                        "UPDATE people SET vault_id = ?, display_name = ? WHERE person_id = ?",
                        (vault_id, vault_name, person_id),
                    )
                else:
                    # Create new person row
                    person_id = f"peo_{uuid.uuid4().hex}"
                    conn.execute(
                        "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES (?, ?, ?, ?)",
                        (
                            person_id,
                            normalize_entity_name(vault_name),
                            vault_name,
                            vault_id,
                        ),
                    )

            if person_id in seen_person_ids:
                cursor.execute(
                    "SELECT note FROM summary_people WHERE summary_id = ? AND person_id = ?",
                    (summary_id, person_id),
                )
                existing_row = cursor.fetchone()
                if existing_row:
                    notes_to_join = []
                    existing_note = existing_row[0]
                    if existing_note and existing_note.strip():
                        notes_to_join.append(existing_note.strip())
                    new_note = person.get("note")
                    if new_note and new_note.strip():
                        notes_to_join.append(new_note.strip())
                    merged_note = "\n".join(notes_to_join) if notes_to_join else None
                    conn.execute(
                        "UPDATE summary_people SET note = ? WHERE summary_id = ? AND person_id = ?",
                        (merged_note, summary_id, person_id),
                    )
                order += 1
                continue
            seen_person_ids.add(person_id)

            conn.execute(
                "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                (summary_id, person_id, person.get("note"), order),
            )
        else:
            # Priority 3: Unlinked person's normalized name (exact match, vault_id IS NULL)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT person_id FROM people WHERE normalized_name = ? AND vault_id IS NULL",
                (normalized_name,),
            )
            row = cursor.fetchone()
            if row is not None:
                person_id = row[0]
                if person_id not in seen_person_ids:
                    seen_person_ids.add(person_id)
                    conn.execute(
                        "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                        (summary_id, person_id, person.get("note"), order),
                    )
                else:
                    cursor.execute(
                        "SELECT note FROM summary_people WHERE summary_id = ? AND person_id = ?",
                        (summary_id, person_id),
                    )
                    existing_row = cursor.fetchone()
                    if existing_row:
                        notes_to_join = []
                        existing_note = existing_row[0]
                        if existing_note and existing_note.strip():
                            notes_to_join.append(existing_note.strip())
                        new_note = person.get("note")
                        if new_note and new_note.strip():
                            notes_to_join.append(new_note.strip())
                        merged_note = (
                            "\n".join(notes_to_join) if notes_to_join else None
                        )
                        conn.execute(
                            "UPDATE summary_people SET note = ? WHERE summary_id = ? AND person_id = ?",
                            (merged_note, summary_id, person_id),
                        )
                order += 1
                continue
            else:
                # Priority 4: Unresolved candidate
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT candidate_id FROM person_candidates WHERE normalized_name = ?",
                    (normalized_name,),
                )
                row = cursor.fetchone()
                if row is not None:
                    candidate_id = row[0]
                else:
                    candidate_id = f"cand_{uuid.uuid4().hex}"
                    conn.execute(
                        "INSERT INTO person_candidates (candidate_id, display_name, normalized_name, status) VALUES (?, ?, ?, ?)",
                        (candidate_id, name, normalized_name, "unresolved"),
                    )

                conn.execute(
                    "INSERT INTO summary_person_candidates (summary_id, candidate_id, note, display_order) VALUES (?, ?, ?, ?)",
                    (summary_id, candidate_id, person.get("note"), order),
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


def _load_summary_children(
    conn: sqlite3.Connection, record: Dict[str, Any]
) -> Dict[str, Any]:
    summary_id = record["summary_id"]
    cursor = conn.cursor()

    cursor.execute(
        "SELECT summary_item_id, kind, body, display_order FROM summary_items WHERE summary_id = ? ORDER BY display_order",
        (summary_id,),
    )
    record["items"] = [
        {
            "summary_item_id": r["summary_item_id"],
            "kind": r["kind"],
            "body": r["body"],
            "display_order": r["display_order"],
        }
        for r in cursor.fetchall()
    ]

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
        SELECT p.project_id, p.display_name, sp.display_order
        FROM summary_projects sp
        JOIN projects p ON sp.project_id = p.project_id
        WHERE sp.summary_id = ?
        ORDER BY sp.display_order
        """,
        (summary_id,),
    )
    rows_p = cursor.fetchall()
    record["projects"] = [r["display_name"] for r in rows_p]
    record["project_ids"] = [r["project_id"] for r in rows_p]

    cursor.execute(
        """
        SELECT pc.*, spc.display_order
        FROM summary_project_candidates spc
        JOIN project_candidates pc ON spc.candidate_id = pc.candidate_id
        WHERE spc.summary_id = ? AND pc.status = 'unresolved'
        ORDER BY spc.display_order
        """,
        (summary_id,),
    )
    record["project_candidates"] = [deserialize_candidate(r) for r in cursor.fetchall()]

    # Fetch resolved people
    cursor.execute(
        """
        SELECT p.person_id, p.display_name, sp.note, sp.display_order
        FROM summary_people sp
        JOIN people p ON sp.person_id = p.person_id
        WHERE sp.summary_id = ?
        """,
        (summary_id,),
    )
    resolved_list = [
        {
            "person_id": r["person_id"],
            "name": r["display_name"],
            "note": r["note"],
            "display_order": r["display_order"],
            "resolution_status": "resolved",
            "candidate_id": None,
        }
        for r in cursor.fetchall()
    ]

    # Fetch unresolved candidates
    cursor.execute(
        """
        SELECT pc.display_name, spc.note, spc.display_order, pc.candidate_id
        FROM summary_person_candidates spc
        JOIN person_candidates pc ON spc.candidate_id = pc.candidate_id
        WHERE spc.summary_id = ?
        """,
        (summary_id,),
    )
    unresolved_list = [
        {
            "name": r["display_name"],
            "note": r["note"],
            "display_order": r["display_order"],
            "resolution_status": "unresolved",
            "candidate_id": r["candidate_id"],
        }
        for r in cursor.fetchall()
    ]

    combined_people = resolved_list + unresolved_list
    combined_people.sort(key=lambda x: x["display_order"])
    record["people"] = combined_people

    return record


def _attach_children_bulk(
    conn: sqlite3.Connection,
    records: List[Dict[str, Any]],
) -> None:
    """Bulk-load items, topics, projects, and people for the given summary records."""
    if not records:
        return

    summary_ids = [r["summary_id"] for r in records]
    placeholders = ", ".join("?" for _ in summary_ids)
    cursor = conn.cursor()

    cursor.execute(
        f"SELECT summary_id, summary_item_id, kind, body, display_order FROM summary_items WHERE summary_id IN ({placeholders}) ORDER BY display_order",
        summary_ids,
    )
    items_by_summary: Dict[str, List[Dict[str, Any]]] = {
        r["summary_id"]: [] for r in records
    }
    for row in cursor.fetchall():
        items_by_summary[row["summary_id"]].append(
            {
                "summary_item_id": row["summary_item_id"],
                "kind": row["kind"],
                "body": row["body"],
                "display_order": row["display_order"],
            }
        )

    cursor.execute(
        f"""
        SELECT st.summary_id, t.display_name
        FROM summary_topics st
        JOIN topics t ON st.topic_id = t.topic_id
        WHERE st.summary_id IN ({placeholders})
        ORDER BY st.display_order
        """,
        summary_ids,
    )
    topics_by_summary: Dict[str, List[str]] = {r["summary_id"]: [] for r in records}
    for row in cursor.fetchall():
        topics_by_summary[row["summary_id"]].append(row["display_name"])

    cursor.execute(
        f"""
        SELECT sp.summary_id, p.project_id, p.display_name
        FROM summary_projects sp
        JOIN projects p ON sp.project_id = p.project_id
        WHERE sp.summary_id IN ({placeholders})
        ORDER BY sp.display_order
        """,
        summary_ids,
    )
    projects_by_summary: Dict[str, List[str]] = {r["summary_id"]: [] for r in records}
    project_ids_by_summary: Dict[str, List[int]] = {r["summary_id"]: [] for r in records}
    for row in cursor.fetchall():
        projects_by_summary[row["summary_id"]].append(row["display_name"])
        project_ids_by_summary[row["summary_id"]].append(row["project_id"])

    cursor.execute(
        f"""
        SELECT spc.summary_id, pc.*
        FROM summary_project_candidates spc
        JOIN project_candidates pc ON spc.candidate_id = pc.candidate_id
        WHERE spc.summary_id IN ({placeholders}) AND pc.status = 'unresolved'
        ORDER BY spc.display_order
        """,
        summary_ids,
    )
    candidates_by_summary: Dict[str, List[Dict[str, Any]]] = {r["summary_id"]: [] for r in records}
    for row in cursor.fetchall():
        candidates_by_summary[row["summary_id"]].append(deserialize_candidate(dict(row)))

    people_by_summary: Dict[str, List[Dict[str, Any]]] = {
        r["summary_id"]: [] for r in records
    }

    # Fetch resolved
    cursor.execute(
        f"""
        SELECT sp.summary_id, sp.person_id, p.display_name, sp.note, sp.display_order
        FROM summary_people sp
        JOIN people p ON sp.person_id = p.person_id
        WHERE sp.summary_id IN ({placeholders})
        """,
        summary_ids,
    )
    for row in cursor.fetchall():
        people_by_summary[row["summary_id"]].append(
            {
                "person_id": row["person_id"],
                "name": row["display_name"],
                "note": row["note"],
                "display_order": row["display_order"],
                "resolution_status": "resolved",
                "candidate_id": None,
            }
        )

    # Fetch unresolved
    cursor.execute(
        f"""
        SELECT spc.summary_id, pc.display_name, spc.note, spc.display_order, pc.candidate_id
        FROM summary_person_candidates spc
        JOIN person_candidates pc ON spc.candidate_id = pc.candidate_id
        WHERE spc.summary_id IN ({placeholders})
        """,
        summary_ids,
    )
    for row in cursor.fetchall():
        people_by_summary[row["summary_id"]].append(
            {
                "name": row["display_name"],
                "note": row["note"],
                "display_order": row["display_order"],
                "resolution_status": "unresolved",
                "candidate_id": row["candidate_id"],
            }
        )

    # Sort each summary's list by display_order
    for sid in people_by_summary:
        people_by_summary[sid].sort(key=lambda x: x["display_order"])

    for record in records:
        sid = record["summary_id"]
        record["items"] = items_by_summary.get(sid, [])
        record["topics"] = topics_by_summary.get(sid, [])
        record["projects"] = projects_by_summary.get(sid, [])
        record["project_ids"] = project_ids_by_summary.get(sid, [])
        record["project_candidates"] = candidates_by_summary.get(sid, [])
        record["people"] = people_by_summary.get(sid, [])


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
        sql = "SELECT s.* FROM summaries s WHERE 1=1"
        params: List[Any] = []
        if period_type:
            sql += " AND s.period_type = ?"
            params.append(period_type)
        if period:
            sql += " AND s.period_key = ?"
            params.append(period)
        if topic:
            sql += """ AND EXISTS (
                SELECT 1 FROM summary_topics st
                JOIN topics t ON st.topic_id = t.topic_id
                WHERE st.summary_id = s.summary_id AND t.normalized_name = ?
            )"""
            params.append(normalize_entity_name(topic))
        if project:
            sql += """ AND EXISTS (
                SELECT 1 FROM summary_projects sp
                JOIN projects p ON sp.project_id = p.project_id
                WHERE sp.summary_id = s.summary_id AND p.normalized_name = ?
            )"""
            params.append(normalize_entity_name(project))
        if person:
            from obsidian_ai_hub.utils.people_loader import (
                load_and_validate_people_notes,
            )

            people_notes_map = load_and_validate_people_notes()
            normalized_person = normalize_entity_name(person)

            if normalized_person in people_notes_map:
                vault_id = people_notes_map[normalized_person]["id"]
                sql += """ AND (
                    EXISTS (
                        SELECT 1 FROM summary_people sp
                        JOIN people p ON sp.person_id = p.person_id
                        WHERE sp.summary_id = s.summary_id AND p.vault_id = ?
                    ) OR EXISTS (
                        SELECT 1 FROM summary_person_candidates spc
                        JOIN person_candidates pc ON spc.candidate_id = pc.candidate_id
                        WHERE spc.summary_id = s.summary_id AND pc.normalized_name = ?
                    )
                )"""
                params.append(vault_id)
                params.append(normalized_person)
            else:
                sql += """ AND EXISTS (
                    SELECT 1 FROM summary_person_candidates spc
                    JOIN person_candidates pc ON spc.candidate_id = pc.candidate_id
                    WHERE spc.summary_id = s.summary_id AND pc.normalized_name = ?
                )"""
                params.append(normalized_person)
        sql += " ORDER BY s.period_start DESC, s.period_key DESC"
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        records = [deserialize_summary(row) for row in rows]
        _attach_children_bulk(conn, records)

        return records
    finally:
        if close_conn:
            conn.close()


def get_summary_options(
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, List[str]]:
    """Return distinct filter candidates for topics, projects, and people that are associated with at least one summary."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT t.display_name
            FROM topics t
            JOIN summary_topics st ON t.topic_id = st.topic_id
            ORDER BY t.display_name
            """
        )
        topics = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            """
            SELECT DISTINCT p.display_name
            FROM projects p
            JOIN summary_projects sp ON p.project_id = sp.project_id
            ORDER BY p.display_name
            """
        )
        projects = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            """
            SELECT DISTINCT p.display_name
            FROM people p
            JOIN summary_people sp ON p.person_id = sp.person_id
            WHERE p.vault_id IS NOT NULL
            ORDER BY p.display_name
            """
        )
        people = [r[0] for r in cursor.fetchall()]
        return {
            "period_types": ["day", "week", "month"],
            "topics": topics,
            "projects": projects,
            "people": people,
        }
    finally:
        if close_conn:
            conn.close()


def update_summary(
    summary_id: str,
    payload: Dict[str, Any],
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Update a summary by ID with only the fields present in payload.
    payload uses exclude_unset semantics: only keys present are updated.
    Explicit None values clear the field (e.g. mood, sleep_raw).
    """
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        if close_conn:
            with conn:
                return _update_summary_in_tx(conn, summary_id, payload)
        else:
            return _update_summary_in_tx(conn, summary_id, payload)
    finally:
        if close_conn:
            conn.close()


def _update_summary_in_tx(
    conn: sqlite3.Connection,
    summary_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    cursor = conn.cursor()

    # 1. Verify summary exists and read period_type
    cursor.execute(
        "SELECT summary_id, period_type FROM summaries WHERE summary_id = ?",
        (summary_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"Summary not found: {summary_id}")

    # 2. Read current children for fields NOT in payload (to preserve)
    preserved_candidates = _read_candidates(conn, summary_id)
    preserved_items = _read_items(conn, summary_id) if "items" not in payload else []
    preserved_topics = _read_topics(conn, summary_id) if "topics" not in payload else []
    preserved_resolved_people = (
        _read_resolved_people(conn, summary_id) if "people" not in payload else []
    )
    preserved_projects = _read_projects(conn, summary_id) if "projects" not in payload else []
    preserved_project_candidates = _read_project_candidates(conn, summary_id) if "project_candidates" not in payload else []

    # 3. Delete all children
    _delete_summary_children(conn, summary_id)

    # 4. Update summaries row with only the fields present in payload
    update_fields = []
    update_values = []
    if "summary" in payload:
        update_fields.append("summary = ?")
        update_values.append(payload["summary"])
    if "keywords" in payload:
        update_fields.append("keywords = ?")
        update_values.append(
            json.dumps(payload["keywords"], ensure_ascii=False)
            if payload["keywords"]
            else None
        )
    if "mood" in payload:
        update_fields.append("mood = ?")
        update_values.append(payload["mood"])
    if "sleep_raw" in payload:
        update_fields.append("sleep_raw = ?")
        update_values.append(payload["sleep_raw"])
        # Recalculate sleep_hours
        update_fields.append("sleep_hours = ?")
        update_values.append(parse_sleep_hours(payload["sleep_raw"]))

    if update_fields:
        sql = f"UPDATE summaries SET {', '.join(update_fields)} WHERE summary_id = ?"
        update_values.append(summary_id)
        cursor.execute(sql, tuple(update_values))

    # 5. Re-insert preserved unresolved candidates (always preserved)
    order = 0
    for cand in preserved_candidates:
        conn.execute(
            "INSERT INTO summary_person_candidates (summary_id, candidate_id, note, display_order) VALUES (?, ?, ?, ?)",
            (summary_id, cand["candidate_id"], cand["note"], order),
        )
        order += 1

    # 6. Insert items
    if "items" in payload:
        raw_items = payload["items"] or []
        for i, item in enumerate(raw_items):
            item_id = f"sit_{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO summary_items (summary_item_id, summary_id, kind, body, display_order) VALUES (?, ?, ?, ?, ?)",
                (item_id, summary_id, item["kind"], item["body"], i),
            )
    else:
        for i, item in enumerate(preserved_items):
            conn.execute(
                "INSERT INTO summary_items (summary_item_id, summary_id, kind, body, display_order) VALUES (?, ?, ?, ?, ?)",
                (item["summary_item_id"], summary_id, item["kind"], item["body"], i),
            )

    # 7. Insert topics
    if "topics" in payload:
        raw_topics = payload["topics"] or []
        normalized = normalize_topics(raw_topics) if raw_topics else []
        for i, display_name in enumerate(normalized):
            normalized_name = normalize_entity_name(display_name)
            topic_id = _get_or_create_entity(
                conn, "topics", display_name, normalized_name
            )
            conn.execute(
                "INSERT INTO summary_topics (summary_id, topic_id, display_order) VALUES (?, ?, ?)",
                (summary_id, topic_id, i),
            )
    else:
        for i, topic in enumerate(preserved_topics):
            normalized_name = normalize_entity_name(topic)
            conn.execute(
                "SELECT topic_id FROM topics WHERE normalized_name = ?",
                (normalized_name,),
            )
            trow = cursor.fetchone()
            if trow:
                conn.execute(
                    "INSERT INTO summary_topics (summary_id, topic_id, display_order) VALUES (?, ?, ?)",
                    (summary_id, trow["topic_id"], i),
                )

    # 8. Insert resolved people (after candidates, with continuing display_order)
    if "people" in payload:
        raw_people = payload["people"] or []
        for person in raw_people:
            conn.execute(
                "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                (summary_id, person["person_id"], person.get("note"), order),
            )
            order += 1
    else:
        for person in preserved_resolved_people:
            conn.execute(
                "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
                (summary_id, person["person_id"], person["note"], order),
            )
            order += 1

    # 9. Insert projects
    if "projects" in payload:
        _insert_projects(conn, summary_id, payload["projects"] or [])
    else:
        _insert_projects(conn, summary_id, preserved_projects)

    # 10. Insert project candidates
    if "project_candidates" in payload:
        _insert_project_candidates(conn, summary_id, payload["project_candidates"] or [])
    else:
        for i, cand_id in enumerate(preserved_project_candidates):
            conn.execute(
                "INSERT INTO summary_project_candidates (summary_id, candidate_id, display_order) VALUES (?, ?, ?)",
                (summary_id, cand_id, i),
            )

    return get_summary_by_id(summary_id, conn=conn)


def _read_candidates(conn: sqlite3.Connection, summary_id: str) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT candidate_id, note, display_order FROM summary_person_candidates WHERE summary_id = ? ORDER BY display_order",
        (summary_id,),
    )
    return [dict(r) for r in cursor.fetchall()]


def _read_projects(conn: sqlite3.Connection, summary_id: str) -> list[int]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT project_id FROM summary_projects WHERE summary_id = ? ORDER BY display_order",
        (summary_id,),
    )
    return [row[0] for row in cursor.fetchall()]


def _read_project_candidates(conn: sqlite3.Connection, summary_id: str) -> list[int]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT candidate_id FROM summary_project_candidates WHERE summary_id = ? ORDER BY display_order",
        (summary_id,),
    )
    return [row[0] for row in cursor.fetchall()]


def _read_items(conn: sqlite3.Connection, summary_id: str) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT summary_item_id, kind, body, display_order FROM summary_items WHERE summary_id = ? ORDER BY display_order",
        (summary_id,),
    )
    return [dict(r) for r in cursor.fetchall()]


def _read_topics(conn: sqlite3.Connection, summary_id: str) -> list[str]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT t.display_name
        FROM summary_topics st
        JOIN topics t ON st.topic_id = t.topic_id
        WHERE st.summary_id = ?
        ORDER BY st.display_order
        """,
        (summary_id,),
    )
    return [r["display_name"] for r in cursor.fetchall()]


def _read_resolved_people(conn: sqlite3.Connection, summary_id: str) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT p.person_id, sp.note, sp.display_order
        FROM summary_people sp
        JOIN people p ON sp.person_id = p.person_id
        WHERE sp.summary_id = ?
        ORDER BY sp.display_order
        """,
        (summary_id,),
    )
    return [dict(r) for r in cursor.fetchall()]


def delete_summary(
    summary_id: str,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """Delete a summary and all its children. Returns True if deleted."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        if close_conn:
            with conn:
                return _delete_summary_in_tx(conn, summary_id)
        else:
            return _delete_summary_in_tx(conn, summary_id)
    finally:
        if close_conn:
            conn.close()


def _delete_summary_in_tx(
    conn: sqlite3.Connection,
    summary_id: str,
) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT summary_id FROM summaries WHERE summary_id = ?", (summary_id,)
    )
    if cursor.fetchone() is None:
        return False

    _delete_summary_children(conn, summary_id)
    conn.execute("DELETE FROM summaries WHERE summary_id = ?", (summary_id,))
    conn.execute(
        "DELETE FROM summary_person_assignments WHERE summary_id = ?", (summary_id,)
    )
    return True
