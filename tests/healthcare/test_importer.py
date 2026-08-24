import importlib.util
import json
from pathlib import Path

import pytest


def _helpers():
    p = Path(__file__).parent / "helpers.py"
    spec = importlib.util.spec_from_file_location("hc_helpers_imp", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_import_mini_counts_and_tables(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)

    from obsidian_ai_hub.healthcare.importer import import_export
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection

    result = import_export(export_dir)
    assert result["records"] == 7  # 3 quantity + 1 HRV + 3 category
    assert result["workouts"] == 1
    assert result["activity_summaries"] == 1
    assert result["ecg_files"] == 1
    assert result["cda_skipped"] is True

    conn = get_healthcare_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM health_records").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM health_record_metadata").fetchone()[0] >= 3
        # HRV beats for the HRVSDNN record
        assert conn.execute("SELECT COUNT(*) FROM health_hrv_beats").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM health_workouts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM health_workout_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM health_workout_statistics").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM health_workout_routes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM health_activity_summaries").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM health_ecg").fetchone()[0] == 1
        # No samples table
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "health_ecg_samples" not in tables

        # health_imports succeeded
        row = conn.execute("SELECT status, export_date, locale, me_json FROM health_imports WHERE import_id=?", (result["import_id"],)).fetchone()
        assert row["status"] == "succeeded"
        assert row["export_date"] == "2026-08-24 17:11:51 +0900"
        assert row["locale"] == "ja_JP"
        assert row["me_json"] is not None
        me = json.loads(row["me_json"])
        assert "HKCharacteristicTypeIdentifierDateOfBirth" in me

        # Quantity numeric vs category text
        hr = conn.execute("SELECT value_text, value_numeric, unit FROM health_records WHERE type='HKQuantityTypeIdentifierHeartRate'").fetchone()
        assert hr["value_numeric"] == pytest.approx(72.0)
        assert hr["value_text"] == "72"
        assert hr["unit"] == "count/min"

        sleep = conn.execute("SELECT value_text, value_numeric, unit FROM health_records WHERE type='HKCategoryTypeIdentifierSleepAnalysis' LIMIT 1").fetchone()
        assert sleep["value_text"] is not None
        assert sleep["value_numeric"] is None
        assert sleep["unit"] is None

        # ECG file_path is relative
        ecg = conn.execute("SELECT file_path, file_name, sample_rate_hz FROM health_ecg LIMIT 1").fetchone()
        assert ecg["file_path"] == "electrocardiograms/ecg_2026-08-20.csv"
        assert ecg["file_name"] == "ecg_2026-08-20.csv"
        assert ecg["sample_rate_hz"] == 512

        # Metadata for sync identifier
        meta = conn.execute("SELECT mkey, mvalue FROM health_record_metadata WHERE mkey='HKMetadataKeySyncIdentifier'").fetchone()
        assert meta is not None
        assert meta["mvalue"] == "sync-hr-001"
    finally:
        conn.close()


def test_idempotent_second_import(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)

    from obsidian_ai_hub.healthcare.importer import import_export
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection

    r1 = import_export(export_dir)
    r2 = import_export(export_dir)
    assert r2["ignored_duplicates"] == 7 + 1 + 1  # records+workouts+activity
    conn = get_healthcare_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM health_records").fetchone()[0] == 7
        assert conn.execute("SELECT COUNT(*) FROM health_workouts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM health_ecg").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM health_imports").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM health_imports WHERE status='succeeded'").fetchone()[0] == 2
    finally:
        conn.close()


