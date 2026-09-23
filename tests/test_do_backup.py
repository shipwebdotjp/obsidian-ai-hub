import logging
import stat
from types import SimpleNamespace

import pytest

from obsidian_ai_hub import do_backup
from obsidian_ai_hub.backup import service as backup_service

GNU_VERSION_OUTPUT = "rsync  version 3.3.0  protocol version 31\n"
OPENRSYNC_VERSION_OUTPUT = (
    "openrsync: protocol version 29\nrsync version 2.6.9 compatible\n"
)


def _patch_run(
    monkeypatch,
    *,
    version_output=GNU_VERSION_OUTPUT,
    sync_results=(),
    calls=None,
):
    """Patch subprocess.run, recording sync/version calls separately."""
    recorded = calls if calls is not None else []
    results = iter(sync_results)

    def run(cmd, *args, **kwargs):
        if cmd[1] == "--version":
            recorded.append(("version", cmd, kwargs))
            return SimpleNamespace(returncode=0, stdout=version_output, stderr="")
        recorded.append(("sync", cmd, kwargs))
        return next(results)

    monkeypatch.setattr(backup_service.subprocess, "run", run)
    return recorded


def _sync_calls(recorded):
    return [entry for entry in recorded if entry[0] == "sync"]


def test_configured_absolute_path_is_used_first(monkeypatch, tmp_path):
    executable = "/opt/homebrew/opt/rsync/bin/rsync"
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", executable)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": str(tmp_path / "one")}],
    )
    # An empty PATH proves the absolute path does not rely on lookup.
    monkeypatch.setenv("PATH", "")
    recorded = _patch_run(
        monkeypatch, sync_results=[SimpleNamespace(returncode=0, stderr="")]
    )

    backup_service.run_backup()

    assert recorded[0][0] == "version"
    assert recorded[0][1] == [executable, "--version"]
    assert _sync_calls(recorded)[0][1][0] == executable


def test_unset_executable_uses_rsync(monkeypatch, tmp_path):
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": str(tmp_path / "one")}],
    )
    recorded = _patch_run(
        monkeypatch, sync_results=[SimpleNamespace(returncode=0, stderr="")]
    )

    backup_service.run_backup()

    assert _sync_calls(recorded)[0][1][0] == "rsync"


def test_openrsync_version_warns_and_still_syncs(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": str(tmp_path / "one")}],
    )
    recorded = _patch_run(
        monkeypatch,
        version_output=OPENRSYNC_VERSION_OUTPUT,
        sync_results=[SimpleNamespace(returncode=0, stderr="")],
    )

    with caplog.at_level(logging.WARNING, logger=backup_service.logger.name):
        backup_service.run_backup()

    assert len(_sync_calls(recorded)) == 1
    assert any("openrsync" in record.message for record in caplog.records)


def test_empty_executable_stops_before_destination(monkeypatch, tmp_path):
    dest = tmp_path / "one"
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", "")
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": str(dest)}],
    )
    recorded = _patch_run(monkeypatch)

    with pytest.raises(backup_service.BackupError):
        backup_service.run_backup()

    assert not dest.exists()
    assert recorded == []


def test_invalid_type_stops_before_destination(monkeypatch, tmp_path):
    dest = tmp_path / "one"
    monkeypatch.setattr(
        backup_service.config, "BACKUP_RSYNC_EXECUTABLE", ["rsync"]
    )
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": str(dest)}],
    )
    recorded = _patch_run(monkeypatch)

    with pytest.raises(backup_service.BackupError):
        backup_service.run_backup()

    assert not dest.exists()
    assert recorded == []


def test_nonexistent_binary_stops_before_destination(monkeypatch, tmp_path):
    dest = tmp_path / "one"
    executable = str(tmp_path / "missing" / "rsync")
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", executable)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": str(dest)}],
    )

    with pytest.raises(backup_service.BackupError):
        backup_service.run_backup()

    assert not dest.exists()


