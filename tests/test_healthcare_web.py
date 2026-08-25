from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.healthcare.helpers import write_mini_export

from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def healthcare_client(test_healthcare_db_path, api_token, api_auth_headers):
    # Seed some data via importer helpers so overview is non-empty
    tmp_root = test_healthcare_db_path.parent
    export_dir = write_mini_export(tmp_root)
    from obsidian_ai_hub.healthcare.importer import import_export

    import_export(export_dir)
    app = create_app(token=api_token)
    return TestClient(app, headers=api_auth_headers)


def test_healthcare_overview_requires_auth(test_healthcare_db_path, api_token):
    app = create_app(token=api_token)
    client = TestClient(app)
    res = client.get("/api/v1/healthcare/overview?start_date=2026-08-01&end_date=2026-08-31")
    assert res.status_code == 401


def test_healthcare_overview_success(healthcare_client):
    # Window that includes the seeded mini export date 2026-08-20 so latest_value is populated.
    res = healthcare_client.get("/api/v1/healthcare/overview?start_date=2026-08-15&end_date=2026-08-21")
    assert res.status_code == 200
    data = res.json()
    assert data["start_date"] == "2026-08-15"
    assert data["end_date"] == "2026-08-21"
    assert data["granularity"] == "day"
    assert len(data["metrics"]) == 11
    # success path should populate latest_value for seeded data (mini export has 2026-08-20)
    assert any(m["latest_value"] is not None for m in data["metrics"])
    #睡眠・スタンドも含まれる
    keys = {m["key"] for m in data["metrics"]}
    assert "sleep" in keys
    assert "stand_hours" in keys
    # Each metric should have buckets length = 7 for day granularity 7 days
    for m in data["metrics"]:
        assert "key" in m
        assert "label" in m
        assert "unit" in m
        assert "aggregation" in m
        assert "buckets" in m
        assert len(m["buckets"]) == 7
        for b in m["buckets"]:
            assert "key" in b
            assert "display_label" in b
            assert "value" in b
            assert "count" in b


def test_healthcare_overview_week_and_month(healthcare_client):
    res = healthcare_client.get("/api/v1/healthcare/overview?start_date=2026-06-01&end_date=2026-07-31")
    assert res.status_code == 200
    assert res.json()["granularity"] == "week"
    res2 = healthcare_client.get("/api/v1/healthcare/overview?start_date=2025-01-01&end_date=2026-12-31")
    assert res2.status_code == 200
    assert res2.json()["granularity"] == "month"


def test_healthcare_overview_bad_date(healthcare_client):
    res = healthcare_client.get("/api/v1/healthcare/overview?start_date=2026-13-01&end_date=2026-08-31")
    assert res.status_code == 400
    res2 = healthcare_client.get("/api/v1/healthcare/overview?start_date=2026-08-31&end_date=2026-08-01")
    assert res2.status_code == 400
    res3 = healthcare_client.get("/api/v1/healthcare/overview?start_date=2010-01-01&end_date=2026-01-01")
    assert res3.status_code == 400


def test_healthcare_overview_empty_when_no_data(test_healthcare_db_path, api_token, api_auth_headers):
    # No import seeded
    app = create_app(token=api_token)
    client = TestClient(app, headers=api_auth_headers)
    res = client.get("/api/v1/healthcare/overview?start_date=2026-08-01&end_date=2026-08-07")
    assert res.status_code == 200
    data = res.json()
    for m in data["metrics"]:
        assert m["latest_value"] is None
        assert all(b["value"] is None for b in m["buckets"])


def test_healthcare_correlation_requires_auth(test_healthcare_db_path, api_token):
    app = create_app(token=api_token)
    client = TestClient(app)
    res = client.get("/api/v1/healthcare/correlation?metric_x=steps&metric_y=sleep&start_date=2026-08-01&end_date=2026-08-07")
    assert res.status_code == 401


