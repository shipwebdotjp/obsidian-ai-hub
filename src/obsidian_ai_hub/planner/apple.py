"""Read-only Apple Calendar / Reminders access for the planner.

Apple is treated as an external system: data is fetched live via EventKit and
never persisted to SQLite. A short in-process cache (see planner.cache) holds
the last fetch result so the Planner screen does not hammer EventKit on every
request. When EventKit is unavailable or the fetch fails, the caller still
receives the internal layers with an error indicator (graceful degradation).
"""

from __future__ import annotations

import logging
import threading
import time as time_mod
from datetime import date, datetime, time as dt_time
from typing import Any, Optional
from zoneinfo import ZoneInfo

from obsidian_ai_hub.planner import cache
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

try:
    from EventKit import (
        EKEventStore,
        EKEntityTypeEvent,
        EKEntityTypeReminder,
        EKAuthorizationStatusAuthorized,
        EKAuthorizationStatusNotDetermined,
    )
    from Foundation import NSRunLoop, NSDate

    EVENT_KIT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised on non-macOS environments
    EVENT_KIT_AVAILABLE = False

DEFAULT_TZ = "Asia/Tokyo"

ACCESS_WAIT_TIMEOUT_SECONDS = 30.0
FETCH_WAIT_TIMEOUT_SECONDS = 15.0


def _wait_for_eventkit(done: threading.Event, timeout: float) -> None:
    """Run the EventKit run loop until `done` fires or `timeout` elapses.

    EventKit completion handlers are delivered on the run loop, which is not
    serviced when the API is called from a background thread. Bounding the wait
    keeps a dropped callback from permanently blocking the caller's thread.
    """
    deadline = time_mod.monotonic() + timeout
    while not done.wait(0.05):
        if time_mod.monotonic() >= deadline:
            raise TimeoutError(f"EventKit operation timed out after {timeout:.0f}s")
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.05)
        )


def _dt_to_nsdate(dt: datetime) -> Any:
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _ensure_entity_access(store: EKEventStore, entity_type: int, label: str) -> None:
    status = EKEventStore.authorizationStatusForEntityType_(entity_type)

    if status == EKAuthorizationStatusAuthorized:
        return

    if status != EKAuthorizationStatusNotDetermined:
        raise PermissionError(f"{label} access is denied/restricted. Enable it in System Settings.")

    done = threading.Event()
    granted_box = {"granted": False, "error": None}

    def handler(granted, error):
        granted_box["granted"] = bool(granted)
        granted_box["error"] = error
        done.set()

    store.requestAccessToEntityType_completion_(entity_type, handler)

    _wait_for_eventkit(done, ACCESS_WAIT_TIMEOUT_SECONDS)

    if not granted_box["granted"]:
        raise PermissionError(f"{label} access not granted")


def _run_loop_wait(done: threading.Event, box: dict, key: str) -> Any:
    _wait_for_eventkit(done, FETCH_WAIT_TIMEOUT_SECONDS)
    return box[key]


def fetch_calendar_events(
    start_date: date,
    end_date: date,
    calendar_name: Optional[str] = None,
    tz_name: str = DEFAULT_TZ,
) -> list[dict]:
    """Fetch calendar events in [start_date, end_date] as dicts.

    All-day events are returned as {"title", "all_day": True}; timed events as
    {"title", "start", "end"} with ISO timestamps in the given timezone.
    """
    config.ensure_external_allowed("Apple Calendar (EventKit)")
    if not EVENT_KIT_AVAILABLE:
        raise ImportError("EventKit is not available on this system.")

    tz = ZoneInfo(tz_name)
    start_dt = datetime.combine(start_date, dt_time.min).replace(tzinfo=tz)
    end_dt = datetime.combine(end_date, dt_time.max).replace(tzinfo=tz)

    store = EKEventStore()
    _ensure_entity_access(store, EKEntityTypeEvent, "Calendar")

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
            out.append({"title": title, "all_day": True})
            continue

        s = datetime.fromtimestamp(
            float(e.startDate().timeIntervalSince1970()), tz=tz
        ).isoformat()
        en = datetime.fromtimestamp(
            float(e.endDate().timeIntervalSince1970()), tz=tz
        ).isoformat()
        out.append({"title": title, "start": s, "end": en, "all_day": False})

    return out


