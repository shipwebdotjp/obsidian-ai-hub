import pytest
from datetime import datetime, timedelta
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.summary.search import compute_max_granularity, search_summaries


@pytest.fixture
def test_db():
    conn = get_db_connection()

    now_iso = datetime.now().isoformat()
    # Insert test projects
    conn.execute(
        "INSERT INTO projects (project_id, normalized_name, display_name, domain, status, created_at, updated_at) VALUES (10, 'project alpha', 'Project Alpha', 'personal', 'active', ?, ?)",
        (now_iso, now_iso),
    )
    conn.execute(
        "INSERT INTO projects (project_id, normalized_name, display_name, domain, status, created_at, updated_at) VALUES (20, 'project beta', 'Project Beta', 'personal', 'active', ?, ?)",
        (now_iso, now_iso),
    )

    # Create various summaries across dates
    day1 = {
        "period_type": "day",
        "period_key": "2026-01-01",
        "period_start": "2026-01-01",
        "period_end": "2026-01-01",
        "summary": "First day summary with Python project and Alice",
        "keywords": ["python", "development"],
        "topics": ["ソフトウェア開発"],
        "project_ids": [10],
        "project_notes": [{"project_id": 10, "display_name": "Project Alpha", "note": "Alpha work"}],
        "people": [{"person_id": "peo_alice", "name": "Alice", "note": "Coffee chat"}],
        "items": [{"kind": "highlights", "body": "Fixed bug in hub"}],
    }
    day2 = {
        "period_type": "day",
        "period_key": "2026-01-02",
        "period_start": "2026-01-02",
        "period_end": "2026-01-02",
        "summary": "Second day summary about reading and health",
        "keywords": ["health", "reading"],
        "topics": ["健康・医療"],
        "items": [{"kind": "highlights", "body": "Went for a run"}],
    }
    week1 = {
        "period_type": "week",
        "period_key": "2026-W01",
        "period_start": "2026-01-05",
        "period_end": "2026-01-11",
        "summary": "Week 1 summary containing Python progress",
        "keywords": ["python", "weekly"],
        "topics": ["ソフトウェア開発"],
        "project_ids": [10],
        "people": [{"person_id": "peo_bob", "name": "Bob", "note": "Code review"}],
        "items": [{"kind": "progress", "body": "Completed feature A"}],
    }
    month1 = {
        "period_type": "month",
        "period_key": "2026-01",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "summary": "January month summary",
        "keywords": ["january", "monthly"],
        "topics": ["ソフトウェア開発", "健康・医療"],
        "project_ids": [10, 20],
        "people": [{"person_id": "peo_alice", "name": "Alice", "note": "Monthly review"}],
        "items": [{"kind": "highlights", "body": "Great month overall"}],
    }

    r1 = summary_store.upsert_summary(day1, conn=conn)
    r2 = summary_store.upsert_summary(day2, conn=conn)
    r3 = summary_store.upsert_summary(week1, conn=conn)
    r4 = summary_store.upsert_summary(month1, conn=conn)

    yield conn

    summary_store.delete_summary(r1["summary_id"], conn=conn)
    summary_store.delete_summary(r2["summary_id"], conn=conn)
    summary_store.delete_summary(r3["summary_id"], conn=conn)
    summary_store.delete_summary(r4["summary_id"], conn=conn)
    conn.execute("DELETE FROM projects WHERE project_id IN (10, 20)")
    conn.close()


def test_granularity_bounds():
    start = datetime.strptime("2026-01-01", "%Y-%m-%d").date()
    # 31 days -> day
    assert compute_max_granularity(start, start + timedelta(days=30), "auto") == "day"
    # 32 days -> week
    assert compute_max_granularity(start, start + timedelta(days=31), "auto") == "week"
    # 180 days -> week
    assert compute_max_granularity(start, start + timedelta(days=179), "auto") == "week"
    # 181 days -> month
    assert compute_max_granularity(start, start + timedelta(days=180), "auto") == "month"

    # Explicit override
    assert compute_max_granularity(start, start + timedelta(days=180), "week") == "week"
    assert compute_max_granularity(start, start + timedelta(days=10), "month") == "month"


def test_invalid_input_dates(test_db):
    with pytest.raises(ValueError):
        search_summaries("invalid-date", "2026-01-10", conn=test_db)

    with pytest.raises(ValueError):
        search_summaries("2026-01-10", "2026-01-01", conn=test_db)

    with pytest.raises(ValueError):
        search_summaries("2026-01-01", "2026-01-10", granularity="unknown", conn=test_db)


