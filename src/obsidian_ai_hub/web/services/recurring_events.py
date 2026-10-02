"""Domain service for recurring events (定期記録・リマインダー)."""

from __future__ import annotations

import calendar
import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from obsidian_ai_hub.database import get_db_connection

JST = timezone(timedelta(hours=9))


class RecurringEventError(Exception):
    """Base exception for recurring event domain errors."""
    pass


class EventTypeNotFoundError(RecurringEventError):
    pass


class EventTypeSchemaLockedError(RecurringEventError):
    pass


class SeriesNotFoundError(RecurringEventError):
    pass


class SeriesAlreadyExistsError(RecurringEventError):
    pass


class RecordNotFoundError(RecurringEventError):
    pass


class InvalidExecutionDateError(RecurringEventError):
    pass


class MediaReferencedError(RecurringEventError):
    pass


def get_jst_now() -> datetime:
    return datetime.now(JST)


def get_jst_today() -> date:
    return get_jst_now().date()


def compute_next_due_date(executed_on: date, interval_value: int, interval_unit: str) -> date:
    """Compute next due date given an execution date and recommended interval."""
    if interval_unit == "day":
        return executed_on + timedelta(days=interval_value)
    elif interval_unit == "week":
        return executed_on + timedelta(days=interval_value * 7)
    elif interval_unit == "month":
        year = executed_on.year + (executed_on.month + interval_value - 1) // 12
        month = (executed_on.month + interval_value - 1) % 12 + 1
        max_day = calendar.monthrange(year, month)[1]
        day = min(executed_on.day, max_day)
        return date(year, month, day)
    else:
        raise ValueError(f"Invalid interval unit: {interval_unit}")


