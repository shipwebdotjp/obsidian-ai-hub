from datetime import datetime
import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub import memory
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.activity import store as activity_store
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def clean_summary_env(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    vault_path.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "VAULT_PATH", vault_path)

    activity_dir = vault_path / "activity"
    activity_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "ACTIVITY_PATH", activity_dir)

    db_path = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_path)

    return vault_path


@pytest.fixture
def loopback_client(clean_summary_env):
    app = create_app(host="127.0.0.1", port=0, token="")
    return TestClient(app)


def _seed_day(
    period_key: str,
    summary: str,
    topics: list[str] | None = None,
    keywords: list[str] | None = None,
):
    summary_store.upsert_summary(
        {
            "period_type": "day",
            "period_key": period_key,
            "period_start": period_key,
            "period_end": period_key,
            "generated_at": f"{period_key}T22:00:00",
            "summary": summary,
            "keywords": keywords or [],
            "mood": "good",
            "sleep_raw": "7h",
            "sleep_hours": 7.0,
            "topics": topics or ["その他"],
            "projects": ["Project A"],
            "people": [{"name": "Alice", "note": "met"}],
            "items": [
                {
                    "kind": "highlights",
                    "body": f"Highlight for {period_key}",
                    "display_order": 0,
                },
                {
                    "kind": "activities",
                    "body": f"Activity for {period_key}",
                    "display_order": 0,
                },
            ],
        }
    )


def _seed_week(period_key: str, start: str, end: str, summary: str):
    summary_store.upsert_summary(
        {
            "period_type": "week",
            "period_key": period_key,
            "period_start": start,
            "period_end": end,
            "generated_at": f"{end}T22:00:00",
            "summary": summary,
            "keywords": [],
            "mood": None,
            "sleep_raw": None,
            "sleep_hours": None,
            "topics": ["LLM・AI活用"],
            "projects": ["Project B"],
            "people": [{"name": "Bob", "note": ""}],
            "items": [
                {
                    "kind": "progress",
                    "body": f"Progress for {period_key}",
                    "display_order": 0,
                },
            ],
        }
    )


def _seed_month(period_key: str, summary: str):
    summary_store.upsert_summary(
        {
            "period_type": "month",
            "period_key": period_key,
            "period_start": f"{period_key}-01",
            "period_end": f"{period_key}-31",
            "generated_at": f"{period_key}-28T22:00:00",
            "summary": summary,
            "keywords": [],
            "mood": None,
            "sleep_raw": None,
            "sleep_hours": None,
            "topics": ["LLM・AI活用"],
            "projects": ["Project B"],
            "people": [],
            "items": [],
        }
    )


def test_dashboard_home(loopback_client, clean_summary_env, monkeypatch):
    # Mock datetime.now() for predictable test dates (say, 2026-07-17)
    fake_now = datetime(2026, 7, 17, 10, 15, 0)

    # Seed data
    _seed_month("2026-07", "Monthly July")
    _seed_week("2026-W29", "2026-07-13", "2026-07-19", "Weekly 29")
    _seed_day("2026-07-16", "Yesterday Daily")

    # Add activity logs for today (2026-07-17)
    activity_store.add_activity(
        activity_date="2026-07-17",
        occurred_at="2026-07-17T10:00:00",
        summary="first log",
    )
    activity_store.add_activity(
        activity_date="2026-07-17",
        occurred_at="2026-07-17T09:30:00",
        summary="second log",
    )

    # We patch datetime.now in service to fake_now
    from obsidian_ai_hub.web import service

    original_func = service.get_dashboard_home
    monkeypatch.setattr(
        service, "get_dashboard_home", lambda now=None: original_func(now=fake_now)
    )

    res = loopback_client.get("/api/v1/summary-dashboard/home")
    assert res.status_code == 200
    data = res.json()

    assert data["this_month_summary"]["summary"] == "Monthly July"
    assert data["latest_week_summary"]["summary"] == "Weekly 29"
    assert data["yesterday_summary"]["summary"] == "Yesterday Daily"

    today_act = data["today_activity"]
    assert today_act["date"] == "2026-07-17"
    # 45 minutes active out of 10h15m (615 minutes) total_seconds.
    assert today_act["active_minutes"] == 45.0
    assert today_act["inactive_minutes"] == 615.0 - 45.0
    assert len(today_act["logs"]) == 2
    assert (
        today_act["logs"][0]["summary"] == "second log"
    )  # Sorted ascending by occurred_at
    assert today_act["logs"][1]["summary"] == "first log"


