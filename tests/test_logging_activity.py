import json
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from obsidian_ai_hub.logging_activity import main


@pytest.fixture
def mock_dependencies():
    with (
        patch("obsidian_ai_hub.logging_activity.accessibility") as mock_acc,
        patch("obsidian_ai_hub.logging_activity.NSScreen") as mock_screen,
        patch("obsidian_ai_hub.logging_activity.capture_screen") as mock_capture,
        patch("obsidian_ai_hub.logging_activity.img2text") as mock_img2text,
        patch("obsidian_ai_hub.logging_activity.llm_client") as mock_llm,
        patch("obsidian_ai_hub.logging_activity.config") as mock_cfg,
        patch("obsidian_ai_hub.logging_activity.get_unique_path") as mock_unique,
        patch("obsidian_ai_hub.logging_activity.add_activity") as mock_add,
        patch(
            "obsidian_ai_hub.logging_activity.get_latest_activity_by_date"
        ) as mock_get_latest,
    ):
        mock_cfg.SCREENSHOT_PATH = Path("/tmp/screenshots")
        mock_cfg.MAKE_TODAY_TARGET_PROVIDER = "test_provider"
        mock_cfg.MAKE_TODAY_TARGET_MODEL = "test_model"

        mock_acc.get_active_window_info.return_value = {
            "app_name": "TestApp",
            "window_title": "TestTitle",
        }

        mock_screen_obj = MagicMock()
        mock_screen_obj.deviceDescription.return_value.objectForKey_.return_value = (
            "Display1"
        )
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
            "get_latest": mock_get_latest,
        }


def test_main_success_case_registers_to_sqlite(mock_dependencies):
    deps = mock_dependencies
    deps["llm"].generate_llm_response.return_value = json.dumps(
        {
            "summary": "開発をしていました",
            "category": "開発",
            "keywords": ["python", "test"],
        }
    )

    with patch("pathlib.Path.mkdir"):
        main()

    deps["add"].assert_called_once()
    kwargs = deps["add"].call_args[1]
    assert kwargs["app_name"] == "TestApp"


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

    deps["llm"].generate_llm_response.return_value = json.dumps(
        {"summary": "New activity", "category": "開発", "keywords": ["python"]}
    )

    with patch("pathlib.Path.mkdir"):
        main()

    deps["llm"].generate_llm_response.assert_called_once()
    deps["add"].assert_called_once()
