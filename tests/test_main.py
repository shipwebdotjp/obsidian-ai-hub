from __future__ import annotations

import sys
from unittest.mock import patch

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
