from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from obsidian_ai_hub import obsidian_inbox_merge
from obsidian_ai_hub.utils import config, webclip

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
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    webclip_dir = vault_dir / "webclip"
    webclip_dir.mkdir(parents=True, exist_ok=True)

    daily_file = vault_dir / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")
    content = "Check this: https://example.com"

    mock_extract_result = json.dumps(
        {
            "results": [
                {"url": "https://example.com", "raw_content": "Page Content here.", "title": "My Example Page"}
            ]
        }
    )

    llm_payload = {
        "published_at": "2026-05-08T12:00:00+09:00",
        "updated_at": "2026-05-08T15:00:00+09:00",
        "category": "ソフトウェア開発",
        "topics": ["ソフトウェア開発", "開発環境・DevOps"],
        "tags": ["python", "testing"],
        "summary": "This is a summary of the page.",
        "key_points": ["First bullet", "Second bullet"],
        "why_saved": "Interesting framework"
    }

    with (
        patch.object(config, "VAULT_PATH", vault_dir),
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
        patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()),
        patch.object(obsidian_inbox_merge.llm_client, "generate_llm_response", return_value=json.dumps(llm_payload)),
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
    # Check appended string
    expected_link = "- 10:30 [webclip] [[webclip/ソフトウェア開発/My Example Page]]"
    assert args[2][0] == expected_link

    # Check generated markdown webclip file
    saved_file = webclip_dir / "ソフトウェア開発" / "My Example Page.md"
    assert saved_file.exists()
    saved_content = saved_file.read_text(encoding="utf-8")
    assert "Page Content here." in saved_content

    # Parse frontmatter to verify fields
    parts = saved_content.split("---")
    assert len(parts) >= 3
    fm = yaml.safe_load(parts[1])
    assert fm["title"] == "My Example Page"
    assert fm["source_url"] == "https://example.com"
    assert fm["clipped_at"] == "2026-05-09T10:30:00+09:00"
    assert fm["published_at"] == "2026-05-08T12:00:00+09:00"
    assert fm["updated_at"] == "2026-05-08T15:00:00+09:00"
    assert fm["category"] == "ソフトウェア開発"
    assert fm["topics"] == ["ソフトウェア開発", "開発環境・DevOps"]
    assert fm["tags"] == ["python", "testing"]
    assert fm["summary"] == "This is a summary of the page."
    assert fm["key_points"] == ["First bullet", "Second bullet"]
    assert fm["why_saved"] == "Interesting framework"


def test_merge_content_with_web_clip_multiple_urls(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    webclip_dir = vault_dir / "webclip"
    webclip_dir.mkdir(parents=True, exist_ok=True)

    daily_file = vault_dir / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")
    content = "https://a.com and https://b.com"

    mock_extract_result = json.dumps(
        {
            "results": [
                {"url": "https://a.com", "raw_content": "Content A", "title": "Page A"},
                {"url": "https://b.com", "raw_content": "Content B", "title": "Page B"},
            ]
        }
    )

    llm_payload_a = {
        "published_at": None,
        "updated_at": None,
        "category": "クラウド・インフラ",
        "topics": ["クラウド・インフラ"],
        "tags": ["aws"],
        "summary": "Sum A",
        "key_points": ["Point A"],
        "why_saved": "Why A"
    }
    llm_payload_b = {
        "published_at": None,
        "updated_at": None,
        "category": "その他",
        "topics": ["その他"],
        "tags": ["misc"],
        "summary": "Sum B",
        "key_points": ["Point B"],
        "why_saved": "Why B"
    }

    with (
        patch.object(config, "VAULT_PATH", vault_dir),
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
        patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()),
        patch.object(obsidian_inbox_merge.llm_client, "generate_llm_response", side_effect=[json.dumps(llm_payload_a), json.dumps(llm_payload_b)]),
        patch.object(obsidian_inbox_merge.extracter, "append_to_subheader_file") as mock_append,
    ):
        obsidian_inbox_merge.web_extract.web_extract.invoke = MagicMock(return_value=mock_extract_result)
        result = obsidian_inbox_merge.merge_content_into_daily_note(content, daily_file, "11:00")

    assert result == "web"
    mock_append.assert_called_once()
    entries = mock_append.call_args.args[2]
    assert len(entries) == 2
    assert "- 11:00 [webclip] [[webclip/クラウド・インフラ/Page A]]" in entries
    assert "- 11:00 [webclip] [[webclip/その他/Page B]]" in entries

    # Check files exist
    assert (webclip_dir / "クラウド・インフラ" / "Page A.md").exists()
    assert (webclip_dir / "その他" / "Page B.md").exists()


