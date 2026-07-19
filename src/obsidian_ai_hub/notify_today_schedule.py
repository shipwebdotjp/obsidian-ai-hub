"""
Notify today's schedule via LINE Messaging API.

Yesterday's day summary is read from SQLite (summaries / summary_items).
Today's schedule info is read from the today daily note subheaders:
- ## ☀️ 今日の天気
- ## 🚩今日の目標
- ## 📅 今日の予定
- ## ✅ 今日のタスク

On Mondays, the previous week's week summary is appended as a second text message.

Configuration (put into your .env):
- LINE_MESSAGING_TOKEN: LINE Messaging API channel access token
- LINE_TARGET_ID: recipient user or group id to push messages to

Intended to be called from batch/morning_routine.sh or similar.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from obsidian_ai_hub.line_notification import build_message_texts
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.utils.line_messaging import send_line_push_messages

logger = logging.getLogger(__name__)


def main() -> int:
    line_token = (
        config.LINE_MESSAGING_TOKEN
        or os.getenv("LINE_MESSAGING_TOKEN")
        or os.getenv("LINE_TOKEN")
        or ""
    )
    line_target = (
        config.LINE_TARGET_ID
        or os.getenv("LINE_TARGET_ID")
        or os.getenv("LINE_TARGET")
        or ""
    )
    today = datetime.now()

    message_texts = build_message_texts(today)

    if not message_texts:
        logger.info("No messages to send today.")
        return 0

    if not line_token or not line_target:
        logger.error(
            "LINE token or target not configured. Set LINE_MESSAGING_TOKEN and LINE_TARGET_ID in .env"
        )
        return 1

    ok = send_line_push_messages(line_token, line_target, message_texts)
    if not ok:
        logger.error("Failed to send LINE message")
        return 1

    logger.info("Sent %d LINE message(s)", len(message_texts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
