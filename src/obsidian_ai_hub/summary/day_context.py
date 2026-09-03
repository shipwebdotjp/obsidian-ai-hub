"""Context collectors for daily summary generation."""

from __future__ import annotations

from datetime import datetime

from obsidian_ai_hub.agents.store import (
    list_daily_session_overviews as list_agent_session_overviews,
)
from obsidian_ai_hub.coding.store import (
    list_daily_session_overviews as list_coding_session_overviews,
)


def load_daily_session_overviews(target_date: datetime) -> tuple[list[dict], list[dict]]:
    """Load metadata-only AI agent and coding session summaries for a calendar day."""
    day = target_date.date()
    return list_agent_session_overviews(day), list_coding_session_overviews(day)
