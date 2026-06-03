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

from obsidian_ai_hub.summerize_day import (
    load_activity_logs,
    load_conversation_logs,
    upsert_monthly_record,
    get_daily_structured_record,
    format_structured_record_as_markdown
)

@pytest.fixture
def mock_config(tmp_path):
    with patch("obsidian_ai_hub.summerize_day.config") as mock_cfg:
        mock_cfg.ACTIVITY_PATH = tmp_path / "activity"
        mock_cfg.AI_LOG_PATH = tmp_path / "ai_logs"
        yield mock_cfg

def test_load_activity_logs(mock_config, tmp_path):
    target_date = datetime(2023, 10, 27)
    activity_dir = mock_config.ACTIVITY_PATH / "2023/10"
    activity_dir.mkdir(parents=True)
    log_file = activity_dir / "2023-10-27.jsonl"

    records = [
        {"timestamp": "2023-10-27T10:00:00", "app_name": "App1", "window_title": "Title1", "summary": "Summary1", "extra": "data"},
        {"timestamp": "2023-10-27T11:00:00", "app_name": "App2", "window_title": "Title2", "summary": "Summary2"}
    ]

    with open(log_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
        f.write("invalid json\n")

    logs = load_activity_logs(target_date)

    assert len(logs) == 2
    assert logs[0]["app_name"] == "App1"
    assert "extra" not in logs[0]
    assert logs[1]["window_title"] == "Title2"
    # Check new fields defaults
    assert logs[0]["category"] == "その他"
    assert logs[0]["keywords"] == []

def test_load_activity_logs_no_file(mock_config):
    target_date = datetime(2023, 10, 27)
    logs = load_activity_logs(target_date)
    assert logs == []

def test_upsert_monthly_record(mock_config, tmp_path):
    target_date = datetime(2023, 10, 27)
    monthly_dir = mock_config.ACTIVITY_PATH / "2023/10"
    monthly_dir.mkdir(parents=True, exist_ok=True)
    log_file = monthly_dir / "2023-10.jsonl"

    record1 = {"date": "2023-10-26", "summary": "Day 26"}
    record2 = {"date": "2023-10-27", "summary": "Day 27"}

    # 1. New file
    upsert_monthly_record(target_date, record2)
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").splitlines()
    assert len(content) == 1
    assert json.loads(content[0])["date"] == "2023-10-27"

    # 2. Add another day (should be sorted)
    upsert_monthly_record(target_date, record1)
    content = log_file.read_text(encoding="utf-8").splitlines()
    assert len(content) == 2
    assert json.loads(content[0])["date"] == "2023-10-26"
    assert json.loads(content[1])["date"] == "2023-10-27"

    # 3. Update existing day
    record2_updated = {"date": "2023-10-27", "summary": "Day 27 Updated"}
    upsert_monthly_record(target_date, record2_updated)
    content = log_file.read_text(encoding="utf-8").splitlines()
    assert len(content) == 2
    assert json.loads(content[1])["summary"] == "Day 27 Updated"

@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record(mock_fm, mock_path, mock_llm, mock_config, tmp_path):
    target_date = datetime(2023, 10, 27)
    daily_content = "---\nmood: Happy\nsleep: 8h\n---\nContent"

    def fm_side_effect(text, key, default=None):
        if key == "mood":
            return "Happy"
        if key == "sleep":
            return "8h"
        return default
    mock_fm.side_effect = fm_side_effect

    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    mock_llm.return_value = json.dumps({
        "summary": "AI Structured Summary",
        "topics": ["AI"],
        "people": [{"name": "Alice", "note": "Researcher"}]
    })

    logs = [{"summary": "Session 1"}]
    activity_logs = [{"summary": "Activity 1"}, {"summary": "Activity 2"}]

    record = get_daily_structured_record(target_date, daily_content, logs, activity_logs)

    assert record["date"] == "2023-10-27"
    assert record["summary"] == "AI Structured Summary"
    assert record["mood"] == "Happy"
    assert record["sleep"] == "8h"
    assert record["source_stats"]["activity_count"] == 2
    assert record["source_stats"]["llm_session_count"] == 1
    assert record["source_stats"]["has_daily_note"] is True
    assert record["people"][0]["name"] == "Alice"

@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_malformed_json(mock_fm, mock_path, mock_llm, mock_config, tmp_path):
    target_date = datetime(2023, 10, 27)
    daily_content = "---\nmood: Happy\n---"

    mock_fm.return_value = "Happy"
    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    # LLM returns malformed JSON
    mock_llm.return_value = "This is not a JSON"

    logs = []
    activity_logs = [{"summary": "Act"}]

    record = get_daily_structured_record(target_date, daily_content, logs, activity_logs)

    # Should not raise and return minimal record
    assert record["date"] == "2023-10-27"
    assert record["summary"] is None
    assert record["mood"] == "Happy"
    assert record["source_stats"]["activity_count"] == 1
    assert record["topics"] == []
    assert record["people"] == []


def test_format_structured_record_as_markdown():
    record = {
        "summary": "Today was productive.",
        "topics": ["AI", "Python"],
        "activities": ["Coding", "Reading"],
        "people": [{"name": "Alice", "note": "Discussed AI"}],
        "keywords": ["LLM", "RAG"]
    }
    activity_logs = [
        {"category": "開発", "keywords": ["Python", "Git"]},
        {"category": "開発", "keywords": ["Python"]},
        {"category": "事務", "keywords": ["Email"]},
    ]

    markdown = format_structured_record_as_markdown(record, activity_logs)

    assert "Today was productive." in markdown
    assert "### トピックス" in markdown
    assert "- AI" in markdown
    assert "- Python" in markdown
    assert "### 活動内容" in markdown
    assert "- Coding" in markdown
    assert "### 人物メモ" in markdown
    assert "- **Alice**: Discussed AI" in markdown
    assert "### キーワード" in markdown
    assert "- LLM" in markdown
    assert "### カテゴリ順位" in markdown
    assert "- 開発: 2" in markdown
    assert "- 事務: 1" in markdown
    assert "### キーワード順位" in markdown
    assert "- Python: 2" in markdown


@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
@patch("obsidian_ai_hub.summerize_day.reader.get_daily_note_path")
@patch("obsidian_ai_hub.summerize_day.extracter.get_frontmatter_value")
def test_get_daily_structured_record_strips_milliseconds(mock_fm, mock_path, mock_llm, mock_config):
    target_date = datetime(2023, 10, 27)
    mock_llm.return_value = json.dumps({"summary": "Test Summary"})
    mock_p = MagicMock()
    mock_p.exists.return_value = True
    mock_path.return_value = mock_p

    activity_logs = [
        {"timestamp": "2023-10-27T10:00:00.123456", "summary": "Activity 1"}
    ]
    get_daily_structured_record(target_date, "content", [], activity_logs)

    args, kwargs = mock_llm.call_args
    prompt = kwargs["prompt"]
    assert "2023-10-27T10:00:00" in prompt
    assert "2023-10-27T10:00:00.123456" not in prompt
