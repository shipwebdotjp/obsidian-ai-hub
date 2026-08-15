from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


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
    token = line_token if line_token is not None else config.LINE_MESSAGING_TOKEN
    target = line_target if line_target is not None else config.LINE_TARGET_ID
    base_url = web_url if web_url is not None else config.OBSIDIAN_AI_HUB_WEB_URL

    if not token or not target or not base_url:
        logger.warning(
            "LINE research-suggestion notification skipped: LINE token, target, "
            "or Web URL is not configured"
        )
        return False

    try:
        from obsidian_ai_hub.utils.line_messaging import send_line_push

        text = build_research_suggestion_text(theme, run_id, base_url)
        return send_line_push(token, target, text)
    except Exception as exc:
        logger.warning(
            "LINE research-suggestion notification push failed: %s",
            type(exc).__name__,
        )
        return False
