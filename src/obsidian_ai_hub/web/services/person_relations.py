import re
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from obsidian_ai_hub.database import get_db_connection

JST = ZoneInfo("Asia/Tokyo")


class SlugConflictError(ValueError):
    def __init__(self, message="Conflict: relation_type slug already exists"):
        super().__init__(message)


class InactiveRelationTypeError(ValueError):
    def __init__(self, message="Inactive relation type cannot be used for new relations"):
        super().__init__(message)


class SelfRelationError(ValueError):
    def __init__(self, message="Self-relations are not allowed"):
        super().__init__(message)


class InvalidDateError(ValueError):
    def __init__(self, message="Invalid date format or date order"):
        super().__init__(message)


def get_jst_today_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def compute_relation_status(
    started_on: Optional[str], ended_on: Optional[str], today_str: Optional[str] = None
) -> str:
    if started_on is None and ended_on is None:
        return "undated"
    if today_str is None:
        today_str = get_jst_today_str()

    if started_on and started_on > today_str:
        return "upcoming"
    if ended_on and ended_on < today_str:
        return "ended"
    return "active"


def validate_dates(started_on: Optional[str], ended_on: Optional[str]) -> None:
    for d_val in (started_on, ended_on):
        if d_val is not None:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", d_val):
                raise InvalidDateError(f"Date must be YYYY-MM-DD: {d_val}")
            try:
                datetime.strptime(d_val, "%Y-%m-%d")
            except ValueError as e:
                raise InvalidDateError(f"Invalid date: {d_val}") from e

    if started_on and ended_on and started_on > ended_on:
        raise InvalidDateError("started_on must be less than or equal to ended_on")


