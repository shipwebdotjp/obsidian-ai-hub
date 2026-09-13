import re
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils.dates import (
    get_partial_date_bounds,
    parse_and_normalize_partial_date,
)
from obsidian_ai_hub.utils.periods import periods_overlap, temporal_ranges_overlap

JST = ZoneInfo("Asia/Tokyo")


class KeyConflictError(ValueError):
    def __init__(self, message="Property key or alias key already exists"):
        super().__init__(message)


class VaultSourceReadOnlyError(ValueError):
    def __init__(self, message="Vault source properties are read-only and managed via Vault notes and sync"):
        super().__init__(message)


class OptionInUseError(ValueError):
    def __init__(self, message="Cannot delete option that is currently in use"):
        super().__init__(message)


class SingleCardinalityOverlapError(ValueError):
    def __init__(self, message="Single cardinality property value period overlaps with an existing entry"):
        super().__init__(message)


class InvalidValueError(ValueError):
    def __init__(self, message="Invalid property value for definition data type"):
        super().__init__(message)


class PropertyConflictError(ValueError):
    def __init__(self, message="Property conflict detected"):
        super().__init__(message)


def validate_and_normalize_partial_date(d_val: Optional[str]) -> Optional[str]:
    if d_val is None:
        return None
    s = str(d_val).strip()
    if not s:
        return None
    try:
        return parse_and_normalize_partial_date(s)
    except ValueError as e:
        raise InvalidValueError(f"Invalid date: {d_val}") from e


def validate_yyyy_mm_dd(d_val: Optional[str]) -> None:
    validate_and_normalize_partial_date(d_val)


