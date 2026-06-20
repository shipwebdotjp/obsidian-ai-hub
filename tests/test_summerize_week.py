import json
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

# Mock modules that might be missing in the environment
mock_modules = [
    "dotenv",
    "md_hybrid_search",
    "AppKit",
    "objc",
    "EventKit",
    "sentence_transformers",
    "torch",
    "transformers",
    "langchain",
    "langchain_openai",
    "langchain_community",
    "langchain_google_genai",
    "langchain_anthropic",
    "langchain_core",
    "langchain_core.messages",
    "langchain_core.tools",
    "yaml",
]
for module_name in mock_modules:
    sys.modules[module_name] = MagicMock()

from obsidian_ai_hub.summerize_week import (
    get_week_dates,
    load_daily_record,
    get_weekly_structured_record,
    format_weekly_record_as_markdown,
    upsert_weekly_record,
    summarize_week
)

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

def test_load_daily_record(mock_config):
    target_date = datetime(2023, 10, 27)
    monthly_dir = mock_config.ACTIVITY_PATH / "2023/10"
    monthly_dir.mkdir(parents=True)
    log_file = monthly_dir / "2023-10.jsonl"

    record = {"date": "2023-10-27", "summary": "Day 27"}
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"date": "2023-10-26", "summary": "Day 26"}) + "\n")
        f.write(json.dumps(record) + "\n")

    loaded = load_daily_record(target_date)
    assert loaded == record

def test_upsert_weekly_record(mock_config):
    iso_year = 2023
    weekly_dir = mock_config.ACTIVITY_PATH / "2023"
    weekly_dir.mkdir(parents=True)
    log_file = weekly_dir / "2023-week.jsonl"

    record1 = {"week_id": "2023-W42", "summary": "Week 42"}
    record2 = {"week_id": "2023-W43", "summary": "Week 43"}

    # 1. New file
    upsert_weekly_record(iso_year, record2)
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").splitlines()
    assert len(content) == 1
    assert json.loads(content[0])["week_id"] == "2023-W43"

    # 2. Add another week (should be sorted)
    upsert_weekly_record(iso_year, record1)
    content = log_file.read_text(encoding="utf-8").splitlines()
    assert len(content) == 2
    assert json.loads(content[0])["week_id"] == "2023-W42"
    assert json.loads(content[1])["week_id"] == "2023-W43"

@patch("obsidian_ai_hub.summerize_week.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_week.llm_client.generate_llm_response")
def test_get_weekly_structured_record(mock_llm, mock_render, mock_config):
    target_date = datetime(2023, 10, 27) # W43
    mock_render.return_value = "Rendered Prompt"
    mock_llm.return_value = json.dumps({
        "summary": "AI Weekly Summary",
        "topics": ["Work"],
        "mood": "Stable",
        "people": [{"name": "Bob", "note": "Partner"}]
    })

    daily_records = [{"summary": "Day 1"}] + [None]*6
    record = get_weekly_structured_record(target_date, daily_records)

    assert record["week_id"] == "2023-W43"
    assert record["summary"] == "AI Weekly Summary"
    assert record["mood"] == "Stable"
    assert record["source_stats"]["daily_record_count"] == 1
    assert record["people"][0]["name"] == "Bob"

@patch("obsidian_ai_hub.summerize_week.prompt.render_prompt")
@patch("obsidian_ai_hub.summerize_week.llm_client.generate_llm_response")
def test_get_weekly_structured_record_malformed_json(mock_llm, mock_render, mock_config):
    target_date = datetime(2023, 10, 27)
    mock_render.return_value = "Rendered Prompt"
    mock_llm.return_value = "```json\nINVALID\n```"

    record = get_weekly_structured_record(target_date, [])

    assert record["week_id"] == "2023-W43"
    assert record["summary"] is None
    assert record["topics"] == []

def test_format_weekly_record_as_markdown():
    record = {
        "summary": "Great week.",
        "topics": ["AI"],
        "mood": "Energetic",
        "sleep": "Good",
        "people": [{"name": "Charlie", "note": "Met"}]
    }
    md = format_weekly_record_as_markdown(record)
    assert "Great week." in md
    assert "### トピックス" in md
    assert "- AI" in md
    assert "### 気分・エネルギー\nEnergetic" in md
    assert "### 睡眠・疲労\nGood" in md
    assert "### 人物メモ" in md
    assert "- **Charlie**: Met" in md

@patch("obsidian_ai_hub.summerize_week.get_weekly_structured_record")
@patch("obsidian_ai_hub.summerize_week.reader.get_weekly_note_content")
@patch("obsidian_ai_hub.summerize_week.reader.get_weekly_note_path")
def test_summarize_week(mock_path, mock_content, mock_gen, mock_config):
    target_date = datetime(2023, 10, 27)
    mock_gen.return_value = {
        "week_id": "2023-W43",
        "summary": "Weekly Summary",
        "topics": ["AI"]
    }
    mock_content.return_value = "## Previous Section\n\n## AIによる要約\nOld content\n\n## Next Section"
    weekly_note_file = mock_config.DAILY_PATH / "2023/10/2023-W43.md"
    weekly_note_file.parent.mkdir(parents=True)
    mock_path.return_value = weekly_note_file

    with patch("obsidian_ai_hub.summerize_week.load_daily_record", return_value=None):
         summarize_week(target_date)

    assert weekly_note_file.exists()
    new_content = weekly_note_file.read_text(encoding="utf-8")
    assert "Weekly Summary" in new_content
    assert "Old content" not in new_content
    assert "## Previous Section" in new_content
    assert "## Next Section" in new_content