def test_backup_error_includes_rsync_stderr(monkeypatch, tmp_path):
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {"source": "/source-one", "destination": str(tmp_path / "one")},
            {"source": "/source-two", "destination": str(tmp_path / "two")},
        ],
    )
    recorded = _patch_run(
        monkeypatch,
        sync_results=[
            SimpleNamespace(returncode=1, stderr="rsync: permission denied\n"),
            SimpleNamespace(returncode=0, stderr=""),
        ],
    )

    with pytest.raises(backup_service.BackupError) as exc_info:
        backup_service.run_backup()

    message = str(exc_info.value)
    assert "/source-one" in message
    assert "exit 1" in message
    assert "rsync: permission denied" in message
    sync_calls = _sync_calls(recorded)
    assert sync_calls[0][2]["text"] is True
    assert sync_calls[0][2]["encoding"] == "utf-8"
    assert sync_calls[0][2]["errors"] == "backslashreplace"


def test_excludes_appended_in_order_after_ds_store(monkeypatch, tmp_path):
    dest = str(tmp_path / "one")
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {
                "source": "/source-one",
                "destination": dest,
                "excludes": ["node_modules/", "*.tmp", "/private/"],
            },
        ],
    )
    recorded = _patch_run(
        monkeypatch, sync_results=[SimpleNamespace(returncode=0, stderr="")]
    )

    backup_service.run_backup()

    cmd = _sync_calls(recorded)[0][1]
    assert cmd[:6] == [
        "rsync",
        "-a",
        "--inplace",
        "--delete",
        "--delete-excluded",
        "--exclude=.DS_Store",
    ]
    assert cmd[6:9] == ["--exclude=node_modules/", "--exclude=*.tmp", "--exclude=/private/"]
    assert cmd[9:] == ["/source-one/", dest]


def test_excludes_are_per_pair(monkeypatch, tmp_path):
    dest_one = str(tmp_path / "one")
    dest_two = str(tmp_path / "two")
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {"source": "/source-one", "destination": dest_one, "excludes": ["a/"]},
            {"source": "/source-two", "destination": dest_two, "excludes": ["b/", "c/"]},
        ],
    )
    recorded = _patch_run(
        monkeypatch,
        sync_results=[
            SimpleNamespace(returncode=0, stderr=""),
            SimpleNamespace(returncode=0, stderr=""),
        ],
    )

    backup_service.run_backup()

    sync_calls = _sync_calls(recorded)
    assert len(sync_calls) == 2
    cmd_one = sync_calls[0][1]
    cmd_two = sync_calls[1][1]
    assert "--exclude=a/" in cmd_one
    assert "--exclude=b/" not in cmd_one
    assert "--exclude=c/" not in cmd_one
    assert "--exclude=a/" not in cmd_two
    assert cmd_two[6:8] == ["--exclude=b/", "--exclude=c/"]
    for cmd in (cmd_one, cmd_two):
        assert "--exclude=.DS_Store" in cmd
        assert "--delete-excluded" in cmd


def test_excludes_not_list_warns_and_syncs_with_default(monkeypatch, tmp_path, caplog):
    dest = str(tmp_path / "one")
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": dest, "excludes": "node_modules/"}],
    )
    recorded = _patch_run(
        monkeypatch, sync_results=[SimpleNamespace(returncode=0, stderr="")]
    )

    with caplog.at_level(logging.WARNING, logger=backup_service.logger.name):
        backup_service.run_backup()

    cmd = _sync_calls(recorded)[0][1]
    assert cmd == [
        "rsync",
        "-a",
        "--inplace",
        "--delete",
        "--delete-excluded",
        "--exclude=.DS_Store",
        "/source-one/",
        dest,
    ]
    assert any("excludes" in record.message for record in caplog.records)


def test_invalid_exclude_elements_warn_and_skip(monkeypatch, tmp_path, caplog):
    dest = str(tmp_path / "one")
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {
                "source": "/source-one",
                "destination": dest,
                "excludes": ["ok/", "", 123, "also-ok/"],
            },
        ],
    )
    recorded = _patch_run(
        monkeypatch, sync_results=[SimpleNamespace(returncode=0, stderr="")]
    )

    with caplog.at_level(logging.WARNING, logger=backup_service.logger.name):
        backup_service.run_backup()

    cmd = _sync_calls(recorded)[0][1]
    assert "--exclude=ok/" in cmd
    assert "--exclude=also-ok/" in cmd
    assert "--exclude=" not in cmd
    assert not any(arg == "--exclude=123" for arg in cmd)
    assert cmd.index("--exclude=ok/") < cmd.index("--exclude=also-ok/")
    warnings = [record.message for record in caplog.records]
    assert sum("exclude pattern" in message for message in warnings) == 2