def test_hierarchical_selection_and_no_duplicates(test_db):
    res = search_summaries("2026-01-01", "2026-01-31", granularity="month", conn=test_db)
    assert res["granularity"] == "month"
    assert len(res["entries"]) == 1
    assert res["entries"][0]["period_type"] == "month"
    period_types = [e["period_type"] for e in res["entries"]]
    assert period_types == ["month"]


def test_fallback_when_upper_unmatched(test_db):
    # Search for "Alice" across whole month with granularity="month"
    res1 = search_summaries("2026-01-01", "2026-01-31", query="Alice", granularity="month", conn=test_db)
    assert len(res1["entries"]) == 1
    assert res1["entries"][0]["period_type"] == "month"

    # Search for "Bob" across whole month with granularity="month"
    res2 = search_summaries("2026-01-01", "2026-01-31", query="Bob", granularity="month", conn=test_db)
    assert len(res2["entries"]) == 1
    assert res2["entries"][0]["period_type"] == "week"
    assert res2["entries"][0]["period_key"] == "2026-W01"


def test_fallback_to_day_when_week_unmatched(test_db):
    res = search_summaries("2026-01-01", "2026-01-11", query="run", granularity="week", conn=test_db)
    assert len(res["entries"]) == 1
    assert res["entries"][0]["period_type"] == "day"
    assert res["entries"][0]["period_key"] == "2026-01-02"


def test_filters_composite(test_db):
    res = search_summaries(
        "2026-01-01",
        "2026-01-31",
        topics=["ソフトウェア開発"],
        project_ids=[10],
        granularity="month",
        conn=test_db,
    )
    assert len(res["entries"]) == 1
    assert "topics" in res["entries"][0]["matched_fields"]
    assert "projects" in res["entries"][0]["matched_fields"]

    res_empty = search_summaries(
        "2026-01-01",
        "2026-01-31",
        person_ids=["peo_unknown"],
        granularity="month",
        conn=test_db,
    )
    assert len(res_empty["entries"]) == 0


def test_coverage_structure(test_db):
    res = search_summaries("2026-01-01", "2026-01-10", query="run", conn=test_db)
    cov = res["coverage"]

    assert cov["requested_days"] == 10
    assert cov["source_covered_days"] == 10
    assert cov["source_missing_days"] == 0
    assert cov["filter_matched_days"] == 1
    assert cov["filter_unmatched_days"] == 9
    assert cov["returned_days"] == 1

    assert isinstance(cov["source_missing_ranges"], list)
    assert isinstance(cov["filter_unmatched_ranges"], list)
    assert isinstance(cov["returned_ranges"], list)
    assert cov["ranges_truncated"] == {
        "source_missing": False,
        "filter_unmatched": False,
        "returned": False,
    }


def test_coverage_without_filters(test_db):
    res = search_summaries("2026-01-01", "2026-01-10", conn=test_db)
    cov = res["coverage"]
    assert cov["requested_days"] == 10
    assert cov["source_covered_days"] == 10
    assert cov["filter_matched_days"] == cov["source_covered_days"]
    assert cov["filter_unmatched_days"] == 0
    assert cov["filter_unmatched_ranges"] == []


def test_empty_results(test_db):
    res = search_summaries("2020-01-01", "2020-01-05", conn=test_db)
    assert res["entries"] == []
    assert res["truncated"] is False
    assert res["next_request"] is None
    cov = res["coverage"]
    assert cov["requested_days"] == 5
    assert cov["source_covered_days"] == 0
    assert cov["source_missing_days"] == 5


def test_budget_truncation_and_next_request(test_db):
    large_days_res = []
    for i in range(1, 25):
        d_str = f"2026-02-{i:02d}"
        rec = {
            "period_type": "day",
            "period_key": d_str,
            "period_start": d_str,
            "period_end": d_str,
            "summary": f"Large summary for day {i} " + ("x" * 400),
            "keywords": ["test", f"kw_{i}"],
            "topics": ["ソフトウェア開発"],
            "items": [{"kind": "highlights", "body": f"Item body for day {i} " + ("y" * 300)}],
        }
        r = summary_store.upsert_summary(rec, conn=test_db)
        large_days_res.append(r)

    try:
        res = search_summaries("2026-02-01", "2026-02-24", granularity="day", conn=test_db)
        assert res["truncated"] is True
        assert res["next_request"] is not None
        assert res["next_request"]["start_date"] == "2026-02-01"
        oldest_returned = res["entries"][-1]["period_start"]
        dt_oldest = datetime.strptime(oldest_returned, "%Y-%m-%d")
        expected_next_end = (dt_oldest - timedelta(days=1)).strftime("%Y-%m-%d")
        assert res["next_request"]["end_date"] == expected_next_end
    finally:
        for r in large_days_res:
            summary_store.delete_summary(r["summary_id"], conn=test_db)
