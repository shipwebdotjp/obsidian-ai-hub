import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub import summerize_month
from obsidian_ai_hub.summary import store
from obsidian_ai_hub.utils import config


@pytest.fixture
def mock_config(tmp_path):
    activity_path = tmp_path / "activity"
    daily_path = tmp_path / "daily"
    template_path = tmp_path / "template" / "daily.md"
    monthly_template_path = tmp_path / "template" / "monthly.md"

    activity_path.mkdir(parents=True, exist_ok=True)
    daily_path.mkdir(parents=True, exist_ok=True)
    monthly_template_path.parent.mkdir(parents=True, exist_ok=True)
    monthly_template_path.write_text("Default Monthly Template")

    with patch("obsidian_ai_hub.utils.config.ACTIVITY_PATH", activity_path), \
         patch("obsidian_ai_hub.utils.config.DAILY_PATH", daily_path), \
         patch("obsidian_ai_hub.utils.config.TEMPLATE_PATH", template_path), \
         patch("obsidian_ai_hub.utils.config.MONTHLY_TEMPLATE_PATH", monthly_template_path):
        yield


def test_get_monthly_note_path(mock_config):
    dt = datetime(2024, 10, 15)
    with patch("obsidian_ai_hub.summerize_month.reader.config.DAILY_PATH", Path("/vault/daily")):
        path = summerize_month.reader.get_monthly_note_path(dt)
        assert path == Path("/vault/daily/2024/10/2024-10.md")


def test_load_weekly_records(mock_config, test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        for rec in [
            {"period_key": "2024-W40", "period_start": "2024-09-30", "period_end": "2024-10-06"},
            {"period_key": "2024-W41", "period_start": "2024-10-07", "period_end": "2024-10-13"},
            {"period_key": "2024-W44", "period_start": "2024-10-28", "period_end": "2024-11-03"},
            {"period_key": "2024-W45", "period_start": "2024-11-04", "period_end": "2024-11-10"},
        ]:
            store.upsert_summary({
                "period_type": "week",
                "period_key": rec["period_key"],
                "period_start": rec["period_start"],
                "period_end": rec["period_end"],
                "generated_at": "2024-10-01T22:00:00",
                "summary": f"Week {rec['period_key']}",
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

    # Test for October
    oct_dt = datetime(2024, 10, 1)
    loaded = summerize_month.load_weekly_records(oct_dt)
    assert len(loaded) == 3
    assert loaded[0]["period_key"] == "2024-W44"
    assert loaded[1]["period_key"] == "2024-W41"
    assert loaded[2]["period_key"] == "2024-W40"


@patch("obsidian_ai_hub.summerize_month.prompt.render_prompt")
@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_summarize_month(mock_llm, mock_render, mock_config, test_memory_db_path):
    mock_render.return_value = "Rendered Prompt"
    mock_llm.return_value = json.dumps({
        "summary": "Monthly summary test",
        "keywords": [" Python ", "Python", "Obsidian"],
        "topics": ["LLM・AI活用"],
        "highlights": ["Highlight 1"],
        "progress": ["Progress 1"],
        "changes": ["Change 1"],
        "learnings": ["Learning 1"],
        "reflections": ["Reflection 1"],
        "patterns": ["Pattern 1"],
        "gratitude": ["Gratitude 1"],
        "people": [{"name": "Person 1", "note": "Note 1"}],
    })

    target_date = datetime(2024, 10, 1)

    conn = memory.get_db_connection()
    try:
        for rec in [
            {"period_key": "2024-W40", "period_start": "2024-09-30", "period_end": "2024-10-06"},
            {"period_key": "2024-W41", "period_start": "2024-10-07", "period_end": "2024-10-13"},
        ]:
            store.upsert_summary({
                "period_type": "week",
                "period_key": rec["period_key"],
                "period_start": rec["period_start"],
                "period_end": rec["period_end"],
                "generated_at": "2024-10-01T22:00:00",
                "summary": f"Week {rec['period_key']}",
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

    summerize_month.summarize_month(target_date)

    # Check SQLite output
    conn = memory.get_db_connection()
    try:
        row = store.get_summary_by_period("month", "2024-10", conn=conn)
        assert row is not None
        assert row["summary"] == "Monthly summary test"
        assert row["keywords"] == ["Python", "Obsidian"]
        assert row["mood"] is None
        assert row["sleep_hours"] is None
    finally:
        conn.close()

    # Check Markdown output
    note_path = config.DAILY_PATH / "2024" / "10" / "2024-10.md"
    assert note_path.exists()
    content = note_path.read_text()
    assert "## AIによる要約" in content
    assert "Monthly summary test" in content
    assert "Progress 1" in content
    assert "Pattern 1" in content


@patch("obsidian_ai_hub.summerize_month.prompt.render_prompt")
@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_get_monthly_structured_record_passes_candidates_and_normalizes_topics(mock_llm, mock_render, mock_config):
    target_date = datetime(2024, 10, 1)
    mock_render.return_value = "Rendered Prompt"

    # LLM returns topics with mixed valid, duplicates, and out-of-candidates
    mock_llm.return_value = json.dumps({
        "summary": "Monthly summary test",
        "topics": ["LLM・AI活用", "未知のトピック", "LLM・AI活用"]
    })

    record = summerize_month.get_monthly_structured_record(target_date, [])

    # Check render_prompt is called with TOPIC_CANDIDATES
    mock_render.assert_called_once()
    context = mock_render.call_args[0][1]
    assert "TOPIC_CANDIDATES" in context
    candidates = json.loads(context["TOPIC_CANDIDATES"])
    assert "LLM・AI活用" in candidates
    assert "その他" in candidates

    # Check parsed and normalized topics in record
    assert record["topics"] == ["LLM・AI活用", "その他"]
