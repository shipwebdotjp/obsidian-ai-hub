import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest
from obsidian_ai_hub.healthcare.importer import _fingerprint_record


def _helpers():
    p = Path(__file__).parent / "helpers.py"
    spec = importlib.util.spec_from_file_location("hc_helpers_q", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _fp(type_, source, start, end, value, unit, suffix=""):
    base = _fingerprint_record(
        type_=type_,
        source_name=source,
        source_version=None,
        start_date=start,
        end_date=end,
        value=value,
        unit=unit,
        sync_id=None,
    )
    return base + suffix


def test_get_daily_aggregates_basic(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)
    from obsidian_ai_hub.healthcare.importer import import_export
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection
    from obsidian_ai_hub.healthcare.queries import get_daily_aggregates

    import_export(export_dir)
    conn = get_healthcare_db_connection()
    try:
        # HeartRate has one record on 2026-08-20 value 72
        agg = get_daily_aggregates(conn, type_="HKQuantityTypeIdentifierHeartRate", start_date="2026-08-20", end_date="2026-08-20")
        assert "2026-08-20" in agg
        assert agg["2026-08-20"]["avg"] == pytest.approx(72.0)
        assert agg["2026-08-20"]["min"] == pytest.approx(72.0)
        assert agg["2026-08-20"]["max"] == pytest.approx(72.0)
        assert agg["2026-08-20"]["sum"] == pytest.approx(72.0)
        assert agg["2026-08-20"]["count"] == 1

        # StepCount also on same day
        agg2 = get_daily_aggregates(conn, type_="HKQuantityTypeIdentifierStepCount", start_date="2026-08-20", end_date="2026-08-20")
        assert agg2["2026-08-20"]["sum"] == pytest.approx(120.0)

        # No data day returns empty dict
        agg3 = get_daily_aggregates(conn, type_="HKQuantityTypeIdentifierStepCount", start_date="2026-08-21", end_date="2026-08-21")
        assert agg3 == {}

        # Range including empty days only returns present days
        agg4 = get_daily_aggregates(conn, type_="HKQuantityTypeIdentifierStepCount", start_date="2026-08-19", end_date="2026-08-22")
        assert list(agg4.keys()) == ["2026-08-20"]
    finally:
        conn.close()


def test_get_daily_aggregates_multiple_records_per_day(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)
    from obsidian_ai_hub.healthcare.importer import import_export
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection
    from obsidian_ai_hub.healthcare.queries import get_daily_aggregates

    res = import_export(export_dir)
    import_id = res["import_id"]
    conn = get_healthcare_db_connection()
    try:
        # Insert 3 heart rate records on 2026-08-21
        for i, v in enumerate([60, 80, 70]):
            sd = f"2026-08-21 0{i+8}:00:00 +0900"
            ed = f"2026-08-21 0{i+8}:01:00 +0900"
            conn.execute(
                "INSERT OR IGNORE INTO health_records (import_id,type,value_text,value_numeric,unit,source_name,start_date,end_date,fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
                (import_id, "HKQuantityTypeIdentifierHeartRate", str(v), float(v), "count/min", "TestWatch", sd, ed, _fp("HKQuantityTypeIdentifierHeartRate", "TestWatch", sd, ed, str(v), "count/min", str(i))),
            )
        conn.commit()
        agg = get_daily_aggregates(conn, type_="HKQuantityTypeIdentifierHeartRate", start_date="2026-08-21", end_date="2026-08-21")
        assert agg["2026-08-21"]["count"] == 3
        assert agg["2026-08-21"]["avg"] == pytest.approx(70.0)
        assert agg["2026-08-21"]["min"] == pytest.approx(60.0)
        assert agg["2026-08-21"]["max"] == pytest.approx(80.0)
        assert agg["2026-08-21"]["sum"] == pytest.approx(210.0)
    finally:
        conn.close()


def test_healthcare_overview_day_granularity(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)
    from obsidian_ai_hub.healthcare.importer import import_export

    res = import_export(export_dir)
    import_id = res["import_id"]
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection

    # Insert steps for 2026-08-01..2026-08-05
    conn = get_healthcare_db_connection()
    try:
        base = date(2026, 8, 1)
        for i in range(5):
            d = base + timedelta(days=i)
            sd = f"{d.isoformat()} 08:00:00 +0900"
            ed = f"{d.isoformat()} 08:01:00 +0900"
            v = str(1000 * (i + 1))
            conn.execute(
                "INSERT OR IGNORE INTO health_records (import_id,type,value_text,value_numeric,unit,source_name,start_date,end_date,fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
                (import_id, "HKQuantityTypeIdentifierStepCount", v, float(v), "count", "TestWatch", sd, ed, _fp("HKQuantityTypeIdentifierStepCount", "TestWatch", sd, ed, v, "count", str(i))),
            )
        conn.commit()
    finally:
        conn.close()

    from obsidian_ai_hub.web.services.healthcare import get_healthcare_overview

    resp = get_healthcare_overview("2026-08-01", "2026-08-05")
    assert resp["granularity"] == "day"
    assert resp["start_date"] == "2026-08-01"
    assert resp["end_date"] == "2026-08-05"
    assert len(resp["metrics"]) == 9
    steps = next(m for m in resp["metrics"] if m["key"] == "steps")
    assert len(steps["buckets"]) == 5
    # Values should be 1000,2000,3000,4000,5000
    vals = [b["value"] for b in steps["buckets"]]
    assert vals == [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
    assert steps["latest_value"] == pytest.approx(5000.0)
    assert steps["previous_value"] == pytest.approx(4000.0)
    assert steps["delta_pct"] == pytest.approx(25.0)
    # HeartRate metric only has 2026-08-20 in fixture, so this range has no HR data
    hr = next(m for m in resp["metrics"] if m["key"] == "heart_rate")
    assert all(b["value"] is None for b in hr["buckets"])
    assert hr["latest_value"] is None


def test_healthcare_overview_week_granularity(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)
    from obsidian_ai_hub.healthcare.importer import import_export

    import_export(export_dir)
    from obsidian_ai_hub.web.services.healthcare import get_healthcare_overview

    # 61 days -> week granularity
    resp = get_healthcare_overview("2026-06-01", "2026-07-31")
    assert resp["granularity"] == "week"
    # Buckets are ISO weeks, count depends on calendar. For Jun 1..Jul31 there are ~9 weeks.
    assert len(resp["metrics"][0]["buckets"]) >= 8
    # Each bucket should have display_label like Wxx
    assert resp["metrics"][0]["buckets"][0]["display_label"].startswith("W")


def test_healthcare_overview_month_granularity(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)
    from obsidian_ai_hub.healthcare.importer import import_export

    import_export(export_dir)
    from obsidian_ai_hub.web.services.healthcare import get_healthcare_overview

    # >366 days -> month
    resp = get_healthcare_overview("2025-01-01", "2026-12-31")
    assert resp["granularity"] == "month"
    assert len(resp["metrics"][0]["buckets"]) == 24
    assert resp["metrics"][0]["buckets"][0]["display_label"] == "2025/01"


def test_healthcare_overview_validation():
    from obsidian_ai_hub.web.services.healthcare import get_healthcare_overview

    with pytest.raises(ValueError, match="Invalid date format"):
        get_healthcare_overview("bad", "2026-08-10")
    with pytest.raises(ValueError, match="start_date must be"):
        get_healthcare_overview("2026-08-10", "2026-08-01")
    with pytest.raises(ValueError, match="exceeds maximum"):
        get_healthcare_overview("2010-01-01", "2026-01-01")


def test_healthcare_overview_avg_aggregation(test_healthcare_db_path: Path, tmp_path: Path):
    helpers = _helpers()
    export_dir = helpers.write_mini_export(tmp_path)
    from obsidian_ai_hub.healthcare.importer import import_export

    res = import_export(export_dir)
    import_id = res["import_id"]
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection
    from obsidian_ai_hub.web.services.healthcare import get_healthcare_overview

    # Insert 3 HR on same day to test avg aggregation bucket
    conn = get_healthcare_db_connection()
    try:
        for i, v in enumerate([60, 80, 70]):
            sd = f"2026-08-22 0{i+8}:00:00 +0900"
            ed = f"2026-08-22 0{i+8}:01:00 +0900"
            conn.execute(
                "INSERT OR IGNORE INTO health_records (import_id,type,value_text,value_numeric,unit,source_name,start_date,end_date,fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
                (import_id, "HKQuantityTypeIdentifierHeartRate", str(v), float(v), "count/min", "TestWatch", sd, ed, _fp("HKQuantityTypeIdentifierHeartRate", "TestWatch", sd, ed, str(v), "count/min", f"hr22-{i}")),
            )
        conn.commit()
    finally:
        conn.close()

    resp = get_healthcare_overview("2026-08-22", "2026-08-22")
    hr = next(m for m in resp["metrics"] if m["key"] == "heart_rate")
    assert len(hr["buckets"]) == 1
    b = hr["buckets"][0]
    # avg should be 70, sum 210, min 60, max 80, count 3, value == avg for avg aggregation
    assert b["value"] == pytest.approx(70.0)
    assert b["avg"] == pytest.approx(70.0)
    assert b["min"] == pytest.approx(60.0)
    assert b["max"] == pytest.approx(80.0)
    assert b["sum"] == pytest.approx(210.0)
    assert b["count"] == 3


def test_healthcare_overview_empty_db(test_healthcare_db_path: Path):
    # No import at all; DB is empty but schema exists
    from obsidian_ai_hub.web.services.healthcare import get_healthcare_overview

    resp = get_healthcare_overview("2026-08-01", "2026-08-07")
    assert resp["granularity"] == "day"
    assert len(resp["metrics"]) == 9
    for m in resp["metrics"]:
        assert all(b["value"] is None for b in m["buckets"])
        assert m["latest_value"] is None
        assert m["delta_pct"] is None
