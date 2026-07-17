import json
from datetime import datetime, timedelta
from unittest.mock import patch

from obsidian_ai_hub import memory
from obsidian_ai_hub.summerize_day import get_daily_structured_record
from obsidian_ai_hub.summerize_week import get_week_dates, get_weekly_structured_record
from obsidian_ai_hub.summerize_month import get_monthly_structured_record, load_weekly_records
from obsidian_ai_hub.summary import store


def _make_day_record(date: datetime, summary: str) -> dict:
    return {
        "period_type": "day",
        "period_key": date.strftime("%Y-%m-%d"),
        "period_start": date.strftime("%Y-%m-%d"),
        "period_end": date.strftime("%Y-%m-%d"),
        "generated_at": f"{date.strftime('%Y-%m-%d')}T22:00:00",
        "summary": summary,
        "keywords": [],
        "mood": "good",
        "sleep_raw": "7h",
        "sleep_hours": 7.0,
        "topics": ["LLM・AI活用"],
        "projects": [],
        "people": [],
        "items": [
            {"kind": "activities", "body": f"Activity on {date.day}", "display_order": 0},
        ],
    }


def test_day_week_month_chain(test_memory_db_path):
    target_week = datetime(2026, 7, 13)  # Monday
    week_dates = get_week_dates(target_week)

    conn = memory.get_db_connection()
    try:
        # Seed 7 daily records
        for d in week_dates:
            store.upsert_summary(_make_day_record(d, f"Day {d.strftime('%Y-%m-%d')}"), conn=conn)
        conn.commit()
    finally:
        conn.close()

    responses = [
        json.dumps({"summary": "Week summary", "progress": ["Week progress"]}),
        json.dumps({"summary": "Month summary"}),
    ]
    with patch("obsidian_ai_hub.utils.llm_client.generate_llm_response", side_effect=responses):
        # Week generation reads days from SQLite
        daily_records = [store.get_summary_by_period("day", d.strftime("%Y-%m-%d")) for d in week_dates]
        week_record = get_weekly_structured_record(target_week, daily_records)
        store.upsert_summary(week_record)

        # Month generation reads weeks from SQLite
        month_date = datetime(2026, 7, 1)
        weekly_records = load_weekly_records(month_date)
        assert len(weekly_records) >= 1
        month_record = get_monthly_structured_record(month_date, weekly_records)
        store.upsert_summary(month_record)

    # Verify all three exist
    assert store.get_summary_by_period("day", "2026-07-13") is not None
    week = store.get_summary_by_period("week", "2026-W29")
    assert week is not None
    assert week["summary"] == "Week summary"
    assert any(i["kind"] == "progress" and i["body"] == "Week progress" for i in week["items"])
    month = store.get_summary_by_period("month", "2026-07")
    assert month is not None
    assert month["summary"] == "Month summary"

