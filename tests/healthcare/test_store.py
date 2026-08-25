import sqlite3
from pathlib import Path

import pytest

from obsidian_ai_hub.healthcare.store import (
    HEALTHCARE_SCHEMA_VERSION,
    create_import_row,
    finish_import_row,
    get_healthcare_db_connection,
    read_ecg_samples,
)
from obsidian_ai_hub.utils import config


def test_schema_version_and_tables(test_healthcare_db_path: Path):
    conn = get_healthcare_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA user_version;")
        assert cur.fetchone()[0] == HEALTHCARE_SCHEMA_VERSION

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
        tables = {row[0] for row in cur.fetchall()}
        expected = {
            "health_imports",
            "health_records",
            "health_record_metadata",
            "health_hrv_beats",
            "health_workouts",
            "health_workout_metadata",
            "health_workout_events",
            "health_workout_statistics",
            "health_workout_routes",
            "health_activity_summaries",
            "health_ecg",
        }
        assert expected.issubset(tables)

        # No health_ecg_samples table (file-reference per spec)
        assert "health_ecg_samples" not in tables

        # Indexes exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name;")
        indexes = {row[0] for row in cur.fetchall()}
        assert "idx_hr_type_start" in indexes
        assert "idx_hrm_key" in indexes
        assert "idx_health_ecg_import" in indexes

        # PRAGMA checks
        cur.execute("PRAGMA journal_mode;")
        assert cur.fetchone()[0].lower() == "wal"
        cur.execute("PRAGMA foreign_keys;")
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_healthcare_db_uses_test_path(test_healthcare_db_path: Path):
    conn = get_healthcare_db_connection()
    try:
        db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])
        assert db_path == test_healthcare_db_path
    finally:
        conn.close()


def test_production_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    protected = tmp_path / "production_healthcare.sqlite3"
    monkeypatch.setenv("OBSIDIAN_AI_HUB_TEST_PRODUCTION_HEALTHCARE_DB_PATH", str(protected))
    monkeypatch.setattr(config, "HEALTHCARE_SQLITE_PATH", protected)
    with pytest.raises(RuntimeError, match="production healthcare database"):
        get_healthcare_db_connection()
    assert not protected.exists()


def test_memory_db_separation_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # HEALTHCARE must not equal MEMORY path
    memory_path = tmp_path / "shared.sqlite3"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", memory_path)
    monkeypatch.setattr(config, "HEALTHCARE_SQLITE_PATH", memory_path)
    with pytest.raises(RuntimeError, match="HEALTHCARE_SQLITE_PATH must not equal MEMORY_SQLITE_PATH"):
        get_healthcare_db_connection()


def test_fingerprint_unique_constraint(test_healthcare_db_path: Path):
    conn = get_healthcare_db_connection()
    try:
        create_import_row(
            conn,
            import_id="imp_001",
            export_dir="/tmp/export",
            started_at="2026-08-20T10:00:00",
        )
        conn.commit()

        # Insert a health_record
        conn.execute(
            """
            INSERT INTO health_records
                (import_id, type, value_text, value_numeric, unit, source_name, start_date, end_date, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("imp_001", "HKQuantityTypeIdentifierHeartRate", "72", 72.0, "count/min", "TestWatch", "2026-08-20 08:00:00 +0900", "2026-08-20 08:01:00 +0900", "fp-001"),
        )
        conn.commit()

        # Duplicate fingerprint must raise IntegrityError
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO health_records
                    (import_id, type, value_text, value_numeric, unit, source_name, start_date, end_date, fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("imp_001", "HKQuantityTypeIdentifierHeartRate", "72", 72.0, "count/min", "TestWatch", "2026-08-20 08:00:00 +0900", "2026-08-20 08:01:00 +0900", "fp-001"),
            )

        # Different fingerprint is fine (INSERT OR IGNORE pattern used by importer)
        conn.execute(
            """
            INSERT OR IGNORE INTO health_records
                (import_id, type, value_text, value_numeric, unit, source_name, start_date, end_date, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("imp_001", "HKQuantityTypeIdentifierHeartRate", "80", 80.0, "count/min", "TestWatch", "2026-08-20 09:00:00 +0900", "2026-08-20 09:01:00 +0900", "fp-002"),
        )
        conn.commit()
        cur = conn.execute("SELECT COUNT(*) FROM health_records;")
        assert cur.fetchone()[0] == 2
    finally:
        conn.close()


def test_cascade_delete_import(test_healthcare_db_path: Path):
    conn = get_healthcare_db_connection()
    try:
        create_import_row(conn, import_id="imp_cascade", export_dir="/tmp/export", started_at="2026-08-20T10:00:00")
        conn.execute(
            "INSERT INTO health_records (import_id, type, source_name, start_date, end_date, fingerprint) VALUES (?,?,?,?,?,?)",
            ("imp_cascade", "HKQuantityTypeIdentifierStepCount", "TestWatch", "2026-08-20 08:00:00 +0900", "2026-08-20 08:01:00 +0900", "fp-cascade-1"),
        )
        rec_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO health_record_metadata (record_id, mkey, mvalue) VALUES (?,?,?)", (rec_id, "k", "v"))
        conn.execute("INSERT INTO health_ecg (import_id, file_path, file_name) VALUES (?,?,?)", ("imp_cascade", "/tmp/a.csv", "a.csv"))
        conn.commit()

        conn.execute("DELETE FROM health_imports WHERE import_id = ?", ("imp_cascade",))
        conn.commit()

        assert conn.execute("SELECT COUNT(*) FROM health_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM health_record_metadata").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM health_ecg").fetchone()[0] == 0
    finally:
        conn.close()


def test_create_and_finish_import_row(test_healthcare_db_path: Path):
    conn = get_healthcare_db_connection()
    try:
        create_import_row(conn, import_id="imp_flow", export_dir="/tmp/export", started_at="2026-08-20T10:00:00", export_date="2026-08-20 10:00:00 +0900", hk_export_version="14", locale="ja_JP", me_json='{"sex":"male"}')
        conn.commit()
        row = conn.execute("SELECT status, export_date, hk_export_version FROM health_imports WHERE import_id='imp_flow'").fetchone()
        assert row["status"] == "running"
        assert row["export_date"] == "2026-08-20 10:00:00 +0900"

        finish_import_row(conn, import_id="imp_flow", finished_at="2026-08-20T10:01:00", status="succeeded", stats={"records": 10})
        conn.commit()
        row = conn.execute("SELECT status, finished_at, stats_json FROM health_imports WHERE import_id='imp_flow'").fetchone()
        assert row["status"] == "succeeded"
        assert "records" in row["stats_json"]
    finally:
        conn.close()


def test_read_ecg_samples(tmp_path: Path):
    # Use the fixture ECG
    fixture = Path(__file__).parent / "fixtures" / "ecg_mini.csv"
    samples = read_ecg_samples(fixture)
    assert len(samples) == 10
    assert samples[0] == pytest.approx(1.342)

    # Write a synthetic one via helpers and read back
    import importlib.util

    helpers_path = Path(__file__).parent / "helpers.py"
    spec = importlib.util.spec_from_file_location("hc_helpers_ecg", helpers_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    dest = tmp_path / "ecg.csv"
    mod.write_ecg_csv(dest, samples=[9.9, 8.8])
    assert read_ecg_samples(dest) == [9.9, 8.8]
    assert read_ecg_samples(dest, limit=1) == [9.9]
