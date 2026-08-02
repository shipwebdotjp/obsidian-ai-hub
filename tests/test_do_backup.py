from types import SimpleNamespace

import pytest

from obsidian_ai_hub import do_backup


def test_backup_error_includes_rsync_stderr(monkeypatch, tmp_path):
    monkeypatch.setattr(
        do_backup.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {"source": "/source-one", "destination": str(tmp_path / "one")},
            {"source": "/source-two", "destination": str(tmp_path / "two")},
        ],
    )
    results = iter(
        [
            SimpleNamespace(returncode=1, stderr="rsync: permission denied\n"),
            SimpleNamespace(returncode=0, stderr=""),
        ]
    )
    monkeypatch.setattr(do_backup.subprocess, "run", lambda *args, **kwargs: next(results))

    with pytest.raises(do_backup.BackupError) as exc_info:
        do_backup.main()

    message = str(exc_info.value)
    assert "/source-one" in message
    assert "exit 1" in message
    assert "rsync: permission denied" in message
