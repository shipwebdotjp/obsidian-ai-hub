import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from obsidian_ai_hub.logging_activity import main, ACTIVITY_CATEGORIES

@pytest.fixture
def mock_dependencies():
    with patch("obsidian_ai_hub.logging_activity.accessibility") as mock_acc, \
         patch("obsidian_ai_hub.logging_activity.NSScreen") as mock_screen, \
         patch("obsidian_ai_hub.logging_activity.capture_screen") as mock_capture, \
         patch("obsidian_ai_hub.logging_activity.img2text") as mock_img2text, \
         patch("obsidian_ai_hub.logging_activity.llm_client") as mock_llm, \
         patch("obsidian_ai_hub.logging_activity.config") as mock_cfg, \
         patch("obsidian_ai_hub.logging_activity.get_unique_path") as mock_unique, \
         patch("obsidian_ai_hub.logging_activity.add_activity") as mock_add, \
         patch("obsidian_ai_hub.logging_activity.get_latest_activity_by_date") as mock_get_latest:

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

        mock_get_latest.return_value = None

        yield {
            "acc": mock_acc,
            "screen": mock_screen,
            "capture": mock_capture,
            "img2text": mock_img2text,
            "llm": mock_llm,
            "cfg": mock_cfg,
            "unique": mock_unique,
            "add": mock_add,
            "get_latest": mock_get_latest
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
    expected_json = {
        "summary": "開発をしていました",
        "category": "開発",
        "keywords": ["python", "test"]
    }
    deps["llm"].generate_llm_response.return_value = json.dumps(expected_json)

    with patch("pathlib.Path.mkdir"):
        main()

    deps["add"].assert_called_once()
    kwargs = deps["add"].call_args[1]

    assert kwargs["app_name"] == "TestApp"
    assert kwargs["summary"] == "開発をしていました"
    assert kwargs["category"] == "開発"
    assert kwargs["keywords"] == ["python", "test"]

def test_main_fallback_invalid_category(mock_dependencies):
    deps = mock_dependencies
    expected_json = {
        "summary": "Unknown activity",
        "category": "InvalidCategory",
        "keywords": ["unknown"]
    }
    deps["llm"].generate_llm_response.return_value = json.dumps(expected_json)

    with patch("pathlib.Path.mkdir"):
        main()

    deps["add"].assert_called_once()
    kwargs = deps["add"].call_args[1]

    assert kwargs["category"] == "その他"
    assert kwargs["summary"] == "Unknown activity"

def test_main_fallback_broken_json(mock_dependencies):
    deps = mock_dependencies
    deps["llm"].generate_llm_response.return_value = "This is not JSON"

    with patch("pathlib.Path.mkdir"):
        main()

    deps["add"].assert_called_once()
    kwargs = deps["add"].call_args[1]

    assert kwargs["category"] == "その他"
    assert kwargs["summary"] == "This is not JSON"

def test_main_fallback_json_markdown_block(mock_dependencies):
    deps = mock_dependencies
    json_content = {
        "summary": "Markdown summary",
        "category": "学習",
        "keywords": ["markdown"]
    }
    deps["llm"].generate_llm_response.return_value = f"```json\n{json.dumps(json_content)}\n```"

    with patch("pathlib.Path.mkdir"):
        main()

    deps["add"].assert_called_once()
    kwargs = deps["add"].call_args[1]

    assert kwargs["category"] == "学習"
    assert kwargs["summary"] == "Markdown summary"

def test_main_skip_duplicate(mock_dependencies):
    deps = mock_dependencies
    deps["get_latest"].return_value = {
        "app_name": "TestApp",
        "window_title": "TestTitle",
    }

    with patch("pathlib.Path.mkdir"):
        main()

    deps["llm"].generate_llm_response.assert_not_called()
    deps["add"].assert_not_called()

def test_main_no_skip_different_activity(mock_dependencies):
    deps = mock_dependencies
    deps["get_latest"].return_value = {
        "app_name": "DifferentApp",
        "window_title": "TestTitle",
    }

    expected_json = {
        "summary": "New activity",
        "category": "開発",
        "keywords": ["python"]
    }
    deps["llm"].generate_llm_response.return_value = json.dumps(expected_json)

    with patch("pathlib.Path.mkdir"):
        main()

    deps["llm"].generate_llm_response.assert_called_once()
    deps["add"].assert_called_once()
