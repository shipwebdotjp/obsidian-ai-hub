from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from obsidian_ai_hub.notifications import NotificationEvent, publish_notification
from obsidian_ai_hub.notifications.models import sanitize_notification_body


def build_suggestion_link(web_url: str, run_id: str) -> str:
    """Build the deep link to the existing Web HITL form for a run_id."""
    base = (web_url or "").rstrip("/")
    return f"{base}/hitl?run_id={quote(run_id, safe='')}"


def build_research_suggestion_text(theme: str, run_id: str, web_url: str) -> str:
    """Build the legacy short LINE text for a research suggestion."""
    lines = ["🔍 調査テーマの提案です", f"「{theme}」", "詳細はリンクから確認・回答してください。"]
    link = build_suggestion_link(web_url, run_id)
    if web_url and link:
        lines.append(link)
    return "\n".join(lines)


def notify_research_suggestion(
    *,
    theme: str,
    run_id: str,
    line_token: Optional[str] = None,
    line_target: Optional[str] = None,
    web_url: Optional[str] = None,
) -> bool:
    """Publish a research proposal through the common audited notification path.

    The optional legacy LINE arguments remain accepted for source compatibility;
    delivery configuration is intentionally owned by notification settings and
    the configured channel adapters.
    """
    del line_token, line_target, web_url
    return publish_notification(
        NotificationEvent(
            event_type="research_suggestion",
            target_id=run_id,
            relative_link=f"/hitl?run_id={quote(run_id, safe='')}",
            category="action_required",
            title="【要対応】調査テーマの提案があります",
            body=sanitize_notification_body(theme),
        )
    )
