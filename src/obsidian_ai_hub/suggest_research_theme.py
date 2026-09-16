from __future__ import annotations

from typing import Any, Optional
from obsidian_ai_hub.research.intake import (
    SUGGEST_RESEARCH_THEME_PROMPT,
    submit_research_suggestion_task,
)


def main(host: Optional[str] = None, port: Optional[int] = None) -> dict[str, Any]:
    receipt = submit_research_suggestion_task(host=host, port=port)
    print(f"task_id: {receipt['task_id']}")
    print(f"status: {receipt['status']}")
    print(f"detail_url: {receipt['detail_url']}")
    return receipt


__all__ = ["SUGGEST_RESEARCH_THEME_PROMPT", "main"]
