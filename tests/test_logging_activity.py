import json
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import pytest

# Mock modules
mock_modules = [
    "dotenv",
    "AppKit",
    "objc",
    "yaml",
    "langchain_core",
    "langchain_core.messages",
    "langchain_core.tools",
    "obsidian_ai_hub.utils.accessibility",
    "obsidian_ai_hub.utils.img2text",
    "obsidian_ai_hub.utils.config",
]
for module_name in mock_modules:
    sys.modules[module_name] = MagicMock()

from obsidian_ai_hub.logging_activity import main, ACTIVITY_CATEGORIES

@pytest.fixture
def mock_dependencies():
    with patch("obsidian_ai_hub.logging_activity.accessibility") as mock_acc, \
         patch("obsidian_ai_hub.logging_activity.NSScreen") as mock_screen, \
         patch("obsidian_ai_hub.logging_activity.capture_screen") as mock_capture, \
         patch("obsidian_ai_hub.logging_activity.img2text") as mock_img2text, \
         patch("obsidian_ai_hub.logging_activity.llm_client") as mock_llm, \
         patch("obsidian_ai_hub.logging_activity.config") as mock_cfg, \
         patch("obsidian_ai_hub.logging_activity.get_unique_path") as mock_unique:

        mock_cfg.SCREENSHOT_PATH = Path("/tmp/screenshots")
        mock_cfg.ACTIVITY_PATH = Path("/tmp/activity")
        mock_cfg.MAKE_TODAY_TARGET_PROVIDER = "test_provider"
        mock_cfg.MAKE_TODAY_TARGET_MODEL = "test_model"

        mock_acc.get_active_window_info.return_value = {
            "app_name": "TestApp",
            "window_title": "TestTitle"
        }

        mock_screen_obj = MagicMock()
        mock_screen_obj.deviceDescription.return_value.objectForKey_.return_value = "Display1"
        mock_screen.screens.return_value = [mock_screen_obj]

        mock_unique.side_effect = lambda d, f: d / f

        mock_img2text.image_to_text.return_value = [("Sample Text", 0.9)]

        yield {
            "acc": mock_acc,
            "screen": mock_screen,
            "capture": mock_capture,
            "img2text": mock_img2text,
            "llm": mock_llm,
            "cfg": mock_cfg,
            "unique": mock_unique
        }

def test_main_uses_display_numbers_for_screenshots(mock_dependencies):
    deps = mock_dependencies

    screen_1 = MagicMock()
    screen_1.deviceDescription.return_value.objectForKey_.return_value = 1
    screen_2 = MagicMock()
    screen_2.deviceDescription.return_value.objectForKey_.return_value = 3
    deps["screen"].screens.return_value = [screen_1, screen_2]

    deps["llm"].generate_llm_response.return_value = json.dumps({
        "summary": "確認作業をしていました",
        "category": "事務・記録",
        "keywords": ["確認"]
    })

    fixed_now = datetime(2026, 6, 4, 10, 45, 44)
    with patch("obsidian_ai_hub.logging_activity.datetime") as mock_datetime, \
         patch("builtins.open", mock_open()), \
         patch("pathlib.Path.mkdir"):
        mock_datetime.now.return_value = fixed_now
        main()

    assert deps["capture"].call_count == 2
    first_call, second_call = deps["capture"].call_args_list

    assert first_call.kwargs["display"] == 1
    assert second_call.kwargs["display"] == 2
    assert str(first_call.args[0]).endswith("_1.png")
    assert str(second_call.args[0]).endswith("_2.png")

def test_main_success_case(mock_dependencies):
    deps = mock_dependencies
    # Mock LLM to return valid JSON
    expected_json = {
        "summary": "開発をしていました",
        "category": "開発",
        "keywords": ["python", "test"]
    }
    deps["llm"].generate_llm_response.return_value = json.dumps(expected_json)

    # Mock file writing
    m = mock_open()
    with patch("builtins.open", m), \
         patch("pathlib.Path.mkdir"):
        main()

    # Check if record contains expected fields
    handle = m()
    written_content = "".join(call.args[0] for call in handle.write.call_args_list)
    record = json.loads(written_content.strip())

    assert record["app_name"] == "TestApp"
    assert record["summary"] == "開発をしていました"
    assert record["category"] == "開発"
    assert record["keywords"] == ["python", "test"]

