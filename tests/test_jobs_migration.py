"""Scheduler Job migration tests: YAML tasks/ -> jobs/ and DB task_state -> job_state."""

import sqlite3

import pytest
import yaml

from obsidian_ai_hub.scheduler_jobs import recurring


def _legacy_job_dict(job_id="j1"):
    return {
        "id": job_id,
        "enabled": True,
        "schedule": {"type": "daily", "hour": 8, "minute": 0},
        "command": "printf hi",
    }


def test_yaml_migration_moves_source_state_and_removes_legacy(tmp_path):
    legacy = tmp_path / "tasks"
    legacy.mkdir()
    (legacy / "tasks.local.yml").write_text(
        yaml.safe_dump([_legacy_job_dict()]), encoding="utf-8"
    )
    (legacy / "last_run.json").write_text("{}", encoding="utf-8")

    dest = recurring.migrate_tasks_yaml_to_jobs(tmp_path)

    assert dest == tmp_path / "jobs" / "jobs.local.yml"
    moved = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert moved[0]["id"] == "j1"
    assert (tmp_path / "jobs" / "last_run.json").exists()
    assert not (legacy / "tasks.local.yml").exists()
    assert not legacy.exists() or list(legacy.iterdir()) == []


def test_yaml_migration_falls_back_to_default_tasks_yml(tmp_path):
    legacy = tmp_path / "tasks"
    legacy.mkdir()
    (legacy / "tasks.yml").write_text(
        yaml.safe_dump([_legacy_job_dict("j2")]), encoding="utf-8"
    )

    dest = recurring.migrate_tasks_yaml_to_jobs(tmp_path)
    moved = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert moved[0]["id"] == "j2"


def test_yaml_migration_stops_when_destination_exists(tmp_path):
    legacy = tmp_path / "tasks"
    legacy.mkdir()
    (legacy / "tasks.local.yml").write_text(
        yaml.safe_dump([_legacy_job_dict()]), encoding="utf-8"
    )
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "jobs.local.yml").write_text(yaml.safe_dump([]), encoding="utf-8")

    with pytest.raises(RuntimeError, match="already exists"):
        recurring.migrate_tasks_yaml_to_jobs(tmp_path)

    # Nothing was merged or deleted.
    assert (legacy / "tasks.local.yml").exists()
    assert yaml.safe_load((jobs_dir / "jobs.local.yml").read_text()) == []


def test_yaml_migration_stops_without_source(tmp_path):
    with pytest.raises(RuntimeError, match="no legacy tasks YAML"):
        recurring.migrate_tasks_yaml_to_jobs(tmp_path)