def test_fingerprint_uses_sync_id(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    # Two records with same syncId but different dates should be considered duplicate (fingerprint = type|syncId)
    # The second should be ignored on second import, but within a single file with two same syncIds, second is duplicate.
    extra = (
        '<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="TestWatch" sourceVersion="11.4" unit="count/min"'
        ' creationDate="2026-08-20 10:00:00 +0900" startDate="2026-08-20 10:00:00 +0900" endDate="2026-08-20 10:01:00 +0900" value="80">'
        ' <MetadataEntry key="HKMetadataKeySyncIdentifier" value="dup-sync"/>'
        '</Record>'
        '<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="TestWatch" sourceVersion="11.4" unit="count/min"'
        ' creationDate="2026-08-20 11:00:00 +0900" startDate="2026-08-20 11:00:00 +0900" endDate="2026-08-20 11:01:00 +0900" value="85">'
        ' <MetadataEntry key="HKMetadataKeySyncIdentifier" value="dup-sync"/>'
        '</Record>'
    )
    export_dir = helpers.write_mini_export(tmp_path, extra_records_xml=extra)

    from obsidian_ai_hub.healthcare.importer import import_export
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection

    result = import_export(export_dir)
    # Mini has 7 records + 2 extra but second extra is duplicate syncId -> only 1 new
    assert result["records"] == 9  # attempted
    assert result["ignored_duplicates"] >= 1
    conn = get_healthcare_db_connection()
    try:
        # Only one of the dup-sync records should be stored
        assert conn.execute("SELECT COUNT(*) FROM health_records WHERE fingerprint IN (SELECT fingerprint FROM health_records WHERE type='HKQuantityTypeIdentifierHeartRate' GROUP BY fingerprint HAVING COUNT(*)>1)").fetchone()[0] == 0
        # Specifically count of dup-sync fingerprint should be 1
        # Compute expected fingerprint to verify
        import hashlib

        fp = hashlib.sha256("HKQuantityTypeIdentifierHeartRate|dup-sync".encode()).hexdigest()
        assert conn.execute("SELECT COUNT(*) FROM health_records WHERE fingerprint=?", (fp,)).fetchone()[0] == 1
    finally:
        conn.close()


def test_dry_run_does_not_write(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)

    from obsidian_ai_hub.healthcare.importer import import_export
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection

    result = import_export(export_dir, dry_run=True)
    assert result["dry_run"] is True
    assert result["records"] == 7
    conn = get_healthcare_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM health_imports").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM health_records").fetchone()[0] == 0
    finally:
        conn.close()


def test_import_without_ecg(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path, include_ecg=False)

    from obsidian_ai_hub.healthcare.importer import import_export
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection

    result = import_export(export_dir)
    assert result["ecg_files"] == 0
    conn = get_healthcare_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM health_ecg").fetchone()[0] == 0
    finally:
        conn.close()


def test_cli_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)

    from obsidian_ai_hub.import_apple_health import main

    result = main(["--export-dir", str(export_dir)])
    assert result["records"] == 7
    assert result["workouts"] == 1


def test_missing_export_dir_raises(tmp_path: Path):
    from obsidian_ai_hub.healthcare.importer import import_export

    with pytest.raises(FileNotFoundError, match="Export dir not found"):
        import_export(tmp_path / "nonexistent")

    helpers = _helpers()
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="export.xml not found"):
        import_export(empty_dir)


def test_cli_dry_run(tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)

    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection
    from obsidian_ai_hub.import_apple_health import main

    result = main(["--export-dir", str(export_dir), "--dry-run"])
    assert result["dry_run"] is True
    assert result["records"] == 7
    conn = get_healthcare_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM health_imports").fetchone()[0] == 0
    finally:
        conn.close()


def test_cli_batch_size_validation(tmp_path: Path):
    from obsidian_ai_hub.import_apple_health import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--batch-size", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--batch-size", "-5"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--batch-size", "notanint"])


def test_failed_import_rollback(test_healthcare_db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)

    from obsidian_ai_hub.healthcare import importer as imp_mod
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection

    orig_handle = imp_mod._handle_record

    call_count = {"n": 0}

    def failing_handle(elem, import_id, conn):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise RuntimeError("injected failure on 3rd record")
        return orig_handle(elem, import_id, conn)

    monkeypatch.setattr(imp_mod, "_handle_record", failing_handle)

    with pytest.raises(RuntimeError, match="injected failure"):
        imp_mod.import_export(export_dir)

    conn = get_healthcare_db_connection()
    try:
        # No partial rows should be committed; only the failed import row remains
        assert conn.execute("SELECT COUNT(*) FROM health_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM health_record_metadata").fetchone()[0] == 0
        row = conn.execute("SELECT status, error FROM health_imports").fetchone()
        assert row is not None
        assert row["status"] == "failed"
        assert "injected failure" in (row["error"] or "")

        # Subsequent successful import should succeed and create rows
        monkeypatch.setattr(imp_mod, "_handle_record", orig_handle)
        result = imp_mod.import_export(export_dir)
        assert result["records"] == 7
        assert conn.execute("SELECT COUNT(*) FROM health_records").fetchone()[0] == 7
    finally:
        conn.close()