def test_main_fallback_invalid_category(mock_dependencies):
    deps = mock_dependencies
    # Mock LLM to return JSON with invalid category
    expected_json = {
        "summary": "Unknown activity",
        "category": "InvalidCategory",
        "keywords": ["unknown"]
    }
    deps["llm"].generate_llm_response.return_value = json.dumps(expected_json)

    m = mock_open()
    with patch("builtins.open", m), \
         patch("pathlib.Path.mkdir"):
        main()

    handle = m()
    written_content = "".join(call.args[0] for call in handle.write.call_args_list)
    record = json.loads(written_content.strip())

    assert record["category"] == "その他" # Fallback to default
    assert record["summary"] == "Unknown activity"

def test_main_fallback_broken_json(mock_dependencies):
    deps = mock_dependencies
    # Mock LLM to return broken JSON
    deps["llm"].generate_llm_response.return_value = "This is not JSON"

    m = mock_open()
    with patch("builtins.open", m), \
         patch("pathlib.Path.mkdir"):
        main()

    handle = m()
    written_content = "".join(call.args[0] for call in handle.write.call_args_list)
    record = json.loads(written_content.strip())

    assert record["category"] == "その他"
    # Should use the response text as summary if it's not a JSON-like string
    assert record["summary"] == "This is not JSON"

def test_main_fallback_json_markdown_block(mock_dependencies):
    deps = mock_dependencies
    # Mock LLM to return JSON in markdown block
    json_content = {
        "summary": "Markdown summary",
        "category": "学習",
        "keywords": ["markdown"]
    }
    deps["llm"].generate_llm_response.return_value = f"```json\n{json.dumps(json_content)}\n```"

    m = mock_open()
    with patch("builtins.open", m), \
         patch("pathlib.Path.mkdir"):
        main()

    handle = m()
    written_content = "".join(call.args[0] for call in handle.write.call_args_list)
    record = json.loads(written_content.strip())

    assert record["category"] == "学習"
    assert record["summary"] == "Markdown summary"

def test_main_skip_duplicate(mock_dependencies, tmp_path):
    deps = mock_dependencies
    deps["cfg"].ACTIVITY_PATH = tmp_path
    activity_dir = deps["cfg"].ACTIVITY_PATH / datetime.now().strftime("%Y/%m")
    activity_dir.mkdir(parents=True, exist_ok=True)
    log_file = activity_dir / datetime.now().strftime("%Y-%m-%d.jsonl")

    # Pre-populate log with same activity
    last_record = {
        "timestamp": "2023-10-27T10:00:00",
        "app_name": "TestApp",
        "window_title": "TestTitle",
        "summary": "Old summary",
        "category": "開発",
        "keywords": ["マルチバイトテスト"]
    }
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(last_record, ensure_ascii=False) + "\n")

    # Mock file writing to track calls
    m = mock_open()
    # We want it to read from the real mock file we just created, but skip writing if duplicate
    with patch("builtins.open", side_effect=open) as mock_file_open, \
         patch("pathlib.Path.mkdir"):
        main()

    # If skipped, generate_llm_response should not be called
    deps["llm"].generate_llm_response.assert_not_called()

def test_main_no_skip_different_activity(mock_dependencies, tmp_path):
    deps = mock_dependencies
    deps["cfg"].ACTIVITY_PATH = tmp_path
    activity_dir = deps["cfg"].ACTIVITY_PATH / datetime.now().strftime("%Y/%m")
    activity_dir.mkdir(parents=True, exist_ok=True)
    log_file = activity_dir / datetime.now().strftime("%Y-%m-%d.jsonl")

    # Pre-populate log with different activity
    last_record = {
        "timestamp": "2023-10-27T10:00:00",
        "app_name": "DifferentApp",
        "window_title": "TestTitle",
        "summary": "Old summary",
        "category": "開発",
        "keywords": ["マルチバイトテスト"]
    }
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(last_record, ensure_ascii=False) + "\n")

    expected_json = {
        "summary": "New activity",
        "category": "開発",
        "keywords": ["python"]
    }
    deps["llm"].generate_llm_response.return_value = json.dumps(expected_json)

    with patch("pathlib.Path.mkdir"):
        main()

    # Should NOT be skipped
    deps["llm"].generate_llm_response.assert_called_once()
