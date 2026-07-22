from pathlib import Path

import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.summary import store


@pytest.fixture(autouse=True)
def mock_people_notes(monkeypatch):
    monkeypatch.setattr(
        "obsidian_ai_hub.utils.people_loader.load_and_validate_people_notes",
        lambda: {
            "alice": {
                "id": "alice-id",
                "name": "Alice",
                "aliases": ["alice", "a-chan"],
                "file_path": Path("alice.md"),
            },
            "a-chan": {
                "id": "alice-id",
                "name": "Alice",
                "aliases": ["alice", "a-chan"],
                "file_path": Path("alice.md"),
            },
        },
    )


def _insert_test_project(conn, display_name, norm_name, domain="personal", status="active"):
    from datetime import datetime
    now_iso = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO projects (
            normalized_name, display_name, domain, status, goal, description,
            keywords, start_date, target_date, completed_date, project_path,
            reference_url, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'goal', 'desc', '[]', NULL, NULL, NULL, NULL, NULL, ?, ?)
    """, (norm_name, display_name, domain, status, now_iso, now_iso))


def test_schema_version_bump(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version;")
        assert cursor.fetchone()[0] == 11

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "summaries" in tables
        assert "summary_items" in tables
        assert "topics" in tables
        assert "projects" in tables
        assert "people" in tables
        assert "summary_topics" in tables
        assert "summary_projects" in tables
        assert "summary_people" in tables
        assert "person_candidates" in tables
        assert "summary_person_candidates" in tables
        assert "summary_person_assignments" in tables
    finally:
        conn.close()


def _make_day_record(period_key="2026-07-17"):
    return {
        "period_type": "day",
        "period_key": period_key,
        "period_start": period_key,
        "period_end": period_key,
        "generated_at": "2026-07-17T22:00:00",
        "summary": "Test daily summary",
        "keywords": ["test", "sqlite"],
        "mood": "good",
        "sleep_raw": "7h30m",
        "sleep_hours": 7.5,
        "items": [
            {"kind": "highlights", "body": "Highlight 1", "display_order": 0},
            {"kind": "activities", "body": "Activity 1", "display_order": 1},
            {"kind": "learnings", "body": "Learning 1", "display_order": 2},
            {"kind": "reflections", "body": "Reflection 1", "display_order": 3},
            {"kind": "gratitude", "body": "Gratitude 1", "display_order": 4},
        ],
        "topics": ["LLM・AI活用", "InvalidTopic"],
        "projects": ["Project A", "project a"],
        "people": [
            {"name": "Alice", "note": "met for lunch"},
            {"name": "alice", "note": "same person"},
        ],
    }


def test_upsert_and_get_day_summary(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        _insert_test_project(conn, "Project A", "project a")
        record = _make_day_record()
        store.upsert_summary(record, conn=conn)

        got = store.get_summary_by_period("day", "2026-07-17", conn=conn)
        assert got is not None
        assert got["summary"] == "Test daily summary"
        assert got["mood"] == "good"
        assert got["sleep_raw"] == "7h30m"
        assert got["sleep_hours"] == 7.5
        assert len(got["items"]) == 5
        assert [i["kind"] for i in got["items"]] == store.DAY_ITEM_KINDS
        # Invalid topic replaced with その他
        assert got["topics"] == ["LLM・AI活用", "その他"]
        # project a merged into Project A (first-seen display name)
        assert got["projects"] == ["Project A"]
        # alice merged into Alice
        assert len(got["people"]) == 1
        assert got["people"][0]["name"] == "Alice"
    finally:
        conn.close()


def test_upsert_updates_existing_record(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        _insert_test_project(conn, "Project A", "project a")
        store.upsert_summary(_make_day_record(), conn=conn)
        updated = _make_day_record()
        updated["summary"] = "Updated summary"
        updated["items"] = [
            {"kind": "highlights", "body": "Only highlight", "display_order": 0}
        ]
        updated["topics"] = ["信仰・聖書"]

        store.upsert_summary(updated, conn=conn)

        got = store.get_summary_by_period("day", "2026-07-17", conn=conn)
        assert got["summary"] == "Updated summary"
        assert len(got["items"]) == 1
        assert got["topics"] == ["信仰・聖書"]
        # Old items replaced, not appended
        assert all(i["kind"] != "activities" for i in got["items"])
    finally:
        conn.close()


def test_list_summaries_with_filters(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        _insert_test_project(conn, "Project A", "project a")
        _insert_test_project(conn, "Project B", "project b")
        store.upsert_summary(_make_day_record("2026-07-17"), conn=conn)
        week_record = {
            "period_type": "week",
            "period_key": "2026-W29",
            "period_start": "2026-07-13",
            "period_end": "2026-07-19",
            "generated_at": "2026-07-19T22:00:00",
            "summary": "Week summary",
            "keywords": ["week"],
            "items": [{"kind": "progress", "body": "Progress", "display_order": 0}],
            "topics": ["LLM・AI活用"],
            "projects": ["Project B"],
            "people": [],
        }
        store.upsert_summary(week_record, conn=conn)

        all_records = store.list_summaries(conn=conn)
        assert len(all_records) == 2

        day_records = store.list_summaries(period_type="day", conn=conn)
        assert len(day_records) == 1
        assert day_records[0]["period_key"] == "2026-07-17"

        topic_filtered = store.list_summaries(topic="LLM・AI活用", conn=conn)
        assert len(topic_filtered) == 2

        project_filtered = store.list_summaries(project="Project B", conn=conn)
        assert len(project_filtered) == 1
        assert project_filtered[0]["period_type"] == "week"
    finally:
        conn.close()


def test_get_summary_options(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        _insert_test_project(conn, "Project A", "project a")
        store.upsert_summary(_make_day_record(), conn=conn)
        options = store.get_summary_options(conn=conn)
        assert "LLM・AI活用" in options["topics"]
        assert "Project A" in options["projects"]
        assert "Alice" in options["people"]
    finally:
        conn.close()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7", 7.0),
        ("7.5", 7.5),
        ("7h", 7.0),
        ("7時間", 7.0),
        ("7時間30分", 7.5),
        ("  7.25 h  ", 7.25),
        ("unknown", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_sleep_hours(raw, expected):
    assert store.parse_sleep_hours(raw) == expected


def test_week_and_month_records_have_no_mood_sleep(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        week_record = {
            "period_type": "week",
            "period_key": "2026-W29",
            "period_start": "2026-07-13",
            "period_end": "2026-07-19",
            "generated_at": "2026-07-19T22:00:00",
            "summary": "Week summary",
            "keywords": [],
            "mood": "should be ignored",
            "sleep_raw": "should be ignored",
            "sleep_hours": 99.0,
            "items": [{"kind": "highlights", "body": "H", "display_order": 0}],
            "topics": [],
            "projects": [],
            "people": [],
        }
        store.upsert_summary(week_record, conn=conn)
        got = store.get_summary_by_period("week", "2026-W29", conn=conn)
        # We still store whatever is passed; caller (generator) is responsible for not passing week mood/sleep.
        # This test documents that the store does not enforce day-only fields.
        assert got["mood"] == "should be ignored"
    finally:
        conn.close()


def test_get_summary_by_period_missing(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        assert store.get_summary_by_period("day", "1900-01-01", conn=conn) is None
    finally:
        conn.close()


def test_invalid_period_type_raises(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        with pytest.raises(ValueError):
            store.upsert_summary(
                {"period_type": "year", "period_key": "2026"}, conn=conn
            )
    finally:
        conn.close()


def test_unresolved_resolved_filtering(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        # Create a summary with both Alice (resolved) and Yamada-kun (unresolved candidate)
        record = {
            "period_type": "day",
            "period_key": "2026-07-20",
            "period_start": "2026-07-20",
            "period_end": "2026-07-20",
            "summary": "Meeting with Alice and Yamada-kun",
            "people": [
                {"name": "Alice", "note": "discussed project status"},
                {"name": "山田君", "note": "guest observer"},
            ],
        }
        store.upsert_summary(record, conn=conn)

        # Retrieve and verify list and resolution status
        got = store.get_summary_by_period("day", "2026-07-20", conn=conn)
        assert got is not None
        assert len(got["people"]) == 2

        alice_p = [p for p in got["people"] if p["name"] == "Alice"][0]
        assert alice_p["resolution_status"] == "resolved"
        assert alice_p["candidate_id"] is None

        yamada_p = [p for p in got["people"] if p["name"] == "山田君"][0]
        assert yamada_p["resolution_status"] == "unresolved"
        assert yamada_p["candidate_id"] is not None

        # Filter by Alice (resolved)
        res_alice = store.list_summaries(person="Alice", conn=conn)
        assert len(res_alice) == 1
        assert res_alice[0]["period_key"] == "2026-07-20"

        # Filter by 山田君 (unresolved)
        res_yamada = store.list_summaries(person="山田君", conn=conn)
        assert len(res_yamada) == 1
        assert res_yamada[0]["period_key"] == "2026-07-20"

        # Verify get_summary_options contains only Alice and not 山田君
        options = store.get_summary_options(conn=conn)
        assert "Alice" in options["people"]
        assert "山田君" not in options["people"]
    finally:
        conn.close()


def test_alias_deduplication(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        # Create a summary with both Alice and A-chan (which both resolve to the same person_id)
        record = {
            "period_type": "day",
            "period_key": "2026-07-22",
            "period_start": "2026-07-22",
            "period_end": "2026-07-22",
            "summary": "Meeting with Alice and her alias A-chan",
            "people": [
                {"name": "Alice", "note": "primary name"},
                {"name": "a-chan", "note": "alias name"},
            ],
        }
        store.upsert_summary(record, conn=conn)

        # Retrieve and verify that Alice is only linked once
        got = store.get_summary_by_period("day", "2026-07-22", conn=conn)
        assert got is not None
        assert len(got["people"]) == 1
        assert got["people"][0]["name"] == "Alice"
        assert got["people"][0]["note"] == "primary name\nalias name"
    finally:
        conn.close()