def test_dashboard_browse_year_level(loopback_client, clean_summary_env):
    _seed_month("2026-07", "Month 7")
    _seed_month("2026-08", "Month 8")
    _seed_week("2026-W29", "2026-07-13", "2026-07-19", "Week 29")  # Overlaps 2026
    _seed_week(
        "2025-W52", "2025-12-29", "2026-01-04", "Week 52"
    )  # Overlaps both 2025 and 2026

    # Browse 2026
    res = loopback_client.get("/api/v1/summary-dashboard/browse?year=2026")
    assert res.status_code == 200
    data = res.json()

    assert data["selected_year"] == "2026"
    assert data["selected_month"] is None
    assert len(data["months"]) == 2
    assert len(data["weeks"]) == 2  # Both W29 and W52 overlap 2026
    assert data["days"] == []


def test_dashboard_browse_month_level(loopback_client, clean_summary_env):
    # Week 29: 2026-07-13 to 2026-07-19 (Overlaps July 2026)
    _seed_week("2026-W29", "2026-07-13", "2026-07-19", "Week 29")
    # Day 1: July 14 (has summary)
    _seed_day("2026-07-14", "Day 14")

    # Day 2: (only activity log, no summary)
    activity_store.add_activity(
        activity_date="2026-07-15",
        occurred_at="2026-07-15T10:00:00",
        summary="activity log",
    )

    res = loopback_client.get("/api/v1/summary-dashboard/browse?month=2026-07")
    assert res.status_code == 200
    data = res.json()

    assert data["selected_month"] == "2026-07"
    assert len(data["weeks"]) == 1
    assert data["weeks"][0]["period_key"] == "2026-W29"

    # 2026-07-15 (no summary) and 2026-07-14 (has summary)
    assert len(data["days"]) == 2
    assert data["days"][0]["date"] == "2026-07-15"
    assert data["days"][0]["has_summary"] is False
    assert data["days"][0]["summary"] is None

    assert data["days"][1]["date"] == "2026-07-14"
    assert data["days"][1]["has_summary"] is True
    assert data["days"][1]["summary"] == "Day 14"


def test_dashboard_browse_validation_mismatch(loopback_client, clean_summary_env):
    res = loopback_client.get(
        "/api/v1/summary-dashboard/browse?year=2025&month=2026-07"
    )
    assert res.status_code == 400


def test_dashboard_summaries_get_by_id(loopback_client, clean_summary_env):
    _seed_day("2026-07-14", "My Day")

    # Get ID
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT summary_id FROM summaries WHERE period_key='2026-07-14'")
        summary_id = cursor.fetchone()[0]
    finally:
        conn.close()

    res = loopback_client.get(f"/api/v1/summary-dashboard/summaries/{summary_id}")
    assert res.status_code == 200
    assert res.json()["summary"] == "My Day"


def test_dashboard_days_get_details(loopback_client, clean_summary_env):
    _seed_day("2026-07-14", "My Day")
    activity_store.add_activity(
        activity_date="2026-07-14",
        occurred_at="2026-07-14T09:00:00",
        summary="something",
    )

    res = loopback_client.get("/api/v1/summary-dashboard/days/2026-07-14")
    assert res.status_code == 200
    data = res.json()
    assert data["date"] == "2026-07-14"
    assert data["summary"]["summary"] == "My Day"
    assert len(data["logs"]) == 1
    assert data["logs"][0]["summary"] == "something"
    assert data["active_minutes"] == 30.0


def test_dashboard_stats_aggregation(loopback_client, clean_summary_env):
    # Seed 3 days with recognised topics from TOPIC_ENUM (all <= 2026-07-15, which is in the past!)
    _seed_day(
        "2026-07-13",
        "Day 13",
        topics=["LLM・AI活用", "健康・医療"],
        keywords=["foo", "bar"],
    )
    _seed_day("2026-07-14", "Day 14", topics=["LLM・AI活用"], keywords=["foo"])
    _seed_day("2026-07-15", "Day 15", topics=["ソフトウェア開発"], keywords=["baz"])

    # Seed activities
    activity_store.add_activity(
        activity_date="2026-07-13", occurred_at="2026-07-13T10:00:00", summary="act"
    )

    res = loopback_client.get(
        "/api/v1/summary-dashboard/stats?start_date=2026-07-13&end_date=2026-07-15"
    )
    assert res.status_code == 200
    data = res.json()

    assert data["granularity"] == "day"
    assert len(data["buckets"]) == 3
    # Check candidate topics / keywords sorting (LLM・AI活用 has 2, others have 1)
    assert data["candidate_topics"][0] == "LLM・AI活用"
    assert data["candidate_keywords"][0] == "foo"

    # Day 13 has topic LLM・AI活用, 健康・医療
    bucket_13 = data["buckets"][0]
    assert bucket_13["key"] == "2026-07-13"
    assert bucket_13["daily_summary_count"] == 1
    assert bucket_13["topic_counts"]["LLM・AI活用"] == 1
    assert bucket_13["topic_counts"]["健康・医療"] == 1
    assert bucket_13["keyword_counts"]["foo"] == 1
    assert bucket_13["keyword_counts"]["bar"] == 1
    assert bucket_13["active_minutes"] == 30.0


