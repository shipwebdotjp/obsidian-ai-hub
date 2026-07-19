import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.summerize_week import (
    get_week_dates,
    load_daily_records,
    get_weekly_structured_record,
    format_weekly_record_as_markdown,
    upsert_summary_record,
    summarize_week,
)
from obsidian_ai_hub.summary import store


@pytest.fixture
def mock_config(tmp_path):
    with patch("obsidian_ai_hub.summerize_week.config") as mock_cfg:
        mock_cfg.ACTIVITY_PATH = tmp_path / "activity"
        mock_cfg.DAILY_PATH = tmp_path / "daily"
        mock_cfg.MAKE_TODAY_TARGET_PROVIDER = "test_provider"
        mock_cfg.MAKE_TODAY_TARGET_MODEL = "test_model"
        yield mock_cfg


def test_get_week_dates():
    # 2023-10-27 is Friday
    target_date = datetime(2023, 10, 27)
    week_dates = get_week_dates(target_date)
    assert len(week_dates) == 7
    assert week_dates[0] == datetime(2023, 10, 23)  # Monday
    assert week_dates[-1] == datetime(2023, 10, 29)  # Sunday


def test_load_daily_records(mock_config, test_memory_db_path):
    week_dates = [datetime(2023, 10, 23) + timedelta(days=i) for i in range(7)]
    conn = memory.get_db_connection()
    try:
        for d in week_dates[:2]:
            store.upsert_summary({
                "period_type": "day",
                "period_key": d.strftime("%Y-%m-%d"),
                "period_start": d.strftime("%Y-%m-%d"),
                "period_end": d.strftime("%Y-%m-%d"),
                "generated_at": "2023-10-23T22:00:00",
                "summary": f"Day {d.day}",
                "keywords": [],
                "mood": None,
                "sleep_raw": None,
                "sleep_hours": None,
                "topics": [],
                "projects": [],
                "people": [],
                "items": [],
            }, conn=conn)
        conn.commit()
    finally:
        conn.close()

    records = load_daily_records(week_dates)
    assert len(records) == 7
    assert records[0]["summary"] == "Day 23"
    assert records[1]["summary"] == "Day 24"
    assert records[2] is None


def test_upsert_summary_record(mock_config, test_memory_db_path):
    record = {
        "period_type": "week",
        "period_key": "2023-W43",
        "period_start": "2023-10-23",
        "period_end": "2023-10-29",
        "generated_at": "2023-10-29T22:00:00",
        "summary": "Week 43",
        "keywords": [],
        "mood": None,
        "sleep_raw": None,
        "sleep_hours": None,
        "topics": [],
        "projects": [],
        "people": [],
        "items": [],
    }
    upsert_summary_record(record)

    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM summaries WHERE period_type = ? AND period_key = ?", ("week", "2023-W43"))
        row = cursor.fetchone()
        assert row is not None
        assert row["summary"] == "Week 43"
    finally:
        conn.close()


@patch("obsidian_ai_hub.summerize_week.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_week.llm_client.generate_llm_response")
def test_get_weekly_structured_record(mock_llm, mock_render, mock_config):
    target_date = datetime(2023, 10, 27)  # W43
    mock_render.return_value = "Rendered Prompt"
    mock_llm.return_value = json.dumps({
        "summary": "AI Weekly Summary",
        "keywords": [" Python ", "Python", "Obsidian"],
        "topics": ["Work"],
        "highlights": ["Highlight 1"],
        "progress": ["Progress 1"],
        "people": [{"name": "Bob", "note": "Partner"}]
    })

    daily_records = [
        {"summary": "Day 1", "mood": "Stable", "sleep_raw": "8h", "sleep_hours": 8.0, "items": []},
        {"summary": "Day 2", "mood": "Energetic", "sleep_raw": "7.5", "sleep_hours": 7.5, "items": []},
        None,
        None,
        None,
        None,
        None,
    ]
    record = get_weekly_structured_record(target_date, daily_records)

    assert record["period_key"] == "2023-W43"
    assert record["summary"] == "AI Weekly Summary"
    assert record["keywords"] == ["Python", "Obsidian"]
    assert record["mood"] is None
    assert record["sleep_hours"] is None
    assert record["people"][0]["name"] == "Bob"
    assert any(i["kind"] == "highlights" and i["body"] == "Highlight 1" for i in record["items"])
    assert any(i["kind"] == "progress" and i["body"] == "Progress 1" for i in record["items"])


@patch("obsidian_ai_hub.summerize_week.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_week.llm_client.generate_llm_response")
def test_get_weekly_structured_record_malformed_json(mock_llm, mock_render, mock_config):
    target_date = datetime(2023, 10, 27)
    mock_render.return_value = "Rendered Prompt"
    mock_llm.return_value = "```json\nINVALID\n```"

    record = get_weekly_structured_record(target_date, [])

    assert record["period_key"] == "2023-W43"
    assert record["summary"] is None
    assert record["topics"] == []


def test_format_weekly_record_as_markdown():
    record = {
        "summary": "Great week.",
        "items": [
            {"kind": "highlights", "body": "Highlight", "display_order": 0},
            {"kind": "progress", "body": "Progress", "display_order": 0},
        ],
        "people": [{"name": "Charlie", "note": "Met"}]
    }
    md = format_weekly_record_as_markdown(record)
    assert "Great week." in md
    assert "### ハイライト" in md
    assert "- Highlight" in md
    assert "### 目標・プロジェクトの前進" in md
    assert "- Progress" in md
    assert "### 人物メモ" in md
    assert "- **Charlie**: Met" in md


@patch("obsidian_ai_hub.summerize_week.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_week.llm_client.generate_llm_response")
def test_summarize_week(mock_llm, mock_render, mock_config, test_memory_db_path):
    target_date = datetime(2023, 10, 27)
    mock_render.return_value = "Rendered Prompt"
    mock_llm.return_value = json.dumps({
        "summary": "Weekly Summary",
        "topics": ["AI"],
        "highlights": ["Highlight"],
    })

    with patch("obsidian_ai_hub.summerize_week.load_daily_records", return_value=[None] * 7):
        summarize_week(target_date)

    conn = memory.get_db_connection()
    try:
        row = store.get_summary_by_period("week", "2023-W43", conn=conn)
        assert row is not None
        assert row["summary"] == "Weekly Summary"
        assert len(row["items"]) == 1
        assert row["items"][0]["kind"] == "highlights"
        assert row["items"][0]["body"] == "Highlight"
    finally:
        conn.close()


@patch("obsidian_ai_hub.summerize_week.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_week.llm_client.generate_llm_response")
def test_get_weekly_structured_record_passes_candidates_and_normalizes_topics(mock_llm, mock_render, mock_config):
    target_date = datetime(2023, 10, 27)  # W43
    mock_render.return_value = "Rendered Prompt"

    # LLM returns topics with mixed valid, duplicates, and out-of-candidates
    mock_llm.return_value = json.dumps({
        "summary": "AI Weekly Summary",
        "topics": ["LLM・AI活用", "未知のトピック", "LLM・AI活用"]
    })

    record = get_weekly_structured_record(target_date, [])

    # Check render_prompt is called with TOPIC_CANDIDATES
    mock_render.assert_called_once()
    context = mock_render.call_args[0][1]
    assert "TOPIC_CANDIDATES" in context
    candidates = json.loads(context["TOPIC_CANDIDATES"])
    assert "LLM・AI活用" in candidates
    assert "その他" in candidates

    # Check parsed and normalized topics in record
    assert record["topics"] == ["LLM・AI活用", "その他"]
