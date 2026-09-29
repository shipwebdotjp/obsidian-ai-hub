from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.coach.service import get_current_jst_iso_week_monday
from obsidian_ai_hub.web.app import create_app

TEST_TOKEN = "test-coach-api-token-123"


@pytest.fixture
def client(monkeypatch, tmp_path):
    db_file = tmp_path / "test_coach_api.db"
    monkeypatch.setenv("OBSIDIAN_AI_HUB_MEMORY_SQLITE_PATH", str(db_file))
    from obsidian_ai_hub.database import get_db_connection
    conn = get_db_connection()
    conn.close()

    app = create_app(host="127.0.0.1", port=0, token=TEST_TOKEN)
    with TestClient(app) as test_client:
        yield test_client


def auth_headers():
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def test_coach_api_auth_required(client):
    res = client.get("/api/v1/coach/goals")
    assert res.status_code == 401


def test_coach_api_scenario(client):
    headers = auth_headers()

    # 1. Create Goal
    res_create = client.post(
        "/api/v1/coach/goals",
        headers=headers,
        json={
            "statement": "専門性を身につける",
            "reason": "キャリア成長のため",
            "initial_focuses": ["週1アウトプット", "毎日15分読書"],
        },
    )
    assert res_create.status_code == 201
    goal = res_create.json()
    goal_id = goal["goal_id"]
    assert goal["statement"] == "専門性を身につける"
    assert len(goal["focuses"]) == 2
    f1 = goal["active_focus"]
    assert f1["name"] == "週1アウトプット"
    f2 = [f for f in goal["focuses"] if f["focus_id"] != f1["focus_id"]][0]

    # 2. Add another Focus candidate
    res_f3 = client.post(
        f"/api/v1/coach/goals/{goal_id}/focuses",
        headers=headers,
        json={"name": "勉強会参加"},
    )
    assert res_f3.status_code == 201
    f3 = res_f3.json()
    assert f3["status"] == "candidate"

    # 3. Create Reflection with 'narrow' decision on a previous week
    current_monday = get_current_jst_iso_week_monday()
    prev_monday = (
        datetime.strptime(current_monday, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    res_refl1 = client.post(
        f"/api/v1/coach/focuses/{f1['focus_id']}/reflections",
        headers=headers,
        json={
            "focus_id": f1["focus_id"],
            "iso_week_monday": prev_monday,
            "worked_well": "記事を1本書けた",
            "difficult_reason": "推敲に時間がかかった",
            "learnings": "箇条書きで構成を作る",
            "next_week_scope": "500字程度のショート記事にする",
            "decision_type": "narrow",
        },
    )
    assert res_refl1.status_code == 201
    refl1 = res_refl1.json()
    assert refl1["decision_type"] == "narrow"

    # 4. Create Reflection with 'change' decision on the current (latest) week
    res_refl2 = client.post(
        f"/api/v1/coach/focuses/{f1['focus_id']}/reflections",
        headers=headers,
        json={
            "focus_id": f1["focus_id"],
            "iso_week_monday": current_monday,
            "worked_well": "読書に切り替えたい",
            "decision_type": "change",
            "target_focus_id": f2["focus_id"],
        },
    )
    assert res_refl2.status_code == 201

    # Verify Goal's active focus switched to f2
    res_goal_updated = client.get(f"/api/v1/coach/goals/{goal_id}", headers=headers)
    assert res_goal_updated.status_code == 200
    goal_updated = res_goal_updated.json()
    assert goal_updated["active_focus"]["focus_id"] == f2["focus_id"]

    # Duplicate reflection on same focus and week -> 409 Conflict
    res_refl_dup = client.post(
        f"/api/v1/coach/focuses/{f1['focus_id']}/reflections",
        headers=headers,
        json={
            "focus_id": f1["focus_id"],
            "iso_week_monday": current_monday,
            "worked_well": "重複テスト",
            "decision_type": "continue",
        },
    )
    assert res_refl_dup.status_code == 409

    # 5. Pause Focus
    res_pause = client.post(
        f"/api/v1/coach/focuses/{f2['focus_id']}/pause",
        headers=headers,
    )
    assert res_pause.status_code == 200
    assert res_pause.json()["status"] == "paused"

    # 6. View Coach Thread
    res_thread = client.get(
        f"/api/v1/coach/goals/{goal_id}/thread",
        headers=headers,
    )
    assert res_thread.status_code == 200
    thread = res_thread.json()
    assert thread["total"] >= 4
    assert len(thread["items"]) > 0
    event_types = {item["event_type"] for item in thread["items"]}
    assert "focus_demoted" in event_types
    assert "focus_activated" in event_types


def test_coach_api_backfill_on_non_active_focus(client):
    headers = auth_headers()

    res_create = client.post(
        "/api/v1/coach/goals",
        headers=headers,
        json={
            "statement": "振り返り習慣",
            "reason": "継続のため",
            "initial_focuses": ["朝振り返り", "夜振り返り"],
        },
    )
    assert res_create.status_code == 201
    goal = res_create.json()
    goal_id = goal["goal_id"]
    f1 = goal["active_focus"]
    f2 = [f for f in goal["focuses"] if f["focus_id"] != f1["focus_id"]][0]

    current_monday = get_current_jst_iso_week_monday()
    prev_monday = (
        datetime.strptime(current_monday, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")
    prev_monday_2 = (
        datetime.strptime(current_monday, "%Y-%m-%d") - timedelta(days=14)
    ).strftime("%Y-%m-%d")

    # Latest-week reflection on the active focus.
    res_current = client.post(
        f"/api/v1/coach/focuses/{f1['focus_id']}/reflections",
        headers=headers,
        json={
            "focus_id": f1["focus_id"],
            "iso_week_monday": current_monday,
            "worked_well": "今週はできた",
            "decision_type": "continue",
        },
    )
    assert res_current.status_code == 201

    # Switch focus so f1 is no longer active.
    res_activate = client.post(
        f"/api/v1/coach/focuses/{f2['focus_id']}/activate",
        headers=headers,
    )
    assert res_activate.status_code == 200

    # Backfill a past week on the non-active focus -> allowed.
    res_backfill = client.post(
        f"/api/v1/coach/focuses/{f1['focus_id']}/reflections",
        headers=headers,
        json={
            "focus_id": f1["focus_id"],
            "iso_week_monday": prev_monday,
            "worked_well": "先週の追記",
            "decision_type": "continue",
        },
    )
    assert res_backfill.status_code == 201

    # Change target must differ from the recorded focus.
    res_same_target = client.post(
        f"/api/v1/coach/focuses/{f1['focus_id']}/reflections",
        headers=headers,
        json={
            "focus_id": f1["focus_id"],
            "iso_week_monday": prev_monday_2,
            "worked_well": "自己切替は不可",
            "decision_type": "change",
            "target_focus_id": f1["focus_id"],
        },
    )
    assert res_same_target.status_code == 400

    # Backfilled change decision does not alter the present focus.
    res_f3 = client.post(
        f"/api/v1/coach/goals/{goal_id}/focuses",
        headers=headers,
        json={"name": "週末振り返り"},
    )
    assert res_f3.status_code == 201
    f3 = res_f3.json()

    res_backfill_change2 = client.post(
        f"/api/v1/coach/focuses/{f1['focus_id']}/reflections",
        headers=headers,
        json={
            "focus_id": f1["focus_id"],
            "iso_week_monday": prev_monday_2,
            "worked_well": "さらに前の追記",
            "decision_type": "change",
            "target_focus_id": f3["focus_id"],
        },
    )
    assert res_backfill_change2.status_code == 201

    res_goal = client.get(f"/api/v1/coach/goals/{goal_id}", headers=headers)
    assert res_goal.status_code == 200
    assert res_goal.json()["active_focus"]["focus_id"] == f2["focus_id"]


def test_coach_api_not_found_and_validation(client):
    headers = auth_headers()

    # 404 missing goal
    res_404 = client.get("/api/v1/coach/goals/cgoal_nonexistent", headers=headers)
    assert res_404.status_code == 404

    # Blank statement -> 422 (Pydantic validation)
    res_blank = client.post(
        "/api/v1/coach/goals",
        headers=headers,
        json={"statement": " ", "reason": "理由", "initial_focuses": ["Focus"]},
    )
    assert res_blank.status_code == 422
