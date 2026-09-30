"""LINE notification for AI planner proposal generation.

Best-effort: never raises, never blocks the generation task. Missing LINE
configuration or a Push API failure only logs a warning without secrets or the
message body (see line_notification.push.push_best_effort).
"""

from __future__ import annotations

from typing import Optional

from obsidian_ai_hub.line_notification.push import push_best_effort

MAX_NOTIFIED_PROPOSALS = 10


def build_planner_link(web_url: str) -> str:
    base = (web_url or "").rstrip("/")
    return f"{base}/planner"


def build_planner_summary_text(proposals: list[dict], web_url: str) -> str:
    if not proposals:
        return "✨ AIプランナー: 今日は新しい提案はありませんでした。"
    lines = ["✨ AIプランナーが新しい提案を作成しました"]
    for p in proposals[:MAX_NOTIFIED_PROPOSALS]:
        kind = "予定" if p.get("kind") == "calendar" else "リマインダー"
        anchor = p.get("start_time") or p.get("due_date") or "日付未定"
        date_part = anchor[:10] if anchor else "日付未定"
        lines.append(f"・[{kind}] {p.get('title', '')} ({date_part})")
    lines.append("プランナー画面で確認・編集・昇格してください。")
    link = build_planner_link(web_url)
    if web_url and link:
        lines.append(link)
    return "\n".join(lines)


def notify_planner_summary(
    proposals: list[dict],
    *,
    line_token: Optional[str] = None,
    line_target: Optional[str] = None,
    web_url: Optional[str] = None,
) -> bool:
    """Best-effort push of the daily planner proposal summary via Notification Publisher."""
    if not proposals:
        return False

    from obsidian_ai_hub.notifications import NotificationEvent, publish_notification

    count = len(proposals)
    event = NotificationEvent(
        event_type="planner",
        target_id=f"planner_batch_{proposals[0].get('proposal_id', 'batch')}",
        relative_link="/planner",
        category="action_required",
        title="【要対応】新しいプランナー提案があります",
        body=f"新しい提案が {count} 件あります",
    )
    return publish_notification(event)