def compute_props_hash(normalized_props: Dict[str, Any]) -> str:
    """Compute a deterministic hash for series property values.

    normalized_props should be a dict of property_id -> formatted_value_str.
    """
    serialized = json.dumps(normalized_props, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# --- Event Types ---

def create_event_type(
    name: str,
    properties: Optional[List[Dict[str, Any]]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Create a new recurring event type with optional property definitions."""
    name = name.strip()
    if not name:
        raise ValueError("Event type name cannot be empty")

    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        now = get_jst_now().isoformat()
        type_id = f"ret_{uuid.uuid4().hex[:12]}"

        # Check unique name
        cur = db.execute("SELECT type_id FROM recurring_event_types WHERE name = ?", (name,))
        if cur.fetchone():
            raise ValueError(f"Event type with name '{name}' already exists")

        db.execute(
            "INSERT INTO recurring_event_types (type_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (type_id, name, now, now),
        )

        if properties:
            for prop in properties:
                prop_key = prop["key"].strip()
                prop_display = prop["display_name"].strip()
                data_type = prop["data_type"]
                if data_type not in ("text", "number", "select"):
                    raise ValueError(f"Invalid property data_type: {data_type}")

                property_id = f"retp_{uuid.uuid4().hex[:12]}"
                db.execute(
                    """
                    INSERT INTO recurring_event_type_properties (
                        property_id, type_id, key, display_name, data_type, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (property_id, type_id, prop_key, prop_display, data_type, now, now),
                )

                if data_type == "select":
                    options = prop.get("options") or []
                    for order, opt in enumerate(options):
                        opt_key = opt["option_key"].strip()
                        opt_display = opt["display_name"].strip()
                        option_id = f"reto_{uuid.uuid4().hex[:12]}"
                        db.execute(
                            """
                            INSERT INTO recurring_event_type_options (
                                option_id, property_id, option_key, display_name, display_order, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (option_id, property_id, opt_key, opt_display, order, now, now),
                        )

        if own_conn:
            db.commit()
        return get_event_type(type_id, conn=db)
    finally:
        if own_conn:
            db.close()


# --- Reminders & Notifications ---

def evaluate_and_send_reminders(now: Optional[datetime] = None, conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """Evaluate due recurring event series and dispatch notifications.

    Evaluated only when JST time >= 09:00 AM.
    Finds series where next_due_date <= today_JST that have not had a notification attempt for that due_date yet.
    """
    now_jst = now.astimezone(JST) if now is not None else get_jst_now()
    if now_jst.hour < 9:
        return []

    today_jst_str = now_jst.date().isoformat()

    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    dispatched_attempts = []

    try:
        from obsidian_ai_hub.notifications.models import NotificationEvent
        from obsidian_ai_hub.notifications.publisher import publish_notification
        from obsidian_ai_hub.notifications.store import get_notification_settings

        all_series = list_series(conn=db)
        due_series = [s for s in all_series if s.get("next_due_date") and s["next_due_date"] <= today_jst_str]

        if not due_series:
            return []

        settings = get_notification_settings()
        action_required_enabled = (
            (settings.get("web_push_enabled") and settings.get("web_push_action_required")) or
            (settings.get("line_enabled") and settings.get("line_action_required"))
        )

        for s in due_series:
            series_id = s["series_id"]
            due_date = s["next_due_date"]

            # Check if attempt already exists for (series_id, due_date)
            cur = db.execute(
                "SELECT attempt_id FROM recurring_event_notification_attempts WHERE series_id = ? AND due_date = ?",
                (series_id, due_date),
            )
            if cur.fetchone():
                continue

            attempt_id = f"rena_{uuid.uuid4().hex[:12]}"
            attempted_at = now_jst.isoformat()

            if not action_required_enabled:
                # Record suppressed attempt
                db.execute(
                    """
                    INSERT INTO recurring_event_notification_attempts (
                        attempt_id, series_id, due_date, status, error_message, attempted_at
                    ) VALUES (?, ?, ?, 'suppressed', NULL, ?)
                    """,
                    (attempt_id, series_id, due_date, attempted_at),
                )
                db.commit()
                dispatched_attempts.append({"series_id": series_id, "due_date": due_date, "status": "suppressed"})
                continue

            # Insert initial 'failed' claim to secure uniqueness and handle crashed sends
            db.execute(
                """
                INSERT INTO recurring_event_notification_attempts (
                    attempt_id, series_id, due_date, status, error_message, attempted_at
                ) VALUES (?, ?, ?, 'failed', 'In-flight delivery claim', ?)
                """,
                (attempt_id, series_id, due_date, attempted_at),
            )
            db.commit()

            # Format properties
            props_parts = []
            for p in s.get("properties") or []:
                if p.get("display_name") and p.get("value_display"):
                    props_parts.append(f"{p['display_name']}={p['value_display']}")
            props_str = f" ({', '.join(props_parts)})" if props_parts else ""

            body = f"{s['type_name']}{props_str} 期限日: {due_date}"

            event = NotificationEvent(
                event_type="recurring_event_reminder",
                target_id=series_id,
                relative_link="/recurring-events",
                category="action_required",
                title=f"【定期記録】{s['type_name']}",
                body=body,
            )

            sent = publish_notification(event)
            final_status = "sent" if sent else "failed"
            err_msg = None if sent else "Notification publisher returned false or failed"

            db.execute(
                "UPDATE recurring_event_notification_attempts SET status = ?, error_message = ? WHERE attempt_id = ?",
                (final_status, err_msg, attempt_id),
            )
            db.commit()

            dispatched_attempts.append({"series_id": series_id, "due_date": due_date, "status": final_status})

        return dispatched_attempts
    finally:
        if own_conn:
            db.close()


def get_event_type(type_id: str, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        cur = db.execute("SELECT * FROM recurring_event_types WHERE type_id = ?", (type_id,))
        row = cur.fetchone()
        if not row:
            raise EventTypeNotFoundError(f"Event type {type_id} not found")

        res = dict(row)
        # Fetch properties
        p_cur = db.execute(
            "SELECT * FROM recurring_event_type_properties WHERE type_id = ? ORDER BY created_at ASC",
            (type_id,),
        )
        props = [dict(p) for p in p_cur.fetchall()]
        for p in props:
            if p["data_type"] == "select":
                o_cur = db.execute(
                    "SELECT * FROM recurring_event_type_options WHERE property_id = ? ORDER BY display_order ASC, created_at ASC",
                    (p["property_id"],),
                )
                p["options"] = [dict(o) for o in o_cur.fetchall()]
            else:
                p["options"] = []
        res["properties"] = props

        # Count series
        s_cur = db.execute("SELECT COUNT(*) FROM recurring_event_series WHERE type_id = ?", (type_id,))
        res["series_count"] = s_cur.fetchone()[0]

        return res
    finally:
        if own_conn:
            db.close()


def list_event_types(conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        cur = db.execute("SELECT type_id FROM recurring_event_types ORDER BY name ASC")
        type_ids = [r[0] for r in cur.fetchall()]
        return [get_event_type(tid, conn=db) for tid in type_ids]
    finally:
        if own_conn:
            db.close()


def update_event_type(
    type_id: str,
    name: Optional[str] = None,
    properties: Optional[List[Dict[str, Any]]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Update event type name and/or property definitions.

    If series exist for this type, schema-breaking modifications are blocked:
    - Cannot add/delete property definitions.
    - Cannot change key or data_type of existing property definitions.
    - Cannot delete options from select properties.
    Allowed when series exist:
    - Change event type display name.
    - Change display_name of properties/options.
    - Add new options to select properties.
    """
    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        event_type = get_event_type(type_id, conn=db)
        has_series = event_type["series_count"] > 0
        now = get_jst_now().isoformat()

        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Event type name cannot be empty")
            # Check unique
            cur = db.execute("SELECT type_id FROM recurring_event_types WHERE name = ? AND type_id != ?", (name, type_id))
            if cur.fetchone():
                raise ValueError(f"Event type with name '{name}' already exists")
            db.execute("UPDATE recurring_event_types SET name = ?, updated_at = ? WHERE type_id = ?", (name, now, type_id))

        if properties is not None:
            existing_props = {p["property_id"]: p for p in event_type["properties"]}
            existing_keys = {p["key"]: p for p in event_type["properties"]}

            if has_series:
                # Check for prohibited structural schema changes
                new_prop_keys = {p.get("key", "").strip() for p in properties if p.get("key")}
                old_prop_keys = set(existing_keys.keys())

                if new_prop_keys != old_prop_keys:
                    raise EventTypeSchemaLockedError(
                        "Cannot add, remove, or rename property keys when series already exist for this event type."
                    )

                for prop in properties:
                    p_key = prop["key"].strip()
                    old_prop = existing_keys[p_key]

                    if prop.get("data_type") and prop["data_type"] != old_prop["data_type"]:
                        raise EventTypeSchemaLockedError(
                            f"Cannot change data_type for property '{p_key}' when series exist."
                        )

                    # Update display_name of property
                    if prop.get("display_name"):
                        db.execute(
                            "UPDATE recurring_event_type_properties SET display_name = ?, updated_at = ? WHERE property_id = ?",
                            (prop["display_name"].strip(), now, old_prop["property_id"]),
                        )

                    if old_prop["data_type"] == "select":
                        existing_opts = {o["option_key"]: o for o in old_prop["options"]}
                        new_opts = prop.get("options") or []
                        new_opt_keys = {o["option_key"].strip() for o in new_opts if o.get("option_key")}

                        # Check that no existing option was deleted
                        if not set(existing_opts.keys()).issubset(new_opt_keys):
                            raise EventTypeSchemaLockedError(
                                f"Cannot remove existing options from select property '{p_key}' when series exist."
                            )

                        for order, opt in enumerate(new_opts):
                            opt_key = opt["option_key"].strip()
                            opt_display = opt["display_name"].strip()

                            if opt_key in existing_opts:
                                # Update display name / order
                                opt_id = existing_opts[opt_key]["option_id"]
                                db.execute(
                                    """
                                    UPDATE recurring_event_type_options
                                    SET display_name = ?, display_order = ?, updated_at = ?
                                    WHERE option_id = ?
                                    """,
                                    (opt_display, order, now, opt_id),
                                )
                            else:
                                # Add new option
                                option_id = f"reto_{uuid.uuid4().hex[:12]}"
                                db.execute(
                                    """
                                    INSERT INTO recurring_event_type_options (
                                        option_id, property_id, option_key, display_name, display_order, created_at, updated_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (option_id, old_prop["property_id"], opt_key, opt_display, order, now, now),
                                )
            else:
                # No series exist: can do full property list replacement
                # First delete existing properties (and options via CASCADE)
                db.execute("DELETE FROM recurring_event_type_properties WHERE type_id = ?", (type_id,))

                for prop in properties:
                    prop_key = prop["key"].strip()
                    prop_display = prop["display_name"].strip()
                    data_type = prop["data_type"]
                    if data_type not in ("text", "number", "select"):
                        raise ValueError(f"Invalid property data_type: {data_type}")

                    property_id = f"retp_{uuid.uuid4().hex[:12]}"
                    db.execute(
                        """
                        INSERT INTO recurring_event_type_properties (
                            property_id, type_id, key, display_name, data_type, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (property_id, type_id, prop_key, prop_display, data_type, now, now),
                    )

                    if data_type == "select":
                        options = prop.get("options") or []
                        for order, opt in enumerate(options):
                            opt_key = opt["option_key"].strip()
                            opt_display = opt["display_name"].strip()
                            option_id = f"reto_{uuid.uuid4().hex[:12]}"
                            db.execute(
                                """
                                INSERT INTO recurring_event_type_options (
                                    option_id, property_id, option_key, display_name, display_order, created_at, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (option_id, property_id, opt_key, opt_display, order, now, now),
                            )

        if own_conn:
            db.commit()
        return get_event_type(type_id, conn=db)
    finally:
        if own_conn:
            db.close()


def delete_event_type(type_id: str, conn: Optional[sqlite3.Connection] = None) -> None:
    """Delete event type. Fails if series exist."""
    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        event_type = get_event_type(type_id, conn=db)
        if event_type["series_count"] > 0:
            raise EventTypeSchemaLockedError("Cannot delete event type that has existing series.")

        db.execute("DELETE FROM recurring_event_types WHERE type_id = ?", (type_id,))
        if own_conn:
            db.commit()
    finally:
        if own_conn:
            db.close()


# --- Series & Records ---

def validate_and_format_property_values(
    event_type: Dict[str, Any],
    property_values: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Validate property values against event type schema.

    Returns (raw_value_records, normalized_hash_dict).
    raw_value_records maps property_id -> dict with keys:
      - value_text
      - value_number
      - option_id
    normalized_hash_dict maps property_id -> canonical string for hashing.
    """
    props = event_type["properties"]
    prop_by_key = {p["key"]: p for p in props}

    if set(prop_by_key.keys()) != set(property_values.keys()):
        missing = set(prop_by_key.keys()) - set(property_values.keys())
        extra = set(property_values.keys()) - set(prop_by_key.keys())
        errs = []
        if missing:
            errs.append(f"missing properties: {missing}")
        if extra:
            errs.append(f"unexpected properties: {extra}")
        raise ValueError(f"Property value mismatch: {', '.join(errs)}")

    raw_records: Dict[str, Any] = {}
    normalized_hash: Dict[str, str] = {}

    for p in props:
        pid = p["property_id"]
        pkey = p["key"]
        val = property_values[pkey]
        dtype = p["data_type"]

        if dtype == "text":
            val_str = str(val).strip() if val is not None else ""
            if not val_str:
                raise ValueError(f"Property '{pkey}' (text) cannot be empty")
            raw_records[pid] = {"value_text": val_str, "value_number": None, "option_id": None}
            normalized_hash[pid] = f"text:{val_str}"

        elif dtype == "number":
            try:
                val_num = float(val)
            except (ValueError, TypeError):
                raise ValueError(f"Property '{pkey}' (number) must be a valid number")
            raw_records[pid] = {"value_text": None, "value_number": val_num, "option_id": None}
            normalized_hash[pid] = f"number:{val_num}"

        elif dtype == "select":
            val_opt_key = str(val).strip()
            opt_matches = [o for o in p["options"] if o["option_key"] == val_opt_key]
            if not opt_matches:
                raise ValueError(f"Property '{pkey}' option_key '{val_opt_key}' not found in options")
            opt_id = opt_matches[0]["option_id"]
            raw_records[pid] = {"value_text": None, "value_number": None, "option_id": opt_id}
            normalized_hash[pid] = f"select:{opt_id}"

    return raw_records, normalized_hash


def create_series_with_start_record(
    type_id: str,
    interval_value: int,
    interval_unit: str,
    property_values: Dict[str, Any],
    executed_on: str,  # YYYY-MM-DD JST
    note: Optional[str] = None,
    media_id: Optional[str] = None,
    count_contribution: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Create a new series along with its initial start record."""
    if interval_value <= 0:
        raise ValueError("interval_value must be a positive integer")
    if interval_unit not in ("day", "week", "month"):
        raise ValueError(f"Invalid interval_unit: {interval_unit}")

    # Validate executed_on JST date
    try:
        exec_date = date.fromisoformat(executed_on.strip())
    except ValueError:
        raise InvalidExecutionDateError(f"Invalid executed_on date format: {executed_on}")

    today_jst = get_jst_today()
    if exec_date > today_jst:
        raise InvalidExecutionDateError(f"executed_on date ({executed_on}) cannot be in the future (today JST is {today_jst.isoformat()})")

    start_count = 1 if count_contribution is None else int(count_contribution)
    if start_count < 0:
        raise ValueError("count_contribution cannot be negative")

    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        event_type = get_event_type(type_id, conn=db)
        raw_prop_recs, norm_hash_dict = validate_and_format_property_values(event_type, property_values)
        props_hash = compute_props_hash(norm_hash_dict)

        # Check unique series
        cur = db.execute(
            "SELECT series_id FROM recurring_event_series WHERE type_id = ? AND props_hash = ?",
            (type_id, props_hash),
        )
        if cur.fetchone():
            raise SeriesAlreadyExistsError("A series with the same type and property values combination already exists.")

        now = get_jst_now().isoformat()
        series_id = f"res_{uuid.uuid4().hex[:12]}"

        # Insert series
        db.execute(
            """
            INSERT INTO recurring_event_series (
                series_id, type_id, interval_value, interval_unit, props_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (series_id, type_id, interval_value, interval_unit, props_hash, now, now),
        )

        # Insert series property values
        for pid, pdata in raw_prop_recs.items():
            db.execute(
                """
                INSERT INTO recurring_event_series_property_values (
                    series_id, property_id, value_text, value_number, option_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (series_id, pid, pdata["value_text"], pdata["value_number"], pdata["option_id"]),
            )

        # Insert start record
        record_id = f"rer_{uuid.uuid4().hex[:12]}"
        db.execute(
            """
            INSERT INTO recurring_event_records (
                record_id, series_id, executed_on, note, media_id, count_contribution, is_start_record, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (record_id, series_id, exec_date.isoformat(), note, media_id, start_count, now, now),
        )

        if own_conn:
            db.commit()

        return get_series_detail(series_id, conn=db)
    finally:
        if own_conn:
            db.close()


def update_series_interval(
    series_id: str,
    interval_value: int,
    interval_unit: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Update recommended interval of a series."""
    if interval_value <= 0:
        raise ValueError("interval_value must be a positive integer")
    if interval_unit not in ("day", "week", "month"):
        raise ValueError(f"Invalid interval_unit: {interval_unit}")

    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        # Check series exists
        get_series_detail(series_id, conn=db)

        now = get_jst_now().isoformat()
        db.execute(
            "UPDATE recurring_event_series SET interval_value = ?, interval_unit = ?, updated_at = ? WHERE series_id = ?",
            (interval_value, interval_unit, now, series_id),
        )

        if own_conn:
            db.commit()

        return get_series_detail(series_id, conn=db)
    finally:
        if own_conn:
            db.close()


def add_execution_record(
    series_id: str,
    executed_on: str,  # YYYY-MM-DD JST
    note: Optional[str] = None,
    media_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Add a new execution record to an existing series. count_contribution is always 1."""
    try:
        exec_date = date.fromisoformat(executed_on.strip())
    except ValueError:
        raise InvalidExecutionDateError(f"Invalid executed_on date format: {executed_on}")

    today_jst = get_jst_today()
    if exec_date > today_jst:
        raise InvalidExecutionDateError(f"executed_on date ({executed_on}) cannot be in the future (today JST is {today_jst.isoformat()})")

    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        get_series_detail(series_id, conn=db)

        now = get_jst_now().isoformat()
        record_id = f"rer_{uuid.uuid4().hex[:12]}"
        db.execute(
            """
            INSERT INTO recurring_event_records (
                record_id, series_id, executed_on, note, media_id, count_contribution, is_start_record, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?)
            """,
            (record_id, series_id, exec_date.isoformat(), note, media_id, now, now),
        )

        if own_conn:
            db.commit()

        return get_series_detail(series_id, conn=db)
    finally:
        if own_conn:
            db.close()


def update_execution_record(
    record_id: str,
    executed_on: Optional[str] = None,
    note: Optional[str] = None,
    media_id: Optional[str] = None,
    clear_media: bool = False,
    count_contribution: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Update an existing execution record.

    Note: count_contribution can only be updated if is_start_record == 1.
    For non-start records, count_contribution is ignored and stays 1.
    """
    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        cur = db.execute("SELECT * FROM recurring_event_records WHERE record_id = ?", (record_id,))
        rec = cur.fetchone()
        if not rec:
            raise RecordNotFoundError(f"Record {record_id} not found")

        rec_dict = dict(rec)
        series_id = rec_dict["series_id"]
        is_start = rec_dict["is_start_record"] == 1

        now = get_jst_now().isoformat()
        updates = ["updated_at = ?"]
        params = [now]

        if executed_on is not None:
            try:
                exec_date = date.fromisoformat(executed_on.strip())
            except ValueError:
                raise InvalidExecutionDateError(f"Invalid executed_on date format: {executed_on}")
            today_jst = get_jst_today()
            if exec_date > today_jst:
                raise InvalidExecutionDateError(f"executed_on date ({executed_on}) cannot be in the future (today JST is {today_jst.isoformat()})")
            updates.append("executed_on = ?")
            params.append(exec_date.isoformat())

        if note is not None:
            updates.append("note = ?")
            params.append(note)

        if clear_media:
            updates.append("media_id = NULL")
        elif media_id is not None:
            updates.append("media_id = ?")
            params.append(media_id)

        if is_start and count_contribution is not None:
            cnt = int(count_contribution)
            if cnt < 0:
                raise ValueError("count_contribution cannot be negative")
            updates.append("count_contribution = ?")
            params.append(cnt)

        params.append(record_id)
        sql = f"UPDATE recurring_event_records SET {', '.join(updates)} WHERE record_id = ?"
        db.execute(sql, params)

        if own_conn:
            db.commit()

        return get_series_detail(series_id, conn=db)
    finally:
        if own_conn:
            db.close()


def delete_execution_record(record_id: str, conn: Optional[sqlite3.Connection] = None) -> Tuple[Optional[str], bool]:
    """Delete an execution record.

    If this was the last record in the series, deletes the entire series as well.
    Returns (series_id, series_deleted).
    """
    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        cur = db.execute("SELECT series_id FROM recurring_event_records WHERE record_id = ?", (record_id,))
        rec = cur.fetchone()
        if not rec:
            raise RecordNotFoundError(f"Record {record_id} not found")

        series_id = rec[0]

        # Delete the record
        db.execute("DELETE FROM recurring_event_records WHERE record_id = ?", (record_id,))

        # Check remaining records count
        r_cur = db.execute("SELECT COUNT(*) FROM recurring_event_records WHERE series_id = ?", (series_id,))
        remaining = r_cur.fetchone()[0]

        series_deleted = False
        if remaining == 0:
            # Delete series (cascades to property values and notification attempts)
            db.execute("DELETE FROM recurring_event_series WHERE series_id = ?", (series_id,))
            series_deleted = True

        if own_conn:
            db.commit()

        return (None if series_deleted else series_id), series_deleted
    finally:
        if own_conn:
            db.close()


def get_series_detail(series_id: str, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Get full series detail with computed metrics and records in executed_on DESC order."""
    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        s_cur = db.execute(
            """
            SELECT s.*, t.name as type_name
            FROM recurring_event_series s
            JOIN recurring_event_types t ON s.type_id = t.type_id
            WHERE s.series_id = ?
            """,
            (series_id,),
        )
        series_row = s_cur.fetchone()
        if not series_row:
            raise SeriesNotFoundError(f"Series {series_id} not found")

        series_dict = dict(series_row)
        type_id = series_dict["type_id"]

        # Fetch event type and property definitions
        event_type = get_event_type(type_id, conn=db)

        # Fetch series property values
        pv_cur = db.execute(
            """
            SELECT pv.*, p.key as property_key, p.display_name as property_display_name, p.data_type,
                   o.option_key, o.display_name as option_display_name
            FROM recurring_event_series_property_values pv
            JOIN recurring_event_type_properties p ON pv.property_id = p.property_id
            LEFT JOIN recurring_event_type_options o ON pv.option_id = o.option_id
            WHERE pv.series_id = ?
            ORDER BY p.created_at ASC
            """,
            (series_id,),
        )
        pv_rows = pv_cur.fetchall()
        properties_list = []
        properties_dict = {}
        for r in pv_rows:
            r_dict = dict(r)
            dtype = r_dict["data_type"]
            val = None
            val_display = None
            if dtype == "text":
                val = r_dict["value_text"]
                val_display = val
            elif dtype == "number":
                val = r_dict["value_number"]
                val_display = str(val)
            elif dtype == "select":
                val = r_dict["option_key"]
                val_display = r_dict["option_display_name"]

            item = {
                "property_id": r_dict["property_id"],
                "key": r_dict["property_key"],
                "display_name": r_dict["property_display_name"],
                "data_type": dtype,
                "value": val,
                "value_display": val_display,
            }
            properties_list.append(item)
            properties_dict[r_dict["property_key"]] = val

        # Fetch records in executed_on DESC, created_at DESC order
        r_cur = db.execute(
            "SELECT * FROM recurring_event_records WHERE series_id = ? ORDER BY executed_on DESC, created_at DESC",
            (series_id,),
        )
        record_rows = [dict(r) for r in r_cur.fetchall()]

        # Attach media references to records
        from obsidian_ai_hub.media import store as media_store

        formatted_records = []
        total_count = 0
        for r in record_rows:
            cnt = r["count_contribution"]
            total_count += cnt
            med_ref = None
            if r["media_id"]:
                med_row = media_store.get_generated_media(r["media_id"])
                if med_row:
                    med_ref = media_store.media_reference(med_row)

            rec_item = {
                "record_id": r["record_id"],
                "series_id": r["series_id"],
                "executed_on": r["executed_on"],
                "note": r["note"],
                "media_id": r["media_id"],
                "media": med_ref,
                "count_contribution": cnt,
                "is_start_record": bool(r["is_start_record"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            formatted_records.append(rec_item)

        # Computed metrics
        latest_executed_on = None
        next_due_date = None
        elapsed_days = None
        latest_photo_thumbnail = None
        latest_note = None

        if formatted_records:
            latest_rec = formatted_records[0]  # First record is latest because of executed_on DESC
            latest_executed_on_str = latest_rec["executed_on"]
            latest_executed_on = date.fromisoformat(latest_executed_on_str)

            # Find latest photo
            for r in formatted_records:
                if r["media"]:
                    latest_photo_thumbnail = r["media"]
                    break

            latest_note = latest_rec["note"]

            today_jst = get_jst_today()
            elapsed_days = (today_jst - latest_executed_on).days
            next_due_date = compute_next_due_date(
                latest_executed_on, series_dict["interval_value"], series_dict["interval_unit"]
            )

        res = {
            "series_id": series_id,
            "type_id": type_id,
            "type_name": series_dict["type_name"],
            "interval_value": series_dict["interval_value"],
            "interval_unit": series_dict["interval_unit"],
            "properties": properties_list,
            "properties_dict": properties_dict,
            "latest_executed_on": latest_executed_on.isoformat() if latest_executed_on else None,
            "next_due_date": next_due_date.isoformat() if next_due_date else None,
            "elapsed_days": elapsed_days,
            "total_count": total_count,
            "latest_photo_thumbnail": latest_photo_thumbnail,
            "latest_note": latest_note,
            "records": formatted_records,
            "created_at": series_dict["created_at"],
            "updated_at": series_dict["updated_at"],
        }
        return res
    finally:
        if own_conn:
            db.close()


def list_series(conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """List all series sorted by next_due_date ASC (earliest due first)."""
    own_conn = conn is None
    db = conn if conn is not None else get_db_connection()
    try:
        s_cur = db.execute("SELECT series_id FROM recurring_event_series")
        series_ids = [r[0] for r in s_cur.fetchall()]

        all_series = [get_series_detail(sid, conn=db) for sid in series_ids]

        # Sort by next_due_date ASC (None goes last if any)
        def sort_key(s: Dict[str, Any]):
            nd = s.get("next_due_date")
            return (0, nd) if nd else (1, "")

        all_series.sort(key=sort_key)
        return all_series
    finally:
        if own_conn:
            db.close()
