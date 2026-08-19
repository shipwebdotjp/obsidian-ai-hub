from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.planner import store


def _now_jst():
    return datetime.now(timezone(timedelta(hours=9)))


def test_create_proposal_persists_fields():
    rec = store.create_proposal(
        kind="calendar",
        title="  歯医者さん  ",
        rationale="来週の予約を忘れがちなため",
        generation_source="daily_06:00",
        start_time="2026-08-26T10:00:00",
        end_time="2026-08-26T10:30:00",
        location="駅前クリニック",
    )
    assert rec["proposal_id"].startswith("pp_")
    assert rec["kind"] == "calendar"
    assert rec["title"] == "歯医者さん"
    assert rec["status"] == "proposed"
    assert rec["rationale"] == "来週の予約を忘れがちなため"
    assert rec["generation_source"] == "daily_06:00"
    assert rec["fingerprint"] is not None

    fetched = store.get_proposal(rec["proposal_id"])
    assert fetched["start_time"] == "2026-08-26T10:00:00"
    assert fetched["location"] == "駅前クリニック"
    assert fetched["created_at"] is not None


def test_create_reminder_proposal_date_only_due():
    rec = store.create_proposal(
        kind="reminder",
        title="本を返す",
        rationale="貸出期限が近い",
        generation_source="daily_06:00",
        due_date="2026-08-20",
    )
    assert rec["due_date"] == "2026-08-20"
    assert rec["start_time"] is None


def test_create_proposal_invalid_fields_raise():
    with pytest.raises(ValueError):
        store.create_proposal(kind="bogus", title="x", rationale="r", generation_source="s")
    with pytest.raises(ValueError):
        store.create_proposal(kind="calendar", title="  ", rationale="r", generation_source="s")
    with pytest.raises(ValueError):
        store.create_proposal(kind="calendar", title="x", rationale="", generation_source="s")


def test_rationale_is_required():
    with pytest.raises(ValueError, match="rationale"):
        store.create_proposal(kind="calendar", title="x", generation_source="s")


def test_active_fingerprint_duplicate_prevention():
    kwargs = {
        "kind": "calendar",
        "title": "ミーティング",
        "rationale": "根拠",
        "generation_source": "daily_06:00",
        "start_time": "2026-08-26T09:00:00",
    }
    first = store.create_proposal(**kwargs)
    with pytest.raises(store.DuplicateActiveProposalError):
        store.create_proposal(**kwargs)

    store.transition_status(first["proposal_id"], to_status="rejected")
    second = store.create_proposal(**kwargs)
    assert second["proposal_id"] != first["proposal_id"]


def test_duplicate_proposal_race_maps_integrity_error():
    kwargs = {
        "kind": "calendar",
        "title": "レース競合",
        "rationale": "根拠",
        "generation_source": "daily_06:00",
        "start_time": "2026-08-26T11:00:00",
    }
    conn_a = get_db_connection()
    conn_b = get_db_connection()
    store.create_proposal(**kwargs, conn=conn_a)
    conn_a.commit()
    with pytest.raises(store.DuplicateActiveProposalError):
        store.create_proposal(**kwargs, conn=conn_b)


def test_promoted_fingerprint_still_blocks():
    kwargs = {
        "kind": "reminder",
        "title": "請求書送付",
        "rationale": "支払い漏れ防止",
        "generation_source": "daily_06:00",
        "due_date": "2026-08-25",
    }
    first = store.create_proposal(**kwargs)
    store.transition_status(first["proposal_id"], to_status="promoted", external_result="Successfully added")
    with pytest.raises(store.DuplicateActiveProposalError):
        store.create_proposal(**kwargs)


def test_expired_fingerprint_released():
    kwargs = {
        "kind": "reminder",
        "title": "備品発注",
        "rationale": "在庫不足",
        "generation_source": "daily_06:00",
        "due_date": "2026-08-30",
    }
    first = store.create_proposal(**kwargs)
    store.transition_status(first["proposal_id"], to_status="expired")
    second = store.create_proposal(**kwargs)
    assert second["proposal_id"] != first["proposal_id"]


def test_fingerprint_ignores_title_case_and_whitespace():
    a = store.compute_fingerprint("calendar", "  歯医者 予約 ", "2026-08-26T10:00:00")
    b = store.compute_fingerprint("calendar", "歯医者 予約", "2026-08-26T10:00:00")
    c = store.compute_fingerprint("calendar", "歯医者予約", "2026-08-26T10:00:00")
    assert a == b == c
    d = store.compute_fingerprint("calendar", "歯医者予約", "2026-08-27T10:00:00")
    assert a != d


def test_list_proposals_filters():
    store.create_proposal(kind="calendar", title="A", rationale="r", generation_source="s", start_time="2026-08-01T09:00:00")
    rec_b = store.create_proposal(kind="reminder", title="B", rationale="r", generation_source="s", due_date="2026-08-02")
    store.create_proposal(kind="calendar", title="C", rationale="r", generation_source="s", start_time="2026-08-03T09:00:00")
    store.transition_status(rec_b["proposal_id"], to_status="promoted", external_result="ok")

    all_proposals = store.list_proposals()
    assert len(all_proposals) == 3

    calendar_only = store.list_proposals(kind="calendar")
    assert len(calendar_only) == 2

    promoted_only = store.list_proposals(status="promoted")
    assert len(promoted_only) == 1
    assert promoted_only[0]["proposal_id"] == rec_b["proposal_id"]


