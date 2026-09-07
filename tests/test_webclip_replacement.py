from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from obsidian_ai_hub.utils import config, webclip


def _make_existing_webclip(webclip_dir: Path, url: str) -> Path:
    existing = webclip_dir / "その他" / "Old Title.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(
        "---\n"
        f"title: Old Title\nsource_url: {url}\n"
        "clipped_at: 2026-07-15T10:30:00+09:00\n"
        "published_at: null\nupdated_at: null\ncategory: その他\n"
        "topics: []\ntags: []\nsummary: ''\nkey_points: []\nwhy_saved: 'keep me'\n"
        "---\n\nold body\n",
        encoding="utf-8",
    )
    return existing


def _reclip(webclip_dir: Path, url: str):
    metadata = {
        "category": "その他",
        "topics": ["その他"],
        "summary": "new",
        "tags": [],
        "key_points": [],
        "file_title": "New Title",
        "published_at": None,
        "updated_at": None,
    }
    with (
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
        patch.object(
            webclip, "generate_webclip_metadata", return_value=metadata
        ),
    ):
        return webclip.process_single_webclip(
            url=url,
            raw_content="new body",
            extracted_title="Old Title",
            hour_str="10:30",
            daily_file=webclip_dir / "2026-07-15.md",
            clipped_at_str="2026-07-15T10:30:00+09:00",
        )


def test_reclip_updates_in_place_and_preserves_path(tmp_path: Path):
    """Re-clips keep the existing path (no rename/move); content is updated."""
    webclip_dir = tmp_path / "webclip"
    url = "https://example.com/c"
    existing = _make_existing_webclip(webclip_dir, url)

    link = _reclip(webclip_dir, url)

    assert existing.exists()
    # No file is created under the new LLM file_title; path is stable.
    assert not (webclip_dir / "その他" / "New Title.md").exists()
    text = existing.read_text(encoding="utf-8")
    assert "new body" in text
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["why_saved"] == "keep me"
    assert "[[webclip/その他/Old Title]]" in link


def test_reclip_mkdir_failure_preserves_old_file(tmp_path: Path):
    webclip_dir = tmp_path / "webclip"
    url = "https://example.com/a"
    existing = _make_existing_webclip(webclip_dir, url)
    assert existing.exists()

    def failing_mkdir(self, *args, **kwargs):
        raise OSError("mkdir failed")

    with (
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
        patch.object(
            webclip,
            "generate_webclip_metadata",
            return_value={
                "category": "その他",
                "topics": ["その他"],
                "summary": "new",
                "tags": [],
                "key_points": [],
                "file_title": "New Title",
                "published_at": None,
                "updated_at": None,
            },
        ),
        patch.object(Path, "mkdir", failing_mkdir),
    ):
        try:
            webclip.process_single_webclip(
                url=url,
                raw_content="new body",
                extracted_title="Old Title",
                hour_str="10:30",
                daily_file=webclip_dir / "2026-07-15.md",
                clipped_at_str="2026-07-15T10:30:00+09:00",
            )
        except OSError:
            pass
        else:
            raise AssertionError("expected mkdir failure to propagate")

    assert existing.exists()
    assert "old body" in existing.read_text(encoding="utf-8")


def test_reclip_write_failure_preserves_old_file(tmp_path: Path):
    webclip_dir = tmp_path / "webclip"
    url = "https://example.com/b"
    existing = _make_existing_webclip(webclip_dir, url)
    assert existing.exists()

    def failing_write(self, *args, **kwargs):
        raise OSError("write failed")

    with (
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
        patch.object(
            webclip,
            "generate_webclip_metadata",
            return_value={
                "category": "その他",
                "topics": ["その他"],
                "summary": "new",
                "tags": [],
                "key_points": [],
                "file_title": "New Title",
                "published_at": None,
                "updated_at": None,
            },
        ),
        patch.object(Path, "write_text", failing_write),
    ):
        try:
            webclip.process_single_webclip(
                url=url,
                raw_content="new body",
                extracted_title="Old Title",
                hour_str="10:30",
                daily_file=webclip_dir / "2026-07-15.md",
                clipped_at_str="2026-07-15T10:30:00+09:00",
            )
        except OSError:
            pass
        else:
            raise AssertionError("expected write failure to propagate")

    assert existing.exists()
