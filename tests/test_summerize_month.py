import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
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

from obsidian_ai_hub import summerize_month
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
    path = summerize_month.reader.get_monthly_note_path(dt)
    assert path.relative_to(config.DAILY_PATH) == Path("2024/10/2024-10.md")

def test_load_weekly_records(mock_config):
    year = "2024"
    log_dir = config.ACTIVITY_PATH / year
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{year}-week.jsonl"

    records = [
        {"week_id": "2024-W40", "week_start_date": "2024-09-30", "week_end_date": "2024-10-06"},
        {"week_id": "2024-W41", "week_start_date": "2024-10-07", "week_end_date": "2024-10-13"},
        {"week_id": "2024-W44", "week_start_date": "2024-10-28", "week_end_date": "2024-11-03"},
        {"week_id": "2024-W45", "week_start_date": "2024-11-04", "week_end_date": "2024-11-10"},
    ]

    with open(log_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    # Test for October
    oct_dt = datetime(2024, 10, 1)
    loaded = summerize_month.load_weekly_records(oct_dt)
    assert len(loaded) == 3
    assert loaded[0]["week_id"] == "2024-W40"
    assert loaded[1]["week_id"] == "2024-W41"
    assert loaded[2]["week_id"] == "2024-W44"

@patch("obsidian_ai_hub.utils.llm_client.generate_llm_response")
def test_summarize_month(mock_llm, mock_config):
    mock_llm.return_value = json.dumps({
        "summary": "Monthly summary test",
        "topics": ["Topic 1"],
        "activities": ["Activity 1"],
        "learnings": ["Learning 1"],
        "reflections": ["Reflection 1"],
        "gratitude": ["Gratitude 1"],
        "people": [{"name": "Person 1", "note": "Note 1"}],
        "questions": ["Question 1"],
        "keywords": ["Keyword 1"],
        "next_actions": ["Next Action 1"],
        "mood": "Good",
        "sleep": "7h"
    })

    target_date = datetime(2024, 10, 1)
    summerize_month.summarize_month(target_date)

    # Check JSONL output
    log_file = config.ACTIVITY_PATH / "2024" / "2024.jsonl"
    assert log_file.exists()
    with open(log_file, "r") as f:
        data = json.loads(f.read())
        assert data["month"] == "2024-10"
        assert data["summary"] == "Monthly summary test"

    # Check Markdown output
    note_path = config.DAILY_PATH / "2024" / "10" / "2024-10.md"
    assert note_path.exists()
    content = note_path.read_text()
    assert "## AIによる要約" in content
    assert "Monthly summary test" in content
    assert "Topic 1" in content
