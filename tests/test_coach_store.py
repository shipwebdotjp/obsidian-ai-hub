from datetime import datetime, timezone
import pytest
import sqlite3

from obsidian_ai_hub.coach.store import CoachStore
from obsidian_ai_hub.database import get_db_connection, run_migration_v70


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")

    # Run migration v70
    run_migration_v70(conn)
    yield conn
    conn.close()


def test_coach_store_goal_crud(db_conn):
    store = CoachStore()
    now = datetime.now(timezone.utc).isoformat()

    goal = store.create_goal(
        db_conn,
        goal_id="cgoal_test1",
        statement="テスト目標",
        reason="テスト理由",
        status="active",
        created_at=now,
        updated_at=now,
    )
    assert goal["goal_id"] == "cgoal_test1"

    fetched = store.get_goal(db_conn, "cgoal_test1")
    assert fetched["statement"] == "テスト目標"

    goals = store.list_goals(db_conn)
    assert len(goals) == 1

    store.update_goal(db_conn, "cgoal_test1", statement="更新目標", status="paused")
    fetched_updated = store.get_goal(db_conn, "cgoal_test1")
    assert fetched_updated["statement"] == "更新目標"
    assert fetched_updated["status"] == "paused"


def test_coach_store_focus_active_unique_constraint(db_conn):
    store = CoachStore()
    now = datetime.now(timezone.utc).isoformat()

    store.create_goal(
        db_conn,
        goal_id="cgoal_test2",
        statement="テスト目標2",
        reason="理由2",
        status="active",
        created_at=now,
        updated_at=now,
    )

    store.create_focus(
        db_conn,
        focus_id="cfoc_1",
        goal_id="cgoal_test2",
        name="Focus 1",
        status="active",
        created_at=now,
        updated_at=now,
    )

    # Attempting to add a second active focus under the same goal must raise IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        store.create_focus(
            db_conn,
            focus_id="cfoc_2",
            goal_id="cgoal_test2",
            name="Focus 2",
            status="active",
            created_at=now,
            updated_at=now,
        )


def test_coach_store_reflection_duplicate_constraint(db_conn):
    store = CoachStore()
    now = datetime.now(timezone.utc).isoformat()

    store.create_goal(
        db_conn,
        goal_id="cgoal_test3",
        statement="目標3",
        reason="理由3",
        status="active",
        created_at=now,
        updated_at=now,
    )
    store.create_focus(
        db_conn,
        focus_id="cfoc_3",
        goal_id="cgoal_test3",
        name="Focus 3",
        status="active",
        created_at=now,
        updated_at=now,
    )

    store.create_reflection(
        db_conn,
        reflection_id="crefl_1",
        focus_id="cfoc_3",
        iso_week_monday="2026-09-21",
        worked_well="できた",
        difficult_reason="難しかった",
        learnings="学び",
        next_week_scope="次週",
        decision_type="continue",
        target_focus_id=None,
        created_at=now,
        updated_at=now,
    )

    # Attempting to create duplicate reflection for same focus and week raises IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        store.create_reflection(
            db_conn,
            reflection_id="crefl_2",
            focus_id="cfoc_3",
            iso_week_monday="2026-09-21",
            worked_well="重複",
            difficult_reason=None,
            learnings=None,
            next_week_scope=None,
            decision_type="continue",
            target_focus_id=None,
            created_at=now,
            updated_at=now,
        )


def test_coach_store_thread_events(db_conn):
    store = CoachStore()
    now = datetime.now(timezone.utc).isoformat()

    store.create_goal(
        db_conn,
        goal_id="cgoal_test4",
        statement="目標4",
        reason="理由4",
        status="active",
        created_at=now,
        updated_at=now,
    )

    store.create_thread_event(
        db_conn,
        event_id="cevt_1",
        goal_id="cgoal_test4",
        focus_id=None,
        reflection_id=None,
        event_type="goal_created",
        payload_json='{"goal_statement": "目標4"}',
        created_at=now,
    )

    events, total = store.list_thread_events_by_goal(db_conn, "cgoal_test4")
    assert total == 1
    assert len(events) == 1
    assert events[0]["payload"]["goal_statement"] == "目標4"