def normalize_endpoints(
    cursor: sqlite3.Cursor,
    relation_type_id: str,
    subject_person_id: str,
    object_person_id: str,
) -> tuple[str, str, dict[str, Any]]:
    if subject_person_id == object_person_id:
        raise SelfRelationError()

    cursor.execute(
        "SELECT relation_type_id, slug, forward_label, reverse_label, directionality, description, is_builtin, is_active "
        "FROM person_relation_types WHERE relation_type_id = ?",
        (relation_type_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise FileNotFoundError(f"Relation type not found: {relation_type_id}")
    rel_type = dict(row)

    directionality = rel_type["directionality"]
    if directionality == "symmetric":
        if subject_person_id > object_person_id:
            return object_person_id, subject_person_id, rel_type
        return subject_person_id, object_person_id, rel_type
    else:
        return subject_person_id, object_person_id, rel_type


def concatenate_notes(existing_note: Optional[str], incoming_note: Optional[str]) -> Optional[str]:
    lines = []

    def _add_text(text: Optional[str]):
        if not text:
            return
        for line in text.splitlines():
            s = line.strip()
            if s and s not in lines:
                lines.append(s)

    _add_text(existing_note)
    _add_text(incoming_note)

    if not lines:
        return None
    return "\n".join(lines)


def _normalize_evidence_tuple(
    source_type: str,
    source_ref: Optional[str],
    quote: Optional[str],
    note: Optional[str],
    observed_at: Optional[str],
) -> tuple[str, str, str, str, str]:
    return (
        (source_type or "").strip(),
        (source_ref or "").strip(),
        (quote or "").strip(),
        (note or "").strip(),
        (observed_at or "").strip(),
    )


def deduplicate_and_add_evidence(
    cursor: sqlite3.Cursor,
    target_relation_id: str,
    evidence_list: list[dict[str, Any]],
    now_iso: str,
) -> int:
    cursor.execute(
        "SELECT source_type, source_ref, quote, note, observed_at FROM person_relation_evidence WHERE relation_id = ?",
        (target_relation_id,),
    )
    existing_ev_rows = cursor.fetchall()
    existing_tuples = {
        _normalize_evidence_tuple(
            r["source_type"], r["source_ref"], r["quote"], r["note"], r["observed_at"]
        )
        for r in existing_ev_rows
    }

    added_count = 0
    for ev in evidence_list:
        norm_tup = _normalize_evidence_tuple(
            ev.get("source_type", "manual"),
            ev.get("source_ref"),
            ev.get("quote"),
            ev.get("note"),
            ev.get("observed_at"),
        )
        if norm_tup in existing_tuples:
            continue

        existing_tuples.add(norm_tup)
        ev_id = f"rle_{uuid.uuid4().hex}"
        cursor.execute(
            """
            INSERT INTO person_relation_evidence (
                evidence_id, relation_id, source_type, source_ref, quote, note, observed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ev_id,
                target_relation_id,
                norm_tup[0] or "manual",
                ev.get("source_ref"),
                ev.get("quote"),
                ev.get("note"),
                ev.get("observed_at"),
                now_iso,
                now_iso,
            ),
        )
        added_count += 1

    return added_count


def create_person_relation_in_tx(
    cursor: sqlite3.Cursor,
    subject_person_id: str,
    object_person_id: str,
    relation_type_id: str,
    started_on: Optional[str] = None,
    ended_on: Optional[str] = None,
    note: Optional[str] = None,
    initial_evidence: Optional[list[dict[str, Any]]] = None,
) -> tuple[dict[str, Any], Literal["created", "merged_into_existing"]]:
    validate_dates(started_on, ended_on)

    norm_subj, norm_obj, rel_type = normalize_endpoints(
        cursor, relation_type_id, subject_person_id, object_person_id
    )

    if not rel_type["is_active"]:
        raise InactiveRelationTypeError()

    # Check for existing relation with same 5 elements
    cursor.execute(
        """
        SELECT relation_id, subject_person_id, object_person_id, relation_type_id, started_on, ended_on, note, created_at, updated_at
        FROM person_relations
        WHERE relation_type_id = ? AND subject_person_id = ? AND object_person_id = ?
          AND COALESCE(started_on, '') = COALESCE(?, '')
          AND COALESCE(ended_on, '') = COALESCE(?, '')
        """,
        (relation_type_id, norm_subj, norm_obj, started_on or "", ended_on or ""),
    )
    existing_row = cursor.fetchone()
    now_iso = datetime.now(JST).isoformat()

    if existing_row is not None:
        existing_rel = dict(existing_row)
        merged_note = concatenate_notes(existing_rel["note"], note)

        cursor.execute(
            "UPDATE person_relations SET note = ?, updated_at = ? WHERE relation_id = ?",
            (merged_note, now_iso, existing_rel["relation_id"]),
        )

        if initial_evidence:
            deduplicate_and_add_evidence(
                cursor, existing_rel["relation_id"], initial_evidence, now_iso
            )

        res_rel = get_person_relation_by_id_in_tx(cursor, existing_rel["relation_id"])
        return res_rel, "merged_into_existing"

    # Create new relation
    rel_id = f"rel_{uuid.uuid4().hex}"
    cursor.execute(
        """
        INSERT INTO person_relations (
            relation_id, subject_person_id, object_person_id, relation_type_id,
            started_on, ended_on, note, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rel_id,
            norm_subj,
            norm_obj,
            relation_type_id,
            started_on,
            ended_on,
            note,
            now_iso,
            now_iso,
        ),
    )

    if initial_evidence:
        deduplicate_and_add_evidence(cursor, rel_id, initial_evidence, now_iso)

    res_rel = get_person_relation_by_id_in_tx(cursor, rel_id)
    return res_rel, "created"


def get_person_relation_by_id_in_tx(
    cursor: sqlite3.Cursor, relation_id: str
) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT r.relation_id, r.subject_person_id, r.object_person_id, r.relation_type_id,
               r.started_on, r.ended_on, r.note, r.created_at, r.updated_at,
               t.slug, t.forward_label, t.reverse_label, t.directionality, t.description, t.is_builtin, t.is_active,
               t.created_at AS type_created_at, t.updated_at AS type_updated_at
        FROM person_relations r
        JOIN person_relation_types t ON r.relation_type_id = t.relation_type_id
        WHERE r.relation_id = ?
        """,
        (relation_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise FileNotFoundError(f"Person relation not found: {relation_id}")

    rel_dict = dict(row)
    rel_type = {
        "relation_type_id": rel_dict["relation_type_id"],
        "slug": rel_dict["slug"],
        "forward_label": rel_dict["forward_label"],
        "reverse_label": rel_dict["reverse_label"],
        "directionality": rel_dict["directionality"],
        "description": rel_dict["description"],
        "is_builtin": bool(rel_dict["is_builtin"]),
        "is_active": bool(rel_dict["is_active"]),
        "created_at": rel_dict["type_created_at"],
        "updated_at": rel_dict["type_updated_at"],
    }

    cursor.execute(
        "SELECT evidence_id, relation_id, source_type, source_ref, quote, note, observed_at, created_at, updated_at "
        "FROM person_relation_evidence WHERE relation_id = ? ORDER BY created_at ASC",
        (relation_id,),
    )
    ev_rows = [dict(r) for r in cursor.fetchall()]

    status = compute_relation_status(rel_dict["started_on"], rel_dict["ended_on"])

    return {
        "relation_id": rel_dict["relation_id"],
        "subject_person_id": rel_dict["subject_person_id"],
        "object_person_id": rel_dict["object_person_id"],
        "relation_type_id": rel_dict["relation_type_id"],
        "started_on": rel_dict["started_on"],
        "ended_on": rel_dict["ended_on"],
        "note": rel_dict["note"],
        "status": status,
        "created_at": rel_dict["created_at"],
        "updated_at": rel_dict["updated_at"],
        "relation_type": rel_type,
        "evidence": ev_rows,
    }


def update_person_relation_in_tx(
    cursor: sqlite3.Cursor,
    relation_id: str,
    started_on: Optional[str] = None,
    ended_on: Optional[str] = None,
    note: Optional[str] = None,
) -> tuple[dict[str, Any], Literal["updated", "merged_into_existing"]]:
    current_rel = get_person_relation_by_id_in_tx(cursor, relation_id)

    new_started_on = started_on if started_on is not None else current_rel["started_on"]
    new_ended_on = ended_on if ended_on is not None else current_rel["ended_on"]
    validate_dates(new_started_on, new_ended_on)

    now_iso = datetime.now(JST).isoformat()

    # Check if updating dates causes semantic collision with another existing relation
    cursor.execute(
        """
        SELECT relation_id, note
        FROM person_relations
        WHERE relation_type_id = ? AND subject_person_id = ? AND object_person_id = ?
          AND COALESCE(started_on, '') = COALESCE(?, '')
          AND COALESCE(ended_on, '') = COALESCE(?, '')
          AND relation_id != ?
        """,
        (
            current_rel["relation_type_id"],
            current_rel["subject_person_id"],
            current_rel["object_person_id"],
            new_started_on or "",
            new_ended_on or "",
            relation_id,
        ),
    )
    target_collision = cursor.fetchone()

    if target_collision is not None:
        surviving_id = target_collision["relation_id"]
        merged_note = concatenate_notes(target_collision["note"], note or current_rel["note"])

        cursor.execute(
            "UPDATE person_relations SET note = ?, updated_at = ? WHERE relation_id = ?",
            (merged_note, now_iso, surviving_id),
        )

        # Move evidence from relation_id to surviving_id with deduplication
        cursor.execute(
            "SELECT source_type, source_ref, quote, note, observed_at FROM person_relation_evidence WHERE relation_id = ?",
            (relation_id,),
        )
        current_evs = [dict(r) for r in cursor.fetchall()]
        deduplicate_and_add_evidence(cursor, surviving_id, current_evs, now_iso)

        # Delete relation_id
        cursor.execute("DELETE FROM person_relations WHERE relation_id = ?", (relation_id,))

        surviving_rel = get_person_relation_by_id_in_tx(cursor, surviving_id)
        return surviving_rel, "merged_into_existing"

    # Standard update
    merged_note = note if note is not None else current_rel["note"]
    cursor.execute(
        "UPDATE person_relations SET started_on = ?, ended_on = ?, note = ?, updated_at = ? WHERE relation_id = ?",
        (new_started_on, new_ended_on, merged_note, now_iso, relation_id),
    )

    updated_rel = get_person_relation_by_id_in_tx(cursor, relation_id)
    return updated_rel, "updated"


def delete_person_relation_in_tx(cursor: sqlite3.Cursor, relation_id: str) -> None:
    cursor.execute("SELECT relation_id FROM person_relations WHERE relation_id = ?", (relation_id,))
    if cursor.fetchone() is None:
        raise FileNotFoundError(f"Person relation not found: {relation_id}")
    cursor.execute("DELETE FROM person_relations WHERE relation_id = ?", (relation_id,))


def preview_person_relation_merge(
    cursor: sqlite3.Cursor, from_person_id: str, to_person_id: str
) -> dict[str, Any]:
    # Fetch all relations involving from_person_id
    cursor.execute(
        """
        SELECT r.relation_id, r.subject_person_id, r.object_person_id, r.relation_type_id,
               r.started_on, r.ended_on, r.note,
               t.slug, t.forward_label, t.reverse_label, t.directionality
        FROM person_relations r
        JOIN person_relation_types t ON r.relation_type_id = t.relation_type_id
        WHERE r.subject_person_id = ? OR r.object_person_id = ?
        """,
        (from_person_id, from_person_id),
    )
    from_relations = cursor.fetchall()

    # Pre-fetch person names map for display
    cursor.execute("SELECT person_id, display_name FROM people")
    people_map = {r["person_id"]: r["display_name"] for r in cursor.fetchall()}

    impacts = []
    transferred_count = 0
    merged_count = 0
    self_conflict_count = 0

    for r in from_relations:
        r_id = r["relation_id"]
        type_id = r["relation_type_id"]
        started_on = r["started_on"]
        ended_on = r["ended_on"]

        # Calculate endpoint substitution
        new_subj = to_person_id if r["subject_person_id"] == from_person_id else r["subject_person_id"]
        new_obj = to_person_id if r["object_person_id"] == from_person_id else r["object_person_id"]

        # If symmetric, order endpoints
        if r["directionality"] == "symmetric":
            if new_subj > new_obj:
                new_subj, new_obj = new_obj, new_subj

        # Identify other person
        other_person_id = new_obj if new_subj == to_person_id else new_subj
        other_person_name = people_map.get(other_person_id, other_person_id)

        # Check self-relation
        if new_subj == new_obj:
            self_conflict_count += 1
            impacts.append(
                {
                    "relation_id": r_id,
                    "other_person_id": to_person_id,
                    "other_person_name": people_map.get(to_person_id, to_person_id),
                    "relation_type_id": type_id,
                    "relation_type_slug": r["slug"],
                    "relation_type_forward_label": r["forward_label"],
                    "relation_type_reverse_label": r["reverse_label"],
                    "started_on": started_on,
                    "ended_on": ended_on,
                    "result_type": "self_relation_conflict",
                    "surviving_relation_id": None,
                }
            )
            continue

        # Check semantic collision on target side
        cursor.execute(
            """
            SELECT relation_id FROM person_relations
            WHERE relation_type_id = ? AND subject_person_id = ? AND object_person_id = ?
              AND COALESCE(started_on, '') = COALESCE(?, '')
              AND COALESCE(ended_on, '') = COALESCE(?, '')
              AND relation_id != ?
            """,
            (type_id, new_subj, new_obj, started_on or "", ended_on or "", r_id),
        )
        existing_target = cursor.fetchone()

        if existing_target is not None:
            merged_count += 1
            surviving_id = existing_target["relation_id"]
            impacts.append(
                {
                    "relation_id": r_id,
                    "other_person_id": other_person_id,
                    "other_person_name": other_person_name,
                    "relation_type_id": type_id,
                    "relation_type_slug": r["slug"],
                    "relation_type_forward_label": r["forward_label"],
                    "relation_type_reverse_label": r["reverse_label"],
                    "started_on": started_on,
                    "ended_on": ended_on,
                    "result_type": "merged_into_existing",
                    "surviving_relation_id": surviving_id,
                }
            )
        else:
            transferred_count += 1
            impacts.append(
                {
                    "relation_id": r_id,
                    "other_person_id": other_person_id,
                    "other_person_name": other_person_name,
                    "relation_type_id": type_id,
                    "relation_type_slug": r["slug"],
                    "relation_type_forward_label": r["forward_label"],
                    "relation_type_reverse_label": r["reverse_label"],
                    "started_on": started_on,
                    "ended_on": ended_on,
                    "result_type": "transferred",
                    "surviving_relation_id": None,
                }
            )

    return {
        "transferred_relations_count": transferred_count,
        "merged_relations_count": merged_count,
        "self_relation_conflicts_count": self_conflict_count,
        "relation_impacts": impacts,
    }


def transfer_person_relations_on_merge(
    cursor: sqlite3.Cursor, from_person_id: str, to_person_id: str
) -> None:
    preview = preview_person_relation_merge(cursor, from_person_id, to_person_id)
    if preview["self_relation_conflicts_count"] > 0:
        raise SelfRelationError("Self-relation detected during merge execution")

    now_iso = datetime.now(JST).isoformat()

    cursor.execute(
        """
        SELECT r.relation_id, r.subject_person_id, r.object_person_id, r.relation_type_id,
               r.started_on, r.ended_on, r.note, t.directionality
        FROM person_relations r
        JOIN person_relation_types t ON r.relation_type_id = t.relation_type_id
        WHERE r.subject_person_id = ? OR r.object_person_id = ?
        """,
        (from_person_id, from_person_id),
    )
    relations_to_process = cursor.fetchall()

    for r in relations_to_process:
        r_id = r["relation_id"]
        type_id = r["relation_type_id"]
        started_on = r["started_on"]
        ended_on = r["ended_on"]
        note = r["note"]

        new_subj = to_person_id if r["subject_person_id"] == from_person_id else r["subject_person_id"]
        new_obj = to_person_id if r["object_person_id"] == from_person_id else r["object_person_id"]

        if r["directionality"] == "symmetric":
            if new_subj > new_obj:
                new_subj, new_obj = new_obj, new_subj

        # Check semantic collision with existing target relation
        cursor.execute(
            """
            SELECT relation_id, note FROM person_relations
            WHERE relation_type_id = ? AND subject_person_id = ? AND object_person_id = ?
              AND COALESCE(started_on, '') = COALESCE(?, '')
              AND COALESCE(ended_on, '') = COALESCE(?, '')
              AND relation_id != ?
            """,
            (type_id, new_subj, new_obj, started_on or "", ended_on or "", r_id),
        )
        existing_target = cursor.fetchone()

        if existing_target is not None:
            surviving_id = existing_target["relation_id"]
            merged_note = concatenate_notes(existing_target["note"], note)

            cursor.execute(
                "UPDATE person_relations SET note = ?, updated_at = ? WHERE relation_id = ?",
                (merged_note, now_iso, surviving_id),
            )

            # Move evidence to surviving_id with deduplication
            cursor.execute(
                "SELECT source_type, source_ref, quote, note, observed_at FROM person_relation_evidence WHERE relation_id = ?",
                (r_id,),
            )
            evs = [dict(ev) for ev in cursor.fetchall()]
            deduplicate_and_add_evidence(cursor, surviving_id, evs, now_iso)

            # Delete transferred relation r_id
            cursor.execute("DELETE FROM person_relations WHERE relation_id = ?", (r_id,))
        else:
            # Simple endpoint update
            cursor.execute(
                "UPDATE person_relations SET subject_person_id = ?, object_person_id = ?, updated_at = ? WHERE relation_id = ?",
                (new_subj, new_obj, now_iso, r_id),
            )


# --- Public Service Functions (Managing DB connection/transaction) ---


def list_person_relation_types() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT relation_type_id, slug, forward_label, reverse_label, directionality,
                   description, is_builtin, is_active, created_at, updated_at
            FROM person_relation_types
            ORDER BY is_builtin DESC, slug ASC
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "relation_type_id": r["relation_type_id"],
                "slug": r["slug"],
                "forward_label": r["forward_label"],
                "reverse_label": r["reverse_label"],
                "directionality": r["directionality"],
                "description": r["description"],
                "is_builtin": bool(r["is_builtin"]),
                "is_active": bool(r["is_active"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def create_person_relation_type(
    slug: str,
    forward_label: str,
    reverse_label: str,
    directionality: Literal["directed", "symmetric"],
    description: Optional[str] = None,
) -> dict[str, Any]:
    slug_clean = slug.strip()
    f_label = forward_label.strip()
    r_label = reverse_label.strip()
    if not slug_clean or not f_label or not r_label:
        raise ValueError("slug, forward_label, and reverse_label must not be empty")
    if directionality not in ("directed", "symmetric"):
        raise ValueError("directionality must be 'directed' or 'symmetric'")

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT relation_type_id FROM person_relation_types WHERE slug = ?", (slug_clean,))
            if cursor.fetchone() is not None:
                raise SlugConflictError(f"Relation type slug already exists: {slug_clean}")

            type_id = f"rlt_{uuid.uuid4().hex}"
            now_iso = datetime.now(JST).isoformat()
            cursor.execute(
                """
                INSERT INTO person_relation_types (
                    relation_type_id, slug, forward_label, reverse_label, directionality,
                    description, is_builtin, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
                """,
                (type_id, slug_clean, f_label, r_label, directionality, description, now_iso, now_iso),
            )
            cursor.execute(
                """
                SELECT relation_type_id, slug, forward_label, reverse_label, directionality,
                       description, is_builtin, is_active, created_at, updated_at
                FROM person_relation_types WHERE relation_type_id = ?
                """,
                (type_id,),
            )
            r = dict(cursor.fetchone())
            r["is_builtin"] = bool(r["is_builtin"])
            r["is_active"] = bool(r["is_active"])
            return r
    finally:
        conn.close()


def update_person_relation_type(
    relation_type_id: str,
    forward_label: Optional[str] = None,
    reverse_label: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT relation_type_id, forward_label, reverse_label, description, is_active "
                "FROM person_relation_types WHERE relation_type_id = ?",
                (relation_type_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError(f"Relation type not found: {relation_type_id}")
            curr = dict(row)

            new_f = forward_label.strip() if forward_label is not None else curr["forward_label"]
            new_r = reverse_label.strip() if reverse_label is not None else curr["reverse_label"]
            if not new_f or not new_r:
                raise ValueError("forward_label and reverse_label must not be empty")

            new_desc = description if description is not None else curr["description"]
            new_active = int(is_active) if is_active is not None else curr["is_active"]
            now_iso = datetime.now(JST).isoformat()

            cursor.execute(
                """
                UPDATE person_relation_types
                SET forward_label = ?, reverse_label = ?, description = ?, is_active = ?, updated_at = ?
                WHERE relation_type_id = ?
                """,
                (new_f, new_r, new_desc, new_active, now_iso, relation_type_id),
            )

            cursor.execute(
                """
                SELECT relation_type_id, slug, forward_label, reverse_label, directionality,
                       description, is_builtin, is_active, created_at, updated_at
                FROM person_relation_types WHERE relation_type_id = ?
                """,
                (relation_type_id,),
            )
            r = dict(cursor.fetchone())
            r["is_builtin"] = bool(r["is_builtin"])
            r["is_active"] = bool(r["is_active"])
            return r
    finally:
        conn.close()


def list_person_relations_for_person(
    person_id: str, status_filter: Optional[str] = None
) -> list[dict[str, Any]]:
    if status_filter and status_filter not in ("upcoming", "active", "ended", "undated"):
        raise ValueError(f"Invalid status filter: {status_filter}")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT person_id FROM people WHERE person_id = ?", (person_id,))
        if cursor.fetchone() is None:
            raise FileNotFoundError(f"Person not found: {person_id}")

        cursor.execute(
            "SELECT relation_id FROM person_relations WHERE subject_person_id = ? OR object_person_id = ? "
            "ORDER BY created_at DESC",
            (person_id, person_id),
        )
        rel_ids = [r["relation_id"] for r in cursor.fetchall()]

        results = []
        for r_id in rel_ids:
            rel = get_person_relation_by_id_in_tx(cursor, r_id)
            if status_filter and rel["status"] != status_filter:
                continue
            results.append(rel)
        return results
    finally:
        conn.close()


def create_person_relation(
    person_id: str,
    subject_person_id: str,
    object_person_id: str,
    relation_type_id: str,
    started_on: Optional[str] = None,
    ended_on: Optional[str] = None,
    note: Optional[str] = None,
    initial_evidence: Optional[list[dict[str, Any]]] = None,
) -> tuple[dict[str, Any], Literal["created", "merged_into_existing"]]:
    if person_id not in (subject_person_id, object_person_id):
        raise ValueError("URL person_id must match either subject_person_id or object_person_id")

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            # Verify subject and object people exist
            cursor.execute("SELECT person_id FROM people WHERE person_id = ?", (subject_person_id,))
            if cursor.fetchone() is None:
                raise FileNotFoundError(f"Person not found: {subject_person_id}")
            cursor.execute("SELECT person_id FROM people WHERE person_id = ?", (object_person_id,))
            if cursor.fetchone() is None:
                raise FileNotFoundError(f"Person not found: {object_person_id}")

            return create_person_relation_in_tx(
                cursor,
                subject_person_id=subject_person_id,
                object_person_id=object_person_id,
                relation_type_id=relation_type_id,
                started_on=started_on,
                ended_on=ended_on,
                note=note,
                initial_evidence=initial_evidence,
            )
    finally:
        conn.close()


def update_person_relation(
    relation_id: str,
    started_on: Optional[str] = None,
    ended_on: Optional[str] = None,
    note: Optional[str] = None,
) -> tuple[dict[str, Any], Literal["updated", "merged_into_existing"]]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            return update_person_relation_in_tx(
                cursor,
                relation_id=relation_id,
                started_on=started_on,
                ended_on=ended_on,
                note=note,
            )
    finally:
        conn.close()


def delete_person_relation(relation_id: str) -> None:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            delete_person_relation_in_tx(cursor, relation_id)
    finally:
        conn.close()


def add_relation_evidence(
    relation_id: str,
    source_type: str = "manual",
    source_ref: Optional[str] = None,
    quote: Optional[str] = None,
    note: Optional[str] = None,
    observed_at: Optional[str] = None,
) -> dict[str, Any]:
    if source_type != "manual":
        raise ValueError("source_type must be 'manual'")
    if observed_at is not None:
        validate_dates(observed_at, None)

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            # Existence check (raises FileNotFoundError for unknown IDs).
            get_person_relation_by_id_in_tx(cursor, relation_id)
            now_iso = datetime.now(JST).isoformat()
            deduplicate_and_add_evidence(
                cursor,
                relation_id,
                [
                    {
                        "source_type": source_type,
                        "source_ref": source_ref,
                        "quote": quote,
                        "note": note,
                        "observed_at": observed_at,
                    }
                ],
                now_iso,
            )
            return get_person_relation_by_id_in_tx(cursor, relation_id)
    finally:
        conn.close()


def update_relation_evidence(
    evidence_id: str,
    source_ref: Optional[str] = None,
    quote: Optional[str] = None,
    note: Optional[str] = None,
    observed_at: Optional[str] = None,
) -> dict[str, Any]:
    if observed_at is not None:
        validate_dates(observed_at, None)

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT evidence_id, relation_id, source_ref, quote, note, observed_at "
                "FROM person_relation_evidence WHERE evidence_id = ?",
                (evidence_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError(f"Relation evidence not found: {evidence_id}")
            ev = dict(row)

            now_iso = datetime.now(JST).isoformat()
            new_ref = source_ref if source_ref is not None else ev["source_ref"]
            new_quote = quote if quote is not None else ev["quote"]
            new_note = note if note is not None else ev["note"]
            new_obs = observed_at if observed_at is not None else ev["observed_at"]

            cursor.execute(
                """
                UPDATE person_relation_evidence
                SET source_ref = ?, quote = ?, note = ?, observed_at = ?, updated_at = ?
                WHERE evidence_id = ?
                """,
                (new_ref, new_quote, new_note, new_obs, now_iso, evidence_id),
            )
            return get_person_relation_by_id_in_tx(cursor, ev["relation_id"])
    finally:
        conn.close()


def delete_relation_evidence(evidence_id: str) -> None:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT evidence_id FROM person_relation_evidence WHERE evidence_id = ?",
                (evidence_id,),
            )
            if cursor.fetchone() is None:
                raise FileNotFoundError(f"Relation evidence not found: {evidence_id}")
            cursor.execute("DELETE FROM person_relation_evidence WHERE evidence_id = ?", (evidence_id,))
    finally:
        conn.close()
