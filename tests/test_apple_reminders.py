import sys
from unittest.mock import MagicMock, patch

# Mock EventKit and Foundation before importing the module under test
mock_eventkit = MagicMock()
mock_foundation = MagicMock()

sys.modules['EventKit'] = mock_eventkit
sys.modules['Foundation'] = mock_foundation

# Setup constants
mock_eventkit.EKEntityTypeReminder = 1
mock_eventkit.EKAuthorizationStatusAuthorized = 3

from obsidian_ai_hub.handler.apple_reminders import add_reminder

def test_add_reminder_success():
    mock_store = MagicMock()
    mock_eventkit.EKEventStore.return_value = mock_store

    mock_eventkit.EKEventStore.authorizationStatusForEntityType_.return_value = 3 # Authorized

    mock_reminder = MagicMock()
    mock_eventkit.EKReminder.reminderWithEventStore_.return_value = mock_reminder

    mock_store.saveReminder_commit_error_.return_value = (True, None)

    with patch('obsidian_ai_hub.handler.apple_reminders.EVENTKIT_AVAILABLE', True):
        result = add_reminder.invoke({"title": "Test Reminder"})

    assert "Successfully added reminder: Test Reminder" in result
    mock_reminder.setTitle_.assert_called_with("Test Reminder")
    mock_store.saveReminder_commit_error_.assert_called()

def test_add_reminder_with_due_date():
    mock_store = MagicMock()
    mock_eventkit.EKEventStore.return_value = mock_store

    mock_eventkit.EKEventStore.authorizationStatusForEntityType_.return_value = 3 # Authorized

    mock_reminder = MagicMock()
    mock_eventkit.EKReminder.reminderWithEventStore_.return_value = mock_reminder

    mock_store.saveReminder_commit_error_.return_value = (True, None)

    # Mock Foundation components
    mock_calendar = MagicMock()
    mock_foundation.NSCalendar.currentCalendar.return_value = mock_calendar
    mock_components = MagicMock()
    mock_calendar.components_fromDate_.return_value = mock_components

    with patch('obsidian_ai_hub.handler.apple_reminders.EVENTKIT_AVAILABLE', True):
        result = add_reminder.invoke({"title": "Test Reminder", "due_date": "2023-12-31T12:00:00"})

    assert "Successfully added reminder: Test Reminder" in result
    mock_reminder.setTitle_.assert_called_with("Test Reminder")
    mock_reminder.setDueDateComponents_.assert_called_with(mock_components)
    mock_store.saveReminder_commit_error_.assert_called()

def test_add_reminder_not_available():
    with patch('obsidian_ai_hub.handler.apple_reminders.EVENTKIT_AVAILABLE', False):
        result = add_reminder.invoke({"title": "Test Reminder"})

    assert "Error: EventKit is not available on this system" in result
