from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.planner import store
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def _fake_external(start_date, end_date):
    return {
        "calendar_events": [
            {
                "title": "Appleイベント",
                "start": "2026-08-20T09:00:00",
                "end": "2026-08-20T10:00:00",
                "all_day": False,
            },
            {
                "title": "終日予定",
                "all_day": True,
                "start": "2026-08-20T00:00:00+09:00",
                "end": "2026-08-20T00:00:00+09:00",
            },
        ],
        "reminders": [{"title": "リマインダー", "due": "2026-08-20"}],
        "error": None,
    }


def _calendar_proposal():
    return store.create_proposal(
        kind="calendar",
        title="歯科検診",
        rationale="根拠",
        generation_source="daily_06:00",
        start_time="2026-08-26T10:00:00",
    )


def test_planner_timeline_merges_layers(test_memory_db_path, client):
    with (
        patch(
            "obsidian_ai_hub.web.services.planner.apple.get_external_data",
            side_effect=_fake_external,
        ),
        patch(
            "obsidian_ai_hub.web.services.planner.recurring.expand_recurring",
            return_value=[
                {
                    "title": "定期掃除",
                    "date": date(2026, 8, 20),
                    "category": 1,
                    "kind": "task",
                    "source": "recurring",
                }
            ],
        ),
    ):
        response = client.get(
            "/api/v1/planner/timeline?start=2026-08-19&end=2026-08-26"
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["apple_events"]) == 2
    assert data["apple_events"][0]["title"] == "Appleイベント"
    assert data["apple_events"][0]["start_time"] == "2026-08-20T09:00:00"
    assert data["apple_events"][1]["all_day"] is True
    assert data["apple_events"][1]["start_time"] == "2026-08-20T00:00:00+09:00"
    assert data["apple_events"][1]["end_time"] == "2026-08-20T00:00:00+09:00"
    assert data["apple_reminders"][0]["title"] == "リマインダー"
    assert data["recurring_events"][0]["title"] == "定期掃除"
    assert data["recurring_events"][0]["date"] == "2026-08-20"
    assert data["apple_error"] is None
    assert data["inbox_pending"] == []


def test_planner_timeline_includes_proposed_proposals(test_memory_db_path, client):
    proposal = _calendar_proposal()
    with (
        patch(
            "obsidian_ai_hub.web.services.planner.apple.get_external_data",
            return_value={
                "calendar_events": [],
                "reminders": [],
                "error": None,
            },
        ),
        patch(
            "obsidian_ai_hub.web.services.planner.recurring.expand_recurring",
            return_value=[],
        ),
    ):
        response = client.get(
            "/api/v1/planner/timeline?start=2026-08-19&end=2026-08-26"
        )

    assert response.status_code == 200
    proposals = response.json()["ai_proposals"]
    assert any(p["proposal_id"] == proposal["proposal_id"] for p in proposals)


def test_planner_proposals_list_and_get(test_memory_db_path, client):
    proposal = _calendar_proposal()

    response = client.get("/api/v1/planner/proposals")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(
        p["proposal_id"] == proposal["proposal_id"] for p in data["items"]
    )

    response = client.get(f"/api/v1/planner/proposals/{proposal['proposal_id']}")
    assert response.status_code == 200
    assert response.json()["title"] == "歯科検診"

    response = client.get("/api/v1/planner/proposals/pp_missing")
    assert response.status_code == 404


def test_planner_proposal_update(test_memory_db_path, client):
    proposal = _calendar_proposal()

    response = client.patch(
        f"/api/v1/planner/proposals/{proposal['proposal_id']}",
        json={"title": "歯科検診(変更)", "location": "駅前"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "歯科検診(変更)"
    assert response.json()["location"] == "駅前"


def test_planner_proposal_reject(test_memory_db_path, client):
    proposal = _calendar_proposal()

    response = client.post(
        f"/api/v1/planner/proposals/{proposal['proposal_id']}/reject", json={}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    response = client.post(
        f"/api/v1/planner/proposals/{proposal['proposal_id']}/reject", json={}
    )
    assert response.status_code == 409


def test_planner_proposal_reject_persists_reason(test_memory_db_path, client):
    proposal = _calendar_proposal()

    response = client.post(
        f"/api/v1/planner/proposals/{proposal['proposal_id']}/reject",
        json={"reason": "下期に延期"},
    )
    assert response.status_code == 200
    assert response.json()["external_result"] == "下期に延期"
    fetched = store.get_proposal(proposal["proposal_id"])
    assert fetched["external_result"] == "下期に延期"


def test_planner_proposal_update_rejects_malformed_datetime(
    test_memory_db_path, client
):
    proposal = _calendar_proposal()

    response = client.patch(
        f"/api/v1/planner/proposals/{proposal['proposal_id']}",
        json={"start_time": "not-a-date"},
    )
    assert response.status_code == 422


def test_planner_timeline_range_limit(test_memory_db_path, client):
    with (
        patch(
            "obsidian_ai_hub.web.services.planner.apple.get_external_data",
            return_value={"calendar_events": [], "reminders": [], "error": None},
        ),
        patch(
            "obsidian_ai_hub.web.services.planner.recurring.expand_recurring",
            return_value=[],
        ),
    ):
        response = client.get(
            "/api/v1/planner/timeline?start=2026-01-01&end=2026-12-31"
        )

    assert response.status_code == 400


def test_planner_proposal_promote(test_memory_db_path, client):
    proposal = _calendar_proposal()
    with patch(
        "obsidian_ai_hub.web.services.planner.promote_service.promote_proposal",
        return_value={
            **store.get_proposal(proposal["proposal_id"]),
            "status": "promoted",
            "promoted_at": "2026-08-19T00:00:00+00:00",
        },
    ) as mock_promote:
        response = client.post(
            f"/api/v1/planner/proposals/{proposal['proposal_id']}/promote"
        )
        mock_promote.assert_called_once_with(proposal["proposal_id"])

    assert response.status_code == 200
    assert response.json()["status"] == "promoted"


def test_planner_generate(test_memory_db_path, client):
    with patch(
        "obsidian_ai_hub.web.services.planner.suggest.generate_proposals",
        return_value=[_calendar_proposal()],
    ) as mock_generate:
        response = client.post("/api/v1/planner/generate")

    assert response.status_code == 200
    data = response.json()
    assert data["generated"] == 1
    assert data["proposals"][0]["kind"] == "calendar"
    mock_generate.assert_called_once_with(source="manual")