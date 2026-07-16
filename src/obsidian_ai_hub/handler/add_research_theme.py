from __future__ import annotations

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _normalize_theme(theme: str) -> str:
    normalized = theme.replace("\r", "").replace("\n", "").strip()
    if not normalized:
        raise ValueError("theme must not be empty")
    return normalized


def append_research_theme(
    theme: str,
    candidate_path: Path | None = None,
    *,
    direction: str | None = None,
) -> str:
    normalized = _normalize_theme(theme)
    normalized_direction = direction.replace("\r", "").replace("\n", "").strip() if direction else None

    from obsidian_ai_hub.research.pipeline import create_theme_and_research
    result = create_theme_and_research(
        theme=normalized,
        direction=normalized_direction,
        kind="explore",
        why_now="",
        confidence=1.0,
    )

    if result["status"] == "candidate":
        job = result.get("job")
        if job and job.get("status") == "succeeded":
            try:
                from obsidian_ai_hub.research.runner import save_research_to_vault
                output_path = save_research_to_vault(result["theme_id"])
                if output_path:
                    from obsidian_ai_hub.research import db
                    db.set_status(result["theme_id"], "approved", reviewed_by="system")
                    logger.info("Research saved to vault: %s", output_path)
            except Exception:
                logger.exception("Failed to save research to vault for theme %s", result["theme_id"])

    logger.info("Added research theme '%s' (status=%s, theme_id=%s)", normalized, result["status"], result.get("theme_id"))
    return result["status"]


def main(theme: str | None = None, direction: str | None = None) -> str:
    if theme is None:
        parser = argparse.ArgumentParser(description="Add a theme to the research candidate list")
        parser.add_argument("theme", help="テーマ名")
        parser.add_argument("--direction", "-d", help="調査方向（任意）")
        args = parser.parse_args()
        theme = args.theme
        direction = args.direction

    return append_research_theme(theme, direction=direction)


if __name__ == "__main__":
    main()
