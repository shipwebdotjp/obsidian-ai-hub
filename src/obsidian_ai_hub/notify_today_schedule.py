"""
Notify today's schedule via LINE Messaging API.

Yesterday's day summary is read from SQLite (summaries / summary_items).
Today's schedule info is read from the today daily note subheaders:
- ## ☀️ 今日の天気
- ## 🚩今日の目標
- ## 📅 今日の予定
- ## ✅ 今日のタスク

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
from obsidian_ai_hub.summary import store

logger = logging.getLogger(__name__)

# Day summary kind display order and Japanese labels for LINE notification
DAY_KIND_LABELS = [
    ("highlights", "ハイライト"),
    ("activities", "活動内容"),
    ("learnings", "学び・整理"),
    ("reflections", "反省・気づき"),
    ("gratitude", "感謝"),
]


def format_summary_for_line(summary_record: dict) -> str:
    """Format a day summary record into a LINE message block."""
    lines = []

    summary_text = (summary_record.get("summary") or "").strip()
    if summary_text:
        lines.append(f"💡昨日の要約\n{summary_text}")

    items_by_kind: dict[str, list[dict]] = {}
    for item in summary_record.get("items") or []:
        kind = item.get("kind", "")
        items_by_kind.setdefault(kind, []).append(item)

    for kind in items_by_kind:
        items_by_kind[kind].sort(key=lambda x: x.get("display_order", 0))

    known_kinds = {k for k, _ in DAY_KIND_LABELS}
    ordered_kinds = list(DAY_KIND_LABELS) + [
        (kind, kind) for kind in items_by_kind if kind not in known_kinds
    ]

    for kind, label in ordered_kinds:
        items = items_by_kind.get(kind)
        if not items:
            continue
        lines.append(f"\n【{label}】")
        for item in items:
            body = (item.get("body") or "").strip()
            if body:
                lines.append(f"・{body}")

    people = summary_record.get("people") or []
    if people:
        lines.append("\n【人物】")
        for p in people:
            name = (p.get("name") or "").strip()
            note = (p.get("note") or "").strip()
            if name:
                lines.append(f"・{name}" + (f": {note}" if note else ""))

    projects = summary_record.get("projects") or []
    if projects:
        lines.append("\n【プロジェクト】")
        for proj in projects:
            proj = (proj or "").strip()
            if proj:
                lines.append(f"・{proj}")

    return "\n".join(lines)


def main():
    line_token = config.LINE_MESSAGING_TOKEN or os.getenv('LINE_MESSAGING_TOKEN') or os.getenv('LINE_TOKEN') or ''
    line_target = config.LINE_TARGET_ID or os.getenv('LINE_TARGET_ID') or os.getenv('LINE_TARGET') or ''
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    message_text = ""

    yesterday_key = yesterday.strftime("%Y-%m-%d")
    yesterday_summary = store.get_summary_by_period("day", yesterday_key)
    if yesterday_summary:
        summary_part = format_summary_for_line(yesterday_summary)
        if summary_part:
            message_text += summary_part + "\n"

    today_note = reader.get_daily_note_content(today)
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