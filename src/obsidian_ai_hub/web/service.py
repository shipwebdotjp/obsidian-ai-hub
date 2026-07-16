import logging
from typing import Optional

from obsidian_ai_hub import memory
from obsidian_ai_hub.web import schemas

logger = logging.getLogger(__name__)


def list_memories(
    status: Optional[str] = None,
    kind: Optional[str] = None,
    topic: Optional[str] = None,
    q: Optional[str] = None,
) -> list[dict]:
    rows = memory.load_all_memories()
    out = []
    for r in rows:
        if status and r.get("status") != status:
            continue
        if kind and r.get("kind") != kind:
            continue
        if topic and topic not in (r.get("topics") or []):
            continue
        if q:
            target = (r.get("content") or "") + " " + " ".join(r.get("tags") or [])
            if q.lower() not in target.lower():
                continue
        out.append(r)
    return out


def get_memory(memory_id: str) -> Optional[dict]:
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return memory.deserialize_memory(dict(row))
    finally:
        conn.close()


def get_events(memory_id: str) -> list[dict]:
    return memory.get_memory_events(memory_id)


REVIEW_ACTIONS = {"approve", "reject", "edit"}


def review_memory(memory_id: str, action: str, new_content: Optional[str] = None) -> dict:
    if action not in REVIEW_ACTIONS:
        raise ValueError("action must be approve/reject/edit")
    if action == "edit" and not (new_content and new_content.strip()):
        raise ValueError("new_content is required for edit action")

    if action == "edit":
        payload = {"content": new_content}
        result = memory.update_memory_fields(memory_id, payload)
        if not result["found"]:
            raise LookupError(memory_id)
        return result["memory"]
    ok = memory.review_memory(memory_id, action, new_content)
    if not ok:
        raise LookupError(memory_id)
    return get_memory(memory_id)


def update_memory(memory_id: str, fields: dict) -> dict:
    return memory.update_memory_fields(memory_id, fields)


def batch_review(memory_ids: list, action: str) -> dict:
    if action not in schemas.ALLOWED_ACTIONS:
        raise ValueError("action must be approve/reject")
    return memory.batch_review_memories(memory_ids, action)

def resolve_memory(
    candidate_id: str,
    action: str,
    target_memory_id: str,
    integrated_content: Optional[str] = None,
    switch_date: Optional[str] = None
) -> tuple[dict, Optional[dict]]:
    return memory.resolve_memory(
        candidate_id,
        action,
        target_memory_id,
        integrated_content=integrated_content,
        switch_date=switch_date
    )


def delete_memory(memory_id: str) -> dict:
    return memory.delete_memory(memory_id)


def batch_delete(memory_ids: list[str]) -> dict:
    return memory.batch_delete_memories(memory_ids)


def get_memory_options() -> dict:
    from obsidian_ai_hub.utils.topics import TOPIC_ENUM
    kinds_order = ["preference", "decision_policy", "fact", "commitment", "pattern", "episode"]
    kinds = [k for k in kinds_order if k in schemas.ALLOWED_KINDS]
    for k in sorted(list(schemas.ALLOWED_KINDS)):
        if k not in kinds_order:
            kinds.append(k)
    return {
        "kinds": kinds,
        "topics": list(TOPIC_ENUM)
    }


def render_copilot_profile() -> list[str]:
    return memory.render_copilot_profile()


# --- Research Theme services ---

def list_research_themes(
    status: Optional[str] = None,
    job_status: Optional[str] = None,
    q: Optional[str] = None,
) -> list[dict]:
    from obsidian_ai_hub.research import db
    return db.list_themes(status=status, job_status=job_status, q=q)


def get_research_theme(theme_id: str) -> Optional[dict]:
    from obsidian_ai_hub.research import db
    theme = db.get_theme(theme_id)
    if theme is None:
        return None
    job = db.latest_job(theme_id)
    theme["latest_job"] = job
    return theme


def review_research_theme(theme_id: str, action: str, reason: Optional[str] = None) -> Optional[dict]:
    from obsidian_ai_hub.research import db
    from obsidian_ai_hub import research_agent
    theme = db.get_theme(theme_id)
    if theme is None:
        return None
    if action == "approve":
        job = db.latest_job(theme_id)
        if job and job.get("status") == "succeeded" and job.get("markdown"):
            research_agent.save_research_to_vault(theme_id)
        db.set_status(theme_id, "approved", reviewed_by="user", reason=reason)
    elif action == "reject":
        db.set_status(theme_id, "rejected", reviewed_by="user", reason=reason)
    else:
        raise ValueError(f"Invalid action: {action}")
    return db.get_theme(theme_id)


def rerun_research_theme(theme_id: str) -> Optional[dict]:
    from obsidian_ai_hub import research_agent
    job = research_agent.run_theme_research(theme_id)
    return job
