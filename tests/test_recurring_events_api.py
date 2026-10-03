"""Tests for recurring events REST API endpoints."""

import pytest
from fastapi.testclient import TestClient
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def client():
    app = create_app(host="127.0.0.1", port=0, token="test-token")
    return TestClient(app)


def test_recurring_events_api_flow(client):
    headers = {"Authorization": "Bearer test-token"}

    # 1. Create Event Type
    resp = client.post(
        "/api/v1/recurring-event-types",
        headers=headers,
        json={
            "name": "車検・整備",
            "properties": [
                {
                    "key": "car",
                    "display_name": "車種",
                    "data_type": "text",
                }
            ],
        },
    )
    assert resp.status_code == 201
    type_data = resp.json()
    type_id = type_data["type_id"]
    assert type_data["name"] == "車検・整備"

    # 2. List Event Types
    resp = client.get("/api/v1/recurring-event-types", headers=headers)
    assert resp.status_code == 200
    types = resp.json()
    assert any(t["type_id"] == type_id for t in types)

    # 3. Create Series
    resp = client.post(
        "/api/v1/recurring-event-series",
        headers=headers,
        json={
            "type_id": type_id,
            "interval_value": 2,
            "interval_unit": "year",  # Wait, interval_unit validation accepts day, week, month!
            "property_values": {"car": "プリウス"},
            "executed_on": "2024-01-01",
        },
    )
    # Should fail validation because 'year' is not in (day, week, month)
    assert resp.status_code == 400

    resp = client.post(
        "/api/v1/recurring-event-series",
        headers=headers,
        json={
            "type_id": type_id,
            "interval_value": 24,
            "interval_unit": "month",
            "property_values": {"car": "プリウス"},
            "executed_on": "2024-01-01",
            "note": "2年車検",
        },
    )
    assert resp.status_code == 201
    series_data = resp.json()
    series_id = series_data["series_id"]
    assert series_data["interval_value"] == 24
    assert series_data["interval_unit"] == "month"

    # 4. List Series
    resp = client.get("/api/v1/recurring-event-series", headers=headers)
    assert resp.status_code == 200
    series_list = resp.json()
    assert len(series_list) >= 1

    # 5. Add Record
    resp = client.post(
        f"/api/v1/recurring-event-series/{series_id}/records",
        headers=headers,
        json={
            "executed_on": "2024-01-02",
            "note": "定期点検追加",
        },
    )
    assert resp.status_code == 201
    updated_series = resp.json()
    assert len(updated_series["records"]) == 2

    # 6. Delete Record
    rec_id = updated_series["records"][0]["record_id"]
    resp = client.delete(f"/api/v1/recurring-event-records/{rec_id}", headers=headers)
    assert resp.status_code == 200
    res = resp.json()
    assert res["success"] is True
    assert res["series_deleted"] is False
