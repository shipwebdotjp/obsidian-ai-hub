from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub import database
from obsidian_ai_hub import hitl
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


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


def test_hitl_api_requires_token_when_not_loopback(test_memory_db_path):
    """HITL endpoints must return 401 on non-loopback host without a valid token."""
    app = create_app(host="0.0.0.0", port=0, token="secret-token")
    client = TestClient(app)

    conn = database.get_db_connection()
    try:
        hitl.register_run_and_questions(
            run_id="run_auth_test",
            handler="dummy",
            checkpoint="chk",
            question_set_id="qs",
            questions_data=[{"question_key": "q", "question_type": "text", "display_text": "Q", "is_required": 1}],
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()

    protected = [
        ("GET", "/api/v1/hitl/runs", None),
        ("GET", "/api/v1/hitl/runs/run_auth_test", None),
        ("POST", "/api/v1/hitl/runs/run_auth_test/questions/q/answer", {"answer": "x"}),
        ("POST", "/api/v1/hitl/runs/run_auth_test/cancel", None),
    ]
    for method, path, payload in protected:
        kwargs = {"json": payload} if payload else {}
        res = client.request(method, path, **kwargs)
        assert res.status_code == 401, (method, path, res.status_code)

        res = client.request(method, path, headers={"Authorization": "Bearer wrong"}, **kwargs)
        assert res.status_code == 401, (method, path, res.status_code)

        res = client.request(method, path, headers={"Authorization": "Bearer secret-token"}, **kwargs)
        assert res.status_code == 200, (method, path, res.status_code)


def test_hitl_api_list_pagination_and_status_filter(test_memory_db_path, client):
    """List endpoint supports status filter and limit/offset pagination."""
    conn = database.get_db_connection()
    try:
        for i in range(3):
            hitl.register_run_and_questions(
                run_id=f"run_pag_{i}",
                handler="dummy",
                checkpoint="chk",
                question_set_id="qs",
                questions_data=[{"question_key": "q", "question_type": "text", "display_text": "Q"}],
                conn=conn,
            )
        conn.commit()
    finally:
        conn.close()

    res = client.get("/api/v1/hitl/runs?status=pending_user")
    assert res.status_code == 200
    data = res.json()
    assert all(item["status"] == "pending_user" for item in data["items"])

    res = client.get("/api/v1/hitl/runs?limit=1&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) <= 1
    assert data["total"] >= 0


def test_hitl_api_returns_404_for_missing_run(client):
    """Detail endpoint returns 404 for non-existent runs."""
    res = client.get("/api/v1/hitl/runs/non_existent_run")
    assert res.status_code == 404

    res = client.post("/api/v1/hitl/runs/non_existent_run/questions/q/answer", json={"answer": "x"})
    assert res.status_code == 404

    res = client.post("/api/v1/hitl/runs/non_existent_run/cancel")
    assert res.status_code == 404


def test_hitl_api_rejects_answer_after_run_completed(test_memory_db_path, client):
    """Submitting an answer to a completed run returns a 409 or 400."""
    conn = database.get_db_connection()
    try:
        hitl.register_run_and_questions(
            run_id="run_completed",
            handler="dummy",
            checkpoint="chk",
            question_set_id="qs",
            questions_data=[{"question_key": "q", "question_type": "text", "display_text": "Q", "is_required": 1}],
            conn=conn,
        )
        hitl.submit_answer("run_completed", "qs", "q", "done", conn)

        def completing_handler(ctx):
            return hitl.HitlResult.complete(checkpoint="done")
        hitl.register_handler("dummy", completing_handler)
        try:
            hitl.dispatch_runs(conn)
        finally:
            hitl.clear_handlers()
    finally:
        conn.close()

    res = client.post("/api/v1/hitl/runs/run_completed/questions/q/answer", json={"answer": "x"})
    assert res.status_code == 400


def test_hitl_api_returns_404_for_cancel_on_missing_run(test_memory_db_path, client):
    """Cancelling a non-existent run returns 404."""
    res = client.post("/api/v1/hitl/runs/non_existent_cancel_test/cancel")
    assert res.status_code == 404
