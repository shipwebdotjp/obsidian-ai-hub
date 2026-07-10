from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import patch, MagicMock

if "EventKit" not in sys.modules:
    mock_eventkit = ModuleType("EventKit")
    mock_eventkit.EKEventStore = type("EKEventStore", (), {})
    mock_eventkit.EKEntityTypeEvent = object()
    mock_eventkit.EKAuthorizationStatusAuthorized = 1
    mock_eventkit.EKAuthorizationStatusNotDetermined = 2
    sys.modules["EventKit"] = mock_eventkit

if "Foundation" not in sys.modules:
    mock_foundation = MagicMock()
    mock_foundation.NSRunLoop = object()
    mock_foundation.NSDate = object()
    mock_foundation.NSDictionary = MagicMock()
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

if "langchain" not in sys.modules:
    sys.modules["langchain"] = MagicMock()

if "langchain.tools" not in sys.modules:
    sys.modules["langchain.tools"] = MagicMock()

if "langchain_core" not in sys.modules:
    sys.modules["langchain_core"] = MagicMock()

if "langchain_core.messages" not in sys.modules:
    sys.modules["langchain_core.messages"] = MagicMock()

if "langchain_core.tools" not in sys.modules:
    sys.modules["langchain_core.tools"] = MagicMock()

if "langchain_openai" not in sys.modules:
    sys.modules["langchain_openai"] = MagicMock()

if "langchain_google_genai" not in sys.modules:
    sys.modules["langchain_google_genai"] = MagicMock()

if "langchain_ollama" not in sys.modules:
    sys.modules["langchain_ollama"] = MagicMock()

if "langchain_community" not in sys.modules:
    sys.modules["langchain_community"] = MagicMock()

if "langchain_community.chat_models" not in sys.modules:
    sys.modules["langchain_community.chat_models"] = MagicMock()

if "langchain_tavily" not in sys.modules:
    sys.modules["langchain_tavily"] = MagicMock()

if "torch" not in sys.modules:
    sys.modules["torch"] = MagicMock()

if "sentence_transformers" not in sys.modules:
    sys.modules["sentence_transformers"] = MagicMock()

if "transformers" not in sys.modules:
    sys.modules["transformers"] = MagicMock()

if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = MagicMock()

if "yaml" not in sys.modules:
    sys.modules["yaml"] = MagicMock()

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock()

if "PIL" not in sys.modules:
    sys.modules["PIL"] = MagicMock()

if "AppKit" not in sys.modules:
    sys.modules["AppKit"] = MagicMock()

if "objc" not in sys.modules:
    sys.modules["objc"] = MagicMock()

if "pydantic" not in sys.modules:
    sys.modules["pydantic"] = MagicMock()

if "ApplicationServices" not in sys.modules:
    sys.modules["ApplicationServices"] = MagicMock()

if "Quartz" not in sys.modules:
    sys.modules["Quartz"] = MagicMock()

if "Vision" not in sys.modules:
    sys.modules["Vision"] = MagicMock()

if "Cocoa" not in sys.modules:
    sys.modules["Cocoa"] = MagicMock()

if "wurlitzer" not in sys.modules:
    sys.modules["wurlitzer"] = MagicMock()

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


def test_vault_search_cli_calls_search(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--vault-search", "--query", "test", "--k", "5", "--search-mode", "similarity"])

    with patch.object(main_module.search_obsidian_vault, "main", return_value=None) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with(
        query="test",
        k=5,
        search_mode="similarity",
        json_output=False
    )


def test_vault_search_cli_calls_search_with_json(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--vault-search", "--query", "test", "--json"])

    with patch.object(main_module.search_obsidian_vault, "main", return_value=None) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with(
        query="test",
        k=10,
        search_mode="hybrid",
        json_output=True
    )


def test_vault_search_cli_requires_query(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--vault-search"])

    with patch("argparse.ArgumentParser.error") as mock_error:
        mock_error.side_effect = SystemExit
        with patch.object(sys, "exit"):
            try:
                main_module.main()
            except SystemExit:
                pass
        mock_error.assert_called_once()
        assert "--vault-search requires --query" in mock_error.call_args[0][0]


def test_query_requires_vault_search(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--query", "test"])

    with patch("argparse.ArgumentParser.error") as mock_error:
        mock_error.side_effect = SystemExit
        with patch.object(sys, "exit"):
            try:
                main_module.main()
            except SystemExit:
                pass
        mock_error.assert_called_once()
        assert "--query requires --vault-search" in mock_error.call_args[0][0]


def test_scan_line_inbox_cli_calls_scan(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--scan-line-inbox"])

    with patch.object(main_module.scan_line_inbox, "main", return_value={}) as mock_main:
        main_module.main()

    mock_main.assert_called_once()


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


def test_summerize_week_cli_accepts_week_date(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--summerize-week", "--week-date", "2026-06-15"])

    with patch.object(main_module.summerize_week, "main", return_value=None) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with("2026-06-15")


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


def test_build_dashboard_cli_calls_export(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--build-dashboard", "--dashboard-year", "2026"])

    with patch.object(main_module.dashboard, "build_dashboard", return_value=None) as mock_build:
        main_module.main()

    mock_build.assert_called_once_with([2026])
