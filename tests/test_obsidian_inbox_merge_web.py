from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


from obsidian_ai_hub import obsidian_inbox_merge
from obsidian_ai_hub.utils import config, webclip


def test_extract_urls():
    text = "Check this out: https://example.com/page. Also https://test.org/path, and (https://nested.com/)."
    urls = obsidian_inbox_merge.extract_urls(text)
    assert urls == [
        "https://example.com/page",
        "https://test.org/path",
        "https://nested.com/",
    ]


def test_extract_urls_deduplication():
    text = "https://example.com https://example.com https://example.com/other"
    urls = obsidian_inbox_merge.extract_urls(text)
    assert urls == ["https://example.com", "https://example.com/other"]


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
    # Mock LLM response to avoid any real network requests
    with (
        patch.object(config, "VAULT_PATH", vault_dir),
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
        patch.object(
            obsidian_inbox_merge.llm_client,
            "generate_llm_response",
            return_value=json.dumps({"category": "その他", "topics": ["その他"]}),
        ),
    ):
        link = webclip.process_single_webclip(
            url="https://different-url.com",
            raw_content="Content stuff",
            extracted_title="My Duplicate",
            hour_str="14:00",
            daily_file=vault_dir / "2026-05-09.md",
            clipped_at_str="2026-05-09T14:00:00+09:00",
        )

    # Smoke assertions
    assert "My Duplicate 2" in link
    new_file = webclip_dir / "その他" / "My Duplicate 2.md"
    assert new_file.exists()
