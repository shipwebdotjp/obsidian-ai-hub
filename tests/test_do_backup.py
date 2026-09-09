import logging
from types import SimpleNamespace

import pytest

from obsidian_ai_hub import do_backup


def _run_ok(monkeypatch, calls):
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(do_backup.subprocess, "run", run)


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
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return next(results)

    monkeypatch.setattr(do_backup.subprocess, "run", run)

    with pytest.raises(do_backup.BackupError) as exc_info:
        do_backup.main()

    message = str(exc_info.value)
    assert "/source-one" in message
    assert "exit 1" in message
    assert "rsync: permission denied" in message
    assert calls[0][1]["text"] is True
    assert calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["errors"] == "backslashreplace"


def test_excludes_appended_in_order_after_ds_store(monkeypatch, tmp_path):
    dest = str(tmp_path / "one")
    monkeypatch.setattr(
        do_backup.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {
                "source": "/source-one",
                "destination": dest,
                "excludes": ["node_modules/", "*.tmp", "/private/"],
            },
        ],
    )
    calls = []
    _run_ok(monkeypatch, calls)

    do_backup.main()

    cmd = calls[0][0][0]
    assert cmd[:5] == ["rsync", "-a", "--delete", "--delete-excluded", "--exclude=.DS_Store"]
    assert cmd[5:8] == ["--exclude=node_modules/", "--exclude=*.tmp", "--exclude=/private/"]
    assert cmd[8:] == ["/source-one/", dest]


def test_excludes_are_per_pair(monkeypatch, tmp_path):
    dest_one = str(tmp_path / "one")
    dest_two = str(tmp_path / "two")
    monkeypatch.setattr(
        do_backup.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {"source": "/source-one", "destination": dest_one, "excludes": ["a/"]},
            {"source": "/source-two", "destination": dest_two, "excludes": ["b/", "c/"]},
        ],
    )
    calls = []
    _run_ok(monkeypatch, calls)

    do_backup.main()

    assert len(calls) == 2
    cmd_one = calls[0][0][0]
    cmd_two = calls[1][0][0]
    assert "--exclude=a/" in cmd_one
    assert "--exclude=b/" not in cmd_one
    assert "--exclude=c/" not in cmd_one
    assert "--exclude=a/" not in cmd_two
    assert cmd_two[5:7] == ["--exclude=b/", "--exclude=c/"]
    # Fixed exclude and --delete-excluded are kept for both pairs.
    for cmd in (cmd_one, cmd_two):
        assert "--exclude=.DS_Store" in cmd
        assert "--delete-excluded" in cmd


def test_excludes_not_list_warns_and_syncs_with_default(monkeypatch, tmp_path, caplog):
    dest = str(tmp_path / "one")
    monkeypatch.setattr(
        do_backup.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": dest, "excludes": "node_modules/"}],
    )
    calls = []
    _run_ok(monkeypatch, calls)

    with caplog.at_level(logging.WARNING, logger=do_backup.logger.name):
        do_backup.main()

    cmd = calls[0][0][0]
    assert cmd == [
        "rsync",
        "-a",
        "--delete",
        "--delete-excluded",
        "--exclude=.DS_Store",
        "/source-one/",
        dest,
    ]
    assert any("excludes" in record.message for record in caplog.records)


def test_invalid_exclude_elements_warn_and_skip(monkeypatch, tmp_path, caplog):
    dest = str(tmp_path / "one")
    monkeypatch.setattr(
        do_backup.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {
                "source": "/source-one",
                "destination": dest,
                "excludes": ["ok/", "", 123, "also-ok/"],
            },
        ],
    )
    calls = []
    _run_ok(monkeypatch, calls)

    with caplog.at_level(logging.WARNING, logger=do_backup.logger.name):
        do_backup.main()

    cmd = calls[0][0][0]
    assert "--exclude=ok/" in cmd
    assert "--exclude=also-ok/" in cmd
    assert "--exclude=" not in cmd
    assert not any(arg == "--exclude=123" for arg in cmd)
    # Order of the valid elements is preserved.
    assert cmd.index("--exclude=ok/") < cmd.index("--exclude=also-ok/")
    warnings = [record.message for record in caplog.records]
    assert sum("exclude pattern" in message for message in warnings) == 2


def test_invalid_excludes_do_not_stop_other_pairs(monkeypatch, tmp_path, caplog):
    dest_one = str(tmp_path / "one")
    dest_two = str(tmp_path / "two")
    monkeypatch.setattr(
        do_backup.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {"source": "/source-one", "destination": dest_one, "excludes": "nope"},
            {"source": "/source-two", "destination": dest_two, "excludes": ["keep/"]},
        ],
    )
    calls = []
    _run_ok(monkeypatch, calls)

    with caplog.at_level(logging.WARNING, logger=do_backup.logger.name):
        do_backup.main()

    assert len(calls) == 2
    assert "--exclude=keep/" in calls[1][0][0]
    assert not any(arg.startswith("--exclude=") and arg != "--exclude=.DS_Store" for arg in calls[0][0][0])


def test_no_excludes_keeps_default_behavior(monkeypatch, tmp_path):
    dest = str(tmp_path / "one")
    monkeypatch.setattr(
        do_backup.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": dest}],
    )
    calls = []
    _run_ok(monkeypatch, calls)

    do_backup.main()

    assert calls[0][0][0] == [
        "rsync",
        "-a",
        "--delete",
        "--delete-excluded",
        "--exclude=.DS_Store",
        "/source-one/",
        dest,
    ]
