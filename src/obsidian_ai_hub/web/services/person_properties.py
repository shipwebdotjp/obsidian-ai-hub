import re
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from obsidian_ai_hub.database import get_db_connection

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


def validate_yyyy_mm_dd(d_val: Optional[str]) -> None:
    if d_val is not None:
        v = d_val.strip()
        if not v:
            return
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise InvalidValueError(f"Date must be in YYYY-MM-DD format: {d_val}")
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError as e:
            raise InvalidValueError(f"Invalid date: {d_val}") from e


def periods_overlap(
    s1: Optional[str], e1: Optional[str], s2: Optional[str], e2: Optional[str]
) -> bool:
    """True if interval [s1, e1] overlaps with [s2, e2]. None means unbounded."""
    cond1 = (s1 is None) or (e2 is None) or (s1 <= e2)
    cond2 = (e1 is None) or (s2 is None) or (e1 >= s2)
    return cond1 and cond2


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
               v.value_text, v.value_date, v.value_number, v.value_boolean, v.option_id,
               v.valid_from, v.valid_until, v.note, v.created_at, v.updated_at,
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
        "value_number": None,
        "value_boolean": None,
        "option_id": None,
    }

    if data_type == "text":
        if raw_val is None or not str(raw_val).strip():
            raise InvalidValueError("Text property value must not be empty")
        cols["value_text"] = str(raw_val).strip()
    elif data_type == "date":
        validate_yyyy_mm_dd(str(raw_val) if raw_val is not None else None)
        cols["value_date"] = str(raw_val).strip()
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
    cursor.execute(
        """
        SELECT property_value_id, value_text, value_date, value_number, value_boolean, option_id, valid_from, valid_until
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

        if periods_overlap(valid_from, valid_until, ex_s, ex_e):
            ex_cols = {
                "value_text": r["value_text"],
                "value_date": r["value_date"],
                "value_number": r["value_number"],
                "value_boolean": r["value_boolean"],
                "option_id": r["option_id"],
            }
            # If same value and same exact period, allowed as exact duplicate
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

    validate_yyyy_mm_dd(valid_from)
    validate_yyyy_mm_dd(valid_until)
    if valid_from and valid_until and valid_from > valid_until:
        raise InvalidValueError("valid_from must be less than or equal to valid_until")

    cols = validate_and_prepare_value_columns(cursor, defn, value)

    if defn["cardinality"] == "single":
        check_single_cardinality_overlap_in_tx(
            cursor, person_id, property_definition_id, valid_from, valid_until, cols
        )

    now_iso = datetime.now(JST).isoformat()
    val_id = f"propval_{uuid.uuid4().hex}"

    cursor.execute(
        """
        INSERT INTO person_property_values (
            property_value_id, person_id, property_definition_id, source_type,
            value_text, value_date, value_number, value_boolean, option_id,
            valid_from, valid_until, note, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            val_id,
            person_id,
            property_definition_id,
            defn["source_type"],
            cols["value_text"],
            cols["value_date"],
            cols["value_number"],
            cols["value_boolean"],
            cols["option_id"],
            valid_from,
            valid_until,
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

    if is_api_call and curr["source_type"] == "vault":
        raise VaultSourceReadOnlyError()

    defn = get_property_definition_by_id_in_tx(cursor, curr["property_definition_id"])

    new_s = valid_from if (provided and "valid_from" in provided) else curr["valid_from"]
    new_e = valid_until if (provided and "valid_until" in provided) else curr["valid_until"]
    new_note = note if (provided and "note" in provided) else curr["note"]

    validate_yyyy_mm_dd(new_s)
    validate_yyyy_mm_dd(new_e)
    if new_s and new_e and new_s > new_e:
        raise InvalidValueError("valid_from must be less than or equal to valid_until")

    if provided and "value" in provided and value is not None:
        cols = validate_and_prepare_value_columns(cursor, defn, value)
    else:
        cols = {
            "value_text": curr["value_text"],
            "value_date": curr["value_date"],
            "value_number": curr["value_number"],
            "value_boolean": curr["value_boolean"],
            "option_id": curr["option_id"],
        }

    if defn["cardinality"] == "single":
        check_single_cardinality_overlap_in_tx(
            cursor,
            curr["person_id"],
            curr["property_definition_id"],
            new_s,
            new_e,
            cols,
            exclude_value_id=property_value_id,
        )

    now_iso = datetime.now(JST).isoformat()

    cursor.execute(
        """
        UPDATE person_property_values
        SET value_text = ?, value_date = ?, value_number = ?, value_boolean = ?, option_id = ?,
            valid_from = ?, valid_until = ?, note = ?, updated_at = ?
        WHERE property_value_id = ?
        """,
        (
            cols["value_text"],
            cols["value_date"],
            cols["value_number"],
            cols["value_boolean"],
            cols["option_id"],
            new_s,
            new_e,
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


def delete_person_property_value_in_tx(
    cursor: sqlite3.Cursor, property_value_id: str, is_api_call: bool = True
) -> dict[str, Any]:
    cursor.execute(
        "SELECT property_value_id, source_type FROM person_property_values WHERE property_value_id = ?",
        (property_value_id,),
    )
    row = cursor.fetchone()
    if row is None:
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

            if is_same_typed_value(fp_cols, tp_cols) and s_date == tp_s and e_date == tp_e:
                is_exact_dup = True
                break

            if card == "single" and periods_overlap(s_date, e_date, tp_s, tp_e):
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
            )
    finally:
        conn.close()


def delete_person_property_value(property_value_id: str) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            return delete_person_property_value_in_tx(
                cursor, property_value_id, is_api_call=True
            )
    finally:
        conn.close()
