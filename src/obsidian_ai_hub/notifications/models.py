from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


NotificationCategory = Literal["action_required", "failure"]


@dataclass(frozen=True)
class NotificationEvent:
    event_type: str
    target_id: str
    relative_link: str
    category: NotificationCategory
    title: str
    body: str

    def format_line_text(self, base_url: str) -> str:
        """Format LINE push message.
        Order: title, subject body (if present), deep link.
        """
        clean_base = base_url.rstrip("/")
        link = f"{clean_base}{self.relative_link}" if self.relative_link.startswith("/") else f"{clean_base}/{self.relative_link}"

        lines = [self.title]
        if self.body.strip():
            lines.append(f"対象: {self.body.strip()}")
        lines.append(link)
        return "\n".join(lines)


def sanitize_notification_body(raw_text: str | None, max_length: int = 80) -> str:
    """Sanitize and truncate body text for notification payloads.

    Removes newlines, strips whitespace, and truncates to max_length.
    Never includes prompts, stack traces, or detailed HITL questions.
    """
    if not raw_text:
        return ""
    # Strip newlines and excess whitespace
    clean = " ".join(raw_text.split())
    if len(clean) > max_length:
        return clean[: max_length - 1] + "…"
    return clean
