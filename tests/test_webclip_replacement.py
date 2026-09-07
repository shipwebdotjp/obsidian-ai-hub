from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub.utils import config, webclip


def _make_existing_webclip(webclip_dir: Path, url: str) -> Path:
    existing = webclip_dir / "その他" / "Old Title.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text(
        "---\n"
        f"title: Old Title\nsource_url: {url}\n"
        "clipped_at: 2026-07-15T10:30:00+09:00\n"
        "published_at: null\nupdated_at: null\ncategory: その他\n"
        "topics: []\ntags: []\nsummary: ''\nkey_points: []\nwhy_saved: ''\n"
        "---\n\nold body\n",
        encoding="utf-8",
    )
    return existing


def _run_reclip(webclip_dir: Path, url: str):
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


def test_reclip_mkdir_failure_preserves_old_file(tmp_path: Path):
    webclip_dir = tmp_path / "webclip"
    url = "https://example.com/a"
    existing = _make_existing_webclip(webclip_dir, url)
    assert existing.exists()

    orig_mkdir = Path.mkdir

    def failing_mkdir(self, *args, **kwargs):
        # Fail only when creating the new target directory/file path area
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
    assert orig_mkdir is not None


def test_reclip_write_failure_preserves_old_file(tmp_path: Path):
    webclip_dir = tmp_path / "webclip"
    url = "https://example.com/b"
    existing = _make_existing_webclip(webclip_dir, url)
    assert existing.exists()

    orig_write = Path.write_text

    def failing_write(self, *args, **kwargs):
        # Allow the initial fixture write (already done); fail only for new target
        if self.resolve() != existing.resolve():
            raise OSError("write failed")
        return orig_write(self, *args, **kwargs)

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
    assert "old body" in existing.read_text(encoding="utf-8")


def test_reclip_success_relocates_after_write(tmp_path: Path):
    webclip_dir = tmp_path / "webclip"
    url = "https://example.com/c"
    existing = _make_existing_webclip(webclip_dir, url)

    _run_reclip(webclip_dir, url)

    new_path = webclip_dir / "その他" / "New Title.md"
    assert new_path.exists()
    assert not existing.exists()
