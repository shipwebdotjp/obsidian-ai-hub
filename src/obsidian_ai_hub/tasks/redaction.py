"""Redact known configured secret values from Task text before persistence.

Only exact matches of secrets the hub already loads from configuration are
redacted. Unknown secrets in free text are the operator's responsibility
(see ``docs/task-agent/specification.md`` §7).
"""

from __future__ import annotations

import os

from obsidian_ai_hub.utils import config

REDACTED = "[REDACTED]"


def configured_secret_values() -> tuple[str, ...]:
    """Return configured secret values, longest first, deduplicated."""
    candidates = [
        config.OPENAI_API_KEY,
        config.GEMINI_API_KEY,
        config.TAVILY_API_KEY,
        config.OPENCODE_API_KEY,
        config.LINE_MESSAGING_TOKEN,
        config.OPEN_WEB_UI_API_KEY,
        os.getenv("OBSIDIAN_AI_HUB_API_TOKEN", ""),
        os.getenv("HUGGINGFACE_API_KEY", ""),
        os.getenv("LINE_CHANNEL_SECRET", ""),
    ]
    seen: set[str] = set()
    values = [v for v in candidates if v and v not in seen and not seen.add(v)]
    values.sort(key=len, reverse=True)
    return tuple(values)


def redact_text(text: str) -> str:
    """Replace known configured secret values in ``text`` with ``[REDACTED]``."""
    redacted = text
    for secret in configured_secret_values():
        redacted = redacted.replace(secret, REDACTED)
    return redacted