def test_get_day_activity_times_future_date(loopback_client, clean_summary_env):
    from obsidian_ai_hub.web import service

    fake_now = datetime(2026, 7, 17, 10, 15, 0)
    # 2026-07-18 is in the future relative to fake_now
    active_mins, inactive_mins = service.get_day_activity_times(
        [], "2026-07-18", now=fake_now
    )
    assert active_mins == 0.0
    assert inactive_mins == 0.0


def test_stats_hourly_category_heatmap(loopback_client, clean_summary_env):
    activity_store.add_activity(
        activity_date="2026-07-13",
        occurred_at="2026-07-13T10:00:00",
        category="開発",
        summary="coding",
    )
    activity_store.add_activity(
        activity_date="2026-07-13",
        occurred_at="2026-07-13T10:05:00",
        category="開発",
        summary="code review",
    )
    activity_store.add_activity(
        activity_date="2026-07-13",
        occurred_at="2026-07-13T10:10:00",
        category="コミュニケーション",
        summary="chat",
    )
    activity_store.add_activity(
        activity_date="2026-07-14",
        occurred_at="2026-07-14T15:00:00",
        category=None,
        summary="uncategorized",
    )

    res = loopback_client.get(
        "/api/v1/summary-dashboard/stats?start_date=2026-07-13&end_date=2026-07-14"
    )
    assert res.status_code == 200
    data = res.json()

    assert "hourly_category_buckets" in data
    assert "activity_categories" in data
    assert len(data["hourly_category_buckets"]) == 24

    bucket_10 = data["hourly_category_buckets"][10]
    assert bucket_10["total_log_count"] == 3
    assert bucket_10["category_counts"]["開発"] == 2
    assert bucket_10["category_counts"]["コミュニケーション"] == 1

    bucket_15 = data["hourly_category_buckets"][15]
    assert bucket_15["total_log_count"] == 1
    assert bucket_15["category_counts"]["その他"] == 1

    for h in range(24):
        if h in (10, 15):
            continue
        b = data["hourly_category_buckets"][h]
        assert b["total_log_count"] == 0

    assert "開発" in data["activity_categories"]
    assert "その他" in data["activity_categories"]


def test_stats_date_range_exceeded(loopback_client, clean_summary_env):
    res = loopback_client.get(
        "/api/v1/summary-dashboard/stats?start_date=2020-01-01&end_date=2031-01-01"
    )
    assert res.status_code == 400


def test_dashboard_strict_date_parsing(loopback_client, clean_summary_env):
    # Test invalid year format
    res = loopback_client.get("/api/v1/summary-dashboard/browse?year=foo")
    assert res.status_code == 400

    # Test invalid month format
    res = loopback_client.get("/api/v1/summary-dashboard/browse?month=2026-7")
    assert res.status_code == 400

    # Test impossible month value
    res = loopback_client.get("/api/v1/summary-dashboard/browse?month=2026-13")
    assert res.status_code == 400

    # Test impossible day details date
    res = loopback_client.get("/api/v1/summary-dashboard/days/2026-02-31")
    assert res.status_code == 400


