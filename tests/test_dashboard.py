import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

mock_modules = [
    "dotenv",
    "yaml",
]
for module_name in mock_modules:
    sys.modules[module_name] = MagicMock()

from obsidian_ai_hub import dashboard


@pytest.fixture
def dashboard_env(tmp_path):
    vault = tmp_path / "vault"
    activity = vault / "activity"
    daily = vault / "daily"
    dashboard_dir = vault / "dashboard"
    for path in (activity, daily, dashboard_dir):
        path.mkdir(parents=True, exist_ok=True)

    with (
        patch.object(dashboard.config, "VAULT_PATH", vault),
        patch.object(dashboard.config, "ACTIVITY_PATH", activity),
        patch.object(dashboard.config, "DAILY_PATH", daily),
        patch.object(dashboard.config, "DASHBOARD_PATH", dashboard_dir),
    ):
        yield {
            "vault": vault,
            "activity": activity,
            "daily": daily,
            "dashboard": dashboard_dir,
        }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_build_dashboard_exports_year_payload_and_html(dashboard_env):
    activity = dashboard_env["activity"]
    daily = dashboard_env["daily"]
    output = dashboard_env["dashboard"]

    _write_jsonl(
        activity / "2026/07/2026-07.jsonl",
        [
            {
                "date": "2026-07-10",
                "summary": "Day 10 summary",
                "topics": ["AI", "Python"],
                "keywords": ["LLM", "RAG"],
                "mood": "Calm",
                "sleep": "7h",
                "source_stats": {"activity_count": 3, "llm_session_count": 1, "has_daily_note": True},
            },
            {
                "date": "2026-07-11",
                "summary": "Day 11 summary",
                "topics": ["AI"],
                "keywords": ["Obsidian"],
                "mood": "Focused",
                "sleep": "6h",
                "source_stats": {"activity_count": 5, "llm_session_count": 2, "has_daily_note": True},
            },
        ],
    )
    _write_jsonl(
        activity / "2026/2026-week.jsonl",
        [
            {
                "week_id": "2026-W28",
                "week_start_date": "2026-07-06",
                "week_end_date": "2026-07-12",
                "summary": "Weekly summary",
                "topics": ["Planning"],
                "keywords": ["Review"],
                "mood": "Stable",
                "sleep": "Good",
                "source_stats": {"daily_record_count": 2},
            }
        ],
    )
    _write_jsonl(
        activity / "2026/2026.jsonl",
        [
            {
                "month": "2026-07",
                "summary": "Monthly summary",
                "topics": ["Monthly"],
                "keywords": ["Retro"],
                "mood": "Good",
                "sleep": "Normal",
                "source_stats": {"weekly_record_count": 1},
            }
        ],
    )

    (daily / "2026/07").mkdir(parents=True, exist_ok=True)
    (daily / "2026/07/2026-07-10.md").write_text("# Daily", encoding="utf-8")
    (daily / "2026/07/2026-07-11.md").write_text("# Daily", encoding="utf-8")
    (daily / "2026/07/2026-W28.md").write_text("# Weekly", encoding="utf-8")
    (daily / "2026/07/2026-07.md").write_text("# Monthly", encoding="utf-8")

    html_path = dashboard.build_dashboard([2026])

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    year_payload = json.loads((output / "years/2026.json").read_text(encoding="utf-8"))

    assert html_path == output / "index.html"
    assert html_path.exists()
    assert manifest["available_years"] == [2026]
    assert manifest["totals"]["daily_count"] == 2
    assert year_payload["daily"][0]["date"] == "2026-07-11"
    assert year_payload["daily"][0]["note_path"] == "daily/2026/07/2026-07-11.md"
    assert year_payload["weekly"][0]["note_path"] == "daily/2026/07/2026-W28.md"
    assert year_payload["monthly"][0]["note_path"] == "daily/2026/07/2026-07.md"
    assert "window.__DASHBOARD_BOOTSTRAP__" in html_path.read_text(encoding="utf-8")


def test_build_dashboard_generates_stats_html(dashboard_env):
    output = dashboard_env["dashboard"]
    # Verify both index.html and stats.html are generated
    html_path = dashboard.build_dashboard([2026])
    assert html_path == output / "index.html"
    assert html_path.exists()

    stats_path = output / "stats.html"
    assert stats_path.exists()

    stats_content = stats_path.read_text(encoding="utf-8")
    assert "window.__DASHBOARD_BOOTSTRAP__" in stats_content
    assert "Topic Trends" in stats_content
    assert "trendsSvg" in stats_content


def test_aggregate_topics_by_granularity_day_and_deduplication():
    # Day granularity with duplicates in individual records
    daily_records = [
        # This record has "AI" duplicated. It should be counted once.
        {
            "date": "2026-07-10",
            "topics": ["AI", "AI", "Python"],
        },
        # This record has "AI" and "OtherTopic"
        {
            "date": "2026-07-11",
            "topics": ["AI", "OtherTopic"],
        }
    ]

    res = dashboard.aggregate_topics_by_granularity(daily_records, 2026, "day")

    # AI and Python are top topics
    top_topics = res["top_topics"]
    assert "AI" in top_topics
    assert "Python" in top_topics

    # Total buckets should represent the whole year (365 days for 2026)
    buckets = res["buckets"]
    assert len(buckets) == 365

    # Let's locate the bucket for 2026-07-10
    b_10 = next(b for b in buckets if b["key"] == "2026-07-10")
    # Python is in top 6, AI is in top 6. Let's see counts.
    # Total deduplicated topics in record 10 is ["AI", "Python"] -> 2 total counts
    assert b_10["total"] == 2
    assert b_10["counts"]["AI"] == 1
    assert b_10["counts"]["Python"] == 1
    assert b_10["proportions"]["AI"] == 0.5
    assert b_10["proportions"]["Python"] == 0.5

    # Bucket for 2026-07-11: ["AI", "OtherTopic"]
    b_11 = next(b for b in buckets if b["key"] == "2026-07-11")
    # "OtherTopic" is in "Other" count if it's not in top_6
    # Let's check proportions sum to 1.0 (100%)
    assert sum(b_11["proportions"].values()) == pytest.approx(1.0)


def test_aggregate_topics_by_granularity_week_and_month():
    daily_records = [
        {"date": "2026-01-01", "topics": ["AI"]},
        {"date": "2026-12-31", "topics": ["Python"]}
    ]

    # Week aggregation
    res_wk = dashboard.aggregate_topics_by_granularity(daily_records, 2026, "week")
    assert len(res_wk["buckets"]) >= 52

    # Month aggregation
    res_m = dashboard.aggregate_topics_by_granularity(daily_records, 2026, "month")
    assert len(res_m["buckets"]) == 12

    # Jan 2026 is month index 0 (2026-01)
    b_jan = res_m["buckets"][0]
    assert b_jan["key"] == "2026-01"
    assert b_jan["total"] == 1
    assert b_jan["counts"]["AI"] == 1


def test_aggregate_topics_by_granularity_empty():
    res = dashboard.aggregate_topics_by_granularity([], 2026, "month")
    assert len(res["buckets"]) == 12
    for b in res["buckets"]:
        assert b["total"] == 0
        assert b["proportions"] == {}
        assert b["counts"] == {}
