from __future__ import annotations

import sys
from unittest.mock import patch

from obsidian_ai_hub import main as main_module


def test_research_agent_cli_accepts_theme_for_on_demand_mode(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--research-agent", "--theme", "topic"])

    with (
        patch.object(
            main_module.research_agent, "main", return_value=None
        ) as mock_main,
    ):
        main_module.main()

    mock_main.assert_called_once_with("topic")


def test_research_agent_cli_requires_theme(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--research-agent"])

    with patch("argparse.ArgumentParser.error") as mock_error:
        mock_error.side_effect = SystemExit
        with patch.object(sys, "exit"):
            try:
                main_module.main()
            except SystemExit:
                pass
        mock_error.assert_called_once()
        assert "--research-agent requires --theme" in mock_error.call_args[0][0]


def test_vault_search_cli_calls_search(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--vault-search",
            "--query",
            "test",
            "--k",
            "5",
            "--search-mode",
            "similarity",
        ],
    )

    with patch.object(
        main_module.search_obsidian_vault, "main", return_value=None
    ) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with(
        query="test", k=5, search_mode="similarity", json_output=False
    )


def test_vault_search_cli_calls_search_with_json(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["prog", "--vault-search", "--query", "test", "--json"]
    )

    with patch.object(
        main_module.search_obsidian_vault, "main", return_value=None
    ) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with(
        query="test", k=10, search_mode="hybrid", json_output=True
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

    with patch.object(
        main_module.scan_line_inbox, "main", return_value={}
    ) as mock_main:
        main_module.main()

    mock_main.assert_called_once()


def test_screenshot_cli_calls_screenshot_with_default_display(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--screenshot"])

    with patch.object(
        main_module.take_screenshot, "main", return_value=None
    ) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with(1)


def test_screenshot_cli_calls_screenshot_with_custom_display(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--screenshot", "--display", "2"])

    with patch.object(
        main_module.take_screenshot, "main", return_value=None
    ) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with(2)


def test_summerize_week_cli_accepts_week_date(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["prog", "--summerize-week", "--week-date", "2026-06-15"]
    )

    with patch.object(
        main_module.summerize_week, "main", return_value=None
    ) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with("2026-06-15")


def test_review_draft_cli_accepts_review_week_date(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["prog", "--review-draft", "--review-week-date", "2026-07-12"]
    )

    with patch.object(main_module.review_draft, "main", return_value=None) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with("2026-07-12")


def test_screenshot_cli_composable_with_other_flags(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--screenshot", "--sync-vault"])

    with (
        patch.object(
            main_module.take_screenshot, "main", return_value=None
        ) as mock_screenshot,
        patch.object(main_module.sync_valut, "main", return_value=None) as mock_sync,
    ):
        main_module.main()

    mock_screenshot.assert_called_once_with(1)
    mock_sync.assert_called_once_with()


def test_suggest_research_theme_cli_calls_suggester(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--suggest-research-theme"])

    with patch.object(
        main_module.suggest_research_theme, "main", return_value=[]
    ) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with()


def test_add_research_theme_cli_calls_handler(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["prog", "--add-research-theme", "--theme", "test theme"]
    )

    with patch.object(
        main_module.add_research_theme, "main", return_value="candidate"
    ) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with("test theme", direction=None)


def test_add_research_theme_with_direction(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--add-research-theme", "--theme", "test", "--direction", "方向"],
    )

    with patch.object(
        main_module.add_research_theme, "main", return_value="candidate"
    ) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with("test", direction="方向")


def test_sync_vault_cli_calls_sync(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--sync-vault"])

    with patch.object(main_module.sync_valut, "main", return_value=None) as mock_main:
        main_module.main()

    mock_main.assert_called_once_with()


def test_debug_alone_does_not_raise_or_start_server(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--debug"])

    with patch("argparse.ArgumentParser.print_help") as mock_help:
        main_module.main()

    mock_help.assert_called_once()


def test_serve_without_debug_uses_no_reload_info_log(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--serve"])

    with (
        patch("uvicorn.run") as mock_uvicorn,
        patch("obsidian_ai_hub.web.app.create_app"),
    ):
        main_module.main()

    mock_uvicorn.assert_called_once()
    kwargs = mock_uvicorn.call_args[1]
    assert kwargs.get("log_level") == "info"
    assert kwargs.get("reload") is None or kwargs.get("reload") is False


def test_serve_with_debug_uses_reload_and_debug_log(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "--serve", "--debug"])

    with patch("uvicorn.run") as mock_uvicorn:
        main_module.main()

    mock_uvicorn.assert_called_once()
    args, kwargs = mock_uvicorn.call_args
    assert args[0] == "obsidian_ai_hub.web.app:create_app"
    assert kwargs.get("log_level") == "debug"
    assert kwargs.get("reload") is True
    assert kwargs.get("factory") is True
