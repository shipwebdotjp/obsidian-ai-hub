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
    get_daily_ai_summary,
    load_conversation_logs,
    upsert_monthly_record,
    get_daily_structured_record
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

@patch("obsidian_ai_hub.summerize_day.llm_client.generate_llm_response")
def test_get_daily_ai_summary(mock_llm, mock_config, tmp_path):
    target_date = datetime(2023, 10, 27)
    mock_llm.return_value = "AI Summary Result"

    # Mock conversation logs
    log_dir = mock_config.AI_LOG_PATH
    log_dir.mkdir(parents=True)
    conv_file = log_dir / "chat@20231027.json"
    conv_data = {"metadata": {"summary": "Chat Summary"}}
    conv_file.write_text(json.dumps(conv_data), encoding="utf-8")

    # Mock activity logs
    activity_dir = mock_config.ACTIVITY_PATH / "2023/10"
    activity_dir.mkdir(parents=True)
    act_file = activity_dir / "2023-10-27.jsonl"
    act_file.write_text(json.dumps({"app_name": "TestApp", "summary": "TestActivity"}), encoding="utf-8")

    result = get_daily_ai_summary(target_date, "Today's note content")

    assert result == "AI Summary Result"
    mock_llm.assert_called_once()
    args, kwargs = mock_llm.call_args
    prompt = kwargs["prompt"]
    assert "Today's note content" in prompt
    assert "TestApp" in prompt
    assert "Chat Summary" in prompt

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
        if key == "mood": return "Happy"
        if key == "sleep": return "8h"
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
