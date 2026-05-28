from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import patch

if "EventKit" not in sys.modules:
    mock_eventkit = ModuleType("EventKit")
    mock_eventkit.EKEventStore = type("EKEventStore", (), {})
    mock_eventkit.EKEntityTypeEvent = object()
    mock_eventkit.EKAuthorizationStatusAuthorized = 1
    mock_eventkit.EKAuthorizationStatusNotDetermined = 2
    sys.modules["EventKit"] = mock_eventkit

if "Foundation" not in sys.modules:
    mock_foundation = ModuleType("Foundation")
    mock_foundation.NSRunLoop = object()
    mock_foundation.NSDate = object()
    sys.modules["Foundation"] = mock_foundation

if "whisper" not in sys.modules:
    mock_whisper = ModuleType("whisper")
    mock_whisper.load_model = lambda *args, **kwargs: None
    sys.modules["whisper"] = mock_whisper

if "md_hybrid_search" not in sys.modules:
    mock_mdhs = ModuleType("md_hybrid_search")
    mock_mdhs.ConfigMismatchError = type("ConfigMismatchError", (Exception,), {})
    mock_mdhs.DirectorySource = type("DirectorySource", (), {})
    mock_mdhs.SearchIndex = type("SearchIndex", (), {})
    sys.modules["md_hybrid_search"] = mock_mdhs

from obsidian_ai_hub import main as main_module


def test_research_agent_cli_accepts_theme_for_on_demand_mode(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--research-agent", "--theme", "topic"])

    with (
        patch.object(main_module.research_agent, "main", return_value=None) as mock_main,
        patch.object(main_module.add_research_theme, "main", return_value=None) as mock_add,
    ):
        main_module.main()

    mock_main.assert_called_once_with("topic")
    mock_add.assert_not_called()


def test_research_agent_cli_uses_queue_mode_without_theme(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--research-agent"])

    with patch.object(main_module.research_agent, "main", return_value=None) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with()


def test_screenshot_cli_calls_screenshot_with_default_display(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--screenshot"])

    with patch.object(main_module.take_screenshot, "main", return_value=None) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with(1)


def test_screenshot_cli_calls_screenshot_with_custom_display(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--screenshot", "--display", "2"])

    with patch.object(main_module.take_screenshot, "main", return_value=None) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with(2)


def test_screenshot_cli_composable_with_other_flags(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--screenshot", "--sync-vault"])

    with (
        patch.object(main_module.take_screenshot, "main", return_value=None) as mock_screenshot,
        patch.object(main_module.sync_valut, "main", return_value=None) as mock_sync
    ):
        main_module.main()

    mock_screenshot.assert_called_once_with(1)
    mock_sync.assert_called_once_with()


def test_suggest_research_theme_cli_calls_suggester(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--suggest-research-theme"])

    with patch.object(main_module.suggest_research_theme, "main", return_value=[]) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with()


def test_sync_vault_cli_calls_sync(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--sync-vault"])

    with patch.object(main_module.sync_valut, "main", return_value=None) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with()
