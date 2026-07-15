from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from obsidian_ai_hub.handler import add_research_theme


def test_append_research_theme_creates_candidate_in_db():
    with patch("obsidian_ai_hub.research_agent.run_theme_research") as mock_research:
        result = add_research_theme.append_research_theme("新しいテーマ")
    assert result == "candidate"
    mock_research.assert_called_once()


def test_append_research_theme_with_direction():
    with patch("obsidian_ai_hub.research_agent.run_theme_research") as mock_research:
        result = add_research_theme.append_research_theme("テーマ", direction="調査方向")
    assert result == "candidate"
    mock_research.assert_called_once()


def test_append_research_theme_rejects_empty_theme():
    with pytest.raises(ValueError):
        add_research_theme.append_research_theme("   ")


def test_append_research_theme_removes_newlines():
    with patch("obsidian_ai_hub.research_agent.run_theme_research") as mock_research:
        add_research_theme.append_research_theme("  新しい\nテーマ\r\n")
    mock_research.assert_called_once()


def test_append_research_theme_handles_duplicate():
    with patch("obsidian_ai_hub.research_agent.run_theme_research") as mock_research:
        result1 = add_research_theme.append_research_theme("重複テスト")
        assert result1 == "candidate"
        mock_research.assert_called_once()

    mock_research.reset_mock()

    with patch("obsidian_ai_hub.research_agent.run_theme_research") as mock_research:
        result2 = add_research_theme.append_research_theme("重複テスト")
        assert result2 == "duplicate"
        mock_research.assert_not_called()
