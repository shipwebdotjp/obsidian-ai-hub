import logging
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.summary.store import normalize_entity_name

logger = logging.getLogger(__name__)


def get_active_projects_for_prompt() -> list[dict]:
    """
    Load active, inquiry, paused projects from the database, and shape them for LLM prompt.
    Does not catch exceptions internally, so they propagate naturally.
    """
    from obsidian_ai_hub.web.service import list_projects
    existing_projects = []
    for status_val in ("inquiry", "active", "paused"):
        for p in list_projects(status=status_val):
            existing_projects.append({
                "id": p["project_id"],
                "display_name": p["display_name"],
                "domain": p["domain"],
                "goal": p.get("goal"),
                "keywords": p.get("keywords") or []
            })
    return existing_projects


def inherit_projects_and_candidates(sub_records: list[dict | None]) -> tuple[list[int], list[dict]]:
    """
    Extracts and aggregates project_ids and unresolved project_candidates from sub-level records,
    validating candidates against database status.
    Returns:
        (project_ids, project_candidates)
    """
    union_project_ids = set()
    union_candidates = []
    seen_candidate_norms = set()

    for r in sub_records:
        if not r:
            continue
        p_ids = r.get("project_ids") or []
        for pid in p_ids:
            if isinstance(pid, int):
                union_project_ids.add(pid)

        pcands = r.get("project_candidates") or []
        for c in pcands:
            if not isinstance(c, dict):
                continue
            status = c.get("status") or "unresolved"
            if status != "unresolved":
                continue
            norm_name = c.get("normalized_name")
            if not norm_name:
                norm_name = normalize_entity_name(c.get("display_name") or c.get("name") or "")
            if norm_name and norm_name not in seen_candidate_norms:
                seen_candidate_norms.add(norm_name)
                union_candidates.append({
                    "display_name": c.get("display_name") or c.get("name"),
                    "domain": c.get("domain") or "personal",
                    "goal": c.get("goal"),
                    "description": c.get("description"),
                    "keywords": c.get("keywords") or [],
                    "start_date": c.get("start_date"),
                    "target_date": c.get("target_date"),
                    "completed_date": c.get("completed_date"),
                    "evidence": c.get("evidence")
                })

    project_ids = list(union_project_ids)
    filtered_candidates = []

    # Double check database status of candidates (no broad exception fallback around verification)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        for c in union_candidates:
            norm_name = normalize_entity_name(c["display_name"])
            cursor.execute("SELECT status FROM project_candidates WHERE normalized_name = ?", (norm_name,))
            row = cursor.fetchone()
            if row is not None:
                status = row["status"]
                if status == "resolved":
                    cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ?", (norm_name,))
                    p_row = cursor.fetchone()
                    if p_row is not None:
                        project_ids.append(p_row[0])
                    continue
                elif status == "rejected":
                    continue
            filtered_candidates.append(c)
    finally:
        conn.close()

    return list(set(project_ids)), filtered_candidates


def parse_llm_project_notes(
    data: dict,
    valid_ids: set[int] | None = None,
) -> dict[int, str]:
    """Parse project_notes from LLM output dict.

    Returns a dict mapping project_id → note for valid entries.
    When valid_ids is provided, only those IDs are accepted.
    Duplicate project_ids are skipped (first wins).
    """
    notes: dict[int, str] = {}
    raw = data.get("project_notes") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return notes
    for item in raw:
        if not isinstance(item, dict):
            continue
        pid = item.get("project_id")
        if not isinstance(pid, int):
            continue
        if valid_ids is not None and pid not in valid_ids:
            continue
        if pid in notes:
            continue
        note = item.get("note")
        notes[pid] = note if isinstance(note, str) else ""
    return notes


def build_project_notes_list(
    notes_map: dict[int, str],
    project_ids: list[int],
) -> list[dict]:
    """Build a sorted list of {project_id, note} from notes_map filtered by project_ids.

    Project IDs are returned in the order of project_ids.
    IDs missing from notes_map get an empty note.
    """
    return [
        {"project_id": pid, "note": notes_map.get(pid, "")}
        for pid in project_ids
    ]


def validate_project_ids(
    raw_ids: list,
    valid_ids: set[int],
) -> list[int]:
    """Validate and deduplicate project IDs, preserving input order."""
    seen: set[int] = set()
    result: list[int] = []
    for p in raw_ids:
        if isinstance(p, int) and p not in seen and p in valid_ids:
            seen.add(p)
            result.append(p)
        elif isinstance(p, str) and str(p).isdigit():
            pid = int(p)
            if pid not in seen and pid in valid_ids:
                seen.add(pid)
                result.append(pid)
    return result
