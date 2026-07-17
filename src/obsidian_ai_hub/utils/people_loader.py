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


def load_and_validate_people_notes() -> dict[str, PersonNote]:
    """
    Load all person notes from under PEOPLE_PATH (vault.people) recursively.
    Validates frontmatter:
      - Requires 'id' and 'name' as non-empty strings.
      - 'aliases' is an optional list of strings.
      - Duplicate normalized mapping across distinct IDs is treated as a validation error.
      - Duplicate IDs across different files is treated as a validation error.

    Returns:
        A dict mapping normalized name/aliases to the PersonNote dict.
        Returns an empty dict if the directory does not exist or has no notes.
    """
    people_path = app_config.PEOPLE_PATH
    if not people_path or not people_path.exists() or not people_path.is_dir():
        logger.info("PEOPLE_PATH %s does not exist or is not a directory. Continuing with empty people list.", people_path)
        return {}

    notes: list[PersonNote] = []
    seen_ids: dict[str, Path] = {}  # id -> file_path
    normalized_to_note: dict[str, PersonNote] = {}  # normalized_name_or_alias -> PersonNote

    # Recursively find all .md files
    for path in sorted(people_path.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Failed to read note file %s: %s", path, e)
            raise ValueError(f"Failed to read note file {path}: {e}")

        try:
            fm = parse_frontmatter(content)
        except Exception as e:
            logger.error("Failed to parse frontmatter for note file %s: %s", path, e)
            raise ValueError(f"Failed to parse frontmatter for note file {path}: {e}")

        # Check required fields
        if "id" not in fm or not fm["id"]:
            raise ValueError(f"Missing or empty required field 'id' in frontmatter of person note {path}")
        if "name" not in fm or not fm["name"]:
            raise ValueError(f"Missing or empty required field 'name' in frontmatter of person note {path}")

        pid = str(fm["id"]).strip()
        pname = str(fm["name"]).strip()

        if not pid:
            raise ValueError(f"Empty 'id' in frontmatter of person note {path}")
        if not pname:
            raise ValueError(f"Empty 'name' in frontmatter of person note {path}")

        # Validate duplicate IDs across files
        if pid in seen_ids:
            raise ValueError(f"Duplicate person ID '{pid}' found in files: {seen_ids[pid]} and {path}")
        seen_ids[pid] = path

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

        note_record: PersonNote = {
            "id": pid,
            "name": pname,
            "aliases": aliases,
            "file_path": path,
        }
        notes.append(note_record)

    # Validate duplicate normalized names/aliases across distinct IDs
    # Maps normalized name/alias -> (id, file_path, original_value)
    name_registry: dict[str, tuple[str, Path, str]] = {}

    for note in notes:
        # Check both name and all aliases
        all_candidate_names = [(note["name"], "name")] + [(alias, f"alias '{alias}'") for alias in note["aliases"]]
        for raw_val, source_desc in all_candidate_names:
            norm_val = normalize_entity_name(raw_val)
            if not norm_val:
                continue

            if norm_val in name_registry:
                existing_id, existing_path, existing_orig = name_registry[norm_val]
                if existing_id != note["id"]:
                    raise ValueError(
                        f"Duplicate mapping for normalized name/alias '{norm_val}' found across different people:\n"
                        f"  - '{existing_orig}' in file {existing_path} (ID: {existing_id})\n"
                        f"  - '{raw_val}' in file {note['file_path']} (ID: {note['id']})"
                    )
            else:
                name_registry[norm_val] = (note["id"], note["file_path"], raw_val)

            # Map to record
            normalized_to_note[norm_val] = note

    return normalized_to_note
