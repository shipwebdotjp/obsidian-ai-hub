from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import TypedDict, Any, Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.utils.extracter import parse_frontmatter
from obsidian_ai_hub.summary.store import normalize_entity_name

logger = logging.getLogger(__name__)

# YAMLError is not a subclass of ValueError/OSError/TypeError, so it needs
# explicit handling to avoid aborting the whole vault scan on a single bad file.
try:
    import yaml as _yaml_for_loader  # type: ignore

    _YAML_ERROR_TUPLE: tuple[type[BaseException], ...] = (_yaml_for_loader.YAMLError,)
except ImportError:
    _YAML_ERROR_TUPLE = ()

_PEOPLE_NOTE_SCAN_EXCEPTS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    TypeError,
) + _YAML_ERROR_TUPLE


class PersonNote(TypedDict):
    id: str
    name: str
    aliases: list[str]
    file_path: Path


def normalize_date_str(val: Any) -> str:
    if isinstance(val, (datetime, date)):
        return val.isoformat()[:10]
    if isinstance(val, str):
        v = val.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            try:
                datetime.strptime(v, "%Y-%m-%d")
                return v
            except ValueError as e:
                raise ValueError(f"Invalid date: {val}") from e
            return v
    raise ValueError(f"Invalid date format: {val}")


def periods_overlap(
    s1: Optional[str], e1: Optional[str], s2: Optional[str], e2: Optional[str]
) -> bool:
    cond1 = (s1 is None) or (e2 is None) or (s1 <= e2)
    cond2 = (e1 is None) or (s2 is None) or (e1 >= s2)
    return cond1 and cond2


