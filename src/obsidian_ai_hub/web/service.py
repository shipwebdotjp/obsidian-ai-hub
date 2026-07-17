import json
import logging
import threading
from pathlib import Path
from typing import Optional

from obsidian_ai_hub import memory
from obsidian_ai_hub.handler import obsidian_vault_retriever
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


def run_research_theme(theme: str, mode: str = "auto") -> tuple[dict, dict]:
    from obsidian_ai_hub.research.runner import (
        get_or_create_theme_and_job,
        submit_research_job_bg,
    )
    from obsidian_ai_hub.research import db
    theme_rec, job_rec = get_or_create_theme_and_job(theme=theme, mode=mode)
    try:
        submit_research_job_bg(
            theme_id=theme_rec["theme_id"],
            job_id=job_rec["job_id"],
            mode=mode,
        )
    except Exception as e:
        logger.exception("Failed to submit background research job")
        db.update_job(job_rec["job_id"], status="failed", error=str(e))
        raise
    return theme_rec, job_rec


# --- Vault Search services ---

_vault_search_lock = threading.Lock()


def search_vault(q: str, k: int = 10, mode: str = "hybrid") -> dict:
    with _vault_search_lock:
        result_json = obsidian_vault_retriever.search_obsidian_vault.func(
            query=q, k=k, search_mode=mode
        )
    try:
        results = json.loads(result_json)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse vault search JSON output: %s", e)
        raise ValueError("vault search returned invalid JSON") from e
    if isinstance(results, dict) and "error" in results:
        raise ValueError(results["error"])
    from obsidian_ai_hub.utils import config
    vault_name = Path(config.VAULT_PATH).name
    for hit in results:
        if not isinstance(hit.get("metadata"), dict):
            hit["metadata"] = {}
        hit["metadata"]["vault_name"] = vault_name
    return {"items": results, "total": len(results)}


def get_vault_file(relative_path: str) -> dict:
    from obsidian_ai_hub.utils import config
    vault_dir = Path(config.VAULT_PATH).resolve()

    p = Path(relative_path)
    if p.is_absolute():
        raise ValueError("Absolute paths are not allowed")

    if ".." in p.parts:
        raise ValueError("Path traversal components (..) are not allowed")

    if p.suffix.lower() != ".md":
        raise ValueError("Only Markdown (.md) files are allowed")

    # Resolve resolved path (to handle symlinks properly)
    try:
        resolved_path = (vault_dir / p).resolve(strict=True)
    except FileNotFoundError:
        # Check traversal on non-existing path
        resolved_path = (vault_dir / p).resolve(strict=False)
        try:
            resolved_path.relative_to(vault_dir)
        except ValueError:
            raise ValueError("Path is outside the Vault")
        raise FileNotFoundError("File not found")

    # Verify containment for existing file
    try:
        resolved_path.relative_to(vault_dir)
    except ValueError:
        raise ValueError("Path is outside the Vault")

    if not resolved_path.is_file():
        raise FileNotFoundError("File is not a file")

    with open(resolved_path, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "content": content,
        "relative_path": relative_path,
    }


# --- Summary services ---

from obsidian_ai_hub.summary import store as summary_store


def list_summaries(
    period_type: Optional[str] = None,
    period: Optional[str] = None,
    topic: Optional[str] = None,
    project: Optional[str] = None,
    person: Optional[str] = None,
) -> list[dict]:
    return summary_store.list_summaries(
        period_type=period_type,
        period=period,
        topic=topic,
        project=project,
        person=person,
    )


def get_summary(summary_id: str) -> Optional[dict]:
    return summary_store.get_summary_by_id(summary_id)


def get_summary_options() -> dict:
    return summary_store.get_summary_options()
