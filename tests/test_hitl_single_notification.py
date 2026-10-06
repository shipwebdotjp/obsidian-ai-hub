"""HITL registration emits exactly one inbox notification per run.

Regression for duplicated system-maintenance inbox rows: registering a run
used to publish once from hitl.service._notify_hitl_if_needed and a second
time from an explicit notify_hitl_run call, producing two notification_inbox
rows with the same target_id.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from obsidian_ai_hub.database import get_db_connection


def _inbox_count_for_run(run_id: str) -> int:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM notification_inbox WHERE target_id = ?;",
            (run_id,),
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def test_system_maintenance_registers_single_notification():
    from obsidian_ai_hub.system_maintenance.proposals import (
        register_maintenance_hitl_run,
    )

    fingerprint = "fp_single_notif_test"
    proposals = [
        {
            "fingerprint": fingerprint,
            "cause": "cause",
            "countermeasure": "measure",
            "severity": "high",
            "coding_instruction": "fix",
        }
    ]
    findings = {
        fingerprint: {
            "label": "label",
            "occurrence_count": 1,
            "first_seen_at": "2026-10-01T00:00:00+00:00",
            "last_seen_at": "2026-10-06T00:00:00+00:00",
            "run_ids": [],
            "call_ids": [],
        }
    }
    run_id = register_maintenance_hitl_run(proposals, findings)
    assert run_id is not None
    assert _inbox_count_for_run(run_id) == 1


def test_calendar_registers_single_notification():
    from obsidian_ai_hub.calendar.hitl import register_calendar_event_approval

    run_id = register_calendar_event_approval(
        "__opcheck_single_notif__",
        {"title": "__opcheck_single_notif__", "start_time": "2026-10-07T10:00:00+09:00"},
    )
    assert run_id is not None
    assert _inbox_count_for_run(run_id) == 1


def test_reminder_registers_single_notification():
    from obsidian_ai_hub.reminders.hitl import register_reminder_approval

    run_id = register_reminder_approval(
        "__opcheck_single_notif__",
        {"title": "__opcheck_single_notif__", "due_date": "2026-10-07"},
    )
    assert run_id is not None
    assert _inbox_count_for_run(run_id) == 1


def test_memory_maintenance_registers_single_notification():
    from obsidian_ai_hub.memory.maintenance import register_maintenance_hitl_run

    base_date = datetime.now(timezone(timedelta(hours=9)))
    proposals = [
        {
            "main_id": "m1",
            "absorbed_ids": [],
            "action": "keep",
            "reason": "reason",
        }
    ]
    memories_map = {"m1": {"memory_id": "m1", "updated_at": "2026-10-01"}}
    run_id = register_maintenance_hitl_run(base_date, proposals, memories_map)
    assert run_id is not None
    assert _inbox_count_for_run(run_id) == 1