def get_vault_property_definitions_lookup(conn: sqlite3.Connection) -> dict[str, Any]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT property_definition_id, key, display_name, data_type, cardinality, source_type
        FROM person_property_definitions
        WHERE source_type = 'vault'
        ORDER BY key ASC
        """
    )
    def_rows = cursor.fetchall()

    definitions_by_id = {}
    key_alias_map = {}

    for row in def_rows:
        d_dict = dict(row)
        def_id = d_dict["property_definition_id"]
        def_key = d_dict["key"]

        # Get aliases
        cursor.execute(
            "SELECT alias_key FROM person_property_definition_aliases WHERE property_definition_id = ?",
            (def_id,),
        )
        aliases = [r[0] for r in cursor.fetchall()]
        d_dict["aliases"] = aliases

        # Map key and aliases
        key_alias_map[def_key] = def_id
        for ak in aliases:
            key_alias_map[ak] = def_id

        # Get options if select
        option_lookup = {}
        if d_dict["data_type"] == "select":
            cursor.execute(
                """
                SELECT option_id, option_key, display_name
                FROM person_property_options
                WHERE property_definition_id = ?
                """,
                (def_id,),
            )
            opt_rows = cursor.fetchall()
            for opt_r in opt_rows:
                opt_id = opt_r["option_id"]
                opt_k = opt_r["option_key"]
                opt_dn = opt_r["display_name"]
                option_lookup[opt_k] = opt_id
                option_lookup[opt_dn] = opt_id

                cursor.execute(
                    "SELECT alias_value FROM person_property_option_aliases WHERE option_id = ?",
                    (opt_id,),
                )
                for alias_r in cursor.fetchall():
                    option_lookup[alias_r[0]] = opt_id

        d_dict["option_lookup"] = option_lookup
        definitions_by_id[def_id] = d_dict

    return {"definitions_by_id": definitions_by_id, "key_alias_map": key_alias_map}


def parse_vault_properties_for_note(
    fm: dict[str, Any], pid: str, pname: str, lookup: dict[str, Any]
) -> dict[str, Any]:
    definitions_by_id = lookup["definitions_by_id"]
    key_alias_map = lookup["key_alias_map"]

    reserved_keys = {"id", "name", "aliases"}

    # Group frontmatter keys by resolved property_definition_id
    found_keys: dict[str, list[str]] = {}
    for fm_k in fm.keys():
        if fm_k in reserved_keys:
            continue
        if fm_k in key_alias_map:
            def_id = key_alias_map[fm_k]
            found_keys.setdefault(def_id, []).append(fm_k)

    parsed_properties: dict[str, list[dict[str, Any]]] = {}
    missing_properties: list[str] = []
    invalid_properties: list[dict[str, Any]] = []

    # 1. Key collision check
    invalid_def_ids = set()
    for def_id, fm_ks in found_keys.items():
        if len(fm_ks) > 1:
            invalid_def_ids.add(def_id)
            defn = definitions_by_id[def_id]
            invalid_properties.append(
                {
                    "person_id": pid,
                    "person_name": pname,
                    "property_key": defn["key"],
                    "property_display_name": defn["display_name"],
                    "reason": f"同一ノート内で複数のキー ({', '.join(fm_ks)}) が同じ属性定義 '{defn['display_name']}' に指定されています。",
                }
            )

    # 2. Process each vault property definition
    for def_id, defn in definitions_by_id.items():
        if def_id in invalid_def_ids:
            continue

        if def_id not in found_keys:
            missing_properties.append(def_id)
            continue

        fm_k = found_keys[def_id][0]
        raw_val = fm[fm_k]

        if raw_val is None or raw_val == "" or raw_val == []:
            parsed_properties[def_id] = []
            continue

        raw_items = raw_val if isinstance(raw_val, list) else [raw_val]

        parsed_items: list[dict[str, Any]] = []
        prop_error: Optional[str] = None

        for item in raw_items:
            if isinstance(item, dict):
                if "value" not in item:
                    prop_error = "値レコードに 'value' フィールドが存在しません。"
                    break
                item_val = item["value"]
                raw_s = item.get("valid_from")
                raw_e = item.get("valid_until")
            else:
                item_val = item
                raw_s = None
                raw_e = None

            # Validate valid_from and valid_until
            try:
                vf = normalize_date_str(raw_s) if raw_s is not None else None
                vu = normalize_date_str(raw_e) if raw_e is not None else None
            except ValueError as e:
                prop_error = str(e)
                break

            if vf and vu and vf > vu:
                prop_error = f"valid_from ({vf}) は valid_until ({vu}) 以下である必要があります。"
                break

            # Validate typed item_val
            data_type = defn["data_type"]
            val_text = None
            val_date = None
            val_num = None
            val_bool = None
            opt_id = None

            try:
                if data_type == "text":
                    if item_val is None or not str(item_val).strip():
                        raise ValueError("テキスト属性値が空です。")
                    val_text = str(item_val).strip()
                elif data_type == "date":
                    val_date = normalize_date_str(item_val)
                elif data_type == "number":
                    if isinstance(item_val, bool):
                        raise ValueError(f"数値属性値の形式が不正です: {item_val}")
                    try:
                        val_num = float(item_val)
                    except (ValueError, TypeError) as e:
                        raise ValueError(f"数値属性値の形式が不正です: {item_val}") from e
                elif data_type == "boolean":
                    if isinstance(item_val, bool):
                        val_bool = 1 if item_val else 0
                    elif isinstance(item_val, (int, str)) and str(item_val).strip().lower() in ("true", "1", "yes"):
                        val_bool = 1
                    elif isinstance(item_val, (int, str)) and str(item_val).strip().lower() in ("false", "0", "no"):
                        val_bool = 0
                    else:
                        raise ValueError(f"真偽値属性の形式が不正です: {item_val}")
                elif data_type == "select":
                    raw_str = str(item_val).strip() if item_val is not None else ""
                    if raw_str in defn["option_lookup"]:
                        opt_id = defn["option_lookup"][raw_str]
                    else:
                        raise ValueError(f"選択肢 '{item_val}' は属性定義 '{defn['display_name']}' の有効な選択肢として解決できません。")
            except ValueError as e:
                prop_error = str(e)
                break

            item_dict = {
                "value_text": val_text,
                "value_date": val_date,
                "value_number": val_num,
                "value_boolean": val_bool,
                "option_id": opt_id,
                "valid_from": vf,
                "valid_until": vu,
            }

            # Deduplicate exact duplicate items in raw input
            if item_dict not in parsed_items:
                parsed_items.append(item_dict)

        if prop_error:
            invalid_properties.append(
                {
                    "person_id": pid,
                    "person_name": pname,
                    "property_key": defn["key"],
                    "property_display_name": defn["display_name"],
                    "reason": prop_error,
                }
            )
            continue

        # Single cardinality overlap check
        if defn["cardinality"] == "single" and len(parsed_items) > 1:
            has_single_conflict = False
            for i in range(len(parsed_items)):
                for j in range(i + 1, len(parsed_items)):
                    pi1 = parsed_items[i]
                    pi2 = parsed_items[j]
                    if periods_overlap(pi1["valid_from"], pi1["valid_until"], pi2["valid_from"], pi2["valid_until"]):
                        # Check if they have different values
                        diff_val = (
                            pi1["value_text"] != pi2["value_text"]
                            or pi1["value_date"] != pi2["value_date"]
                            or pi1["value_number"] != pi2["value_number"]
                            or pi1["value_boolean"] != pi2["value_boolean"]
                            or pi1["option_id"] != pi2["option_id"]
                        )
                        if diff_val:
                            has_single_conflict = True
                            break
                if has_single_conflict:
                    break

            if has_single_conflict:
                invalid_properties.append(
                    {
                        "person_id": pid,
                        "person_name": pname,
                        "property_key": defn["key"],
                        "property_display_name": defn["display_name"],
                        "reason": f"単数属性 '{defn['display_name']}' で期間が重複する複数の異なる値が指定されています。",
                    }
                )
                continue

        parsed_properties[def_id] = parsed_items

    return {
        "parsed_properties": parsed_properties,
        "missing_properties": missing_properties,
        "invalid_properties": invalid_properties,
    }


def load_people_notes_with_report(
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[dict[str, PersonNote], dict[str, Any]]:
    """
    Load all person notes from under PEOPLE_PATH (vault.people) recursively.
    Does not raise exceptions on validation errors, but skipped notes and collisions
    are isolated and reported.

    Returns:
        A tuple of (safe_map, report):
          - safe_map: A dict mapping normalized name/aliases to safe PersonNote dicts.
          - report: A dict with detailed information of validation problems.
    """
    people_path = app_config.PEOPLE_PATH

    report = {
        "file_deficiencies": [],
        "duplicate_ids": [],
        "normalized_name_collisions": [],
        "alias_collisions": [],
        "parsed_notes": [],
    }

    if not people_path or not people_path.exists() or not people_path.is_dir():
        logger.info(
            "PEOPLE_PATH %s does not exist or is not a directory. Continuing with empty people list.",
            people_path,
        )
        return {}, report

    # Stage 1: Read files and catch file deficiencies
    raw_notes = []
    for path in sorted(people_path.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)

            # Check required fields - strictly validate type first
            if "id" not in fm or not isinstance(fm["id"], str) or not fm["id"].strip():
                raise ValueError(
                    f"Missing or empty required field 'id' in frontmatter of person note {path}"
                )
            if (
                "name" not in fm
                or not isinstance(fm["name"], str)
                or not fm["name"].strip()
            ):
                raise ValueError(
                    f"Missing or empty required field 'name' in frontmatter of person note {path}"
                )

            pid = fm["id"].strip()
            pname = fm["name"].strip()

            # Aliases validation
            aliases: list[str] = []
            if "aliases" in fm:
                raw_aliases = fm["aliases"]
                if raw_aliases is not None:
                    if not isinstance(raw_aliases, list):
                        raise ValueError(
                            f"'aliases' field in frontmatter of {path} must be a list of strings, got {type(raw_aliases)}"
                        )
                    for val in raw_aliases:
                        if val is None or not isinstance(val, str):
                            raise ValueError(
                                f"Alias '{val}' in {path} is not a valid string"
                            )
                        aliases.append(val.strip())

            raw_notes.append(
                {
                    "id": pid,
                    "name": pname,
                    "aliases": aliases,
                    "file_path": path,
                    "frontmatter": fm,
                }
            )
        except (OSError, ValueError, TypeError) as e:
            report["file_deficiencies"].append({"path": str(path), "message": str(e)})

    report["parsed_notes"] = raw_notes

    # Stage 2: Check for duplicate IDs
    id_to_notes = {}
    for note in raw_notes:
        id_to_notes.setdefault(note["id"], []).append(note)

    duplicate_ids_set = set()
    stage2_notes = []
    for pid, notes in id_to_notes.items():
        if len(notes) > 1:
            duplicate_ids_set.add(pid)
            report["duplicate_ids"].append(
                {"id": pid, "paths": [str(n["file_path"]) for n in notes]}
            )
        else:
            stage2_notes.append(notes[0])

    # Stage 3: Check for normalized name collisions
    norm_name_to_notes = {}
    for note in stage2_notes:
        norm_name = normalize_entity_name(note["name"])
        if norm_name:
            norm_name_to_notes.setdefault(norm_name, []).append(note)

    colliding_names_set = set()
    stage3_notes = []
    for norm_name, notes in norm_name_to_notes.items():
        distinct_ids = {n["id"] for n in notes}
        if len(distinct_ids) > 1:
            colliding_names_set.add(norm_name)
            report["normalized_name_collisions"].append(
                {
                    "normalized_name": norm_name,
                    "notes": [
                        {"id": n["id"], "name": n["name"], "path": str(n["file_path"])}
                        for n in notes
                    ],
                }
            )
        else:
            stage3_notes.extend(notes)

    # Stage 4: Check for alias collisions
    claims: dict[str, list[dict]] = {}
    for note in stage3_notes:
        # Main name claim
        norm_name = normalize_entity_name(note["name"])
        if norm_name:
            claims.setdefault(norm_name, []).append(
                {
                    "id": note["id"],
                    "name": note["name"],
                    "path": str(note["file_path"]),
                    "role": "name",
                }
            )
        # Alias claims
        for alias in note["aliases"]:
            norm_alias = normalize_entity_name(alias)
            if norm_alias:
                claims.setdefault(norm_alias, []).append(
                    {
                        "id": note["id"],
                        "name": note["name"],
                        "path": str(note["file_path"]),
                        "role": "alias",
                        "alias_value": alias,
                    }
                )

    colliding_aliases_set = set()
    alias_exclusions: dict[
        str, set[str]
    ] = {}  # id -> set of normalized aliases to exclude

    for norm_str, claim_list in claims.items():
        distinct_ids = {c["id"] for c in claim_list}
        if len(distinct_ids) > 1:
            report["alias_collisions"].append(
                {
                    "alias": norm_str,
                    "notes": [
                        {
                            "id": c["id"],
                            "name": c["name"],
                            "path": c["path"],
                            "role": c["role"],
                        }
                        for c in claim_list
                    ],
                }
            )
            colliding_aliases_set.add(norm_str)
            for c in claim_list:
                if c["role"] == "alias":
                    alias_exclusions.setdefault(c["id"], set()).add(norm_str)

    # Construct final safe map and safe notes
    normalized_to_note = {}
    for note in stage3_notes:
        pid = note["id"]
        safe_aliases = []
        exclusions = alias_exclusions.get(pid, set())
        for alias in note["aliases"]:
            norm_alias = normalize_entity_name(alias)
            if norm_alias and norm_alias not in exclusions:
                safe_aliases.append(alias)

        safe_note: PersonNote = {
            "id": pid,
            "name": note["name"],
            "aliases": safe_aliases,
            "file_path": note["file_path"],
        }

        # Map normalized name
        norm_name = normalize_entity_name(note["name"])
        if norm_name:
            normalized_to_note[norm_name] = safe_note

        # Map safe normalized aliases
        for alias in safe_aliases:
            norm_alias = normalize_entity_name(alias)
            if norm_alias:
                normalized_to_note[norm_alias] = safe_note

    # Stage 5: Parse Vault property frontmatter for vault-source property definitions
    close_conn_on_exit = False
    if conn is None:
        try:
            conn = get_db_connection()
            close_conn_on_exit = True
        except Exception as e:
            logger.warning("Could not connect to DB for vault property loader: %s", e)
            conn = None

    property_report = {
        "invalid_properties": [],
        "parsed_properties_by_note_id": {},
        "missing_properties_by_note_id": {},
    }

    if conn is not None:
        try:
            lookup = get_vault_property_definitions_lookup(conn)
            for note in stage3_notes:
                note_id = note["id"]
                fm = note.get("frontmatter", {})
                p_res = parse_vault_properties_for_note(
                    fm, note_id, note["name"], lookup
                )
                if p_res["invalid_properties"]:
                    property_report["invalid_properties"].extend(
                        p_res["invalid_properties"]
                    )
                property_report["parsed_properties_by_note_id"][note_id] = p_res[
                    "parsed_properties"
                ]
                property_report["missing_properties_by_note_id"][note_id] = p_res[
                    "missing_properties"
                ]
        finally:
            if close_conn_on_exit:
                conn.close()

    report["property_report"] = property_report

    return normalized_to_note, report


def find_person_note_path_by_vault_id(vault_id: str) -> Optional[Path]:
    """Find a single person note file by its frontmatter ``id`` (vault_id).

    Lightweight single-note lookup that stops at the first matching file.
    Unlike :func:`load_people_notes_with_report`, it does not perform the full
    4-stage validation pipeline or build collision reports. Used by the
    ``people_get`` agent tool to avoid re-parsing every person note on each
    invocation.
    """
    if not vault_id or not isinstance(vault_id, str):
        return None
    stripped_vault_id = vault_id.strip()
    if not stripped_vault_id:
        return None
    people_path = app_config.PEOPLE_PATH
    if not people_path or not people_path.exists() or not people_path.is_dir():
        return None
    # Iterate lazily; avoid sorted() which forces full enumeration + sort.
    for path in people_path.rglob("*.md"):
        try:
            content = path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            pid = fm.get("id")
            if isinstance(pid, str) and pid.strip() == stripped_vault_id:
                return path
        except _PEOPLE_NOTE_SCAN_EXCEPTS:
            continue
    return None


def load_and_validate_people_notes() -> dict[str, PersonNote]:
    """
    Wrapper for existing backward-compatibility.
    Does not discard the validation report; instead, it raises the first encountered error
    to preserve original strict failure behavior for non-Web-UI callers (e.g. existing tests).
    """
    safe_map, report = load_people_notes_with_report()

    if report.get("file_deficiencies"):
        raise ValueError(report["file_deficiencies"][0]["message"])
    if report.get("duplicate_ids"):
        dup = report["duplicate_ids"][0]
        raise ValueError(
            f"Duplicate person ID '{dup['id']}' found in files: {', '.join(dup['paths'])}"
        )
    if report.get("normalized_name_collisions"):
        col = report["normalized_name_collisions"][0]
        raise ValueError(
            f"Duplicate mapping for normalized name/alias '{col['normalized_name']}'"
        )
    if report.get("alias_collisions"):
        col = report["alias_collisions"][0]
        raise ValueError(
            f"Duplicate mapping for normalized name/alias '{col['alias']}'"
        )

    return safe_map
