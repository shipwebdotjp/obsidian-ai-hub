from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from obsidian_ai_hub import obsidian_inbox_merge
from obsidian_ai_hub.obsidian_inbox_merge import INBOX_FRESH_GRACE_SECONDS


def _create_template(daily_template: Path) -> None:
    daily_template.parent.mkdir(parents=True, exist_ok=True)
    daily_template.write_text("# Daily\n## 📝メモ\n", encoding="utf-8")


def _set_mtime(path: Path, dt: datetime) -> None:
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


def test_process_inbox_file_defers_fresh_markdown(tmp_path: Path):
    """最終更新から5秒未満のファイルは処理せず削除しない。"""
    inbox = tmp_path / "vault" / "Inbox"
    inbox.mkdir(parents=True)
    inbox_file = inbox / "note.md"
    inbox_file.write_text("hello", encoding="utf-8")

    fixed_now = datetime(2026, 8, 19, 10, 0, 0)
    _set_mtime(inbox_file, fixed_now - timedelta(seconds=INBOX_FRESH_GRACE_SECONDS - 1))

    with patch.object(obsidian_inbox_merge, "is_icloud_offloaded", return_value=False):
        obsidian_inbox_merge.process_inbox_file(inbox_file, now=fixed_now)

    assert inbox_file.exists(), "fresh file must remain for the next per-minute run"


def test_process_inbox_file_processes_stale_markdown(tmp_path: Path):
    """最終更新から5秒以上のファイルは処理して削除する。"""
    inbox = tmp_path / "vault" / "Inbox"
    inbox.mkdir(parents=True)
    inbox_file = inbox / "note.md"
    inbox_file.write_text("hello", encoding="utf-8")

    daily_template = (
        tmp_path / "vault" / obsidian_inbox_merge.config.DAILY_DIR_NAME
        / obsidian_inbox_merge.config.TEMPLATE_DIR_NAME
        / obsidian_inbox_merge.config.DAILY_TEMPLATE_FILENAME
    )
    _create_template(daily_template)

    fixed_now = datetime(2026, 8, 19, 10, 0, 0)
    _set_mtime(inbox_file, fixed_now - timedelta(seconds=INBOX_FRESH_GRACE_SECONDS + 1))

    with (
        patch.object(obsidian_inbox_merge, "is_icloud_offloaded", return_value=False),
        patch.object(
            obsidian_inbox_merge, "merge_content_into_daily_note", return_value="memo"
        ) as mock_merge,
    ):
        obsidian_inbox_merge.process_inbox_file(inbox_file, now=fixed_now)

    mock_merge.assert_called_once()
    assert not inbox_file.exists(), "processed file must be removed"


def test_process_inbox_file_markdown_success_deletes(tmp_path: Path):
    """Markdownの成功処理は元ファイルを削除する。"""
    inbox = tmp_path / "vault" / "Inbox"
    inbox.mkdir(parents=True)
    inbox_file = inbox / "2026-08-19.md"
    inbox_file.write_text("memo body", encoding="utf-8")

    daily_template = (
        tmp_path / "vault" / obsidian_inbox_merge.config.DAILY_DIR_NAME
        / obsidian_inbox_merge.config.TEMPLATE_DIR_NAME
        / obsidian_inbox_merge.config.DAILY_TEMPLATE_FILENAME
    )
    _create_template(daily_template)

    fixed_now = datetime(2026, 8, 19, 10, 0, 0)
    _set_mtime(inbox_file, fixed_now - timedelta(seconds=60))

    with (
        patch.object(obsidian_inbox_merge, "is_icloud_offloaded", return_value=False),
        patch.object(
            obsidian_inbox_merge, "merge_content_into_daily_note", return_value="memo"
        ),
    ):
        obsidian_inbox_merge.process_inbox_file(inbox_file, now=fixed_now)

    assert not inbox_file.exists()