def test_merge_content_with_web_clip_failure_fallback(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    webclip_dir = vault_dir / "webclip"
    webclip_dir.mkdir(parents=True, exist_ok=True)

    daily_file = vault_dir / "2026-05-09.md"
    daily_file.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")
    content = "https://fail.com"

    with (
        patch.object(config, "VAULT_PATH", vault_dir),
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
        patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()),
        patch.object(obsidian_inbox_merge.extracter, "append_to_subheader_file") as mock_append,
    ):
        obsidian_inbox_merge.web_extract.web_extract.invoke = MagicMock(side_effect=Exception("API Error"))
        result = obsidian_inbox_merge.merge_content_into_daily_note(content, daily_file, "12:00")

    assert result == "web"
    mock_append.assert_called_once()
    entries = mock_append.call_args.args[2]
    assert len(entries) == 1
    assert "- 12:00 [webclip] [[webclip/その他/fail.com]]" in entries[0]

    # Check fallback file is generated with correct frontmatter defaults
    fallback_file = webclip_dir / "その他" / "fail.com.md"
    assert fallback_file.exists()
    content_raw = fallback_file.read_text(encoding="utf-8")
    parts = content_raw.split("---")
    assert len(parts) >= 3
    fm = yaml.safe_load(parts[1])
    assert fm["title"] == "fail.com"
    assert fm["source_url"] == "https://fail.com"
    assert fm["category"] == "その他"
    assert fm["topics"] == []
    assert fm["tags"] == []
    assert fm["summary"] == ""
    assert fm["key_points"] == []
    assert fm["why_saved"] == ""


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


def test_topic_normalization_and_conflict_serial(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    webclip_dir = vault_dir / "webclip"
    webclip_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create a file to trigger serial serial-number naming conflict under fallback folder "その他"
    existing_dest_dir = webclip_dir / "その他"
    existing_dest_dir.mkdir(parents=True, exist_ok=True)
    existing_file = existing_dest_dir / "My Duplicate.md"
    existing_file.write_text("existing content", encoding="utf-8")

    # Call process_single_webclip with same title but different URL (no move, just new serial copy)
    with (
        patch.object(config, "VAULT_PATH", vault_dir),
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
    ):
        link = webclip.process_single_webclip(
            url="https://different-url.com",
            raw_content="Content stuff",
            extracted_title="My Duplicate",
            hour_str="14:00",
            daily_file=vault_dir / "2026-05-09.md",
            clipped_at_str="2026-05-09T14:00:00+09:00"
        )

    # Expected file should have "My Duplicate 2" name because of name collision with distinct URL
    assert "- 14:00 [webclip] [[webclip/その他/My Duplicate 2]]" in link
    new_file = webclip_dir / "その他" / "My Duplicate 2.md"
    assert new_file.exists()


def test_same_url_full_update_and_move(tmp_path: Path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    webclip_dir = vault_dir / "webclip"
    webclip_dir.mkdir(parents=True, exist_ok=True)

    # Pre-create a webclip with specific URL under category "健康・医療"
    old_cat_dir = webclip_dir / "健康・医療"
    old_cat_dir.mkdir(parents=True, exist_ok=True)
    old_file = old_cat_dir / "Target_Page.md"

    old_frontmatter = {
        "title": "Target Page",
        "source_url": "https://update-me.com",
        "clipped_at": "2026-05-08T10:00:00+09:00",
        "category": "健康・医療"
    }
    old_file.write_text(f"---\n{yaml.dump(old_frontmatter)}---\nold content", encoding="utf-8")

    # Re-import or patch config to point to webclip_dir
    with (
        patch.object(config, "VAULT_PATH", vault_dir),
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
        patch.object(obsidian_inbox_merge.llm_client, "generate_llm_response", return_value=json.dumps({
            "published_at": None,
            "updated_at": None,
            "category": "金融・投資",  # Change Category!
            "topics": ["金融・投資"],
            "tags": ["money"],
            "summary": "New text",
            "key_points": ["Point"],
            "why_saved": "Reason"
        }))
    ):
        print("WEBCLIP_PATH is:", config.WEBCLIP_PATH)
        print("Files in webclip_dir:")
        for p in webclip_dir.rglob("*"):
            print(" -", p)
        existing = webclip.find_existing_webclip_file("https://update-me.com")
        print("Found existing file as:", existing)

        link = webclip.process_single_webclip(
            url="https://update-me.com",
            raw_content="new body text",
            extracted_title="Target Page",
            hour_str="15:30",
            daily_file=vault_dir / "2026-05-09.md",
            clipped_at_str="2026-05-09T15:30:00+09:00"
        )

    # 1. Old file must be deleted (because category/path changed)
    assert not old_file.exists()

    # 2. New file must exist under new category folder
    new_file = webclip_dir / "金融・投資" / "Target Page.md"
    assert new_file.exists()

    new_content = new_file.read_text(encoding="utf-8")
    assert "new body text" in new_content
    assert "New text" in new_content

    # 3. Daily note link matches new location
    assert "- 15:30 [webclip] [[webclip/金融・投資/Target Page]]" in link