def test_invalid_excludes_do_not_stop_other_pairs(monkeypatch, tmp_path, caplog):
    dest_one = str(tmp_path / "one")
    dest_two = str(tmp_path / "two")
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {"source": "/source-one", "destination": dest_one, "excludes": "nope"},
            {"source": "/source-two", "destination": dest_two, "excludes": ["keep/"]},
        ],
    )
    recorded = _patch_run(
        monkeypatch,
        sync_results=[
            SimpleNamespace(returncode=0, stderr=""),
            SimpleNamespace(returncode=0, stderr=""),
        ],
    )

    with caplog.at_level(logging.WARNING, logger=backup_service.logger.name):
        backup_service.run_backup()

    sync_calls = _sync_calls(recorded)
    assert len(sync_calls) == 2
    assert "--exclude=keep/" in sync_calls[1][1]
    assert not any(
        arg.startswith("--exclude=") and arg != "--exclude=.DS_Store"
        for arg in sync_calls[0][1]
    )


def test_no_excludes_keeps_default_behavior(monkeypatch, tmp_path):
    dest = str(tmp_path / "one")
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": dest}],
    )
    recorded = _patch_run(
        monkeypatch, sync_results=[SimpleNamespace(returncode=0, stderr="")]
    )

    backup_service.run_backup()

    assert _sync_calls(recorded)[0][1] == [
        "rsync",
        "-a",
        "--inplace",
        "--delete",
        "--delete-excluded",
        "--exclude=.DS_Store",
        "/source-one/",
        dest,
    ]


def test_no_sync_folders_raises_and_skips_preflight(monkeypatch):
    monkeypatch.setattr(backup_service.config, "BACKUP_SYNC_FOLDERS", [])
    recorded = _patch_run(monkeypatch)

    with pytest.raises(backup_service.BackupError):
        backup_service.run_backup()

    assert recorded == []


def test_malformed_pair_is_skipped_without_aborting(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [
            "not-a-mapping",
            {"source": 123, "destination": str(tmp_path / "bad")},
            {"source": "/source-one", "destination": str(tmp_path / "one")},
        ],
    )
    recorded = _patch_run(
        monkeypatch, sync_results=[SimpleNamespace(returncode=0, stderr="")]
    )

    with caplog.at_level(logging.WARNING, logger=backup_service.logger.name):
        backup_service.run_backup()

    sync_calls = _sync_calls(recorded)
    assert len(sync_calls) == 1
    assert sync_calls[0][1][-2:] == ["/source-one/", str(tmp_path / "one")]
    assert not (tmp_path / "bad").exists()


def test_do_backup_main_wraps_service(monkeypatch, tmp_path):
    monkeypatch.setattr(backup_service.config, "BACKUP_RSYNC_EXECUTABLE", None)
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [{"source": "/source-one", "destination": str(tmp_path / "one")}],
    )
    _patch_run(monkeypatch, sync_results=[SimpleNamespace(returncode=0, stderr="")])

    do_backup.main()

    assert do_backup.BackupError is backup_service.BackupError


def test_fake_gnu_rsync_receives_args_without_touching_source(monkeypatch, tmp_path):
    """End-to-end call against a fake GNU rsync binary on disk."""
    args_file = tmp_path / "recorded-args.txt"
    fake_rsync = tmp_path / "fake-rsync"
    fake_rsync.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then\n'
        '  echo "rsync  version 3.3.0  protocol version 31"\n'
        "  exit 0\n"
        "fi\n"
        f'printf "%s\\n" "$@" > "{args_file}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_rsync.chmod(fake_rsync.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("original", encoding="utf-8")
    dest = tmp_path / "dest"

    monkeypatch.setattr(
        backup_service.config, "BACKUP_RSYNC_EXECUTABLE", str(fake_rsync)
    )
    monkeypatch.setattr(
        backup_service.config,
        "BACKUP_SYNC_FOLDERS",
        [
            {
                "source": str(source),
                "destination": str(dest),
                "excludes": ["skip/"],
            }
        ],
    )

    backup_service.run_backup()

    recorded = args_file.read_text(encoding="utf-8").splitlines()
    assert recorded == [
        "-a",
        "--inplace",
        "--delete",
        "--delete-excluded",
        "--exclude=.DS_Store",
        "--exclude=skip/",
        f"{source}/",
        str(dest),
    ]
    assert (source / "note.txt").read_text(encoding="utf-8") == "original"