def test_healthcare_correlation_success(healthcare_client):
    # Seed extra correlated data: steps 3000+500*i and sleep 6+0.5*i for 5 days
    from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection
    from obsidian_ai_hub.healthcare.importer import _fingerprint_record
    from datetime import date, timedelta

    conn = get_healthcare_db_connection()
    import_id = conn.execute("SELECT import_id FROM health_imports LIMIT 1").fetchone()[0]
    for i, day in enumerate(["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]):
        val = str(3000 + i * 500)
        sd = f"{day} 08:00:00 +0900"
        ed = f"{day} 08:01:00 +0900"
        fp = _fingerprint_record(type_="HKQuantityTypeIdentifierStepCount", source_name="TestWatch", source_version=None, start_date=sd, end_date=ed, value=val, unit="count", sync_id=None)
        conn.execute(
            "INSERT OR IGNORE INTO health_records (import_id,type,value_text,value_numeric,unit,source_name,start_date,end_date,fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
            (import_id, "HKQuantityTypeIdentifierStepCount", val, float(val), "count", "TestWatch", sd, ed, fp),
        )
        s2 = f"{day} 23:05:00 +0900"
        dt = date.fromisoformat(day)
        nd = (dt + timedelta(days=1)).isoformat()
        total_min = 5 + i * 30
        hour = 5 + total_min // 60
        minute = total_min % 60
        ed2 = f"{nd} {hour:02d}:{minute:02d}:00 +0900"
        fp2 = _fingerprint_record(type_="HKCategoryTypeIdentifierSleepAnalysis", source_name="TestWatch", source_version=None, start_date=s2, end_date=ed2, value="HKCategoryValueSleepAnalysisAsleepCore", unit=None, sync_id=None)
        conn.execute(
            "INSERT OR IGNORE INTO health_records (import_id,type,value_text,value_numeric,unit,source_name,start_date,end_date,fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
            (import_id, "HKCategoryTypeIdentifierSleepAnalysis", "HKCategoryValueSleepAnalysisAsleepCore", None, None, "TestWatch", s2, ed2, fp2),
        )
    conn.commit()
    conn.close()

    res = healthcare_client.get("/api/v1/healthcare/correlation?metric_x=steps&metric_y=sleep&start_date=2026-08-10&end_date=2026-08-14")
    assert res.status_code == 200
    data = res.json()
    assert data["metric_x"] == "steps"
    assert data["metric_y"] == "sleep"
    assert data["start_date"] == "2026-08-10"
    assert data["end_date"] == "2026-08-14"
    assert data["granularity"] == "day"
    assert data["n"] == 5
    assert len(data["points"]) == 5
    # Strong positive correlation
    assert data["pearson_r"] == pytest.approx(1.0, abs=0.01)
    assert data["regression_slope"] is not None
    assert data["regression_intercept"] is not None
    # Points are sorted by date
    assert data["points"][0]["date"] == "2026-08-10"
    assert data["points"][0]["x"] == pytest.approx(3000.0)
    assert data["points"][0]["y"] == pytest.approx(6.0, abs=0.05)


def test_healthcare_correlation_empty_and_single_point(healthcare_client):
    # Empty range
    res = healthcare_client.get("/api/v1/healthcare/correlation?metric_x=steps&metric_y=sleep&start_date=2020-01-01&end_date=2020-01-05")
    assert res.status_code == 200
    data = res.json()
    assert data["n"] == 0
    assert data["pearson_r"] is None
    assert data["points"] == []

    # Single point -> pearson is None. healthcare_client is function-scoped with a fresh DB
    # seeded only with the mini export, so this single-day window has exactly one common day.
    res2 = healthcare_client.get("/api/v1/healthcare/correlation?metric_x=steps&metric_y=sleep&start_date=2026-08-20&end_date=2026-08-20")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["n"] == 1
    assert data2["pearson_r"] is None
    assert data2["regression_slope"] is None


def test_healthcare_correlation_bad_metric(healthcare_client):
    res = healthcare_client.get("/api/v1/healthcare/correlation?metric_x=unknown&metric_y=sleep&start_date=2026-08-01&end_date=2026-08-07")
    assert res.status_code == 400
    res2 = healthcare_client.get("/api/v1/healthcare/correlation?metric_x=steps&metric_y=unknown&start_date=2026-08-01&end_date=2026-08-07")
    assert res2.status_code == 400
    res3 = healthcare_client.get("/api/v1/healthcare/correlation?metric_x=steps&metric_y=sleep&start_date=2026-08-31&end_date=2026-08-01")
    assert res3.status_code == 400
    res4 = healthcare_client.get("/api/v1/healthcare/correlation?metric_x=steps&metric_y=sleep&start_date=2010-01-01&end_date=2026-01-01")
    assert res4.status_code == 400