def _reminder_components_to_iso(comp: Any) -> str:
    year = int(comp.year())
    month = int(comp.month())
    day = int(comp.day())
    hour = comp.hour()
    minute = comp.minute()
    second = comp.second()
    if hour is None and minute is None and second is None:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return (
        f"{year:04d}-{month:02d}-{day:02d}"
        f"T{int(hour or 0):02d}:{int(minute or 0):02d}:{int(second or 0):02d}"
    )


def fetch_incomplete_reminders(
    start_date: date,
    end_date: date,
    tz_name: str = DEFAULT_TZ,
) -> list[dict]:
    """Fetch incomplete reminders due within [start_date, end_date] as dicts.

    Each reminder is {"title", "due"} where due is an ISO datetime or a
    date-only (YYYY-MM-DD) string when no time is set.
    """
    config.ensure_external_allowed("Apple Reminders (EventKit)")
    if not EVENT_KIT_AVAILABLE:
        raise ImportError("EventKit is not available on this system.")

    tz = ZoneInfo(tz_name)
    start_dt = datetime.combine(start_date, dt_time.min).replace(tzinfo=tz)
    end_dt = datetime.combine(end_date, dt_time.max).replace(tzinfo=tz)

    store = EKEventStore()
    _ensure_entity_access(store, EKEntityTypeReminder, "Reminders")

    calendars = list(store.calendarsForEntityType_(EKEntityTypeReminder))
    predicate = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        _dt_to_nsdate(start_dt),
        _dt_to_nsdate(end_dt),
        calendars,
    )

    done = threading.Event()
    box = {"reminders": []}

    def completion(reminders):
        box["reminders"] = list(reminders or [])
        done.set()

    store.fetchRemindersMatchingPredicate_completion_(predicate, completion)
    _run_loop_wait(done, box, "reminders")

    out = []
    for r in box["reminders"]:
        title = str(r.title() or "")
        comp = r.dueDateComponents()
        if comp is None:
            continue
        out.append({"title": title, "due": _reminder_components_to_iso(comp)})
    return out


def _fetch_external_raw(start_date: date, end_date: date) -> dict:
    """Fetch both Apple sources for a range.

    Returns {"calendar_events": [...], "reminders": [...], "error": None}.
    On any failure the Apple layers degrade to empty lists with a message.
    """
    try:
        calendar_name = config.APPLE_CALENDAR_NAME or None
        calendar_events = fetch_calendar_events(start_date, end_date, calendar_name)
        reminders = fetch_incomplete_reminders(start_date, end_date)
        return {
            "calendar_events": calendar_events,
            "reminders": reminders,
            "error": None,
        }
    except ImportError as exc:
        logger.info("Apple EventKit unavailable for planner: %s", exc)
        return {"calendar_events": [], "reminders": [], "error": str(exc)}
    except Exception as exc:
        logger.warning("Failed to fetch Apple planner data: %s", type(exc).__name__)
        return {"calendar_events": [], "reminders": [], "error": str(exc)}


def get_external_data(start_date: date, end_date: date) -> dict:
    """Return Apple data for a range, using a short-lived in-process cache.

    The cache is keyed by the display range; an explicit refresh, a successful
    promotion, or a display range change invalidates the relevant entries.
    """
    key = ("apple", start_date, end_date)

    def fetch() -> dict:
        return _fetch_external_raw(start_date, end_date)

    return cache.cached_or_fetch(key, fetch)


def invalidate_cache() -> None:
    """Drop all cached Apple reads (explicit refresh / successful promotion)."""
    cache.invalidate_all()