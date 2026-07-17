import sys
from datetime import date
from unittest.mock import MagicMock
import pytest
import sqlite3

mock_modules = {
    "EventKit": MagicMock(),
    "AppKit": MagicMock(),
    "objc": MagicMock(),
    "Foundation": MagicMock(),
    "ApplicationServices": MagicMock(),
    "atomacos": MagicMock(),
    "Quartz": MagicMock(),
    "Vision": MagicMock(),
    "Cocoa": MagicMock(),
}
for name, m in mock_modules.items():
    sys.modules[name] = m

from obsidian_ai_hub import memory
from obsidian_ai_hub.activity import store


def test_add_and_get_activities_by_date(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        store.add_activity(conn=conn, activity_date="2026-07-20", occurred_at="2026-07-20T10:00:00", summary="first")
        store.add_activity(conn=conn, activity_date="2026-07-20", occurred_at="2026-07-20T11:00:00", summary="second")
        store.add_activity(conn=conn, activity_date="2026-07-21", occurred_at="2026-07-21T09:00:00", summary="other")

        acts = store.get_activities_by_date("2026-07-20", conn=conn)
        assert len(acts) == 2

        latest = store.get_latest_activity_by_date("2026-07-20", conn=conn)
        assert latest is not None
        assert latest["summary"] == "second"

        none_latest = store.get_latest_activity_by_date("2026-07-19", conn=conn)
        assert none_latest is None
    finally:
        conn.close()


def test_get_recent_activities_filters_empty_summary(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        store.add_activity(conn=conn, activity_date="2026-07-22", summary="Active today")
        store.add_activity(conn=conn, activity_date="2026-07-21", summary="", occurred_at="2026-07-21T09:00:00")
        store.add_activity(conn=conn, activity_date="2026-07-21", summary=None)
        store.add_activity(conn=conn, activity_date="2026-07-21", summary="   ")

        recent = store.get_recent_activities(days=1, base_date=date(2026, 7, 22), conn=conn)
        assert len(recent) == 1
        assert recent[0]["summary"] == "Active today"
    finally:
        conn.close()


def test_unique_source_path_and_line_constraint(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        store.add_activity(conn=conn, source_path="log.jsonl", source_line=5)

        with pytest.raises(sqlite3.IntegrityError):
            store.add_activity(conn=conn, source_path="log.jsonl", source_line=5)
    finally:
        conn.close()


def test_no_conn_specified(test_memory_db_path):
    act = store.add_activity(summary="Self-contained")
    assert act["activity_id"].startswith("act_")

    acts = store.get_activities_by_date(act["activity_date"])
    assert len(acts) == 1