def get_property_definition_by_id_in_tx(
    cursor: sqlite3.Cursor, property_definition_id: str
) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT property_definition_id, key, display_name, data_type, cardinality, source_type, created_at, updated_at
        FROM person_property_definitions
        WHERE property_definition_id = ?
        """,
        (property_definition_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise FileNotFoundError(f"Property definition not found: {property_definition_id}")
    defn = dict(row)

    # Fetch aliases
    cursor.execute(
        "SELECT alias_key FROM person_property_definition_aliases WHERE property_definition_id = ? ORDER BY alias_key ASC",
        (property_definition_id,),
    )
    defn["aliases"] = [r["alias_key"] for r in cursor.fetchall()]

    # Fetch options with option aliases
    cursor.execute(
        """
        SELECT option_id, option_key, display_name, display_order
        FROM person_property_options
        WHERE property_definition_id = ?
        ORDER BY display_order ASC, option_key ASC
        """,
        (property_definition_id,),
    )
    opt_rows = cursor.fetchall()
    options = []
    for opt_r in opt_rows:
        opt_dict = dict(opt_r)
        cursor.execute(
            "SELECT alias_value FROM person_property_option_aliases WHERE option_id = ? ORDER BY alias_value ASC",
            (opt_dict["option_id"],),
        )
        opt_dict["aliases"] = [r["alias_value"] for r in cursor.fetchall()]
        options.append(opt_dict)

    defn["options"] = options
    return defn


def list_property_definitions_in_tx(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    cursor.execute(
        "SELECT property_definition_id FROM person_property_definitions ORDER BY key ASC"
    )
    def_ids = [r["property_definition_id"] for r in cursor.fetchall()]
    return [get_property_definition_by_id_in_tx(cursor, d_id) for d_id in def_ids]


def create_property_definition_in_tx(
    cursor: sqlite3.Cursor,
    key: str,
    display_name: str,
    data_type: str,
    cardinality: str,
    source_type: str = "database",
    aliases: Optional[list[str]] = None,
    options: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    clean_key = key.strip()
    clean_name = display_name.strip()
    if not clean_key or not clean_name:
        raise ValueError("key and display_name must not be empty")
    if data_type not in ("text", "date", "number", "boolean", "select"):
        raise ValueError(f"Invalid data_type: {data_type}")
    if cardinality not in ("single", "multiple"):
        raise ValueError(f"Invalid cardinality: {cardinality}")
    if source_type not in ("database", "vault"):
        raise ValueError(f"Invalid source_type: {source_type}")

    # Check key uniqueness
    cursor.execute(
        "SELECT property_definition_id FROM person_property_definitions WHERE key = ?",
        (clean_key,),
    )
    if cursor.fetchone() is not None:
        raise KeyConflictError(f"Property definition key already exists: {clean_key}")

    cursor.execute(
        "SELECT alias_id FROM person_property_definition_aliases WHERE alias_key = ?",
        (clean_key,),
    )
    if cursor.fetchone() is not None:
        raise KeyConflictError(f"Property definition alias already exists for key: {clean_key}")

    # Process definition aliases
    clean_aliases = []
    if aliases:
        for a in aliases:
            ca = a.strip()
            if ca and ca not in clean_aliases:
                cursor.execute(
                    "SELECT property_definition_id FROM person_property_definitions WHERE key = ?",
                    (ca,),
                )
                if cursor.fetchone() is not None:
                    raise KeyConflictError(f"Alias '{ca}' conflicts with an existing definition key")
                cursor.execute(
                    "SELECT alias_id FROM person_property_definition_aliases WHERE alias_key = ?",
                    (ca,),
                )
                if cursor.fetchone() is not None:
                    raise KeyConflictError(f"Alias '{ca}' already exists")
                clean_aliases.append(ca)

    now_iso = datetime.now(JST).isoformat()
    def_id = f"propdef_{uuid.uuid4().hex}"

    cursor.execute(
        """
        INSERT INTO person_property_definitions (
            property_definition_id, key, display_name, data_type, cardinality, source_type, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (def_id, clean_key, clean_name, data_type, cardinality, source_type, now_iso, now_iso),
    )

    for ca in clean_aliases:
        alias_id = f"pdalias_{uuid.uuid4().hex}"
        cursor.execute(
            """
            INSERT INTO person_property_definition_aliases (
                alias_id, property_definition_id, alias_key, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (alias_id, def_id, ca, now_iso),
        )

    if data_type == "select":
        if not options:
            raise ValueError("options are required for data_type 'select'")
        for opt in options:
            opt_key = opt["option_key"].strip()
            opt_name = opt["display_name"].strip()
            opt_order = opt.get("display_order", 0)
            opt_aliases = opt.get("aliases", [])

            opt_id = f"propopt_{uuid.uuid4().hex}"
            cursor.execute(
                """
                INSERT INTO person_property_options (
                    option_id, property_definition_id, option_key, display_name, display_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (opt_id, def_id, opt_key, opt_name, opt_order, now_iso, now_iso),
            )
            for opt_a in opt_aliases:
                ca_val = opt_a.strip()
                if ca_val:
                    opt_alias_id = f"poalias_{uuid.uuid4().hex}"
                    cursor.execute(
                        """
                        INSERT INTO person_property_option_aliases (
                            alias_id, option_id, alias_value, created_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (opt_alias_id, opt_id, ca_val, now_iso),
                    )

    return get_property_definition_by_id_in_tx(cursor, def_id)


def update_property_definition_in_tx(
    cursor: sqlite3.Cursor,
    property_definition_id: str,
    display_name: Optional[str] = None,
    aliases: Optional[list[str]] = None,
    options: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    curr = get_property_definition_by_id_in_tx(cursor, property_definition_id)
    now_iso = datetime.now(JST).isoformat()

    new_name = display_name.strip() if display_name is not None else curr["display_name"]
    if not new_name:
        raise ValueError("display_name must not be empty")

    cursor.execute(
        "UPDATE person_property_definitions SET display_name = ?, updated_at = ? WHERE property_definition_id = ?",
        (new_name, now_iso, property_definition_id),
    )

    if aliases is not None:
        cursor.execute(
            "DELETE FROM person_property_definition_aliases WHERE property_definition_id = ?",
            (property_definition_id,),
        )
        clean_aliases = []
        for a in aliases:
            ca = a.strip()
            if ca and ca not in clean_aliases:
                cursor.execute(
                    "SELECT property_definition_id FROM person_property_definitions WHERE key = ?",
                    (ca,),
                )
                if cursor.fetchone() is not None:
                    raise KeyConflictError(f"Alias '{ca}' conflicts with an existing definition key")
                cursor.execute(
                    "SELECT alias_id FROM person_property_definition_aliases WHERE alias_key = ? AND property_definition_id != ?",
                    (ca, property_definition_id),
                )
                if cursor.fetchone() is not None:
                    raise KeyConflictError(f"Alias '{ca}' already exists")
                clean_aliases.append(ca)

        for ca in clean_aliases:
            alias_id = f"pdalias_{uuid.uuid4().hex}"
            cursor.execute(
                """
                INSERT INTO person_property_definition_aliases (
                    alias_id, property_definition_id, alias_key, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (alias_id, property_definition_id, ca, now_iso),
            )

    if curr["data_type"] == "select" and options is not None:
        # Map existing options by option_key
        existing_opts_by_key = {opt["option_key"]: opt for opt in curr["options"]}
        new_opts_by_key = {opt["option_key"].strip(): opt for opt in options}

        # Check for removed options that are in use
        for old_key, old_opt in existing_opts_by_key.items():
            if old_key not in new_opts_by_key:
                cursor.execute(
                    "SELECT property_value_id FROM person_property_values WHERE option_id = ?",
                    (old_opt["option_id"],),
                )
                if cursor.fetchone() is not None:
                    raise OptionInUseError(
                        f"Cannot delete option '{old_key}' ({old_opt['display_name']}) because it is currently in use"
                    )
                cursor.execute(
                    "DELETE FROM person_property_options WHERE option_id = ?",
                    (old_opt["option_id"],),
                )

        # Upsert options
        for opt_key, opt_data in new_opts_by_key.items():
            opt_name = opt_data["display_name"].strip()
            opt_order = opt_data.get("display_order", 0)
            opt_aliases = opt_data.get("aliases", [])

            if opt_key in existing_opts_by_key:
                existing_id = existing_opts_by_key[opt_key]["option_id"]
                cursor.execute(
                    """
                    UPDATE person_property_options
                    SET display_name = ?, display_order = ?, updated_at = ?
                    WHERE option_id = ?
                    """,
                    (opt_name, opt_order, now_iso, existing_id),
                )
                cursor.execute(
                    "DELETE FROM person_property_option_aliases WHERE option_id = ?",
                    (existing_id,),
                )
                for opt_a in opt_aliases:
                    ca_val = opt_a.strip()
                    if ca_val:
                        opt_alias_id = f"poalias_{uuid.uuid4().hex}"
                        cursor.execute(
                            """
                            INSERT INTO person_property_option_aliases (
                                alias_id, option_id, alias_value, created_at
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (opt_alias_id, existing_id, ca_val, now_iso),
                        )
            else:
                opt_id = f"propopt_{uuid.uuid4().hex}"
                cursor.execute(
                    """
                    INSERT INTO person_property_options (
                        option_id, property_definition_id, option_key, display_name, display_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (opt_id, property_definition_id, opt_key, opt_name, opt_order, now_iso, now_iso),
                )
                for opt_a in opt_aliases:
                    ca_val = opt_a.strip()
                    if ca_val:
                        opt_alias_id = f"poalias_{uuid.uuid4().hex}"
                        cursor.execute(
                            """
                            INSERT INTO person_property_option_aliases (
                                alias_id, option_id, alias_value, created_at
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (opt_alias_id, opt_id, ca_val, now_iso),
                        )

    return get_property_definition_by_id_in_tx(cursor, property_definition_id)


def delete_property_definition_in_tx(
    cursor: sqlite3.Cursor, property_definition_id: str
) -> dict[str, Any]:
    defn = get_property_definition_by_id_in_tx(cursor, property_definition_id)

    cursor.execute(
        "SELECT COUNT(*) FROM person_property_values WHERE property_definition_id = ?",
        (property_definition_id,),
    )
    val_count = cursor.fetchone()[0]

    opt_count = len(defn["options"])

    cursor.execute(
        "DELETE FROM person_property_definitions WHERE property_definition_id = ?",
        (property_definition_id,),
    )

    return {
        "success": True,
        "deleted_property_definition_id": property_definition_id,
        "deleted_values_count": val_count,
        "deleted_options_count": opt_count,
    }


def resolve_option(
    cursor: sqlite3.Cursor, property_definition_id: str, raw_value: Any
) -> dict[str, Any]:
    """Resolve raw option value (option_id, option_key, or option alias) to option dict."""
    val_str = str(raw_value).strip()

    # Try matching option_id or option_key
    cursor.execute(
        """
        SELECT option_id, option_key, display_name, display_order
        FROM person_property_options
        WHERE property_definition_id = ? AND (option_id = ? OR option_key = ?)
        """,
        (property_definition_id, val_str, val_str),
    )
    row = cursor.fetchone()
    if row is not None:
        return dict(row)

    # Try matching option_alias
    cursor.execute(
        """
        SELECT o.option_id, o.option_key, o.display_name, o.display_order
        FROM person_property_options o
        JOIN person_property_option_aliases a ON o.option_id = a.option_id
        WHERE o.property_definition_id = ? AND a.alias_value = ?
        """,
        (property_definition_id, val_str),
    )
    row = cursor.fetchone()
    if row is not None:
        return dict(row)

    raise InvalidValueError(f"Option value '{raw_value}' could not be resolved to a valid option")


def format_property_value(
    row: sqlite3.Row | dict[str, Any]
) -> dict[str, Any]:
    r = dict(row)
    data_type = r["data_type"]

    val = None
    if data_type == "text":
        val = r["value_text"]
    elif data_type == "date":
        val = r["value_date"]
    elif data_type == "number":
        val = r["value_number"]
    elif data_type == "boolean":
        val = bool(r["value_boolean"]) if r["value_boolean"] is not None else None
    elif data_type == "select":
        val = r.get("option_key")

    return {
        "property_value_id": r["property_value_id"],
        "person_id": r["person_id"],
        "property_definition_id": r["property_definition_id"],
        "property_key": r["property_key"],
        "property_display_name": r["property_display_name"],
        "data_type": data_type,
        "cardinality": r["cardinality"],
        "source_type": r["source_type"],
        "value": val,
        "value_text": r["value_text"],
        "value_date": r["value_date"],
        "value_number": r["value_number"],
        "value_boolean": bool(r["value_boolean"]) if r["value_boolean"] is not None else None,
        "option_id": r.get("option_id"),
        "option_key": r.get("option_key"),
        "option_display_name": r.get("option_display_name"),
        "valid_from": r["valid_from"],
        "valid_until": r["valid_until"],
        "note": r["note"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def list_person_properties_in_tx(
    cursor: sqlite3.Cursor, person_id: str
) -> list[dict[str, Any]]:
    cursor.execute("SELECT person_id FROM people WHERE person_id = ?", (person_id,))
    if cursor.fetchone() is None:
        raise FileNotFoundError(f"Person not found: {person_id}")

    cursor.execute(
        """
        SELECT v.property_value_id, v.person_id, v.property_definition_id, v.source_type,
               v.value_text, v.value_date, v.value_date_min, v.value_date_max,
               v.value_number, v.value_boolean, v.option_id,
               v.valid_from, v.valid_from_min, v.valid_until, v.valid_until_max,
               v.note, v.created_at, v.updated_at,
               d.key AS property_key, d.display_name AS property_display_name,
               d.data_type, d.cardinality,
               o.option_key, o.display_name AS option_display_name
        FROM person_property_values v
        JOIN person_property_definitions d ON v.property_definition_id = d.property_definition_id
        LEFT JOIN person_property_options o ON v.option_id = o.option_id
        WHERE v.person_id = ?
        ORDER BY d.key ASC, v.created_at ASC
        """,
        (person_id,),
    )
    return [format_property_value(row) for row in cursor.fetchall()]


def validate_and_prepare_value_columns(
    cursor: sqlite3.Cursor, defn: dict[str, Any], raw_val: Any
) -> dict[str, Any]:
    """Validate type and return column assignment dict."""
    data_type = defn["data_type"]

    cols: dict[str, Any] = {
        "value_text": None,
        "value_date": None,
        "value_date_min": None,
        "value_date_max": None,
        "value_number": None,
        "value_boolean": None,
        "option_id": None,
    }

    if data_type == "text":
        if raw_val is None or not str(raw_val).strip():
            raise InvalidValueError("Text property value must not be empty")
        cols["value_text"] = str(raw_val).strip()
    elif data_type == "date":
        if raw_val is None or not str(raw_val).strip():
            raise InvalidValueError("Date property value must not be empty")
        norm_d = validate_and_normalize_partial_date(str(raw_val).strip())
        d_min, d_max = get_partial_date_bounds(norm_d)
        cols["value_date"] = norm_d
        cols["value_date_min"] = d_min
        cols["value_date_max"] = d_max
    elif data_type == "number":
        try:
            cols["value_number"] = float(raw_val)
        except (ValueError, TypeError) as e:
            raise InvalidValueError(f"Invalid number value: {raw_val}") from e
    elif data_type == "boolean":
        if isinstance(raw_val, bool):
            cols["value_boolean"] = 1 if raw_val else 0
        elif isinstance(raw_val, (int, str)) and str(raw_val).strip().lower() in ("true", "1", "yes"):
            cols["value_boolean"] = 1
        elif isinstance(raw_val, (int, str)) and str(raw_val).strip().lower() in ("false", "0", "no"):
            cols["value_boolean"] = 0
        else:
            raise InvalidValueError(f"Invalid boolean value: {raw_val}")
    elif data_type == "select":
        opt = resolve_option(cursor, defn["property_definition_id"], raw_val)
        cols["option_id"] = opt["option_id"]

    return cols


def is_same_typed_value(cols1: dict[str, Any], cols2: dict[str, Any]) -> bool:
    return (
        cols1.get("value_text") == cols2.get("value_text")
        and cols1.get("value_date") == cols2.get("value_date")
        and cols1.get("value_number") == cols2.get("value_number")
        and cols1.get("value_boolean") == cols2.get("value_boolean")
        and cols1.get("option_id") == cols2.get("option_id")
    )


def check_single_cardinality_overlap_in_tx(
    cursor: sqlite3.Cursor,
    person_id: str,
    property_definition_id: str,
    valid_from: Optional[str],
    valid_until: Optional[str],
    new_cols: dict[str, Any],
    exclude_value_id: Optional[str] = None,
) -> None:
    from_min, _ = get_partial_date_bounds(valid_from)
    _, until_max = get_partial_date_bounds(valid_until)

    cursor.execute(
        """
        SELECT property_value_id, value_text, value_date, value_number, value_boolean, option_id,
               valid_from, valid_from_min, valid_until, valid_until_max
        FROM person_property_values
        WHERE person_id = ? AND property_definition_id = ?
        """,
        (person_id, property_definition_id),
    )
    existing_rows = cursor.fetchall()

    for r in existing_rows:
        if exclude_value_id and r["property_value_id"] == exclude_value_id:
            continue

        ex_s = r["valid_from"]
        ex_e = r["valid_until"]
        ex_s_min = r["valid_from_min"]
        ex_e_max = r["valid_until_max"]

        if temporal_ranges_overlap(from_min, until_max, ex_s_min, ex_e_max):
            ex_cols = {
                "value_text": r["value_text"],
                "value_date": r["value_date"],
                "value_number": r["value_number"],
                "value_boolean": r["value_boolean"],
                "option_id": r["option_id"],
            }
            # If same value and same exact period strings, allowed as exact duplicate
            if is_same_typed_value(new_cols, ex_cols) and valid_from == ex_s and valid_until == ex_e:
                continue
            raise SingleCardinalityOverlapError(
                f"Period [{valid_from or ''}, {valid_until or ''}] overlaps with an existing entry [{ex_s or ''}, {ex_e or ''}] for single-cardinality property"
            )


def create_person_property_value_in_tx(
    cursor: sqlite3.Cursor,
    person_id: str,
    property_definition_id: str,
    value: Any,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    note: Optional[str] = None,
    is_api_call: bool = True,
) -> dict[str, Any]:
    cursor.execute("SELECT person_id FROM people WHERE person_id = ?", (person_id,))
    if cursor.fetchone() is None:
        raise FileNotFoundError(f"Person not found: {person_id}")

    defn = get_property_definition_by_id_in_tx(cursor, property_definition_id)

    if is_api_call and defn["source_type"] == "vault":
        raise VaultSourceReadOnlyError()

    norm_from = validate_and_normalize_partial_date(valid_from)
    norm_until = validate_and_normalize_partial_date(valid_until)
    from_min, _ = get_partial_date_bounds(norm_from)
    _, until_max = get_partial_date_bounds(norm_until)

    if from_min and until_max and from_min > until_max:
        raise InvalidValueError("valid_from must be less than or equal to valid_until")

    cols = validate_and_prepare_value_columns(cursor, defn, value)

    if defn["cardinality"] == "single":
        check_single_cardinality_overlap_in_tx(
            cursor, person_id, property_definition_id, norm_from, norm_until, cols
        )

    now_iso = datetime.now(JST).isoformat()
    val_id = f"propval_{uuid.uuid4().hex}"

    cursor.execute(
        """
        INSERT INTO person_property_values (
            property_value_id, person_id, property_definition_id, source_type,
            value_text, value_date, value_date_min, value_date_max,
            value_number, value_boolean, option_id,
            valid_from, valid_from_min, valid_until, valid_until_max,
            note, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            val_id,
            person_id,
            property_definition_id,
            defn["source_type"],
            cols["value_text"],
            cols["value_date"],
            cols["value_date_min"],
            cols["value_date_max"],
            cols["value_number"],
            cols["value_boolean"],
            cols["option_id"],
            norm_from,
            from_min,
            norm_until,
            until_max,
            note,
            now_iso,
            now_iso,
        ),
    )

    cursor.execute(
        """
        SELECT v.property_value_id, v.person_id, v.property_definition_id, v.source_type,
               v.value_text, v.value_date, v.value_number, v.value_boolean, v.option_id,
               v.valid_from, v.valid_until, v.note, v.created_at, v.updated_at,
               d.key AS property_key, d.display_name AS property_display_name,
               d.data_type, d.cardinality,
               o.option_key, o.display_name AS option_display_name
        FROM person_property_values v
        JOIN person_property_definitions d ON v.property_definition_id = d.property_definition_id
        LEFT JOIN person_property_options o ON v.option_id = o.option_id
        WHERE v.property_value_id = ?
        """,
        (val_id,),
    )
    return format_property_value(cursor.fetchone())


def update_person_property_value_in_tx(
    cursor: sqlite3.Cursor,
    property_value_id: str,
    value: Any = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    note: Optional[str] = None,
    provided: Optional[list[str]] = None,
    is_api_call: bool = True,
    expected_person_id: Optional[str] = None,
) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT v.property_value_id, v.person_id, v.property_definition_id, v.source_type,
               v.value_text, v.value_date, v.value_number, v.value_boolean, v.option_id,
               v.valid_from, v.valid_until, v.note, v.created_at, v.updated_at,
               d.key AS property_key, d.display_name AS property_display_name,
               d.data_type, d.cardinality,
               o.option_key, o.display_name AS option_display_name
        FROM person_property_values v
        JOIN person_property_definitions d ON v.property_definition_id = d.property_definition_id
        LEFT JOIN person_property_options o ON v.option_id = o.option_id
        WHERE v.property_value_id = ?
        """,
        (property_value_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise FileNotFoundError(f"Property value not found: {property_value_id}")
    curr = dict(row)

    if expected_person_id is not None and curr["person_id"] != expected_person_id:
        raise FileNotFoundError(f"Property value not found: {property_value_id}")

    if is_api_call and curr["source_type"] == "vault":
        raise VaultSourceReadOnlyError()

    defn = get_property_definition_by_id_in_tx(cursor, curr["property_definition_id"])

    raw_s = valid_from if (provided and "valid_from" in provided) else curr["valid_from"]
    raw_e = valid_until if (provided and "valid_until" in provided) else curr["valid_until"]
    new_note = note if (provided and "note" in provided) else curr["note"]

    norm_s = validate_and_normalize_partial_date(raw_s)
    norm_e = validate_and_normalize_partial_date(raw_e)
    from_min, _ = get_partial_date_bounds(norm_s)
    _, until_max = get_partial_date_bounds(norm_e)

    if from_min and until_max and from_min > until_max:
        raise InvalidValueError("valid_from must be less than or equal to valid_until")

    if provided and "value" in provided and value is not None:
        cols = validate_and_prepare_value_columns(cursor, defn, value)
    else:
        cols = {
            "value_text": curr["value_text"],
            "value_date": curr["value_date"],
            "value_date_min": curr.get("value_date_min"),
            "value_date_max": curr.get("value_date_max"),
            "value_number": curr["value_number"],
            "value_boolean": curr["value_boolean"],
            "option_id": curr["option_id"],
        }

    if defn["cardinality"] == "single":
        check_single_cardinality_overlap_in_tx(
            cursor,
            curr["person_id"],
            curr["property_definition_id"],
            norm_s,
            norm_e,
            cols,
            exclude_value_id=property_value_id,
        )

    now_iso = datetime.now(JST).isoformat()

    cursor.execute(
        """
        UPDATE person_property_values
        SET value_text = ?, value_date = ?, value_date_min = ?, value_date_max = ?,
            value_number = ?, value_boolean = ?, option_id = ?,
            valid_from = ?, valid_from_min = ?, valid_until = ?, valid_until_max = ?,
            note = ?, updated_at = ?
        WHERE property_value_id = ?
        """,
        (
            cols["value_text"],
            cols["value_date"],
            cols["value_date_min"],
            cols["value_date_max"],
            cols["value_number"],
            cols["value_boolean"],
            cols["option_id"],
            norm_s,
            from_min,
            norm_e,
            until_max,
            new_note,
            now_iso,
            property_value_id,
        ),
    )

    cursor.execute(
        """
        SELECT v.property_value_id, v.person_id, v.property_definition_id, v.source_type,
               v.value_text, v.value_date, v.value_number, v.value_boolean, v.option_id,
               v.valid_from, v.valid_until, v.note, v.created_at, v.updated_at,
               d.key AS property_key, d.display_name AS property_display_name,
               d.data_type, d.cardinality,
               o.option_key, o.display_name AS option_display_name
        FROM person_property_values v
        JOIN person_property_definitions d ON v.property_definition_id = d.property_definition_id
        LEFT JOIN person_property_options o ON v.option_id = o.option_id
        WHERE v.property_value_id = ?
        """,
        (property_value_id,),
    )
    return format_property_value(cursor.fetchone())


def replace_person_property_values_in_tx(
    cursor: sqlite3.Cursor,
    person_id: str,
    property_definition_id: str,
    items: list[dict[str, Any]],
    is_api_call: bool = True,
) -> list[dict[str, Any]]:
    cursor.execute("SELECT person_id FROM people WHERE person_id = ?", (person_id,))
    if cursor.fetchone() is None:
        raise FileNotFoundError(f"Person not found: {person_id}")

    defn = get_property_definition_by_id_in_tx(cursor, property_definition_id)

    if is_api_call and defn["source_type"] == "vault":
        raise VaultSourceReadOnlyError()
    if defn["cardinality"] != "multiple":
        raise ValueError("Bulk save is only supported for multiple-cardinality properties")

    cursor.execute(
        "SELECT property_value_id FROM person_property_values WHERE person_id = ? AND property_definition_id = ?",
        (person_id, property_definition_id),
    )
    existing_ids = {r["property_value_id"] for r in cursor.fetchall()}

    seen_ids: set[str] = set()
    prepared: list[tuple[Optional[str], dict[str, Any], Optional[str], Optional[str], Optional[str]]] = []
    for item in items:
        value_id = item.get("property_value_id")
        raw_val = item.get("value")
        valid_from = item.get("valid_from")
        valid_until = item.get("valid_until")
        note = item.get("note")

        if value_id is not None:
            if value_id in seen_ids:
                raise ValueError(f"Duplicate property_value_id in request: {value_id}")
            seen_ids.add(value_id)
            cursor.execute(
                "SELECT property_value_id, person_id, property_definition_id FROM person_property_values WHERE property_value_id = ?",
                (value_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError(f"Property value not found: {value_id}")
            if row["person_id"] != person_id or row["property_definition_id"] != property_definition_id:
                raise ValueError(
                    f"Property value does not belong to this person and property definition: {value_id}"
                )

        norm_from = validate_and_normalize_partial_date(valid_from)
        norm_until = validate_and_normalize_partial_date(valid_until)
        from_min, _ = get_partial_date_bounds(norm_from)
        _, until_max = get_partial_date_bounds(norm_until)

        if from_min and until_max and from_min > until_max:
            raise InvalidValueError("valid_from must be less than or equal to valid_until")

        cols = validate_and_prepare_value_columns(cursor, defn, raw_val)
        prepared.append((value_id, cols, norm_from, from_min, norm_until, until_max, note))

    # Request omits existing values -> delete them (empty list deletes all)
    for stale_id in existing_ids - seen_ids:
        cursor.execute(
            "DELETE FROM person_property_values WHERE property_value_id = ?",
            (stale_id,),
        )

    now_iso = datetime.now(JST).isoformat()
    for value_id, cols, norm_from, from_min, norm_until, until_max, note in prepared:
        if value_id is not None:
            cursor.execute(
                """
                UPDATE person_property_values
                SET value_text = ?, value_date = ?, value_date_min = ?, value_date_max = ?,
                    value_number = ?, value_boolean = ?, option_id = ?,
                    valid_from = ?, valid_from_min = ?, valid_until = ?, valid_until_max = ?,
                    note = ?, updated_at = ?
                WHERE property_value_id = ?
                """,
                (
                    cols["value_text"],
                    cols["value_date"],
                    cols["value_date_min"],
                    cols["value_date_max"],
                    cols["value_number"],
                    cols["value_boolean"],
                    cols["option_id"],
                    norm_from,
                    from_min,
                    norm_until,
                    until_max,
                    note,
                    now_iso,
                    value_id,
                ),
            )
        else:
            new_id = f"propval_{uuid.uuid4().hex}"
            cursor.execute(
                """
                INSERT INTO person_property_values (
                    property_value_id, person_id, property_definition_id, source_type,
                    value_text, value_date, value_date_min, value_date_max,
                    value_number, value_boolean, option_id,
                    valid_from, valid_from_min, valid_until, valid_until_max,
                    note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id,
                    person_id,
                    property_definition_id,
                    defn["source_type"],
                    cols["value_text"],
                    cols["value_date"],
                    cols["value_date_min"],
                    cols["value_date_max"],
                    cols["value_number"],
                    cols["value_boolean"],
                    cols["option_id"],
                    norm_from,
                    from_min,
                    norm_until,
                    until_max,
                    note,
                    now_iso,
                    now_iso,
                ),
            )

    cursor.execute(
        """
        SELECT v.property_value_id, v.person_id, v.property_definition_id, v.source_type,
               v.value_text, v.value_date, v.value_number, v.value_boolean, v.option_id,
               v.valid_from, v.valid_until, v.note, v.created_at, v.updated_at,
               d.key AS property_key, d.display_name AS property_display_name,
               d.data_type, d.cardinality,
               o.option_key, o.display_name AS option_display_name
        FROM person_property_values v
        JOIN person_property_definitions d ON v.property_definition_id = d.property_definition_id
        LEFT JOIN person_property_options o ON v.option_id = o.option_id
        WHERE v.person_id = ? AND v.property_definition_id = ?
        ORDER BY v.created_at ASC
        """,
        (person_id, property_definition_id),
    )
    return [format_property_value(row) for row in cursor.fetchall()]


def delete_person_property_value_in_tx(
    cursor: sqlite3.Cursor,
    property_value_id: str,
    is_api_call: bool = True,
    expected_person_id: Optional[str] = None,
) -> dict[str, Any]:
    cursor.execute(
        "SELECT property_value_id, person_id, source_type FROM person_property_values WHERE property_value_id = ?",
        (property_value_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise FileNotFoundError(f"Property value not found: {property_value_id}")
    if expected_person_id is not None and row["person_id"] != expected_person_id:
        raise FileNotFoundError(f"Property value not found: {property_value_id}")

    if is_api_call and row["source_type"] == "vault":
        raise VaultSourceReadOnlyError()

    cursor.execute(
        "DELETE FROM person_property_values WHERE property_value_id = ?",
        (property_value_id,),
    )
    return {"success": True, "deleted_property_value_id": property_value_id}


def preview_person_property_merge(
    cursor: sqlite3.Cursor, from_person_id: str, to_person_id: str
) -> dict[str, Any]:
    from_props = list_person_properties_in_tx(cursor, from_person_id)
    to_props = list_person_properties_in_tx(cursor, to_person_id)

    impacts = []
    transferred_count = 0
    merged_count = 0
    conflicts_count = 0

    for fp in from_props:
        fp_id = fp["property_value_id"]
        def_id = fp["property_definition_id"]
        def_key = fp["property_key"]
        def_name = fp["property_display_name"]
        card = fp["cardinality"]
        s_type = fp["source_type"]
        s_date = fp["valid_from"]
        e_date = fp["valid_until"]

        fp_cols = {
            "value_text": fp["value_text"],
            "value_date": fp["value_date"],
            "value_number": fp["value_number"],
            "value_boolean": fp["value_boolean"],
            "option_id": fp["option_id"],
        }

        # Compare against target's properties under same definition
        target_matches = [tp for tp in to_props if tp["property_definition_id"] == def_id]

        is_exact_dup = False
        has_period_conflict = False

        fp_s_min, _ = get_partial_date_bounds(s_date)
        _, fp_e_max = get_partial_date_bounds(e_date)

        for tp in target_matches:
            tp_cols = {
                "value_text": tp["value_text"],
                "value_date": tp["value_date"],
                "value_number": tp["value_number"],
                "value_boolean": tp["value_boolean"],
                "option_id": tp["option_id"],
            }
            tp_s = tp["valid_from"]
            tp_e = tp["valid_until"]
            tp_s_min, _ = get_partial_date_bounds(tp_s)
            _, tp_e_max = get_partial_date_bounds(tp_e)

            if is_same_typed_value(fp_cols, tp_cols) and s_date == tp_s and e_date == tp_e:
                is_exact_dup = True
                break

            if card == "single" and temporal_ranges_overlap(fp_s_min, fp_e_max, tp_s_min, tp_e_max):
                has_period_conflict = True

        if is_exact_dup:
            merged_count += 1
            impacts.append(
                {
                    "property_value_id": fp_id,
                    "property_definition_id": def_id,
                    "property_key": def_key,
                    "property_display_name": def_name,
                    "source_type": s_type,
                    "valid_from": s_date,
                    "valid_until": e_date,
                    "result_type": "merged_into_existing",
                    "conflict_reason": None,
                }
            )
        elif has_period_conflict:
            conflicts_count += 1
            impacts.append(
                {
                    "property_value_id": fp_id,
                    "property_definition_id": def_id,
                    "property_key": def_key,
                    "property_display_name": def_name,
                    "source_type": s_type,
                    "valid_from": s_date,
                    "valid_until": e_date,
                    "result_type": "property_conflict",
                    "conflict_reason": f"Single cardinality period overlap with different value for property '{def_name}'",
                }
            )
        else:
            transferred_count += 1
            impacts.append(
                {
                    "property_value_id": fp_id,
                    "property_definition_id": def_id,
                    "property_key": def_key,
                    "property_display_name": def_name,
                    "source_type": s_type,
                    "valid_from": s_date,
                    "valid_until": e_date,
                    "result_type": "transferred",
                    "conflict_reason": None,
                }
            )

    return {
        "transferred_properties_count": transferred_count,
        "merged_properties_count": merged_count,
        "property_conflicts_count": conflicts_count,
        "property_impacts": impacts,
    }


def transfer_person_properties_on_merge(
    cursor: sqlite3.Cursor, from_person_id: str, to_person_id: str
) -> None:
    preview = preview_person_property_merge(cursor, from_person_id, to_person_id)
    if preview["property_conflicts_count"] > 0:
        raise PropertyConflictError("Property conflict detected during merge execution")

    for impact in preview["property_impacts"]:
        p_id = impact["property_value_id"]
        res_type = impact["result_type"]

        if res_type == "transferred":
            cursor.execute(
                "UPDATE person_property_values SET person_id = ? WHERE property_value_id = ?",
                (to_person_id, p_id),
            )
        elif res_type == "merged_into_existing":
            cursor.execute(
                "DELETE FROM person_property_values WHERE property_value_id = ?",
                (p_id,),
            )


# --- Public Outer Service Functions ---


def list_property_definitions() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        return list_property_definitions_in_tx(cursor)
    finally:
        conn.close()


def create_property_definition(
    key: str,
    display_name: str,
    data_type: str,
    cardinality: str,
    source_type: str = "database",
    aliases: Optional[list[str]] = None,
    options: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            return create_property_definition_in_tx(
                cursor,
                key=key,
                display_name=display_name,
                data_type=data_type,
                cardinality=cardinality,
                source_type=source_type,
                aliases=aliases,
                options=options,
            )
    finally:
        conn.close()


def search_people_by_properties_in_tx(
    cursor: sqlite3.Cursor,
    name_query: Optional[str] = None,
    conditions: Optional[list[dict[str, Any]]] = None,
    valid_period: Optional[dict[str, Any]] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if limit < 1 or limit > 100:
        raise InvalidValueError("Limit must be between 1 and 100")
    if offset < 0:
        raise InvalidValueError("Offset must be non-negative")

    cond_list = conditions or []
    if len(cond_list) > 10:
        raise InvalidValueError("Maximum 10 property conditions allowed")

    period_cond = valid_period or {"mode": "current"}
    mode = period_cond.get("mode", "current")

    q_start_min: Optional[str] = None
    q_end_max: Optional[str] = None

    if mode == "current":
        today_str = datetime.now(JST).strftime("%Y-%m-%d")
        q_start_min = today_str
        q_end_max = today_str
    elif mode == "as_of":
        as_of_val = period_cond.get("as_of")
        if not as_of_val or not str(as_of_val).strip():
            raise InvalidValueError("as_of is required when mode is 'as_of'")
        norm_as_of = validate_and_normalize_partial_date(str(as_of_val))
        d_min, d_max = get_partial_date_bounds(norm_as_of)
        q_start_min = d_min
        q_end_max = d_max
    elif mode == "between":
        p_start = period_cond.get("start")
        p_end = period_cond.get("end")
        if not p_start and not p_end:
            raise InvalidValueError("at least one of start or end is required when mode is 'between'")
        if p_start:
            norm_s = validate_and_normalize_partial_date(str(p_start))
            s_min, _ = get_partial_date_bounds(norm_s)
            q_start_min = s_min
        if p_end:
            norm_e = validate_and_normalize_partial_date(str(p_end))
            _, e_max = get_partial_date_bounds(norm_e)
            q_end_max = e_max
        if q_start_min and q_end_max and q_start_min > q_end_max:
            raise InvalidValueError("start date must be less than or equal to end date")
    elif mode == "all":
        pass
    else:
        raise InvalidValueError(f"Invalid valid_period mode: {mode}")

    params: list[Any] = []
    where_clauses: list[str] = []

    if name_query and name_query.strip():
        import unicodedata
        clean_name = unicodedata.normalize("NFKC", name_query.strip()).casefold()
        name_pattern = f"%{clean_name}%"
        where_clauses.append(
            """
            (
                nfkc_casefold(p.display_name) LIKE ? OR
                nfkc_casefold(p.normalized_name) LIKE ? OR
                EXISTS (
                    SELECT 1 FROM person_aliases pa
                    WHERE pa.person_id = p.person_id
                    AND (nfkc_casefold(pa.display_name) LIKE ? OR nfkc_casefold(pa.normalized_name) LIKE ?)
                )
            )
            """
        )
        params.extend([name_pattern, name_pattern, name_pattern, name_pattern])

    validated_conds = []
    for idx, cond in enumerate(cond_list):
        prop_def_id = cond.get("property_definition_id")
        if not prop_def_id:
            raise InvalidValueError("property_definition_id is required for condition")

        defn = get_property_definition_by_id_in_tx(cursor, prop_def_id)
        data_type = defn["data_type"]
        op = cond.get("operator")

        val = cond.get("value")
        val_from = cond.get("value_from")
        val_to = cond.get("value_to")

        if data_type == "text":
            if op != "contains":
                raise InvalidValueError(f"Operator '{op}' is not supported for text data_type")
            if val is None or not str(val).strip():
                raise InvalidValueError("value is required for 'contains' operator")
        elif data_type in ("select", "boolean"):
            if op != "eq":
                raise InvalidValueError(f"Operator '{op}' is not supported for {data_type} data_type")
            if val is None or (isinstance(val, str) and not val.strip()):
                raise InvalidValueError("value is required for 'eq' operator")
        elif data_type == "number":
            if op not in ("eq", "gte", "lte", "between"):
                raise InvalidValueError(f"Operator '{op}' is not supported for number data_type")
            if op in ("eq", "gte", "lte"):
                if val is None or isinstance(val, bool):
                    raise InvalidValueError(f"value is required for number '{op}' operator")
                try:
                    float(val)
                except (ValueError, TypeError) as e:
                    raise InvalidValueError(f"Invalid number value: {val}") from e
            elif op == "between":
                if val_from is None or val_to is None or isinstance(val_from, bool) or isinstance(val_to, bool):
                    raise InvalidValueError("value_from and value_to are required for number 'between' operator")
                try:
                    vf = float(val_from)
                    vt = float(val_to)
                except (ValueError, TypeError) as e:
                    raise InvalidValueError(f"Invalid number range values: {val_from}, {val_to}") from e
                if vf > vt:
                    raise InvalidValueError("value_from must be less than or equal to value_to")
        elif data_type == "date":
            if op != "overlaps":
                raise InvalidValueError(f"Operator '{op}' is not supported for date data_type")
            if not val and not val_from and not val_to:
                raise InvalidValueError("At least one date parameter (value, value_from, value_to) is required")
        else:
            raise InvalidValueError(f"Unsupported data_type: {data_type}")

        validated_conds.append({
            "defn": defn,
            "op": op,
            "value": val,
            "value_from": val_from,
            "value_to": val_to,
        })

        sub_sql_parts = ["v.person_id = p.person_id", "v.property_definition_id = ?"]
        sub_params = [prop_def_id]

        if data_type == "text":
            import unicodedata
            clean_v = unicodedata.normalize("NFKC", str(val).strip()).casefold()
            sub_sql_parts.append("nfkc_casefold(v.value_text) LIKE ?")
            sub_params.append(f"%{clean_v}%")
        elif data_type == "select":
            opt = resolve_option(cursor, prop_def_id, val)
            sub_sql_parts.append("v.option_id = ?")
            sub_params.append(opt["option_id"])
        elif data_type == "boolean":
            b_val = 1 if (isinstance(val, bool) and val) or str(val).strip().lower() in ("true", "1", "yes") else 0
            sub_sql_parts.append("v.value_boolean = ?")
            sub_params.append(b_val)
        elif data_type == "number":
            num_v = float(val) if val is not None else None
            if op == "eq":
                sub_sql_parts.append("v.value_number = ?")
                sub_params.append(num_v)
            elif op == "gte":
                sub_sql_parts.append("v.value_number >= ?")
                sub_params.append(num_v)
            elif op == "lte":
                sub_sql_parts.append("v.value_number <= ?")
                sub_params.append(num_v)
            elif op == "between":
                vf = float(val_from)
                vt = float(val_to)
                sub_sql_parts.append("v.value_number BETWEEN ? AND ?")
                sub_params.extend([vf, vt])
        elif data_type == "date":
            d_start = val_from or val
            d_end = val_to or val
            if d_start:
                norm_ds = validate_and_normalize_partial_date(str(d_start))
                ds_min, _ = get_partial_date_bounds(norm_ds)
            else:
                ds_min = None

            if d_end:
                norm_de = validate_and_normalize_partial_date(str(d_end))
                _, de_max = get_partial_date_bounds(norm_de)
            else:
                de_max = None

            if ds_min and de_max and ds_min > de_max:
                raise InvalidValueError("Date range start must be less than or equal to end")

            sub_sql_parts.append("(v.value_date_min IS NULL OR ? IS NULL OR v.value_date_min <= ?)")
            sub_params.extend([de_max, de_max])
            sub_sql_parts.append("(v.value_date_max IS NULL OR ? IS NULL OR v.value_date_max >= ?)")
            sub_params.extend([ds_min, ds_min])

        if mode != "all":
            sub_sql_parts.append("(v.valid_from_min IS NULL OR ? IS NULL OR v.valid_from_min <= ?)")
            sub_params.extend([q_end_max, q_end_max])
            sub_sql_parts.append("(v.valid_until_max IS NULL OR ? IS NULL OR v.valid_until_max >= ?)")
            sub_params.extend([q_start_min, q_start_min])

        where_clauses.append(f"EXISTS (SELECT 1 FROM person_property_values v WHERE {' AND '.join(sub_sql_parts)})")
        params.extend(sub_params)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    cursor.execute(f"SELECT COUNT(*) FROM people p {where_sql}", params)
    total_count = cursor.fetchone()[0]

    cursor.execute(
        f"""
        SELECT p.person_id, p.display_name, p.normalized_name, p.vault_id,
               (SELECT COUNT(*) FROM summary_people sp WHERE sp.person_id = p.person_id) AS summary_count
        FROM people p
        {where_sql}
        ORDER BY p.display_name ASC, p.person_id ASC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    people_rows = cursor.fetchall()

    items = []
    for p_row in people_rows:
        person_id = p_row["person_id"]

        cursor.execute(
            "SELECT normalized_name, display_name FROM person_aliases WHERE person_id = ? ORDER BY display_name ASC",
            (person_id,),
        )
        aliases = [dict(a_row) for a_row in cursor.fetchall()]

        person_dict = {
            "person_id": person_id,
            "display_name": p_row["display_name"],
            "normalized_name": p_row["normalized_name"],
            "vault_id": p_row["vault_id"],
            "aliases": aliases,
            "summary_count": p_row["summary_count"],
        }

        matched_props = []
        for cond_info in validated_conds:
            defn = cond_info["defn"]
            prop_def_id = defn["property_definition_id"]
            data_type = defn["data_type"]
            op = cond_info["op"]
            val = cond_info["value"]
            val_from = cond_info["value_from"]
            val_to = cond_info["value_to"]

            m_sql_parts = ["v.person_id = ?", "v.property_definition_id = ?"]
            m_params = [person_id, prop_def_id]

            if data_type == "text":
                import unicodedata
                clean_v = unicodedata.normalize("NFKC", str(val).strip()).casefold()
                m_sql_parts.append("nfkc_casefold(v.value_text) LIKE ?")
                m_params.append(f"%{clean_v}%")
            elif data_type == "select":
                opt = resolve_option(cursor, prop_def_id, val)
                m_sql_parts.append("v.option_id = ?")
                m_params.append(opt["option_id"])
            elif data_type == "boolean":
                b_val = 1 if (isinstance(val, bool) and val) or str(val).strip().lower() in ("true", "1", "yes") else 0
                m_sql_parts.append("v.value_boolean = ?")
                m_params.append(b_val)
            elif data_type == "number":
                num_v = float(val) if val is not None else None
                if op == "eq":
                    m_sql_parts.append("v.value_number = ?")
                    m_params.append(num_v)
                elif op == "gte":
                    m_sql_parts.append("v.value_number >= ?")
                    m_params.append(num_v)
                elif op == "lte":
                    m_sql_parts.append("v.value_number <= ?")
                    m_params.append(num_v)
                elif op == "between":
                    vf = float(val_from)
                    vt = float(val_to)
                    m_sql_parts.append("v.value_number BETWEEN ? AND ?")
                    m_params.extend([vf, vt])
            elif data_type == "date":
                d_start = val_from or val
                d_end = val_to or val
                ds_min = get_partial_date_bounds(validate_and_normalize_partial_date(str(d_start)))[0] if d_start else None
                de_max = get_partial_date_bounds(validate_and_normalize_partial_date(str(d_end)))[1] if d_end else None
                m_sql_parts.append("(v.value_date_min IS NULL OR ? IS NULL OR v.value_date_min <= ?)")
                m_params.extend([de_max, de_max])
                m_sql_parts.append("(v.value_date_max IS NULL OR ? IS NULL OR v.value_date_max >= ?)")
                m_params.extend([ds_min, ds_min])

            if mode != "all":
                m_sql_parts.append("(v.valid_from_min IS NULL OR ? IS NULL OR v.valid_from_min <= ?)")
                m_params.extend([q_end_max, q_end_max])
                m_sql_parts.append("(v.valid_until_max IS NULL OR ? IS NULL OR v.valid_until_max >= ?)")
                m_params.extend([q_start_min, q_start_min])

            cursor.execute(
                f"""
                SELECT v.property_value_id, v.property_definition_id, v.value_text, v.value_date,
                       v.value_number, v.value_boolean, v.option_id, v.valid_from, v.valid_until,
                       d.key AS property_key, d.display_name AS property_display_name, d.data_type,
                       o.option_key
                FROM person_property_values v
                JOIN person_property_definitions d ON v.property_definition_id = d.property_definition_id
                LEFT JOIN person_property_options o ON v.option_id = o.option_id
                WHERE {' AND '.join(m_sql_parts)}
                ORDER BY v.created_at ASC, v.property_value_id ASC
                LIMIT 1
                """,
                m_params,
            )
            m_row = cursor.fetchone()
            if m_row:
                m_dt = m_row["data_type"]
                m_val = None
                if m_dt == "text":
                    m_val = m_row["value_text"]
                elif m_dt == "date":
                    m_val = m_row["value_date"]
                elif m_dt == "number":
                    m_val = m_row["value_number"]
                elif m_dt == "boolean":
                    m_val = bool(m_row["value_boolean"]) if m_row["value_boolean"] is not None else None
                elif m_dt == "select":
                    m_val = m_row["option_key"]

                matched_props.append(
                    {
                        "property_value_id": m_row["property_value_id"],
                        "property_definition_id": m_row["property_definition_id"],
                        "property_key": m_row["property_key"],
                        "property_display_name": m_row["property_display_name"],
                        "data_type": m_dt,
                        "value": m_val,
                        "valid_from": m_row["valid_from"],
                        "valid_until": m_row["valid_until"],
                    }
                )

        items.append({
            "person": person_dict,
            "matched_properties": matched_props,
        })

    return {"items": items, "total": total_count}


def register_nfkc_casefold(conn: sqlite3.Connection) -> None:
    import unicodedata
    def _nfkc_casefold(text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        return unicodedata.normalize("NFKC", str(text)).casefold()
    conn.create_function("nfkc_casefold", 1, _nfkc_casefold)


def search_people_by_properties(
    name_query: Optional[str] = None,
    conditions: Optional[list[dict[str, Any]]] = None,
    valid_period: Optional[dict[str, Any]] = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    conn = get_db_connection()
    register_nfkc_casefold(conn)
    try:
        cursor = conn.cursor()
        return search_people_by_properties_in_tx(
            cursor,
            name_query=name_query,
            conditions=conditions,
            valid_period=valid_period,
            limit=limit,
            offset=offset,
        )
    finally:
        conn.close()


def get_person_properties_for_ai(person_id: str) -> list[dict[str, Any]]:
    """Return minimal person property projection for AI tools.

    Includes key, display_name, data_type, value, valid_from, valid_until.
    Sorted by definition key ASC, then created_at ASC.
    Returns [] if no properties exist.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT d.key, d.display_name, d.data_type,
                   v.value_text, v.value_date, v.value_number, v.value_boolean,
                   o.option_key, v.valid_from, v.valid_until, v.created_at
            FROM person_property_values v
            JOIN person_property_definitions d ON v.property_definition_id = d.property_definition_id
            LEFT JOIN person_property_options o ON v.option_id = o.option_id
            WHERE v.person_id = ?
            ORDER BY d.key ASC, v.created_at ASC
            """,
            (person_id,),
        )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            data_type = r["data_type"]
            val = None
            if data_type == "text":
                val = r["value_text"]
            elif data_type == "date":
                val = r["value_date"]
            elif data_type == "number":
                val = r["value_number"]
            elif data_type == "boolean":
                val = bool(r["value_boolean"]) if r["value_boolean"] is not None else None
            elif data_type == "select":
                val = r["option_key"]

            result.append(
                {
                    "key": r["key"],
                    "display_name": r["display_name"],
                    "data_type": data_type,
                    "value": val,
                    "valid_from": r["valid_from"],
                    "valid_until": r["valid_until"],
                }
            )
        return result
    finally:
        conn.close()


def update_property_definition(
    property_definition_id: str,
    display_name: Optional[str] = None,
    aliases: Optional[list[str]] = None,
    options: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            return update_property_definition_in_tx(
                cursor,
                property_definition_id=property_definition_id,
                display_name=display_name,
                aliases=aliases,
                options=options,
            )
    finally:
        conn.close()


def delete_property_definition(property_definition_id: str) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            return delete_property_definition_in_tx(cursor, property_definition_id)
    finally:
        conn.close()


def list_person_properties(person_id: str) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        return list_person_properties_in_tx(cursor, person_id)
    finally:
        conn.close()


def create_person_property_value(
    person_id: str,
    property_definition_id: str,
    value: Any,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            return create_person_property_value_in_tx(
                cursor,
                person_id=person_id,
                property_definition_id=property_definition_id,
                value=value,
                valid_from=valid_from,
                valid_until=valid_until,
                note=note,
                is_api_call=True,
            )
    finally:
        conn.close()


def update_person_property_value(
    property_value_id: str,
    value: Any = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    note: Optional[str] = None,
    provided: Optional[list[str]] = None,
    expected_person_id: Optional[str] = None,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            return update_person_property_value_in_tx(
                cursor,
                property_value_id=property_value_id,
                value=value,
                valid_from=valid_from,
                valid_until=valid_until,
                note=note,
                provided=provided,
                is_api_call=True,
                expected_person_id=expected_person_id,
            )
    finally:
        conn.close()


def delete_person_property_value(
    property_value_id: str, expected_person_id: Optional[str] = None
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            return delete_person_property_value_in_tx(
                cursor,
                property_value_id,
                is_api_call=True,
                expected_person_id=expected_person_id,
            )
    finally:
        conn.close()


def matches_temporal_condition(
    val_date_min: Optional[str],
    val_date_max: Optional[str],
    valid_from_min: Optional[str],
    valid_until_max: Optional[str],
    query_start: Optional[str] = None,
    query_end: Optional[str] = None,
) -> bool:
    """Helper primitive for v2 temporal search: checks if property date/period overlaps with query date bounds."""
    q_min, _ = get_partial_date_bounds(query_start)
    _, q_max = get_partial_date_bounds(query_end)

    if val_date_min is not None or val_date_max is not None:
        if not temporal_ranges_overlap(val_date_min, val_date_max, q_min, q_max):
            return False

    return temporal_ranges_overlap(valid_from_min, valid_until_max, q_min, q_max)


def replace_person_property_values(
    person_id: str,
    property_definition_id: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            return replace_person_property_values_in_tx(
                cursor,
                person_id=person_id,
                property_definition_id=property_definition_id,
                items=items,
                is_api_call=True,
            )
    finally:
        conn.close()
