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
    assert len(data["metrics"]) == 9
    # success path should populate latest_value for seeded data (mini export has 2026-08-20)
    assert any(m["latest_value"] is not None for m in data["metrics"])
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
