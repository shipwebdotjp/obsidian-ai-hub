from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.web import schemas


def get_edit_options() -> dict:
    from obsidian_ai_hub.utils.topics import TOPIC_ENUM
    from obsidian_ai_hub.summary.store import (
        DAY_ITEM_KINDS,
        WEEK_ITEM_KINDS,
        MONTH_ITEM_KINDS,
    )

    return {
        "topics": list(TOPIC_ENUM),
        "item_kinds": {
            "day": DAY_ITEM_KINDS,
            "week": WEEK_ITEM_KINDS,
            "month": MONTH_ITEM_KINDS,
        },
    }


def update_summary_detail(summary_id: str, body: schemas.SummaryUpdateRequest) -> dict:
    from obsidian_ai_hub.utils.topics import TOPIC_ENUM
    from obsidian_ai_hub.summary.store import (
        DAY_ITEM_KINDS,
        WEEK_ITEM_KINDS,
        MONTH_ITEM_KINDS,
    )

    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise ValueError("empty payload")

    # Load current summary to check period_type
    current = summary_store.get_summary_by_id(summary_id)
    if current is None:
        raise FileNotFoundError(f"Summary not found: {summary_id}")
    period_type = current["period_type"]

    allowed_kinds = {
        "day": DAY_ITEM_KINDS,
        "week": WEEK_ITEM_KINDS,
        "month": MONTH_ITEM_KINDS,
    }[period_type]

    # Validate summary body
    if "summary" in payload:
        val = payload["summary"]
        if val is not None and not str(val).strip():
            raise ValueError("summary body must not be empty")

    # Validate items
    if "items" in payload:
        raw_items = payload["items"]
        if raw_items is None:
            raw_items = []
        for item in raw_items:
            if item["kind"] not in allowed_kinds:
                raise ValueError(
                    f"Invalid item kind '{item['kind']}' for {period_type} summary; allowed: {allowed_kinds}"
                )
            if not item["body"] or not str(item["body"]).strip():
                raise ValueError("item body must not be empty")
            item["body"] = str(item["body"]).strip()
        payload["items"] = raw_items

    # Validate topics
    if "topics" in payload:
        topics = payload["topics"]
        if topics is None:
            topics = []
        for t in topics:
            if t not in TOPIC_ENUM:
                raise ValueError(
                    f"Invalid topic '{t}'; must be one of the standard candidates"
                )
        if len(topics) > 5:
            raise ValueError("topics must contain at most 5 items")
        payload["topics"] = topics

    # Validate keywords: trim, drop empty, dedup
    if "keywords" in payload:
        kw = payload["keywords"]
        if kw is None:
            kw = []
        seen_kw = set()
        cleaned_kw = []
        for k in kw:
            trimmed = str(k).strip()
            if trimmed and trimmed not in seen_kw:
                seen_kw.add(trimmed)
                cleaned_kw.append(trimmed)
        payload["keywords"] = cleaned_kw

    # Validate people: dedup person_id, existence check
    if "people" in payload:
        people = payload["people"]
        if people is None:
            people = []
        seen_pids = set()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            for p in people:
                pid = p["person_id"]
                if pid in seen_pids:
                    raise ValueError(f"Duplicate person_id: {pid}")
                seen_pids.add(pid)
                cursor.execute(
                    "SELECT person_id FROM people WHERE person_id = ?", (pid,)
                )
                if cursor.fetchone() is None:
                    raise ValueError(f"Person not found: {pid}")
        finally:
            conn.close()
        payload["people"] = people

    # Validate project_notes: only currently linked project IDs, no duplicates
    # project_notes is a partial update: only the note field is updated for matched
    # projects; projects not in the array are preserved with their existing notes.
    if "project_notes" in payload:
        pn = payload["project_notes"]
        if pn is None:
            pn = []
        seen_pids = set()
        linked_pids = {p["project_id"] for p in current.get("project_notes", [])}
        for item in pn:
            pid = item["project_id"]
            if pid in seen_pids:
                raise ValueError(f"Duplicate project_id in project_notes: {pid}")
            seen_pids.add(pid)
            if pid not in linked_pids:
                raise ValueError(
                    f"Project {pid} is not linked to this summary and cannot have a note assigned"
                )
        payload["project_notes"] = pn

    # Validate mood/sleep_raw: day-only
    if ("mood" in payload or "sleep_raw" in payload) and period_type != "day":
        raise ValueError("mood and sleep_raw can only be set on day summaries")

    try:
        result = summary_store.update_summary(summary_id, payload)
    except ValueError:
        raise ValueError(f"Summary not found: {summary_id}")
    return result


def delete_summary_detail(summary_id: str) -> bool:
    return summary_store.delete_summary(summary_id)
