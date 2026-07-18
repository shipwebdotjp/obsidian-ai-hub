from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict, Any

from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.utils.extracter import parse_frontmatter
from obsidian_ai_hub.summary.store import normalize_entity_name

logger = logging.getLogger(__name__)


class PersonNote(TypedDict):
    id: str
    name: str
    aliases: list[str]
    file_path: Path


def load_people_notes_with_report() -> tuple[dict[str, PersonNote], dict[str, Any]]:
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
        "parsed_notes": []
    }

    if not people_path or not people_path.exists() or not people_path.is_dir():
        logger.info("PEOPLE_PATH %s does not exist or is not a directory. Continuing with empty people list.", people_path)
        return {}, report

    # Stage 1: Read files and catch file deficiencies
    raw_notes = []
    for path in sorted(people_path.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)

            # Check required fields - strictly validate type first
            if "id" not in fm or not isinstance(fm["id"], str) or not fm["id"].strip():
                raise ValueError(f"Missing or empty required field 'id' in frontmatter of person note {path}")
            if "name" not in fm or not isinstance(fm["name"], str) or not fm["name"].strip():
                raise ValueError(f"Missing or empty required field 'name' in frontmatter of person note {path}")

            pid = fm["id"].strip()
            pname = fm["name"].strip()

            # Aliases validation
            aliases: list[str] = []
            if "aliases" in fm:
                raw_aliases = fm["aliases"]
                if raw_aliases is not None:
                    if not isinstance(raw_aliases, list):
                        raise ValueError(f"'aliases' field in frontmatter of {path} must be a list of strings, got {type(raw_aliases)}")
                    for val in raw_aliases:
                        if val is None or not isinstance(val, str):
                            raise ValueError(f"Alias '{val}' in {path} is not a valid string")
                        aliases.append(val.strip())

            raw_notes.append({
                "id": pid,
                "name": pname,
                "aliases": aliases,
                "file_path": path,
            })
        except (OSError, ValueError, TypeError) as e:
            report["file_deficiencies"].append({
                "path": str(path),
                "message": str(e)
            })

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
            report["duplicate_ids"].append({
                "id": pid,
                "paths": [str(n["file_path"]) for n in notes]
            })
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
            report["normalized_name_collisions"].append({
                "normalized_name": norm_name,
                "notes": [{"id": n["id"], "name": n["name"], "path": str(n["file_path"])} for n in notes]
            })
        else:
            stage3_notes.extend(notes)

    # Stage 4: Check for alias collisions
    claims: dict[str, list[dict]] = {}
    for note in stage3_notes:
        # Main name claim
        norm_name = normalize_entity_name(note["name"])
        if norm_name:
            claims.setdefault(norm_name, []).append({
                "id": note["id"],
                "name": note["name"],
                "path": str(note["file_path"]),
                "role": "name"
            })
        # Alias claims
        for alias in note["aliases"]:
            norm_alias = normalize_entity_name(alias)
            if norm_alias:
                claims.setdefault(norm_alias, []).append({
                    "id": note["id"],
                    "name": note["name"],
                    "path": str(note["file_path"]),
                    "role": "alias",
                    "alias_value": alias
                })

    colliding_aliases_set = set()
    alias_exclusions: dict[str, set[str]] = {} # id -> set of normalized aliases to exclude

    for norm_str, claim_list in claims.items():
        distinct_ids = {c["id"] for c in claim_list}
        if len(distinct_ids) > 1:
            report["alias_collisions"].append({
                "alias": norm_str,
                "notes": [{"id": c["id"], "name": c["name"], "path": c["path"], "role": c["role"]} for c in claim_list]
            })
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
            "file_path": note["file_path"]
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

    return normalized_to_note, report


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
        raise ValueError(f"Duplicate person ID '{dup['id']}' found in files: {', '.join(dup['paths'])}")
    if report.get("normalized_name_collisions"):
        col = report["normalized_name_collisions"][0]
        raise ValueError(f"Duplicate mapping for normalized name/alias '{col['normalized_name']}'")
    if report.get("alias_collisions"):
        col = report["alias_collisions"][0]
        raise ValueError(f"Duplicate mapping for normalized name/alias '{col['alias']}'")

    return safe_map
