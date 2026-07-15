from __future__ import annotations

import logging
from typing import Optional

from obsidian_ai_hub import research_dedup, research_themes
from obsidian_ai_hub.memory import get_embedder

logger = logging.getLogger(__name__)


def create_theme_and_research(
    *,
    theme: str,
    direction: Optional[str] = None,
    kind: str = "explore",
    why_now: str = "",
    confidence: float = 1.0,
) -> dict:
    normalized = research_themes.normalize_theme_key(theme)
    existing = research_themes.find_exact_duplicate(normalized)
    if existing:
        logger.info("Exact duplicate found for '%s': %s", theme, existing["theme_id"])
        research_themes.create_theme(
            theme=theme,
            direction=direction,
            kind=kind,
            why_now=why_now,
            confidence=confidence,
            status="duplicate",
            duplicate_of_theme_id=existing["theme_id"],
            duplicate_reason="normalized exact match",
        )
        return {"status": "duplicate", "theme_id": existing["theme_id"]}

    embedder = get_embedder()
    similar = research_themes.find_top_similar(theme, embedder, k=5) if embedder else []

    decision = research_dedup.run_dedup_review(theme, direction, why_now, similar)
    logger.info("Dedup decision for '%s': %s (failed=%s)", theme, decision["decision"], decision.get("failed"))

    if decision["decision"] == "duplicate":
        target = decision["target_theme_id"]
        rec = research_themes.create_theme(
            theme=theme,
            direction=direction,
            kind=kind,
            why_now=why_now,
            confidence=confidence,
            status="duplicate",
            duplicate_of_theme_id=target,
            duplicate_reason=decision.get("reason"),
        )
        return {"status": "duplicate", "theme_id": rec["theme_id"]}

    rec = research_themes.create_theme(
        theme=theme,
        direction=direction,
        kind=kind,
        why_now=why_now,
        confidence=confidence,
        status="candidate",
        related_theme_ids=decision.get("related_ids", []),
        duplicate_reason=decision.get("reason"),
    )

    try:
        _run_research(rec["theme_id"])
    except Exception as exc:
        logger.exception("Immediate research failed for theme %s: %s", rec["theme_id"], exc)

    job = research_themes.latest_job(rec["theme_id"])
    return {"status": "candidate", "theme_id": rec["theme_id"], "job": job}


def _run_research(theme_id: str) -> None:
    from obsidian_ai_hub.research_agent import run_theme_research
    run_theme_research(theme_id)
