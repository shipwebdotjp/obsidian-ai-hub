from __future__ import annotations

import logging
from typing import Callable, Optional

from obsidian_ai_hub.utils import config, line_messaging

logger = logging.getLogger(__name__)


def push_best_effort(
    text_builder: Callable[[str], str],
    *,
    label: str,
    line_token: Optional[str] = None,
    line_target: Optional[str] = None,
    web_url: Optional[str] = None,
) -> bool:
    """Best-effort LINE push shared by all HITL notification senders.

    The caller provides a text_builder that turns the resolved Web base URL
    into the final message text, so the common configuration resolution and
    failure handling are reused. This must never raise: missing configuration
    or a Push API failure only produces a warning without secrets or the
    notification body, and False is returned. Outbox, retry, and sent-state
    persistence are not implemented.
    """
    token = line_token if line_token is not None else config.LINE_MESSAGING_TOKEN
    target = line_target if line_target is not None else config.LINE_TARGET_ID
    base_url = web_url if web_url is not None else config.OBSIDIAN_AI_HUB_WEB_URL

    if not token or not target or not base_url:
        logger.warning(
            "LINE %s notification skipped: LINE token, target, "
            "or Web URL is not configured",
            label,
        )
        return False

    try:
        text = text_builder(base_url)
        ok = line_messaging.send_line_push(token, target, text)
        if not ok:
            logger.warning("LINE %s notification push failed: non-2xx response", label)
        return ok
    except Exception as exc:
        logger.warning(
            "LINE %s notification push failed: %s",
            label,
            type(exc).__name__,
        )
        return False