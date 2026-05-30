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

from obsidian_ai_hub.summerize_day import load_activity_logs, get_daily_ai_summary, load_conversation_logs

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
    # Check new fields
    assert "category" in logs[0]
    assert "keywords" in logs[0]

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
