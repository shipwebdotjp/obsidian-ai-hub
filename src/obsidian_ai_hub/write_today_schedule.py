"""
Fetch today's events from Apple Calendar and Reminders, then write them into
the daily note under 「今日の予定」 and 「今日のタスク」 sections.

Configuration (put into your .env):
- APPLE_CALENDAR_NAME: title of the calendar in Calendar.app to query (optional;
  all calendars are queried if unset)
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, date, time, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo
import threading
from EventKit import (
    EKEntityTypeEvent,
    EKEventStore,
    EKAuthorizationStatusAuthorized,
    EKAuthorizationStatusNotDetermined,
)
from Foundation import NSRunLoop, NSDate

from obsidian_ai_hub.planner import recurring
from obsidian_ai_hub.utils import config, reader

logger = logging.getLogger(__name__)

CAT_TASK = 1
CAT_EVENT = 2
WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"]


def _fetch_apple_reminders(
    start_date: date, end_date: date
) -> List[Dict[str, Any]]:
    MONTH_NAMES = [
        None,
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]

    syear = start_date.year
    smonth = MONTH_NAMES[start_date.month]
    sday = start_date.day

    eyear = end_date.year
    emonth = MONTH_NAMES[end_date.month]
    eday = end_date.day

    script = f"""
    tell application "Reminders"
        set startDate to current date
        set year of startDate to {syear}
        set month of startDate to {smonth}
        set day of startDate to {sday}
        set hours of startDate to 0
        set minutes of startDate to 0
        set seconds of startDate to 0

        set endDate to current date
        set year of endDate to {eyear}
        set month of endDate to {emonth}
        set day of endDate to {eday}
        set hours of endDate to 23
        set minutes of endDate to 59
        set seconds of endDate to 59

        set targetReminders to reminders of list "やること" ¬
            whose completed is false ¬
            and due date ≥ startDate ¬
            and due date ≤ endDate

        set output to ""
        repeat with r in targetReminders
            set output to output & name of r & "||" & (due date of r as string) & linefeed
        end repeat
        return output
    end tell
    """

    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)

    events = []
    for line in result.stdout.splitlines():
        if "||" in line:
            name, due = line.split("||", 1)
            events.append({"name": name, "due": due})

    return events


def _ensure_calendar_access(store: EKEventStore) -> None:
    status = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeEvent)

    if status == EKAuthorizationStatusAuthorized:
        return

    if status != EKAuthorizationStatusNotDetermined:
        raise PermissionError(
            "Calendar access is denied/restricted. Enable it in System Settings."
        )

    done = threading.Event()
    granted_box = {"granted": False, "error": None}

    def handler(granted, error):
        granted_box["granted"] = bool(granted)
        granted_box["error"] = error
        done.set()

    store.requestAccessToEntityType_completion_(EKEntityTypeEvent, handler)

    while not done.wait(0.05):
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.05)
        )

    if not granted_box["granted"]:
        raise PermissionError("Calendar access not granted")


def _dt_to_nsdate(dt: datetime) -> NSDate:
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def fetch_calendar_events(
    calendar_name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    tz_name: str = "Asia/Tokyo",
):
    config.ensure_external_allowed("Apple Calendar (EventKit)")
    if start_date is None:
        start_date = date.today()
    if end_date is None:
        end_date = start_date

    tz = ZoneInfo(tz_name)

    start_dt = datetime.combine(start_date, time.min).replace(tzinfo=tz)
    end_dt = datetime.combine(end_date, time.max).replace(tzinfo=tz)

    store = EKEventStore()
    _ensure_calendar_access(store)

    calendars = list(store.calendarsForEntityType_(EKEntityTypeEvent))

    if calendar_name:
        target = [c for c in calendars if str(c.title()) == calendar_name]
        if not target:
            raise ValueError(f"Calendar not found: {calendar_name}")
        calendars = target

    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        _dt_to_nsdate(start_dt),
        _dt_to_nsdate(end_dt),
        calendars,
    )
    events = list(store.eventsMatchingPredicate_(predicate))
    events.sort(key=lambda e: float(e.startDate().timeIntervalSince1970()))

    out = []
    for e in events:
        title = str(e.title() or "")

        is_all_day = False
        if hasattr(e, "isAllDay"):
            is_all_day = bool(e.isAllDay())
        elif hasattr(e, "allDay"):
            is_all_day = bool(e.allDay())

        if is_all_day:
            out.append({"title": title})
            continue

        s = datetime.fromtimestamp(
            float(e.startDate().timeIntervalSince1970()), tz=tz
        ).isoformat()
        en = datetime.fromtimestamp(
            float(e.endDate().timeIntervalSince1970()), tz=tz
        ).isoformat()
        out.append({"title": title, "start": s, "end": en})

    return out


def _format_events_to_lines(events: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for ev in events:
        title = ev.get("title") or ""
        s = ev.get("start")
        e = ev.get("end")
        if s and isinstance(s, str):
            try:
                start_str = datetime.fromisoformat(s).strftime("%H:%M")
            except ValueError:
                start_str = s
            if e and isinstance(e, str):
                try:
                    end_str = datetime.fromisoformat(e).strftime("%H:%M")
                except ValueError:
                    end_str = e
                lines.append(f"{title} {start_str}~{end_str}")
            else:
                lines.append(f"{title} {start_str}")
        else:
            lines.append(title)
    return lines


def _format_recurring_item(item: Dict[str, Any]) -> str:
    """Format a recurring item (from expand_recurring) for daily note."""
    title = item.get("title") or ""
    if item.get("all_day"):
        return title
    s = item.get("start_time")
    e = item.get("end_time")
    if s and isinstance(s, str):
        try:
            start_str = datetime.fromisoformat(s).strftime("%H:%M")
        except ValueError:
            return title
        if e and isinstance(e, str):
            try:
                end_str = datetime.fromisoformat(e).strftime("%H:%M")
            except ValueError:
                return f"{title} {start_str}"
            return f"{title} {start_str}~{end_str}"
        return f"{title} {start_str}"
    return title


def get_weekday_rule_dates(
    target_date: date, weekdays: List[int], nth: List[int]
) -> List[date]:
    """Return dates within the month of target_date that match weekday numbers
    and nth occurrences.

    weekdays: weekday numbers (0=Sunday..6=Saturday)
    nth: list of occurrences (1-based)
    """
    year = target_date.year
    month = target_date.month
    results: List[date] = []

    for weekday in weekdays:
        days_in_month: List[date] = []
        for d in range(1, 32):
            try:
                dt = date(year, month, d)
            except ValueError:
                break
            if dt.weekday() == (weekday - 1 if weekday != 0 else 6):
                days_in_month.append(dt)

        for idx, dd in enumerate(days_in_month, start=1):
            if idx in nth:
                results.append(dd)

    return results


def get_monthday_rule_dates(target_day: date, dates: List[int]) -> List[date]:
    """Return concrete date objects in the same year/month as target_day for the
    provided day numbers. Invalid dates (e.g. Feb 30) are skipped.
    """
    results: List[date] = []
    year = target_day.year
    month = target_day.month
    for d in dates:
        if d == 0:
            if month == 12:
                next_month_first = date(year + 1, 1, 1)
            else:
                next_month_first = date(year, month + 1, 1)
            last_day = next_month_first - timedelta(days=1)
            results.append(last_day)
            continue
        try:
            results.append(date(year, month, d))
        except ValueError:
            pass
    return results


def is_date_in_list(target: date, days: List[date]) -> bool:
    return any(
        d.year == target.year and d.month == target.month and d.day == target.day
        for d in days
    )


def main() -> int:
    cal_name = config.APPLE_CALENDAR_NAME or None

    now = datetime.now()
    today_date = date(now.year, now.month, now.day)

    events: List[str] = []
    tasks: List[str] = []

    calendar_events = fetch_calendar_events(cal_name)
    if calendar_events:
        events.extend(_format_events_to_lines(calendar_events))

    # Recurring config events (unified via planner.recurring, now with time support)
    try:
        recurring_items = recurring.expand_recurring(today_date, today_date)
    except Exception:
        logger.exception("Failed to expand recurring events for today")
        recurring_items = []
    for item in recurring_items:
        formatted = _format_recurring_item(item)
        if item.get("kind") == "event":
            events.append(formatted)
        else:
            tasks.append(formatted)

    reminder_events = _fetch_apple_reminders(today_date, today_date)
    if reminder_events:
        for ev in reminder_events:
            name = ev.get("name", "")
            tasks.append(f"{name}")

    if events or tasks:
        obs_parts = []
        if events:
            obs_parts.append("## 📅 今日の予定")
            obs_parts.append("\n".join(f"- {e}" for e in events))
        if tasks:
            obs_parts.append("## ✅ 今日のタスク")
            obs_parts.append("\n".join(f"- [ ] {t}" for t in tasks))
        obs_text = "\n".join(obs_parts)
        today = datetime.now()

        today_note = reader.get_daily_note_content(today)
        new_today_note = today_note.replace("## ✅今日のタスク", f"{obs_text}")
        with open(reader.get_daily_note_path(today), "w") as f:
            f.write(new_today_note)
        return 0

    logger.info("No events or tasks to write today.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
