from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from obsidian_ai_hub import obsidian_inbox_merge

def test_extract_urls():
    text = "Check this out: https://example.com/page. Also https://test.org/path, and (https://nested.com/)."
    urls = obsidian_inbox_merge.extract_urls(text)
    assert urls == [
        "https://example.com/page",
        "https://test.org/path",
        "https://nested.com/"
    ]

def test_extract_urls_deduplication():
    text = "https://example.com https://example.com https://example.com/other"
    urls = obsidian_inbox_merge.extract_urls(text)
    assert urls == ["https://example.com", "https://example.com/other"]

def test_infer_title():
    raw_content = "\n\n  \nMy Page Title\nSome description here."
    title = obsidian_inbox_merge.infer_title("https://example.com", raw_content)
    assert title == "My Page Title"

def test_infer_title_fallback():
    title = obsidian_inbox_merge.infer_title("https://example.com/some/path", "")
    assert title == "example.com/some/path"

def test_infer_title_long():
    long_title = "A" * 150
    title = obsidian_inbox_merge.infer_title("https://example.com", long_title)
    assert len(title) == 100
    assert title.endswith("...")

def test_merge_content_with_web_clip(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    content = "Check this: https://example.com"

    mock_extract_result = json.dumps([
        {"url": "https://example.com", "raw_content": "Page Title\nContent here."}
    ])

    with (
        patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()),
        patch.object(obsidian_inbox_merge.llm_client, "generate_llm_response", return_value="Summary text.")
    ):
        obsidian_inbox_merge.web_extract.web_extract.invoke = MagicMock(return_value=mock_extract_result)
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            content, daily_file, "10:30"
        )

    assert result == "web"
    note_content = daily_file.read_text(encoding="utf-8")
    assert "- 10:30 [web] [Page Title](https://example.com)" in note_content
    assert "  Summary text." in note_content

def test_merge_content_with_web_clip_multiple_urls(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    content = "https://a.com and https://b.com"

    mock_extract_result = json.dumps([
        {"url": "https://a.com", "raw_content": "Title A\nContent A"},
        {"url": "https://b.com", "raw_content": "Title B\nContent B"}
    ])

    with (
        patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()),
        patch.object(obsidian_inbox_merge.llm_client, "generate_llm_response", side_effect=["Summary A", "Summary B"])
    ):
        obsidian_inbox_merge.web_extract.web_extract.invoke = MagicMock(return_value=mock_extract_result)
        obsidian_inbox_merge.merge_content_into_daily_note(content, daily_file, "11:00")

    note_content = daily_file.read_text(encoding="utf-8")
    assert "- 11:00 [web] [Title A](https://a.com)" in note_content
    assert "  Summary A" in note_content
    assert "- 11:00 [web] [Title B](https://b.com)" in note_content
    assert "  Summary B" in note_content

def test_merge_content_with_web_clip_failure_fallback(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    content = "https://fail.com"

    with patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()):
        obsidian_inbox_merge.web_extract.web_extract.invoke = MagicMock(side_effect=Exception("API Error"))
        obsidian_inbox_merge.merge_content_into_daily_note(content, daily_file, "12:00")

    note_content = daily_file.read_text(encoding="utf-8")
    assert "- 12:00 [web] https://fail.com" in note_content

def test_non_web_content_still_works(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")

    content = "Just a plain memo without URLs"

    with (
        patch.object(obsidian_inbox_merge, "classify_inbox_content", return_value=obsidian_inbox_merge.InboxClassification(category="memo")),
        patch.object(obsidian_inbox_merge.extracter, "append_to_subheader_file") as mock_append
    ):
        result = obsidian_inbox_merge.merge_content_into_daily_note(content, daily_file, "13:00")

    assert result == "memo"
    mock_append.assert_called_once_with(daily_file.as_posix(), "## 📝メモ", ["- 13:00 [memo] Just a plain memo without URLs"])
