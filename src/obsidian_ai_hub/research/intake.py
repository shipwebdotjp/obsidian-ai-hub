"""Research theme intake entry points."""

from __future__ import annotations

from typing import Any, Optional
from obsidian_ai_hub.tasks.intake import submit_request

SUGGEST_RESEARCH_THEME_PROMPT = (
    "直近の活動やノート等からユーザーに最適なリサーチテーマを1件選定し、"
    "必要な読取Capabilityを活用した上で、research_theme_propose でHITL候補として登録してください。"
)


def submit_research_suggestion_task(
    host: Optional[str] = None, port: Optional[int] = None
) -> dict[str, Any]:
    """Submit a task to select and propose a research theme candidate."""
    return submit_request(SUGGEST_RESEARCH_THEME_PROMPT, host=host, port=port)
