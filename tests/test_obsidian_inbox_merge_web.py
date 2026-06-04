from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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

def test_merge_content_with_web_clip(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    content = "Check this: https://example.com"

    mock_extract_result = json.dumps(
        {
            "results": [
                {"url": "https://example.com", "raw_content": "Page Title\nContent here."}
            ]
        }
    )

    with (
        patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()),
        patch.object(obsidian_inbox_merge.llm_client, "generate_llm_response", return_value="Summary text."),
        patch.object(obsidian_inbox_merge.extracter, "append_to_subheader_file") as mock_append,
    ):
        obsidian_inbox_merge.web_extract.web_extract.invoke = MagicMock(return_value=mock_extract_result)
        result = obsidian_inbox_merge.merge_content_into_daily_note(
            content, daily_file, "10:30"
        )

    assert result == "web"
    mock_append.assert_called_once()
    args = mock_append.call_args.args
    assert args[0] == daily_file.as_posix()
    assert args[1] == "## 📝メモ"
    assert len(args[2]) == 1
    assert "https://example.com" in args[2][0]

def test_merge_content_with_web_clip_multiple_urls(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    content = "https://a.com and https://b.com"

    mock_extract_result = json.dumps(
        {
            "results": [
                {"url": "https://a.com", "raw_content": "Title A\nContent A"},
                {"url": "https://b.com", "raw_content": "Title B\nContent B"},
            ]
        }
    )

    with (
        patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()),
        patch.object(obsidian_inbox_merge.llm_client, "generate_llm_response", side_effect=["Summary A", "Summary B"]),
        patch.object(obsidian_inbox_merge.extracter, "append_to_subheader_file") as mock_append,
    ):
        obsidian_inbox_merge.web_extract.web_extract.invoke = MagicMock(return_value=mock_extract_result)
        result = obsidian_inbox_merge.merge_content_into_daily_note(content, daily_file, "11:00")

    assert result == "web"
    mock_append.assert_called_once()
    entries = mock_append.call_args.args[2]
    assert len(entries) == 2
    assert any("https://a.com" in entry for entry in entries)
    assert any("https://b.com" in entry for entry in entries)

def test_merge_content_with_web_clip_failure_fallback(tmp_path: Path):
    daily_file = tmp_path / "2026-05-09.md"
    content = "https://fail.com"

    with (
        patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()),
        patch.object(obsidian_inbox_merge.extracter, "append_to_subheader_file") as mock_append,
    ):
        obsidian_inbox_merge.web_extract.web_extract.invoke = MagicMock(side_effect=Exception("API Error"))
        result = obsidian_inbox_merge.merge_content_into_daily_note(content, daily_file, "12:00")

    assert result == "web"
    mock_append.assert_called_once()
    entries = mock_append.call_args.args[2]
    assert len(entries) == 1
    assert "https://fail.com" in entries[0]

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
