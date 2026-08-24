"""Healthcare DB store — separate SQLite file from memory.sqlite3.

Schema v1 covers the plan in docs/healthcare-import/plan.md.
Follows src/obsidian_ai_hub/database.py patterns (WAL, foreign_keys,
busy_timeout, user_version migration).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from obsidian_ai_hub.utils import config

HEALTHCARE_SCHEMA_VERSION = 1


def _assert_test_healthcare_is_not_production(db_path: Path) -> None:
    """Reject the configured production healthcare DB while pytest isolation is active."""
    if os.getenv("OBSIDIAN_AI_HUB_TESTING") != "1":
        return
    production_paths = [
        value
        for name in (
            "OBSIDIAN_AI_HUB_TEST_PRODUCTION_HEALTHCARE_DB_PATH",
            "OBSIDIAN_AI_HUB_TEST_PRODUCTION_DB_PATH",
        )
        if (value := os.getenv(name))
    ]
    if not production_paths:
        raise RuntimeError(
            "OBSIDIAN_AI_HUB_TEST_PRODUCTION_HEALTHCARE_DB_PATH is required in test mode"
        )
    for production_path in production_paths:
        if db_path.expanduser().resolve() == Path(production_path).expanduser().resolve():
            raise RuntimeError(
                "Refusing to open the production healthcare database while tests are running"
            )


def _assert_not_memory_db(db_path: Path) -> None:
    """Guard against accidentally co-locating healthcare DB with memory DB.

    Healthcare must be a separate file per docs/healthcare-import/plan.md.
    """
    memory_path = Path(config.MEMORY_SQLITE_PATH).expanduser().resolve()
    if db_path.expanduser().resolve() == memory_path:
        raise RuntimeError(
            "HEALTHCARE_SQLITE_PATH must not equal MEMORY_SQLITE_PATH "
            "(healthcare uses a separate DB)"
        )


def _get_healthcare_db_path() -> Path:
    return Path(config.HEALTHCARE_SQLITE_PATH)


def get_healthcare_db_connection() -> sqlite3.Connection:
    db_path = _get_healthcare_db_path()
    _assert_test_healthcare_is_not_production(db_path)
    # Enforce separation; surfaces as RuntimeError before any file is created
    _assert_not_memory_db(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")

    # Migrations
    cur = conn.cursor()
    cur.execute("PRAGMA user_version;")
    current_version = cur.fetchone()[0]

    if current_version == 0:
        _create_schema_v1(conn)
        conn.execute(f"PRAGMA user_version = {HEALTHCARE_SCHEMA_VERSION};")
        conn.commit()
    elif current_version < HEALTHCARE_SCHEMA_VERSION:
        # Future migrations go here: if current_version <= 1: run_migration_v2(conn)
        raise RuntimeError(
            f"Unsupported healthcare DB version {current_version} "
            f"(expected {HEALTHCARE_SCHEMA_VERSION}); migration not implemented"
        )
    elif current_version > HEALTHCARE_SCHEMA_VERSION:
        raise RuntimeError(
            f"Healthcare DB version {current_version} is newer than code "
            f"version {HEALTHCARE_SCHEMA_VERSION}"
        )

    # Ensure v1 indexes exist for DBs created before incremental index additions
    # (idempotent for new DBs). Covers ocr指摘の性能対策とECG冪等。
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hw_import ON health_workouts(import_id);")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_health_ecg_file_path ON health_ecg(file_path);"
    )
    conn.commit()

    return conn


def _create_schema_v1(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_imports (
            import_id TEXT PRIMARY KEY,
            export_dir TEXT NOT NULL,
            export_date TEXT,
            hk_export_version TEXT,
            locale TEXT,
            me_json TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')),
            stats_json TEXT NOT NULL DEFAULT '{}',
            error TEXT
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id TEXT NOT NULL REFERENCES health_imports(import_id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            value_text TEXT,
            value_numeric REAL,
            unit TEXT,
            source_name TEXT NOT NULL,
            source_version TEXT,
            device_raw TEXT,
            creation_date TEXT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hr_type_start ON health_records(type, start_date);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hr_start ON health_records(start_date);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hr_import ON health_records(import_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hr_source ON health_records(source_name);")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_record_metadata (
            record_id INTEGER NOT NULL REFERENCES health_records(record_id) ON DELETE CASCADE,
            mkey TEXT NOT NULL,
            mvalue TEXT NOT NULL,
            PRIMARY KEY(record_id, mkey)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hrm_key ON health_record_metadata(mkey);")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_hrv_beats (
            record_id INTEGER NOT NULL REFERENCES health_records(record_id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            bpm REAL NOT NULL,
            time TEXT NOT NULL,
            PRIMARY KEY(record_id, seq)
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_workouts (
            workout_id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id TEXT NOT NULL REFERENCES health_imports(import_id) ON DELETE CASCADE,
            activity_type TEXT NOT NULL,
            duration REAL, duration_unit TEXT,
            total_distance REAL, total_distance_unit TEXT,
            total_energy_burned REAL, total_energy_burned_unit TEXT,
            source_name TEXT NOT NULL, source_version TEXT,
            device_raw TEXT,
            creation_date TEXT, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_workout_metadata (
            workout_id INTEGER NOT NULL REFERENCES health_workouts(workout_id) ON DELETE CASCADE,
            mkey TEXT NOT NULL, mvalue TEXT NOT NULL, PRIMARY KEY(workout_id,mkey)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_workout_events (
            workout_id INTEGER NOT NULL REFERENCES health_workouts(workout_id) ON DELETE CASCADE,
            seq INTEGER NOT NULL, type TEXT NOT NULL, date TEXT NOT NULL,
            duration REAL, duration_unit TEXT, PRIMARY KEY(workout_id,seq)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_workout_statistics (
            workout_id INTEGER NOT NULL REFERENCES health_workouts(workout_id) ON DELETE CASCADE,
            type TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            average REAL, minimum REAL, maximum REAL, sum REAL, unit TEXT,
            PRIMARY KEY(workout_id,type)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_workout_routes (
            workout_id INTEGER NOT NULL REFERENCES health_workouts(workout_id) ON DELETE CASCADE,
            seq INTEGER NOT NULL DEFAULT 0,
            source_name TEXT, source_version TEXT, device_raw TEXT,
            creation_date TEXT, start_date TEXT, end_date TEXT, file_path TEXT,
            PRIMARY KEY(workout_id, seq)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hw_import ON health_workouts(import_id);")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_activity_summaries (
            import_id TEXT NOT NULL REFERENCES health_imports(import_id) ON DELETE CASCADE,
            date_components TEXT PRIMARY KEY,
            raw_xml TEXT NOT NULL,
            raw_json TEXT NOT NULL
        );
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS health_ecg (
            ecg_id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id TEXT NOT NULL REFERENCES health_imports(import_id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            recorded_at TEXT,
            classification TEXT,
            symptoms TEXT,
            software_version TEXT,
            device TEXT,
            sample_rate_hz INTEGER,
            lead TEXT,
            unit TEXT,
            sha256 TEXT,
            file_size INTEGER
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_health_ecg_import ON health_ecg(import_id);")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_health_ecg_file_path ON health_ecg(file_path);")


# Helpers for import flow (kept here to avoid importer importing store internals)

def create_import_row(
    conn: sqlite3.Connection,
    *,
    import_id: str,
    export_dir: str,
    started_at: str,
    export_date: str | None = None,
    hk_export_version: str | None = None,
    locale: str | None = None,
    me_json: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO health_imports
            (import_id, export_dir, export_date, hk_export_version, locale, me_json, started_at, status, stats_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'running', '{}')
        """,
        (import_id, export_dir, export_date, hk_export_version, locale, me_json, started_at),
    )