def test_yaml_migration_rejects_invalid_jobs(tmp_path):
    legacy = tmp_path / "tasks"
    legacy.mkdir()
    (legacy / "tasks.local.yml").write_text(
        yaml.safe_dump([{"id": "dup", "schedule": {"type": "minutely"}, "command": "echo 1"},
                        {"id": "dup", "schedule": {"type": "minutely"}, "command": "echo 2"}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate job ID"):
        recurring.migrate_tasks_yaml_to_jobs(tmp_path)
    assert not (tmp_path / "jobs" / "jobs.local.yml").exists()


def test_runner_fails_closed_with_legacy_files(monkeypatch, tmp_path):
    legacy = tmp_path / "tasks"
    legacy.mkdir()
    leftover = legacy / "tasks.local.yml"
    leftover.write_text(yaml.safe_dump([_legacy_job_dict()]), encoding="utf-8")

    monkeypatch.setattr(recurring, "LEGACY_TASK_FILES", (leftover,))
    monkeypatch.setattr(recurring.config, "IS_TEST_ENV", False)

    with pytest.raises(RuntimeError, match="migration"):
        recurring.assert_no_legacy_task_files()
    with pytest.raises(RuntimeError, match="migration"):
        recurring.load_jobs()
    with pytest.raises(RuntimeError, match="migration"):
        recurring.get_jobs_file_and_revision()


def test_db_v48_copies_task_state_to_job_state_and_drops_old(tmp_path):
    from obsidian_ai_hub import database

    db_file = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE task_state (
            task_id TEXT PRIMARY KEY,
            last_check_at TEXT NOT NULL,
            consecutive_empty_count INTEGER NOT NULL DEFAULT 0,
            last_processed_at TEXT,
            last_error_at TEXT,
            last_error_message TEXT,
            last_error_type TEXT,
            processed_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO task_state (task_id, last_check_at, consecutive_empty_count,"
        " processed_count, skipped_count, failed_count, updated_at)"
        " VALUES ('merge_inbox', '2026-09-17T00:00:00+00:00', 2, 5, 1, 0,"
        " '2026-09-17T00:00:00+00:00');"
    )
    conn.execute("PRAGMA user_version = 47;")
    conn.commit()

    try:
        database.run_migration_v48(conn)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "job_state" in tables
        assert "one_shot_jobs" in tables
        assert "task_state" not in tables

        row = conn.execute("SELECT * FROM job_state WHERE job_id = 'merge_inbox'").fetchone()
        assert row is not None
        assert row["consecutive_empty_count"] == 2
        assert row["processed_count"] == 5
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 48
    finally:
        conn.close()


def test_db_v58_rebuilds_one_shot_and_adds_dispatches(tmp_path):
    """v58 must preserve existing command rows while allowing workflow targets."""
    from obsidian_ai_hub import database

    db_file = tmp_path / "v57.sqlite3"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE one_shot_jobs (
            job_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            run_at_utc TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            agent_id TEXT,
            session_id TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            exit_code INTEGER,
            segments_json TEXT NOT NULL DEFAULT '[]',
            output_truncated INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT
        );
    """)
    conn.execute(
        "INSERT INTO one_shot_jobs (job_id, command, run_at_utc, status, created_at,"
        " exit_code, segments_json, output_truncated)"
        " VALUES ('old1', 'printf hi', '2026-09-17T00:00:00+00:00', 'succeeded',"
        " '2026-09-17T00:00:00+00:00', 0, '[{\"args\":[\"printf\",\"hi\"]}]', 0);"
    )
    conn.execute("PRAGMA user_version = 57;")
    conn.commit()

    try:
        database.run_migration_v58(conn)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "workflow_schedule_dispatches" in tables

        row = conn.execute("SELECT * FROM one_shot_jobs WHERE job_id = 'old1'").fetchone()
        assert row is not None
        assert row["target_kind"] == "command"
        assert row["command"] == "printf hi"
        assert row["status"] == "succeeded"
        assert row["exit_code"] == 0

        # A workflow target row may now store a NULL command.
        conn.execute(
            "INSERT INTO one_shot_jobs (job_id, target_kind, command, workflow_id,"
            " run_at_utc, status, created_at)"
            " VALUES ('wf1', 'workflow', NULL, 'wf_x', '2026-09-17T00:00:00+00:00',"
            " 'queued', '2026-09-17T00:00:00+00:00');"
        )
        wf = conn.execute("SELECT * FROM one_shot_jobs WHERE job_id = 'wf1'").fetchone()
        assert wf["command"] is None
        assert wf["target_kind"] == "workflow"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 58
    finally:
        conn.close()


def test_fresh_db_has_job_state_and_one_shot_jobs_without_task_state(test_memory_db_path):
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "job_state" in tables
        assert "one_shot_jobs" in tables
        assert "task_state" not in tables
    finally:
        conn.close()


def test_old_scheduler_imports_fail():
    with pytest.raises(ImportError):
        import obsidian_ai_hub.task_runner  # noqa: F401


def test_load_jobs_returns_empty_when_no_file_exists(monkeypatch, tmp_path):
    """Fresh installs without jobs YAML read as empty instead of crashing."""
    missing = tmp_path / "no-such-dir" / "jobs.test.yml"
    monkeypatch.setattr(recurring, "TEST_JOB_FILE", missing)
    monkeypatch.setattr(recurring, "LOCAL_JOB_FILE", missing)
    monkeypatch.setattr(recurring, "DEFAULT_JOB_FILE", missing)
    assert recurring.load_jobs() == []


def test_corrupt_yaml_surfaces_instead_of_empty(monkeypatch, tmp_path):
    """Corrupt YAML must raise (API 500 / loud runner failure), never read as []."""
    bad = tmp_path / "jobs.test.yml"
    bad.write_text("id: [unclosed\n  broken: : :", encoding="utf-8")
    monkeypatch.setattr(recurring, "TEST_JOB_FILE", bad)
    monkeypatch.setattr(recurring, "LOCAL_JOB_FILE", bad)
    monkeypatch.setattr(recurring, "DEFAULT_JOB_FILE", bad)

    with pytest.raises(Exception):
        recurring.load_jobs()
    with pytest.raises(Exception):
        recurring.get_jobs_file_and_revision()


def test_frontend_preset_options_match_backend():
    """JobPage preset list must equal backend PRESET_FLAGS (no drift)."""
    import re

    repo_root = recurring.config.BASE_DIR
    frontend = (repo_root / "frontend" / "src" / "features" / "jobs" / "JobPage.tsx").read_text(
        encoding="utf-8"
    )
    ui_flags = sorted(set(re.findall(r'flag: "(--[a-z-]+)"', frontend)))
    assert ui_flags == sorted(recurring.PRESET_FLAGS.keys())
    assert "--notify-calendar-event" not in ui_flags
