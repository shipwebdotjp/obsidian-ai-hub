from __future__ import annotations

import logging

from obsidian_ai_hub.notifications.models import NotificationEvent
from obsidian_ai_hub.utils import config, line_messaging

logger = logging.getLogger(__name__)


def send_line_push_result(event: NotificationEvent) -> str:
    """Send LINE push notification and return line_status string.

    Possible return values: 'sent', 'failed', 'not_configured'.
    Never raises exceptions, and logs warnings without sensitive info.
    """
    token = config.LINE_MESSAGING_TOKEN
    target = config.LINE_TARGET_ID
    base_url = config.OBSIDIAN_AI_HUB_WEB_URL

    if not token or not target or not base_url:
        logger.warning(
            "LINE notification skipped: LINE token, target, or Web URL is not configured"
        )
        return "not_configured"

    try:
        text = event.format_line_text(base_url)
        ok = line_messaging.send_line_push(token, target, text)
        if not ok:
            logger.warning("LINE notification push failed: non-2xx response")
            return "failed"
        return "sent"
    except Exception as exc:
        logger.warning("LINE notification push failed: %s", type(exc).__name__)
        return "failed"


def send_line_push_best_effort(event: NotificationEvent) -> bool:
    """Best-effort LINE push notification (backwards-compatible wrapper)."""
    return send_line_push_result(event) == "sent"
