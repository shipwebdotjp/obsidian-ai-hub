from __future__ import annotations

from typing import Optional
from urllib.parse import quote

from obsidian_ai_hub.line_notification.push import push_best_effort


def build_suggestion_link(web_url: str, run_id: str) -> str:
    """Build the deep link to the existing Web HITL form for a run_id.

    Only the run_id is placed in the query string; the Bearer token or any other
    secret is never included. The run_id is percent-encoded so special
    characters in run IDs do not break the URL.
    """
    base = (web_url or "").rstrip("/")
    return f"{base}/hitl?run_id={quote(run_id, safe='')}"


def build_research_suggestion_text(theme: str, run_id: str, web_url: str) -> str:
    """Build the short LINE notification text for a research suggestion.

    The text is intentionally short: a theme line and a deep link to the
    existing Web HITL form. Selection, comments, and cancellation are completed
    on the Web UI with the same Bearer-authenticated HITL answer flow.
    """
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
    """Best-effort push of a research suggestion notification to LINE.

    This is notification-only and must never fail the caller. If any required
    configuration (LINE token / target / Web URL) is missing or the Push API
    call fails, a warning is logged without secrets or the notification body,
    and False is returned. Outbox, retry, and sent-state persistence are not
    implemented: on recovery a notification may be missed, and on re-run it may
    be duplicated.
    """

    def _build(base_url: str) -> str:
        return build_research_suggestion_text(theme, run_id, base_url)

    return push_best_effort(
        _build,
        label="research-suggestion",
        line_token=line_token,
        line_target=line_target,
        web_url=web_url,
    )
