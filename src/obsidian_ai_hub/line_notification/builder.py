from __future__ import annotations

import logging
from datetime import datetime, timedelta

from obsidian_ai_hub.summary import store
from obsidian_ai_hub.utils import extracter, reader

logger = logging.getLogger(__name__)

DAY_KIND_LABELS: list[tuple[str, str]] = [
    ("highlights", "ハイライト"),
    ("activities", "活動内容"),
    ("learnings", "学び・整理"),
    ("reflections", "反省・気づき"),
    ("gratitude", "感謝"),
]

WEEK_KIND_LABELS: list[tuple[str, str]] = [
    ("highlights", "ハイライト"),
    ("progress", "進捗"),
    ("learnings", "学び・整理"),
    ("reflections", "反省・気づき"),
    ("patterns", "パターン"),
    ("gratitude", "感謝"),
]


def format_summary_for_line(
    summary_record: dict,
    kind_labels: list[tuple[str, str]] | None = None,
) -> str:
    """Format a summary record into a LINE message block.

    kind_labels controls the display order and Japanese labels.
    Defaults to DAY_KIND_LABELS if not specified.
    """
    if kind_labels is None:
        kind_labels = DAY_KIND_LABELS
    lines = []

    summary_text = (summary_record.get("summary") or "").strip()
    if summary_text:
        lines.append(f"💡要約\n{summary_text}")

    items_by_kind: dict[str, list[dict]] = {}
    for item in summary_record.get("items") or []:
        kind = item.get("kind", "")
        items_by_kind.setdefault(kind, []).append(item)

    for kind in items_by_kind:
        items_by_kind[kind].sort(key=lambda x: x.get("display_order", 0))

    known_kinds = {k for k, _ in kind_labels}
    ordered_kinds = list(kind_labels) + [
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


def is_monday(dt: datetime) -> bool:
    """Return True if dt falls on a Monday (ISO weekday 1)."""
    return dt.isocalendar()[2] == 1


def prev_iso_week_key(dt: datetime) -> str:
    """Return the ISO week key (e.g. '2026-W03') for the week before dt's current week.

    The previous week is defined as the ISO week containing the Sunday immediately
    before the Monday of dt's current ISO week.
    """
    _, _, iso_weekday = dt.isocalendar()
    sunday = dt - timedelta(days=iso_weekday - 1) + timedelta(days=6)
    prev_sunday = sunday - timedelta(days=7)
    yr, wk, _ = prev_sunday.isocalendar()
    return f"{yr}-W{wk:02d}"


def build_week_summary_text(dt: datetime) -> str:
    """Build the previous week's summary text. Returns empty string if no summary found."""
    week_key = prev_iso_week_key(dt)
    week_summary = store.get_summary_by_period("week", week_key)
    if not week_summary:
        return ""
    return format_summary_for_line(week_summary, kind_labels=WEEK_KIND_LABELS)


def build_daily_message_text(today: datetime) -> str:
    """Build the daily notification text (yesterday summary + today schedule).

    Returns empty string if there is nothing to notify.
    """
    yesterday = today - timedelta(days=1)
    parts: list[str] = []

    yesterday_key = yesterday.strftime("%Y-%m-%d")
    yesterday_summary = store.get_summary_by_period("day", yesterday_key)
    if yesterday_summary:
        summary_part = format_summary_for_line(yesterday_summary)
        if summary_part:
            parts.append(summary_part)

    today_note = reader.get_daily_note_content(today)
    today_weather = extracter.get_subheader_view(today_note, "## ☀️ 今日の天気")
    if today_weather:
        parts.append(f"☀️今日の天気: {today_weather}")
    today_target = extracter.get_subheader_view(today_note, "## 🚩今日の目標")
    if today_target:
        parts.append(f"🚩今日の目標: {today_target}")
    today_schedule = extracter.get_subheader_view(today_note, "## 📅 今日の予定")
    if today_schedule:
        parts.append(f"📅今日の予定: {today_schedule}")
    today_task = extracter.get_subheader_view(today_note, "## ✅ 今日のタスク")
    if today_task:
        parts.append(f"✅今日のタスク: {today_task}")

    return "\n".join(parts)


def build_message_texts(today: datetime) -> list[str]:
    """Build the list of message texts to send via LINE.

    - Always includes the daily message if non-empty.
    - On Mondays, includes the previous week summary as an additional message.
    - Returns 0-2 messages.
    """
    texts: list[str] = []

    daily = build_daily_message_text(today)
    if daily:
        texts.append(daily)

    if is_monday(today):
        weekly = build_week_summary_text(today)
        if weekly:
            texts.append(weekly)

    return texts
