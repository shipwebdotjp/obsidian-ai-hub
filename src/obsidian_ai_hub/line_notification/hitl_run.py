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
    """Best-effort push of a HITL Run notification to LINE.

    Notification-only and must never fail the caller: missing configuration or
    a Push API failure logs a warning without secrets or the notification body
    and returns False. Only the run_id goes into the deep link; no credentials
    are ever included.
    """

    def _build(base_url: str) -> str:
        return build_hitl_run_text(
            kind=kind,
            title=title,
            description=description,
            run_id=run_id,
            web_url=base_url,
            round_number=round_number,
        )

    return push_best_effort(
        _build,
        label="hitl-run",
        line_token=line_token,
        line_target=line_target,
        web_url=web_url,
    )