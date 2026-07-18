from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from obsidian_ai_hub.utils import config

try:
    from EventKit import (
        EKEventStore,
        EKEntityTypeEvent,
        EKAuthorizationStatusAuthorized,
        EKAuthorizationStatusNotDetermined,
        EKEvent,
    )
    from Foundation import NSRunLoop, NSDate
    EVENT_KIT_AVAILABLE = True
except ImportError:
    EVENT_KIT_AVAILABLE = False

logger = logging.getLogger(__name__)

class AddCalendarEventInput(BaseModel):
    """Input for adding a calendar event."""
    title: str = Field(description="The title of the event.")
    start_time: str = Field(description="The start time of the event in ISO format (e.g., '2023-10-27T10:00:00').")
    end_time: Optional[str] = Field(default=None, description="The end time of the event in ISO format. If not provided, defaults to 1 hour after start_time.")
    location: Optional[str] = Field(default=None, description="The location of the event.")
    calendar_name: Optional[str] = Field(default=None, description="The name of the calendar to add the event to. Defaults to the default calendar.")

def _ensure_calendar_access(store: EKEventStore) -> None:
    import threading
    status = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeEvent)

    if status == EKAuthorizationStatusAuthorized:
        return

    if status != EKAuthorizationStatusNotDetermined:
        raise PermissionError("Calendar access is denied/restricted. Enable it in System Settings.")

    done = threading.Event()
    granted_box = {"granted": False, "error": None}

    def handler(granted, error):
        granted_box["granted"] = bool(granted)
        granted_box["error"] = error
        done.set()

    store.requestAccessToEntityType_completion_(EKEntityTypeEvent, handler)

    while not done.wait(0.05):
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

    if not granted_box["granted"]:
        raise PermissionError("Calendar access not granted")

def _dt_to_nsdate(dt: datetime) -> NSDate:
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())

@tool(args_schema=AddCalendarEventInput)
def add_calendar_event(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    calendar_name: Optional[str] = None,
) -> str:
    """
    Add a new event to the macOS Calendar.

    Args:
        title: The title/subject of the event.
        start_time: Start time in ISO format (YYYY-MM-DDTHH:MM:SS).
        end_time: Optional end time in ISO format.
        location: Optional location string.
        calendar_name: Optional name of the calendar (e.g., 'Work', 'Home').
    """
    config.ensure_external_allowed("Apple Calendar")
    if not EVENT_KIT_AVAILABLE:
        return "Error: EventKit is not available on this system (macOS only)."

    try:
        start_dt = datetime.fromisoformat(start_time)
        if end_time:
            end_dt = datetime.fromisoformat(end_time)
        else:
            end_dt = start_dt + timedelta(hours=1)
    except ValueError as e:
        return f"Error parsing dates: {e}"

    store = EKEventStore()
    try:
        _ensure_calendar_access(store)
    except PermissionError as e:
        return str(e)

    # Find the target calendar
    calendars = list(store.calendarsForEntityType_(EKEntityTypeEvent))
    target_calendar = store.defaultCalendarForNewEvents()

    if calendar_name:
        found = False
        for cal in calendars:
            if str(cal.title()) == calendar_name:
                target_calendar = cal
                found = True
                break
        if not found:
            return f"Error: Calendar '{calendar_name}' not found."

    # Create the event
    event = EKEvent.eventWithEventStore_(store)
    event.setTitle_(title)
    event.setStartDate_(_dt_to_nsdate(start_dt))
    event.setEndDate_(_dt_to_nsdate(end_dt))
    if location:
        event.setLocation_(location)
    event.setCalendar_(target_calendar)

    # Save the event
    # saveEvent:span:error: (EKSpanThisEvent = 0)
    success, error = store.saveEvent_span_error_(event, 0, None)

    if success:
        return f"Successfully added event '{title}' to calendar '{target_calendar.title()}' from {start_dt} to {end_dt}."
    else:
        return f"Failed to save event: {error}"

def main():
    parser = argparse.ArgumentParser(description="Add a calendar event to macOS Calendar")
    parser.add_argument("title", help="Event title")
    parser.add_argument("start_time", help="Start time (ISO format)")
    parser.add_argument("--end_time", help="End time (ISO format)")
    parser.add_argument("--location", help="Event location")
    parser.add_argument("--calendar", help="Calendar name")

    args = parser.parse_args()

    result = add_calendar_event.invoke({
        "title": args.title,
        "start_time": args.start_time,
        "end_time": args.end_time,
        "location": args.location,
        "calendar_name": args.calendar
    })
    print(result)

if __name__ == "__main__":
    main()
