"""Tests for recurring event reminders and notifications."""

from datetime import datetime, timezone, timedelta
import pytest
from obsidian_ai_hub.web.services import recurring_events as re_service
from obsidian_ai_hub.database import get_db_connection

JST = timezone(timedelta(hours=9))


def test_evaluate_and_send_reminders_before_9am():
    # 8:59 AM JST
    dt = datetime(2025, 4, 10, 8, 59, 0, tzinfo=JST)
    res = re_service.evaluate_and_send_reminders(now=dt)
    assert res == []


def test_evaluate_and_send_reminders_flow(monkeypatch):
    # Setup notification settings (suppressed)
    conn = get_db_connection()
    conn.execute("UPDATE notification_settings SET web_push_enabled = 0, line_enabled = 0 WHERE id = 1")
    conn.commit()
    conn.close()

    et = re_service.create_event_type("ドアホン充電")
    # Due on 2025-04-10
    series = re_service.create_series_with_start_record(
        type_id=et["type_id"],
        interval_value=1,
        interval_unit="day",
        property_values={},
        executed_on="2025-04-09",
    )
    assert series["next_due_date"] == "2025-04-10"

    # Evaluate at 9:05 AM JST on 2025-04-10
    dt_905 = datetime(2025, 4, 10, 9, 5, 0, tzinfo=JST)
    attempts = re_service.evaluate_and_send_reminders(now=dt_905)
    assert len(attempts) == 1
    assert attempts[0]["series_id"] == series["series_id"]
    assert attempts[0]["due_date"] == "2025-04-10"
    assert attempts[0]["status"] == "suppressed"

    # Evaluating again on the same due_date should skip (already suppressed attempt recorded)
    dt_1000 = datetime(2025, 4, 10, 10, 0, 0, tzinfo=JST)
    attempts_again = re_service.evaluate_and_send_reminders(now=dt_1000)
    assert attempts_again == []

    # Mock notifications enabled & successful publish
    conn = get_db_connection()
    conn.execute("UPDATE notification_settings SET line_enabled = 1, line_action_required = 1 WHERE id = 1")
    conn.commit()
    conn.close()

    published_events = []
    monkeypatch.setattr(
        "obsidian_ai_hub.notifications.publisher.publish_notification",
        lambda event: published_events.append(event) or True,
    )

    # Add a record to advance the due_date to 2025-04-11
    re_service.add_execution_record(series["series_id"], executed_on="2025-04-10")
    s_updated = re_service.get_series_detail(series["series_id"])
    assert s_updated["next_due_date"] == "2025-04-11"

    # Evaluate on 2025-04-11
    dt_next_day = datetime(2025, 4, 11, 9, 15, 0, tzinfo=JST)
    new_attempts = re_service.evaluate_and_send_reminders(now=dt_next_day)
    assert len(new_attempts) == 1
    assert new_attempts[0]["due_date"] == "2025-04-11"
    assert new_attempts[0]["status"] == "sent"

    assert len(published_events) == 1
    ev = published_events[0]
    assert ev.event_type == "recurring_event_reminder"
    assert "ドアホン充電" in ev.title
    assert "2025-04-11" in ev.body
    assert ev.relative_link == "/recurring-events"
