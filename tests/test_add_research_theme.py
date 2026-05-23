from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from obsidian_ai_hub.handler import add_research_theme


def test_append_research_theme_creates_candidate_item(tmp_path: Path):
    candidate_path = tmp_path / "リサーチ候補テーマリスト.md"

    with patch.object(add_research_theme.config, "RESEARCH_CANDIDATE_THEME_LIST_PATH", candidate_path):
        result_path = add_research_theme.append_research_theme("新しいテーマ")

    assert result_path == candidate_path
    assert candidate_path.read_text(encoding="utf-8") == "- [ ] 新しいテーマ\n"


def test_append_research_theme_preserves_existing_content(tmp_path: Path):
    candidate_path = tmp_path / "リサーチ候補テーマリスト.md"
    candidate_path.write_text("- [ ] 既存テーマ", encoding="utf-8")

    with patch.object(add_research_theme.config, "RESEARCH_CANDIDATE_THEME_LIST_PATH", candidate_path):
        add_research_theme.append_research_theme("追加テーマ")

    assert candidate_path.read_text(encoding="utf-8") == "- [ ] 既存テーマ\n- [ ] 追加テーマ\n"


def test_append_research_theme_rejects_empty_theme():
    with pytest.raises(ValueError):
        add_research_theme.append_research_theme("   ")


def test_append_research_theme_removes_newlines(tmp_path: Path):
    candidate_path = tmp_path / "リサーチ候補テーマリスト.md"

    with patch.object(add_research_theme.config, "RESEARCH_CANDIDATE_THEME_LIST_PATH", candidate_path):
        add_research_theme.append_research_theme("  新しい\nテーマ\r\n")

    assert candidate_path.read_text(encoding="utf-8") == "- [ ] 新しいテーマ\n"


def test_append_research_theme_can_store_direction(tmp_path: Path):
    candidate_path = tmp_path / "リサーチ候補テーマリスト.md"

    with patch.object(add_research_theme.config, "RESEARCH_CANDIDATE_THEME_LIST_PATH", candidate_path):
        add_research_theme.append_research_theme("テーマ", direction="調査方向")

    assert candidate_path.read_text(encoding="utf-8") == "- [ ] テーマ / 調査方向\n"
