import requests
import logging

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

def send_line_push(token: str, to: str, message_text: str) -> bool:
    config.ensure_external_allowed("LINE Messaging API")

    payload = {
        "to": to,
        "messages": [{"type": "text", "text": message_text}]
    }
    headers = {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': f'Bearer {token}'
    }

    try:
        resp = requests.post('https://api.line.me/v2/bot/message/push', json=payload, headers=headers, timeout=10)
        if resp.status_code >= 200 and resp.status_code < 300:
            return True
        logger.error('LINE API responded with %s', resp.status_code)
        return False
    except Exception as exc:
        logger.error('Failed to send LINE message: %s', type(exc).__name__)
        return False