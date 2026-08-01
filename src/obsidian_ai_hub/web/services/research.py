import logging
from typing import Optional

logger = logging.getLogger(__name__)


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
