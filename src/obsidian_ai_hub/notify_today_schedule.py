"""
Notify today's schedule via LINE Messaging API.

Read these subheaders from yesterday daily note:
- ## AIによる要約

Read these subheaders from today daily note:
- ## ☀️ 今日の天気
- ## 🚩今日の目標
- ## 📅 今日の予定
- ## ✅ 今日のタスク

and notify them via LINE Messaging API.

Configuration (put into your .env):
- LINE_MESSAGING_TOKEN: LINE Messaging API channel access token
- LINE_TARGET_ID: recipient user or group id to push messages to

Intended to be called from batch/morning_routine.sh or similar.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta
from obsidian_ai_hub.utils import config, reader, extracter
from obsidian_ai_hub.utils.line_messaging import send_line_push

logger = logging.getLogger(__name__)

def main():
    line_token = config.LINE_MESSAGING_TOKEN or os.getenv('LINE_MESSAGING_TOKEN') or os.getenv('LINE_TOKEN') or ''
    line_target = config.LINE_TARGET_ID or os.getenv('LINE_TARGET_ID') or os.getenv('LINE_TARGET') or ''
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    message_text = ""

    # print(f"Yesterday: {yesterday}")
    yesterday_note = reader.get_daily_note_content(yesterday)
    # print(f"Yesterday's note: {yesterday_note[:100]}")
    # print(f"Today: {today}")
    today_note = reader.get_daily_note_content(today)
    # print(f"Today's note: {today_note[:100]}")
    yesterday_ai_summary = extracter.get_subheader_view(yesterday_note, "## AIによる要約")
    if yesterday_ai_summary:
        message_text += f"💡昨日の要約: {yesterday_ai_summary}\n"
    today_weather = extracter.get_subheader_view(today_note, "## ☀️ 今日の天気")
    if today_weather:
        message_text += f"☀️今日の天気: {today_weather}\n"
    today_target = extracter.get_subheader_view(today_note, "## 🚩今日の目標")
    if today_target:
        message_text += f"🚩今日の目標: {today_target}\n"
    today_schedule = extracter.get_subheader_view(today_note, "## 📅 今日の予定")
    if today_schedule:
        message_text += f"📅今日の予定: {today_schedule}\n"
    today_task = extracter.get_subheader_view(today_note, "## ✅ 今日のタスク")
    if today_task:
        message_text += f"✅今日のタスク: {today_task}\n"

    if message_text:
        if not line_token or not line_target:
            logger.error('LINE token or target not configured. Set LINE_MESSAGING_TOKEN and LINE_TARGET_ID in .env')
        else:
            ok = send_line_push(line_token, line_target, message_text)
            if not ok:
                logger.error('Failed to send LINE message')
                return 1
            else:
                logger.info('Sent LINE message')
        return 0
    else:
        logger.info('No messages to send today.')

if __name__ == '__main__':
    main()