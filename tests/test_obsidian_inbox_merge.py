from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub import obsidian_inbox_merge


def test_merge_content_into_daily_note_completes_successfully(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    with (
        patch.object(
            obsidian_inbox_merge.llm_client,
            "generate_llm_response",
            return_value='{"category":"memo"}',
        ),
        patch.object(obsidian_inbox_merge.add_research_theme, "append_research_theme") as mock_append,
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            "some content", daily_file, "08:30"
        )

    assert result is not None
    assert "some content" in daily_file.read_text(encoding="utf-8")


def test_merge_content_with_location_completes_successfully(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📍今日の移動\n", encoding="utf-8")
    content = "---\nlocation: home\n---\nmoving"

    with patch.object(obsidian_inbox_merge.config, "LOCATION_MAP", {"home": "Home"}, create=True):
        result = obsidian_inbox_merge.merge_content_into_daily_note(content, daily_file, "07:45")

    assert result == "location"
    assert "07:45" in daily_file.read_text(encoding="utf-8")
    assert "Home" in daily_file.read_text(encoding="utf-8")
