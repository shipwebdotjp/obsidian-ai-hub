from __future__ import annotations

import requests
import logging

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


def _post_line_push(token: str, to: str, messages: list[dict]) -> bool:
    """Shared internal: POST a messages array to the LINE Push API. Returns True on 2xx."""
    config.ensure_external_allowed("LINE Messaging API")
    payload = {"to": to, "messages": messages}
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/push",
            json=payload,
            headers=headers,
            timeout=10,
        )
        if 200 <= resp.status_code < 300:
            return True
        logger.error("LINE API responded with %s", resp.status_code)
        return False
    except requests.RequestException as exc:
        logger.error("Failed to send LINE message: %s", type(exc).__name__)
        return False


def send_line_push(token: str, to: str, message_text: str) -> bool:
    """Send a single text message via LINE Push API."""
    return _post_line_push(token, to, [{"type": "text", "text": message_text}])


def send_line_push_messages(token: str, to: str, message_texts: list[str]) -> bool:
    """Send 1-5 text messages in a single LINE Push API call."""
    if not 1 <= len(message_texts) <= 5:
        raise ValueError(f"message_texts must have 1-5 items, got {len(message_texts)}")
    messages = [{"type": "text", "text": t} for t in message_texts]
    return _post_line_push(token, to, messages)
