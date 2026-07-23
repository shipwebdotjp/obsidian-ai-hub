from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub import database
from obsidian_ai_hub import hitl
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_hitl_api_lifecycle(test_memory_db_path, client):
    conn = database.get_db_connection()
    try:
        run_id = "api_run_test"
        handler = "dummy_handler"
        checkpoint = "init_check"
        question_set_id = "set_api_1"

        questions_data = [
            {
                "question_key": "q_bool",
                "question_type": "boolean",
                "display_text": "Is this a test?",
                "choices": [True, False],
                "is_required": 1,
            },
            {
                "question_key": "q_comment",
                "question_type": "text",
                "display_text": "Any feedback?",
                "is_required": 0,
            },
        ]

        # Register run & questions
        hitl.register_run_and_questions(
            run_id=run_id,
            handler=handler,
            checkpoint=checkpoint,
            question_set_id=question_set_id,
            questions_data=questions_data,
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()

    # 1. GET /api/v1/hitl/runs - Paginated list of HITL runs
    response = client.get("/api/v1/hitl/runs")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1

    # Check that our run is in the list
    runs = [r for r in data["items"] if r["run_id"] == run_id]
    assert len(runs) == 1
    assert runs[0]["status"] == "pending_user"

    # 2. GET /api/v1/hitl/runs/{run_id} - Run detail with questions
    response = client.get(f"/api/v1/hitl/runs/{run_id}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["run_id"] == run_id
    assert detail["handler"] == handler
    assert "questions" in detail
    assert len(detail["questions"]) == 2

    # Verify deserialization
    q_map = {q["question_key"]: q for q in detail["questions"]}
    assert q_map["q_bool"]["choices"] == [True, False]
    assert q_map["q_bool"]["status"] == "pending"

    # 3. POST /api/v1/hitl/runs/{run_id}/questions/{question_key}/answer - Submit answer
    # Try invalid choice first (choices: [True, False])
    response = client.post(
        f"/api/v1/hitl/runs/{run_id}/questions/q_bool/answer",
        json={"answer": "invalid_choice"}
    )
    assert response.status_code == 400

    # Submit valid choice
    response = client.post(
        f"/api/v1/hitl/runs/{run_id}/questions/q_bool/answer",
        json={"answer": True}
    )
    assert response.status_code == 200
    assert response.json() == {"success": True}

    # Verify run transitioned to ready_to_resume (all required are answered)
    response = client.get(f"/api/v1/hitl/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "ready_to_resume"

    # 4. POST /api/v1/hitl/runs/{run_id}/cancel - Cancel run
    # Create another run to test cancellation
    conn = database.get_db_connection()
    try:
        hitl.register_run_and_questions(
            run_id="cancel_run_test",
            handler="dummy",
            checkpoint="none",
            question_set_id="qs",
            questions_data=[{"question_key": "q", "question_type": "text", "display_text": "text"}],
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post("/api/v1/hitl/runs/cancel_run_test/cancel")
    assert response.status_code == 200
    assert response.json() == {"success": True}

    # Check status is cancelled
    response = client.get("/api/v1/hitl/runs/cancel_run_test")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
