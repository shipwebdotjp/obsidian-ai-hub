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