def test_list_proposals_invalid_filters_raise():
    with pytest.raises(ValueError):
        store.list_proposals(status="bogus")
    with pytest.raises(ValueError):
        store.list_proposals(kind="bogus")
    with pytest.raises(ValueError):
        store.list_proposals(limit=-1)


def test_transition_status_success_and_guard():
    rec = store.create_proposal(kind="calendar", title="A", rationale="r", generation_source="s", start_time="2026-08-01T09:00:00")
    changed = store.transition_status(rec["proposal_id"], to_status="promoted", external_result="Successfully added event 'A'")
    assert changed is True
    fetched = store.get_proposal(rec["proposal_id"])
    assert fetched["status"] == "promoted"
    assert fetched["promoted_at"] is not None
    assert fetched["external_result"] == "Successfully added event 'A'"

    again = store.transition_status(rec["proposal_id"], to_status="rejected")
    assert again is False


def test_transition_status_rejected_sets_rejected_at():
    rec = store.create_proposal(kind="reminder", title="A", rationale="r", generation_source="s")
    assert store.transition_status(rec["proposal_id"], to_status="rejected") is True
    fetched = store.get_proposal(rec["proposal_id"])
    assert fetched["status"] == "rejected"
    assert fetched["rejected_at"] is not None


def test_transition_status_invalid_target_raises():
    rec = store.create_proposal(kind="calendar", title="A", rationale="r", generation_source="s")
    with pytest.raises(ValueError):
        store.transition_status(rec["proposal_id"], to_status="bogus")
    with pytest.raises(ValueError):
        store.transition_status(rec["proposal_id"], to_status="proposed")
    fetched = store.get_proposal(rec["proposal_id"])
    assert fetched["status"] == "proposed"


def test_update_proposal_fields_edits_and_recomputes_fingerprint():
    rec = store.create_proposal(kind="calendar", title="A", rationale="r", generation_source="s", start_time="2026-08-01T09:00:00")
    old_fp = rec["fingerprint"]
    updated = store.update_proposal_fields(
        rec["proposal_id"],
        title="A (改定)",
        start_time="2026-08-02T09:00:00",
        rationale="新しい根拠",
    )
    assert updated["title"] == "A (改定)"
    assert updated["start_time"] == "2026-08-02T09:00:00"
    assert updated["rationale"] == "新しい根拠"
    assert updated["fingerprint"] != old_fp


def test_update_proposal_fields_only_when_proposed():
    rec = store.create_proposal(kind="calendar", title="A", rationale="r", generation_source="s")
    store.transition_status(rec["proposal_id"], to_status="promoted")
    with pytest.raises(ValueError, match="proposed"):
        store.update_proposal_fields(rec["proposal_id"], title="B")


def test_update_proposal_fields_fingerprint_conflict():
    store.create_proposal(kind="calendar", title="A", rationale="r", generation_source="s", start_time="2026-08-01T09:00:00")
    b = store.create_proposal(kind="calendar", title="B", rationale="r", generation_source="s", start_time="2026-08-01T09:00:00")
    with pytest.raises(store.DuplicateActiveProposalError):
        store.update_proposal_fields(b["proposal_id"], title="A")
    fetched = store.get_proposal(b["proposal_id"])
    assert fetched["title"] == "B"


def test_update_proposal_fields_invalid_kind_raises_and_leaves_untouched():
    rec = store.create_proposal(kind="calendar", title="A", rationale="r", generation_source="s")
    with pytest.raises(ValueError):
        store.update_proposal_fields(rec["proposal_id"], kind="bogus")
    fetched = store.get_proposal(rec["proposal_id"])
    assert fetched["kind"] == "calendar"
    assert fetched["status"] == "proposed"


def test_cleanup_expired_proposals_only_marks_old_proposed():
    old_dt = _now_jst() - timedelta(days=10)
    conn = get_db_connection()
    rec_old = store.create_proposal(kind="calendar", title="Old", rationale="r", generation_source="s", conn=conn)
    rec_recent = store.create_proposal(kind="calendar", title="Recent", rationale="r", generation_source="s", conn=conn)
    conn.execute(
        "UPDATE planner_proposals SET created_at = ? WHERE proposal_id = ?",
        (old_dt.isoformat(timespec="seconds"), rec_old["proposal_id"]),
    )
    conn.commit()

    deleted = store.cleanup_expired_proposals(days=7, conn=conn, now_dt=_now_jst())
    assert deleted == 1
    old_fetched = store.get_proposal(rec_old["proposal_id"], conn=conn)
    assert old_fetched["status"] == "expired"
    assert old_fetched["expired_at"] is not None
    recent_fetched = store.get_proposal(rec_recent["proposal_id"], conn=conn)
    assert recent_fetched["status"] == "proposed"


def test_cleanup_expired_proposals_does_not_touch_promoted():
    old_dt = _now_jst() - timedelta(days=10)
    conn = get_db_connection()
    rec = store.create_proposal(kind="reminder", title="Promoted", rationale="r", generation_source="s", conn=conn)
    store.transition_status(rec["proposal_id"], to_status="promoted", external_result="ok", conn=conn)
    conn.execute(
        "UPDATE planner_proposals SET created_at = ? WHERE proposal_id = ?",
        (old_dt.isoformat(timespec="seconds"), rec["proposal_id"]),
    )
    conn.commit()
    assert store.cleanup_expired_proposals(days=7, conn=conn, now_dt=_now_jst()) == 0
    assert store.get_proposal(rec["proposal_id"], conn=conn)["status"] == "promoted"


def test_get_proposal_missing_returns_none():
    assert store.get_proposal("pp_nonexistent") is None
