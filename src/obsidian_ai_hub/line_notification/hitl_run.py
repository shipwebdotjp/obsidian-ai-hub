from __future__ import annotations

from typing import Optional

from obsidian_ai_hub.line_notification.push import push_best_effort
from obsidian_ai_hub.line_notification.suggestion import build_suggestion_link


def build_hitl_run_text(
    *,
    kind: str,
    title: str,
    description: str,
    run_id: str,
    web_url: str,
    round_number: Optional[int] = None,
) -> str:
    """Build the LINE notification text for an arbitrary HITL Run.

    The text is intentionally short: a kind/title line, an optional round
    indicator for re-proposal rounds, an optional description, and a deep link
    to the existing Web HITL form. Selection, comments, and cancellation are
    completed on the Web UI with the same Bearer-authenticated HITL answer
    flow. Rounds 2 and later are labeled as re-proposals with their round
    number.
    """
    if round_number is not None and round_number >= 2:
        header = f"{kind}の再提案です（ラウンド {round_number}）"
    else:
        header = f"{kind}の確認です"

    lines = [header, title]
    if description:
        lines.append(description)
    lines.append("詳細はリンクから確認・回答してください。")
    link = build_suggestion_link(web_url, run_id)
    if web_url and link:
        lines.append(link)
    return "\n".join(lines)


def notify_hitl_run(
    *,
    kind: str,
    title: str,
    description: str,
    run_id: str,
    round_number: Optional[int] = None,
    line_token: Optional[str] = None,
    line_target: Optional[str] = None,
    web_url: Optional[str] = None,
) -> bool:
    """Best-effort push of a HITL Run notification via the new Notification Publisher."""
    from urllib.parse import quote
    from obsidian_ai_hub.notifications import (
        NotificationEvent,
        publish_notification,
        sanitize_notification_body,
    )

    if round_number is not None and round_number >= 2:
        notif_title = f"【要対応】{kind}の再提案（ラウンド {round_number}）"
    else:
        notif_title = f"【要対応】{kind}の確認が必要です"

    event = NotificationEvent(
        event_type="hitl",
        target_id=run_id,
        relative_link=f"/hitl?run_id={quote(run_id)}",
        category="action_required",
        title=notif_title,
        body=sanitize_notification_body(title or description),
    )
    return publish_notification(event)