def test_dashboard_activity_project_association(loopback_client, clean_summary_env):
    conn = memory.get_db_connection()
    try:
        # Create a project
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO projects (
                project_id, normalized_name, display_name, domain, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                123,
                "dashboard-proj",
                "Dashboard Proj Display",
                "work",
                "active",
                "2026-07-14T10:00:00",
                "2026-07-14T10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Seed daily summary and associated activity log
    _seed_day("2026-07-14", "My Associated Day")
    activity_store.add_activity(
        activity_date="2026-07-14",
        occurred_at="2026-07-14T09:00:00",
        summary="something linked to project",
        project_id=123,
    )

    # 1. Verify /summary-dashboard/days/{target_date} API response
    res_days = loopback_client.get("/api/v1/summary-dashboard/days/2026-07-14")
    assert res_days.status_code == 200
    data_days = res_days.json()
    assert len(data_days["logs"]) == 1
    assert data_days["logs"][0]["project_id"] == 123
    assert data_days["logs"][0]["project_name"] == "Dashboard Proj Display"


def test_dashboard_home_with_project_association(loopback_client, clean_summary_env, monkeypatch):
    fake_now = datetime(2026, 7, 14, 10, 15, 0)

    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO projects (
                project_id, normalized_name, display_name, domain, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                456,
                "home-proj",
                "Home Proj Display",
                "work",
                "active",
                "2026-07-14T10:00:00",
                "2026-07-14T10:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    activity_store.add_activity(
        activity_date="2026-07-14",
        occurred_at="2026-07-14T09:00:00",
        summary="home log with project",
        project_id=456,
    )

    from obsidian_ai_hub.web import service

    original_func = service.get_dashboard_home
    monkeypatch.setattr(
        service, "get_dashboard_home", lambda now=None: original_func(now=fake_now)
    )

    res = loopback_client.get("/api/v1/summary-dashboard/home")
    assert res.status_code == 200
    data = res.json()
    assert len(data["today_activity"]["logs"]) == 1
    assert data["today_activity"]["logs"][0]["project_id"] == 456
    assert data["today_activity"]["logs"][0]["project_name"] == "Home Proj Display"


def test_project_notes_update_via_api(loopback_client, clean_summary_env):
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO projects (normalized_name, display_name, domain, status, created_at, updated_at)
            VALUES ('api-proj', 'API Proj', 'work', 'active', '2026-07-14T10:00:00', '2026-07-14T10:00:00')
        """)
        conn.commit()
        proj_id = cursor.lastrowid
    finally:
        conn.close()

    summary_store.upsert_summary({
        "period_type": "day",
        "period_key": "2026-07-14",
        "period_start": "2026-07-14",
        "period_end": "2026-07-14",
        "generated_at": "2026-07-14T22:00:00",
        "summary": "API Test Day",
        "keywords": [],
        "mood": None,
        "sleep_raw": None,
        "sleep_hours": None,
        "topics": [],
        "project_ids": [proj_id],
        "project_notes": [{"project_id": proj_id, "note": "Initial note"}],
        "people": [],
        "items": [],
    })

    # Get summary_id
    summary_id = summary_store.get_summary_by_period("day", "2026-07-14")["summary_id"]

    # Update project_notes via API
    res = loopback_client.patch(
        f"/api/v1/summary-dashboard/summaries/{summary_id}",
        json={"project_notes": [{"project_id": proj_id, "note": "Updated note"}]},
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["project_notes"]) == 1
    assert data["project_notes"][0]["note"] == "Updated note"

    # Reject non-linked project_id
    res = loopback_client.patch(
        f"/api/v1/summary-dashboard/summaries/{summary_id}",
        json={"project_notes": [{"project_id": 99999, "note": "Should fail"}]},
    )
    assert res.status_code == 400

    # Reject duplicate project_id
    res = loopback_client.patch(
        f"/api/v1/summary-dashboard/summaries/{summary_id}",
        json={"project_notes": [
            {"project_id": proj_id, "note": "First"},
            {"project_id": proj_id, "note": "Duplicate"},
        ]},
    )
    assert res.status_code == 400


def test_summary_update_validation_and_not_found(loopback_client, clean_summary_env):
    # Setup standard daily summary
    summary_store.upsert_summary({
        "period_type": "day",
        "period_key": "2026-07-15",
        "period_start": "2026-07-15",
        "period_end": "2026-07-15",
        "generated_at": "2026-07-15T22:00:00",
        "summary": "Validation Test Day",
        "keywords": [],
        "mood": None,
        "sleep_raw": None,
        "sleep_hours": None,
        "topics": [],
        "people": [],
        "items": [],
    })
    summary_id = summary_store.get_summary_by_period("day", "2026-07-15")["summary_id"]

    # 1. Non-existent summary ID must return 404 FileNotFoundError
    res = loopback_client.patch(
        "/api/v1/summary-dashboard/summaries/nonexistent_id",
        json={"summary": "Should be 404"}
    )
    assert res.status_code == 404
    assert "summary not found" in res.json()["detail"]

    # Insert a valid person to database
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_111', 'alice', 'Alice')"
        )
        conn.commit()
    finally:
        conn.close()

    # 2. Duplicate person_id must return 400 validation error
    res = loopback_client.patch(
        f"/api/v1/summary-dashboard/summaries/{summary_id}",
        json={"people": [
            {"person_id": "peo_111", "note": "Duplicate 1"},
            {"person_id": "peo_111", "note": "Duplicate 2"}
        ]}
    )
    assert res.status_code == 400
    assert "Duplicate person_id: peo_111" in res.json()["detail"]

    # 3. Missing person_id in order must return 400 with first missing person_id
    res = loopback_client.patch(
        f"/api/v1/summary-dashboard/summaries/{summary_id}",
        json={"people": [
            {"person_id": "peo_111", "note": "Found"},
            {"person_id": "peo_999", "note": "First missing"},
            {"person_id": "peo_888", "note": "Second missing"}
        ]}
    )
    assert res.status_code == 400
    assert "Person not found: peo_999" in res.json()["detail"]
