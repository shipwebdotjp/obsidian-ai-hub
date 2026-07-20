from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from obsidian_ai_hub.handler import add_research_theme


def test_append_research_theme_creates_candidate_in_db():
    with patch("obsidian_ai_hub.research.runner.run_theme_research") as mock_research:
        result = add_research_theme.append_research_theme("新しいテーマ")
    assert result == "candidate"
    mock_research.assert_called_once()


def test_append_research_theme_with_direction():
    with patch("obsidian_ai_hub.research.runner.run_theme_research") as mock_research:
        result = add_research_theme.append_research_theme(
            "テーマ", direction="調査方向"
        )
    assert result == "candidate"
    mock_research.assert_called_once()


def test_append_research_theme_rejects_empty_theme():
    with pytest.raises(ValueError):
        add_research_theme.append_research_theme("   ")


def test_append_research_theme_removes_newlines():
    with patch("obsidian_ai_hub.research.runner.run_theme_research") as mock_research:
        add_research_theme.append_research_theme("  新しい\nテーマ\r\n")
    mock_research.assert_called_once()


def test_append_research_theme_handles_duplicate():
    with patch("obsidian_ai_hub.research.runner.run_theme_research") as mock_research:
        result1 = add_research_theme.append_research_theme("重複テスト")
        assert result1 == "candidate"
        mock_research.assert_called_once()

    mock_research.reset_mock()

    with patch("obsidian_ai_hub.research.runner.run_theme_research") as mock_research:
        result2 = add_research_theme.append_research_theme("重複テスト")
        assert result2 == "duplicate"
        mock_research.assert_not_called()


def test_append_research_theme_approves_after_successful_vault_save():
    result = {
        "status": "candidate",
        "theme_id": "theme_success",
        "job": {"status": "succeeded"},
    }
    with (
        patch(
            "obsidian_ai_hub.research.pipeline.create_theme_and_research",
            return_value=result,
        ),
        patch(
            "obsidian_ai_hub.research.runner.save_research_to_vault",
            return_value=Path("/tmp/research.md"),
        ),
        patch("obsidian_ai_hub.research.db.set_status") as mock_set_status,
    ):
        status = add_research_theme.append_research_theme("保存成功テーマ")

    assert status == "candidate"
    mock_set_status.assert_called_once_with(
        "theme_success", "approved", reviewed_by="system"
    )


def test_append_research_theme_keeps_candidate_when_vault_save_returns_none():
    result = {
        "status": "candidate",
        "theme_id": "theme_unsaved",
        "job": {"status": "succeeded"},
    }
    with (
        patch(
            "obsidian_ai_hub.research.pipeline.create_theme_and_research",
            return_value=result,
        ),
        patch(
            "obsidian_ai_hub.research.runner.save_research_to_vault",
            return_value=None,
        ),
        patch("obsidian_ai_hub.research.db.set_status") as mock_set_status,
    ):
        status = add_research_theme.append_research_theme("保存未完了テーマ")

    assert status == "candidate"
    mock_set_status.assert_not_called()
