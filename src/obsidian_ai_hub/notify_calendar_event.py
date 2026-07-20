"""
Notify today's calendar events and configured recurring reminders via LINE Messaging API.

This script uses the `gog` CLI to fetch calendar events (prefer --json flag) and
sends a text push message to LINE Messaging API when there are messages to send.

Configuration (put into your .env):
- GOG_CALENDAR_ID: calendar id to query (e.g. primary or email)
- LINE_MESSAGING_TOKEN: LINE Messaging API channel access token
- LINE_TARGET_ID: recipient user or group id to push messages to

Intended to be called from batch/morning_routine.sh or similar.
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, date, time, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import threading
from EventKit import (
    EKEntityTypeEvent,
    EKEventStore,
    EKAuthorizationStatusAuthorized,
    EKAuthorizationStatusNotDetermined,
)
from Foundation import NSRunLoop, NSDate

from obsidian_ai_hub.utils import config, reader

logger = logging.getLogger(__name__)

try:
    import requests
except Exception:  # pragma: no cover - requests is recommended
    requests = None

try:
    from dateutil import parser as dateutil_parser
except Exception:  # pragma: no cover - optional
    dateutil_parser = None

CAT_TASK = 1
CAT_EVENT = 2
WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"]


def _get_apple_reminder_events(
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

    # Build AppleScript date objects using numeric components to avoid locale-dependent
    # parsing of date strings.
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

    # NotDetermined: 対話実行で許可ダイアログを出せる環境のみ推奨
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
    # dt は tz-aware を想定
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def get_calendar_events_eventkit(
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

        # 全日イベント判定（PyObjC環境によってメソッド名が違う場合があるため両対応）
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


def _parse_event_times(ev: Dict[str, Any]) -> Dict[str, Optional[datetime]]:
    """Return dict with 'start' and 'end' datetimes or None for all-day events."""
    # Preferred keys: start.dateTime, start.date, startLocal, start
    start = None
    end = None

    s = ev.get("start") or ev.get("startLocal") or ev.get("start")
    e = ev.get("end") or ev.get("endLocal") or ev.get("end")

    def _parse(val: Any) -> Optional[datetime]:
        if not val:
            return None
        if isinstance(val, dict):
            # google-like: {"dateTime": "...", "date": "..."}
            if "dateTime" in val:
                dt = val["dateTime"]
            elif "date" in val:
                # all-day
                return None
            else:
                # unknown dict shape
                return None
        else:
            dt = val

        if isinstance(dt, str):
            try:
                if dateutil_parser:
                    return dateutil_parser.parse(dt)
                # Python's fromisoformat supports offset-aware strings in 3.7+
                return datetime.fromisoformat(dt)
            except Exception:
                # last resort: try slicing
                try:
                    return datetime.fromisoformat(dt.replace("Z", "+00:00"))
                except Exception:
                    return None
        return None

    start = _parse(s)
    end = _parse(e)
    return {"start": start, "end": end}


def all_plan_to_msg(events: List[Dict[str, Any]]) -> List[str]:
    msgs: List[str] = []
    for ev in events:
        title = ev.get("summary") or ev.get("title") or ev.get("name") or ""
        times = _parse_event_times(ev)
        if times["start"] is None:
            # all-day event
            msgs.append(title)
            continue
        start_local = times["start"]
        end_local = times["end"]
        start_str = start_local.strftime("%H:%M") if start_local else ""
        end_str = end_local.strftime("%H:%M") if end_local else ""
        if start_str and end_str:
            msgs.append(f"{title} {start_str}~{end_str}")
        else:
            msgs.append(title)
    return msgs


def get_days(
    target_date: date, days_number: List[int], nthday: List[int]
) -> List[date]:
    """Return dates within the month of target_date that match weekday numbers and nth occurrences.

    days_number: list of weekday numbers (GAS: 0=Sunday..6=Saturday)
    nthday: list of occurrences (1-based)
    """
    year = target_date.year
    month = target_date.month
    results: List[date] = []

    # Build list of all days for each requested weekday
    for weekday in days_number:
        days_in_month: List[date] = []
        for d in range(1, 32):
            try:
                dt = date(year, month, d)
            except ValueError:
                break
            if dt.weekday() == (weekday - 1 if weekday != 0 else 6):
                # converting because google used 0=Sunday; Python weekday: 0=Mon..6=Sun
                # Adjust: if weekday==0 (Sunday in google), map to python 6; else weekday-1
                days_in_month.append(dt)

        # pick specified nth occurrences
        for idx, dd in enumerate(days_in_month, start=1):
            if idx in nthday:
                results.append(dd)

    return results


def get_dates_in_month(target_day: date, dates: List[int]) -> List[date]:
    """Return concrete date objects in the same year/month as target_day for the
    provided day numbers. Invalid dates (e.g. Feb 30) are skipped.
    """
    results: List[date] = []
    year = target_day.year
    month = target_day.month
    for d in dates:
        # special sentinel: 0 means last day of the month
        if d == 0:
            # compute first day of next month then subtract one day
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
            # skip invalid day numbers for the month
            pass
    return results


def is_today(target: date, days: List[date]) -> bool:
    return any(
        d.year == target.year and d.month == target.month and d.day == target.day
        for d in days
    )


def main() -> int:
    # Load configuration from environment
    cal_id = (
        config.GOG_CALENDAR_ID
        or os.getenv("GOG_CALENDAR_ID")
        or os.getenv("CALENDAR_ID")
        or "primary"
    )

    now = datetime.now()
    today_date = date(now.year, now.month, now.day)

    events: List[str] = []
    tasks: List[str] = []

    # Fetch today's events from Calendar.app
    calendar_events = get_calendar_events_eventkit(cal_id)
    if calendar_events:
        events.extend(all_plan_to_msg(calendar_events))

    # Regular weekly rules
    for event in config.REGULARLY_WEEKDAY_EVENTS:
        number_ofdays = event[0]
        days_string = event[1]
        day_offset = event[2]
        event_name = event[3]
        category = event[4]

        # convert Japanese weekday strings to numbers used in googlecalendar.gs (0=Sun..6=Sat)
        days_number = [WEEKDAYS.index(d) for d in days_string]
        target_day = date(now.year, now.month, now.day) - timedelta(days=day_offset)

        # getDays expects a date object and returns date objects
        target_days = get_days(target_day, days_number, number_ofdays)
        if is_today(target_day, target_days):
            if category == CAT_EVENT:
                events.append(event_name)
            else:
                tasks.append(event_name)

    # Regular monthly date rules
    for event in config.REGULARLY_DATE_EVENTS:
        number_ofdates = event[0]
        day_offset = event[1]
        event_name = event[2]
        category = event[3]

        target_day = date(now.year, now.month, now.day) - timedelta(days=day_offset)

        # Use helper to build concrete dates in the target month
        target_days = get_dates_in_month(target_day, number_ofdates)

        if is_today(target_day, target_days):
            if category == CAT_EVENT:
                events.append(event_name)
            else:
                tasks.append(event_name)

    # Reminder events from Apple Reminders
    reminder_events = _get_apple_reminder_events(today_date, today_date)
    if reminder_events:
        for ev in reminder_events:
            name = ev.get("name", "")
            tasks.append(f"{name}")

    if events or tasks:
        # for obsidian
        obs_parts = []
        if events:
            obs_parts.append("## 📅 今日の予定")
            obs_parts.append("\n".join(f"- {e}" for e in events))
        if tasks:
            obs_parts.append("## ✅ 今日のタスク")
            obs_parts.append("\n".join(f"- [ ] {t}" for t in tasks))
        obs_text = "\n".join(obs_parts)
        today = datetime.now()

        # 今日のノートに目標を追記
        today_note = reader.get_daily_note_content(today)
        new_today_note = today_note.replace("## ✅今日のタスク", f"{obs_text}")
        with open(reader.get_daily_note_path(today), "w") as f:
            f.write(new_today_note)
        return 0

    logger.info("No messages to send today.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
