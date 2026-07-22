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
        patch(
            "obsidian_ai_hub.logging_activity.get_active_projects_for_prompt",
            return_value=[],
        ) as mock_get_projects,
    ):
        mock_cfg.SCREENSHOT_PATH = Path("/tmp/screenshots")
        mock_cfg.MAKE_TODAY_TARGET_PROVIDER = "test_provider"
        mock_cfg.MAKE_TODAY_TARGET_MODEL = "test_model"
        mock_cfg.ACTIVITY_CLASSIFICATION_PROMPT_PATH = Path("config/prompts/activity_classification.md")

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
            "get_projects": mock_get_projects,
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


def test_main_project_id_validation_cases(mock_dependencies):
    deps = mock_dependencies

    active_projects_mock = [
        {"id": 42, "display_name": "Proj A", "domain": "work", "keywords": []},
        {"id": 7, "display_name": "Proj B", "domain": "personal", "keywords": []},
    ]

    with patch(
        "obsidian_ai_hub.logging_activity.get_active_projects_for_prompt",
        return_value=active_projects_mock,
    ):
        # Case 1: Valid numeric project_id matching active projects
        deps["llm"].generate_llm_response.return_value = json.dumps(
            {
                "summary": "Proj A work",
                "category": "開発",
                "keywords": ["test"],
                "project_id": 42,
            }
        )
        with patch("pathlib.Path.mkdir"):
            main()
        kwargs1 = deps["add"].call_args[1]
        assert kwargs1["project_id"] == 42
        deps["add"].reset_mock()

        # Case 2: Valid string numerical project_id matching active projects
        deps["llm"].generate_llm_response.return_value = json.dumps(
            {
                "summary": "Proj B work",
                "category": "開発",
                "keywords": ["test"],
                "project_id": "7",
            }
        )
        with patch("pathlib.Path.mkdir"):
            main()
        kwargs2 = deps["add"].call_args[1]
        assert kwargs2["project_id"] == 7
        deps["add"].reset_mock()

        # Case 3: Invalid/Out of bounds project_id (e.g., 999)
        deps["llm"].generate_llm_response.return_value = json.dumps(
            {
                "summary": "Unknown project",
                "category": "開発",
                "keywords": ["test"],
                "project_id": 999,
            }
        )
        with patch("pathlib.Path.mkdir"):
            main()
        kwargs3 = deps["add"].call_args[1]
        assert kwargs3["project_id"] is None
        deps["add"].reset_mock()

        # Case 4: Non-integer string ("null" / "不明") or bool
        deps["llm"].generate_llm_response.return_value = json.dumps(
            {
                "summary": "Null project",
                "category": "開発",
                "keywords": ["test"],
                "project_id": "null",
            }
        )
        with patch("pathlib.Path.mkdir"):
            main()
        kwargs4 = deps["add"].call_args[1]
        assert kwargs4["project_id"] is None
        deps["add"].reset_mock()

        # Case 5: Boolean project_id (should be None)
        deps["llm"].generate_llm_response.return_value = json.dumps(
            {
                "summary": "Bool project",
                "category": "開発",
                "keywords": ["test"],
                "project_id": False,
            }
        )
        with patch("pathlib.Path.mkdir"):
            main()
        kwargs5 = deps["add"].call_args[1]
        assert kwargs5["project_id"] is None
        deps["add"].reset_mock()

        # Case 6: Non-integer float (should be None)
        deps["llm"].generate_llm_response.return_value = json.dumps(
            {
                "summary": "Float project",
                "category": "開発",
                "keywords": ["test"],
                "project_id": 42.7,
            }
        )
        with patch("pathlib.Path.mkdir"):
            main()
        kwargs6 = deps["add"].call_args[1]
        assert kwargs6["project_id"] is None
        deps["add"].reset_mock()
