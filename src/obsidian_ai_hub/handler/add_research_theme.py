from __future__ import annotations

import argparse
from pathlib import Path

from obsidian_ai_hub.research_agent import read_lines, write_lines_atomic
from obsidian_ai_hub.utils import config


CHECKBOX_UNCHECKED = "- [ ]"


def _normalize_theme(theme: str) -> str:
    normalized = theme.replace("\r", "").replace("\n", "").strip()
    if not normalized:
        raise ValueError("theme must not be empty")
    return normalized


def _normalize_direction(direction: str) -> str:
    normalized = direction.replace("\r", "").replace("\n", "").strip()
    if not normalized:
        raise ValueError("direction must not be empty")
    return normalized


def _format_candidate_line(theme: str, direction: str | None = None) -> str:
    if direction is None:
        return f"{CHECKBOX_UNCHECKED} {theme}\n"
    return f"{CHECKBOX_UNCHECKED} {theme} / {direction}\n"


def append_research_theme(
    theme: str,
    candidate_path: Path | None = None,
    *,
    direction: str | None = None,
) -> Path:
    """Append a research theme to the candidate list.

    The candidate list is stored as Markdown checkbox items so it can be
    consumed by `research_agent.main()`.
    """
    normalized = _normalize_theme(theme)
    normalized_direction = _normalize_direction(direction) if direction is not None else None
    target_path = candidate_path or config.RESEARCH_CANDIDATE_THEME_LIST_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    lines = read_lines(target_path) if target_path.exists() else []
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] = lines[-1] + "\n"
    lines.append(_format_candidate_line(normalized, normalized_direction))
    write_lines_atomic(target_path, lines)
    return target_path


def main(theme: str | None = None) -> Path:
    if theme is None:
        parser = argparse.ArgumentParser(description="Add a theme to the research candidate list")
        parser.add_argument("theme", help="テーマ名")
        args = parser.parse_args()
        theme = args.theme

    return append_research_theme(theme)


if __name__ == "__main__":
    main()
