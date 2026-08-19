from __future__ import annotations

from unittest.mock import patch

import pytest

from obsidian_ai_hub.planner import cache, promote, store


def _calendar_proposal():
    return store.create_proposal(
        kind="calendar",
        title="歯科検診",
        rationale="根拠",
        generation_source="daily_06:00",
        start_time="2026-08-26T10:00:00",
        end_time="2026-08-26T10:30:00",
        location="駅前クリニック",
    )


def _reminder_proposal():
    return store.create_proposal(
        kind="reminder",
        title="本を返す",
        rationale="根拠",
        generation_source="daily_06:00",
        due_date="2026-08-20",
    )


def test_promote_calendar_proposal_succeeds_and_invalidates_cache():
    proposal = _calendar_proposal()
    cache.put_cached(("apple", "2026-08-19", "2026-08-26"), {"events": []})

    with patch.object(
        promote._add_calendar_event,
        "add_calendar_event",
    ) as mock_calendar:
        mock_calendar.invoke.return_value = (
            "Successfully added event '歯科検診' to calendar 'Work' from "
            "2026-08-26T10:00:00 to 2026-08-26T10:30:00."
        )
        updated = promote.promote_proposal(proposal["proposal_id"])

    assert updated["status"] == "promoted"
    assert updated["promoted_at"] is not None
    assert updated["external_result"].startswith("Successfully")
    mock_calendar.invoke.assert_called_once_with(
        {
            "title": "歯科検診",
            "start_time": "2026-08-26T10:00:00",
            "end_time": "2026-08-26T10:30:00",
            "location": "駅前クリニック",
        }
    )
    assert cache.get_cached(("apple", "2026-08-19", "2026-08-26")) is None


def test_promote_reminder_proposal_succeeds():
    proposal = _reminder_proposal()

    with patch.object(
        promote._apple_reminders,
        "add_reminder",
    ) as mock_reminder:
        mock_reminder.invoke.return_value = "Successfully added reminder: 本を返す"
        updated = promote.promote_proposal(proposal["proposal_id"])

    assert updated["status"] == "promoted"
    mock_reminder.invoke.assert_called_once_with(
        {"title": "本を返す", "due_date": "2026-08-20"}
    )


def test_promote_failure_keeps_proposal_proposed():
    proposal = _calendar_proposal()

    with patch.object(
        promote._add_calendar_event,
        "add_calendar_event",
    ) as mock_calendar:
        mock_calendar.invoke.return_value = "Error: Calendar access denied."
        with pytest.raises(RuntimeError, match="Apple promotion failed"):
            promote.promote_proposal(proposal["proposal_id"])

    assert store.get_proposal(proposal["proposal_id"])["status"] == "proposed"


def test_promote_already_promoted_raises():
    proposal = _calendar_proposal()
    store.transition_status(proposal["proposal_id"], to_status="promoted")

    with pytest.raises(ValueError, match="status"):
        promote.promote_proposal(proposal["proposal_id"])


def test_promote_missing_proposal_raises():
    with pytest.raises(LookupError, match="not found"):
        promote.promote_proposal("pp_does_not_exist")


def test_promote_exposes_eventkit_unavailability_as_runtime_error():
    proposal = _calendar_proposal()

    with patch.object(
        promote._add_calendar_event,
        "add_calendar_event",
    ) as mock_calendar:
        mock_calendar.invoke.return_value = (
            "Error: EventKit is not available on this system (macOS only)."
        )
        with pytest.raises(RuntimeError, match="Apple promotion failed"):
            promote.promote_proposal(proposal["proposal_id"])

    assert store.get_proposal(proposal["proposal_id"])["status"] == "proposed"