def finish_import_row(
    conn: sqlite3.Connection,
    *,
    import_id: str,
    finished_at: str,
    status: str,
    stats: dict | None = None,
    error: str | None = None,
) -> None:
    stats_json = json.dumps(stats or {}, ensure_ascii=False)
    conn.execute(
        """
        UPDATE health_imports
        SET finished_at = ?, status = ?, stats_json = ?, error = ?
        WHERE import_id = ?
        """,
        (finished_at, status, stats_json, error, import_id),
    )


def read_ecg_samples(ecg_file_path: Path, *, limit: int | None = None) -> list[float]:
    """Read ECG samples from a CSV file referenced by health_ecg.file_path.

    The file format is the Apple Health ECG export (Japanese headers).
    Samples start after the line '単位,µV'. Each sample is one value per line.
    Malformed sample rows raise ValueError instead of being silently skipped,
    because silent truncation would corrupt medical waveform data.
    Streams line-by-line so `limit` avoids buffering the whole waveform.
    """
    import math

    samples: list[float] = []
    found_header = False
    in_samples = False

    with ecg_file_path.open(encoding="utf-8-sig", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not found_header:
                if line.startswith("単位") or "µV" in line:
                    found_header = True
                continue
            s = line.strip().strip('"').strip("'")
            if not s:
                continue
            if not in_samples:
                try:
                    v = float(s)
                    if not math.isfinite(v):
                        raise ValueError
                    in_samples = True
                except ValueError:
                    continue
            else:
                if "," in s:
                    raise ValueError(
                        f"Malformed ECG sample row in {ecg_file_path}: {s!r} (unexpected comma)"
                    )
                try:
                    v = float(s)
                except ValueError as exc:
                    raise ValueError(
                        f"Malformed ECG sample row in {ecg_file_path}: {s!r}"
                    ) from exc
                if not math.isfinite(v):
                    raise ValueError(f"Non-finite ECG sample row in {ecg_file_path}: {s!r}")
            samples.append(v)
            if limit is not None and len(samples) >= limit:
                break

    if not found_header:
        raise ValueError(
            f"ECG sample header ('単位,µV') not found in {ecg_file_path}; "
            "refusing to return an empty waveform"
        )
    if not samples:
        raise ValueError(f"No numeric ECG samples found in {ecg_file_path}")
    return samples