def test_process_inbox_file_icloud_wait_failure_keeps_file(tmp_path: Path):
    """iCloud待機失敗時は元ファイルを残す。"""
    inbox = tmp_path / "vault" / "Inbox"
    inbox.mkdir(parents=True)
    inbox_file = inbox / "voice.m4a"
    inbox_file.write_bytes(b"\x00")

    fixed_now = datetime(2026, 8, 19, 10, 0, 0)

    with (
        patch.object(obsidian_inbox_merge, "is_icloud_offloaded", return_value=True),
        patch.object(obsidian_inbox_merge, "wait_for_icloud_download", return_value=False),
    ):
        obsidian_inbox_merge.process_inbox_file(inbox_file, now=fixed_now)

    assert inbox_file.exists(), "iCloud wait failure must leave the file in place"


def test_process_inbox_file_read_failure_keeps_file(tmp_path: Path):
    """Markdown読込失敗時は元ファイルを残す。"""
    inbox = tmp_path / "vault" / "Inbox"
    inbox.mkdir(parents=True)
    inbox_file = inbox / "note.md"
    inbox_file.write_text("body", encoding="utf-8")

    daily_template = (
        tmp_path / "vault" / obsidian_inbox_merge.config.DAILY_DIR_NAME
        / obsidian_inbox_merge.config.TEMPLATE_DIR_NAME
        / obsidian_inbox_merge.config.DAILY_TEMPLATE_FILENAME
    )
    _create_template(daily_template)

    fixed_now = datetime(2026, 8, 19, 10, 0, 0)
    _set_mtime(inbox_file, fixed_now - timedelta(seconds=60))

    original_read_text = Path.read_text

    def failing_read_text(self, *args, **kwargs):
        raise OSError("simulated read failure")

    with (
        patch.object(obsidian_inbox_merge, "is_icloud_offloaded", return_value=False),
        patch.object(Path, "read_text", failing_read_text),
        patch.object(
            obsidian_inbox_merge, "merge_content_into_daily_note"
        ) as mock_merge,
    ):
        obsidian_inbox_merge.process_inbox_file(inbox_file, now=fixed_now)

    mock_merge.assert_not_called()
    assert inbox_file.exists(), "read failure must leave the file in place"

    del failing_read_text
    assert Path.read_text is original_read_text


def test_process_inbox_file_transcribe_failure_keeps_file_and_cleans_tmp(tmp_path: Path):
    """音声転記失敗時は元ファイルを残し一時ファイルを掃除する。"""
    inbox = tmp_path / "vault" / "Inbox"
    inbox.mkdir(parents=True)
    inbox_file = inbox / "voice.m4a"
    inbox_file.write_bytes(b"\x00")

    fixed_now = datetime(2026, 8, 19, 10, 0, 0)

    def fail_load_model(*args, **kwargs):
        raise RuntimeError("simulated whisper failure")

    with (
        patch.object(obsidian_inbox_merge, "is_icloud_offloaded", return_value=False),
        patch.object(obsidian_inbox_merge.whisper, "load_model", side_effect=fail_load_model),
        patch.object(
            obsidian_inbox_merge, "merge_content_into_daily_note"
        ) as mock_merge,
    ):
        obsidian_inbox_merge.process_inbox_file(inbox_file, now=fixed_now)

    mock_merge.assert_not_called()
    assert inbox_file.exists(), "transcribe failure must leave the file in place"

    remaining_tmp = [
        p for p in tmp_path.rglob("*") if p.is_file() and p.suffix == ".m4a" and p != inbox_file
    ]
    assert remaining_tmp == [], f"audio temp files must be cleaned up: {remaining_tmp}"


def test_process_inbox_file_unsupported_extension_is_skipped(tmp_path: Path):
    """非対応拡張子は処理せず削除もしない。"""
    inbox = tmp_path / "vault" / "Inbox"
    inbox.mkdir(parents=True)
    inbox_file = inbox / "note.txt"
    inbox_file.write_text("hello", encoding="utf-8")

    fixed_now = datetime(2026, 8, 19, 10, 0, 0)

    with (
        patch.object(obsidian_inbox_merge, "is_icloud_offloaded", return_value=False),
        patch.object(
            obsidian_inbox_merge, "merge_content_into_daily_note"
        ) as mock_merge,
    ):
        obsidian_inbox_merge.process_inbox_file(inbox_file, now=fixed_now)

    mock_merge.assert_not_called()
    assert inbox_file.exists()
