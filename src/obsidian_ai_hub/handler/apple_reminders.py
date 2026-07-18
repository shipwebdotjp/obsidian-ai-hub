from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

try:
    from EventKit import (
        EKEventStore,
        EKEntityTypeReminder,
        EKReminder,
        EKAuthorizationStatusAuthorized,
        EKAuthorizationStatusNotDetermined,
    )
    from Foundation import NSRunLoop, NSDate, NSCalendar, NSCalendarUnitYear, NSCalendarUnitMonth, NSCalendarUnitDay, NSCalendarUnitHour, NSCalendarUnitMinute, NSCalendarUnitSecond
    EVENTKIT_AVAILABLE = True
except ImportError:
    EVENTKIT_AVAILABLE = False

class AddReminderInput(BaseModel):
    """Input for adding a reminder."""
    title: str = Field(description="The title of the reminder.")
    due_date: Optional[str] = Field(
        default=None,
        description="The due date of the reminder in ISO format (e.g., '2023-12-31' or '2023-12-31T23:59:59')."
    )

def _ensure_reminder_access(store: EKEventStore) -> None:
    if not EVENTKIT_AVAILABLE:
        raise ImportError("EventKit is not available on this system.")

    status = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeReminder)

    if status == EKAuthorizationStatusAuthorized:
        return

    if status != EKAuthorizationStatusNotDetermined:
        raise PermissionError("Reminders access is denied/restricted. Enable it in System Settings.")

    import threading
    done = threading.Event()
    granted_box = {"granted": False, "error": None}

    def handler(granted, error):
        granted_box["granted"] = bool(granted)
        granted_box["error"] = error
        done.set()

    store.requestAccessToEntityType_completion_(EKEntityTypeReminder, handler)

    while not done.wait(0.05):
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

    if not granted_box["granted"]:
        raise PermissionError(f"Reminders access not granted: {granted_box['error']}")

@tool(args_schema=AddReminderInput)
def add_reminder(title: str, due_date: Optional[str] = None) -> str:
    config.ensure_external_allowed("Apple Reminders")

    """
    Add a new reminder to Apple Reminders.
    """
    if not EVENTKIT_AVAILABLE:
        return "Error: EventKit is not available on this system (requires macOS)."

    try:
        store = EKEventStore()
        _ensure_reminder_access(store)

        reminder = EKReminder.reminderWithEventStore_(store)
        reminder.setTitle_(title)
        reminder.setCalendar_(store.defaultCalendarForNewReminders())

        if due_date:
            try:
                dt = datetime.fromisoformat(due_date)

                calendar = NSCalendar.currentCalendar()
                unit_flags = (
                    NSCalendarUnitYear | NSCalendarUnitMonth | NSCalendarUnitDay |
                    NSCalendarUnitHour | NSCalendarUnitMinute | NSCalendarUnitSecond
                )
                components = calendar.components_fromDate_(unit_flags, NSDate.dateWithTimeIntervalSince1970_(dt.timestamp()))
                reminder.setDueDateComponents_(components)
            except ValueError:
                return f"Error: Invalid due_date format: {due_date}. Use ISO format."

        error = None
        success, error = store.saveReminder_commit_error_(reminder, True, None)

        if success:
            return f"Successfully added reminder: {title}"
        else:
            return f"Failed to add reminder: {error}"

    except Exception as e:
        logger.exception("Failed to add reminder")
        return f"Error: {str(e)}"
