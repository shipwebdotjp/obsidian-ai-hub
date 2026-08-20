"""Full-app context aggregation for AI planner proposal generation.

There is no single context aggregator in the app today, so the planner builds
its own pack from recent daily notes, day/week summaries, activity logs,
research themes + feedback, active projects, long-term memory, and the
authoritative upcoming schedule. Each block degrades gracefully to an empty
string when its source fails.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from obsidian_ai_hub.planner import apple, recurring

logger = logging.getLogger(__name__)

RECENT_DAYS = 7
ACTIVITY_DAYS = 30
MAX_NOTE_CHARS = 800
MAX_BLOCK_ITEMS = 30
SCHEDULE_CONTEXT_DAYS = 30


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = (text or "").replace("\r", " ").replace("\n", " ").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _build_daily_notes_block() -> str:
    try:
        from obsidian_ai_hub.utils import reader
    except Exception:
        logger.exception("Failed to import daily note reader")
        return ""

    lines: list[str] = []
    for offset in range(RECENT_DAYS - 1, -1, -1):
        day = date.today() - timedelta(days=offset)
        try:
            content = reader.get_daily_note_content(day)
        except Exception:
            logger.exception("Failed to load daily note for %s", day)
            content = ""
        if not content or not content.strip():
            continue
        excerpt = _truncate_text(content, MAX_NOTE_CHARS)
        lines.append(f"- {day.isoformat()} | {excerpt}")
        if len(lines) >= MAX_BLOCK_ITEMS:
            break
    if not lines:
        return ""
    return "## 直近のDaily Note\n" + "\n".join(lines)


def _build_summaries_block() -> str:
    from obsidian_ai_hub.summary import store as summary_store

    lines: list[str] = []
    today = date.today()
    for offset in range(RECENT_DAYS - 1, -1, -1):
        day = today - timedelta(days=offset)
        try:
            record = summary_store.get_summary_by_period("day", day.isoformat())
        except Exception:
            logger.exception("Failed to load day summary for %s", day)
            record = None
        if record and record.get("summary"):
            lines.append(f"- {day.isoformat()} | {_truncate_text(record['summary'], MAX_NOTE_CHARS)}")

    iso = today.isocalendar()
    week_key = f"{iso.year}-W{iso.week:02d}"
    try:
        week = summary_store.get_summary_by_period("week", week_key)
    except Exception:
        logger.exception("Failed to load week summary %s", week_key)
        week = None
    if week and week.get("summary"):
        lines.append(f"- {week_key} (週次) | {_truncate_text(week['summary'], MAX_NOTE_CHARS)}")

    if not lines:
        return ""
    return "## サマリ\n" + "\n".join(lines)


def _build_activities_block() -> str:
    from obsidian_ai_hub.activity import store as activity_store

    try:
        entries = activity_store.get_recent_activities(days=ACTIVITY_DAYS)
    except Exception:
        logger.exception("Failed to load recent activities")
        return ""
    if not entries:
        return ""

    lines: list[str] = []
    for e in entries[:MAX_BLOCK_ITEMS]:
        date_str = e.get("activity_date", "")
        summary = _truncate_text(e.get("summary", ""), MAX_NOTE_CHARS)
        category = e.get("category", "") or ""
        keywords = ", ".join(e.get("keywords", []) or [])
        line = f"- {date_str} | {summary}"
        if category:
            line += f" / category: {category}"
        if keywords:
            line += f" / keywords: {keywords[:200]}"
        lines.append(line)
    return "## アクティビティ\n" + "\n".join(lines)


def _build_research_block() -> str:
    from obsidian_ai_hub.research import db

    lines: list[str] = []
    try:
        themes = db.list_themes(status="approved")
    except Exception:
        logger.exception("Failed to load approved research themes")
        themes = []
    for t in themes[:20]:
        theme = t.get("theme") or ""
        if theme:
            lines.append(f"- approved: {_truncate_text(theme, 120)}")

    try:
        feedbacks = db.list_theme_feedback(limit=20)
    except Exception:
        logger.exception("Failed to load research theme feedback")
        feedbacks = []
    for f in feedbacks:
        theme = f.get("theme") or ""
        decision = f.get("feedback_decision") or ""
        if theme and decision in ("approved", "rejected"):
            lines.append(f"- feedback[{decision}]: {_truncate_text(theme, 120)}")

    if not lines:
        return ""
    return "## リサーチ\n" + "\n".join(lines[:MAX_BLOCK_ITEMS])


def _build_projects_block() -> str:
    from obsidian_ai_hub.summary import project_utils

    try:
        projects = project_utils.get_active_projects_for_prompt()
    except Exception:
        logger.exception("Failed to load active projects")
        return ""
    if not projects:
        return ""

    lines: list[str] = []
    for p in projects[:15]:
        name = p.get("display_name") or p.get("name") or ""
        goal = _truncate_text(p.get("goal", ""), 200)
        if name:
            lines.append(f"- {name}" + (f": {goal}" if goal else ""))
    if not lines:
        return ""
    return "## アクティブプロジェクト\n" + "\n".join(lines)


def _build_memory_block() -> str:
    from obsidian_ai_hub.memory import context as memory_context

    try:
        compiled = memory_context.compile_context("planner")
    except Exception:
        logger.exception("Failed to compile long-term memory context")
        return ""
    text = (compiled or {}).get("context", "")
    if not text or not text.strip():
        return ""
    return text.strip()


def _build_authoritative_schedule_block(
    reference_date: date | None = None,
) -> str:
    """Format upcoming Apple and configured recurring items for the LLM.

    Apple Calendar and Reminders are fetched live through the planner's
    short-lived cache. Configured recurring items are expanded from their
    read-only source of truth. Neither source is persisted as part of proposal
    generation.
    """
    start_date = reference_date or date.today()
    end_date = start_date + timedelta(days=SCHEDULE_CONTEXT_DAYS - 1)

    try:
        external = apple.get_external_data(start_date, end_date) or {}
    except Exception:
        logger.exception("Failed to load Apple schedule for planner context")
        external = {}

    try:
        recurring_items = recurring.expand_recurring(start_date, end_date)
    except Exception:
        logger.exception("Failed to expand recurring schedule for planner context")
        recurring_items = []

    apple_events = external.get("calendar_events", []) or []
    apple_reminders = external.get("reminders", []) or []
    if not apple_events and not apple_reminders and not recurring_items:
        return ""

    lines = [
        "## 今後30日間の正本スケジュール"
        f"（{start_date.isoformat()}〜{end_date.isoformat()}）"
    ]

    if apple_events:
        lines.append("### Apple Calendar")
        for event in apple_events[:MAX_BLOCK_ITEMS]:
            title = _truncate_text(str(event.get("title") or ""), 200)
            if not title:
                continue
            start = event.get("start") or "日時未設定"
            end = event.get("end") or ""
            timing = str(start) if not end else f"{start}〜{end}"
            all_day = " / 終日" if event.get("all_day") else ""
            lines.append(f"- {timing}{all_day} | {title}")

    if apple_reminders:
        lines.append("### Apple Reminders")
        for reminder in apple_reminders[:MAX_BLOCK_ITEMS]:
            title = _truncate_text(str(reminder.get("title") or ""), 200)
            if not title:
                continue
            due = reminder.get("due") or "期限未設定"
            lines.append(f"- {due} | {title}")

    if recurring_items:
        lines.append("### CONFIG 定期予定")
        for item in recurring_items[:MAX_BLOCK_ITEMS]:
            title = _truncate_text(str(item.get("title") or ""), 200)
            if not title:
                continue
            item_date = item.get("date")
            day = item_date.isoformat() if isinstance(item_date, date) else str(item_date)
            kind = "タスク" if item.get("kind") == "task" else "予定"
            lines.append(f"- {day} / {kind} | {title}")

    return "\n".join(lines)


def build_planner_context_pack() -> str:
    blocks = [
        _build_daily_notes_block(),
        _build_summaries_block(),
        _build_activities_block(),
        _build_research_block(),
        _build_projects_block(),
        _build_memory_block(),
        _build_authoritative_schedule_block(),
    ]
    return "\n\n".join(b for b in blocks if b)


def build_excluded_inbox_items() -> str:
    """List Inbox calendar/reminder items already pending human approval.

    The planner generator must not propose duplicates of items that are already
    awaiting approval through the existing Inbox -> HITL flow.
    """
    from obsidian_ai_hub.hitl import store as hitl_store

    try:
        runs, _ = hitl_store.list_runs(status="pending_user", limit=50)
    except Exception:
        logger.exception("Failed to load pending HITL runs")
        return "(none)"

    lines: list[str] = []
    for run in runs:
        handler = run.get("handler") or ""
        if handler not in ("calendar.add_approved_event", "reminders.add_approved_reminder"):
            continue
        title = run.get("title") or ""
        if title:
            lines.append(f"- [{handler}] {title}")

    if not lines:
        return "(none)"
    return "\n".join(lines)


def build_existing_proposals_block() -> str:
    """Summarize recent promoted/rejected proposals to avoid re-proposing them."""
    from obsidian_ai_hub.planner import store

    lines: list[str] = []
    for status in ("promoted", "rejected"):
        try:
            proposals = store.list_proposals(status=status, limit=15)
        except Exception:
            logger.exception("Failed to load %s proposals", status)
            continue
        for p in proposals:
            title = p.get("title") or ""
            if not title:
                continue
            anchor = p.get("start_time") or p.get("due_date") or ""
            lines.append(f"- [{status}] {title} ({p.get('kind')} {anchor})".strip())

    if not lines:
        return "(none)"
    return "\n".join(lines[:MAX_BLOCK_ITEMS])
