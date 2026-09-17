import pytest
from obsidian_ai_hub.coding import store
from obsidian_ai_hub.web.routes.coding import StartCodingRunRequest, SlashInvocationModel


def test_compute_idempotency_hash_includes_slash_invocation():
    h1 = store.compute_idempotency_hash("hello", None)
    h2 = store.compute_idempotency_hash("hello", {"kind": "skill", "name": "pdftomd"})
    h3 = store.compute_idempotency_hash("hello", {"kind": "skill", "name": "other"})

    assert h1 != h2
    assert h2 != h3


def test_start_queued_run_persists_and_restores_slash_invocation(tmp_path, monkeypatch):
    from obsidian_ai_hub.database import get_db_connection

    db = get_db_connection()

    cur = db.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, keywords, created_at, updated_at) "
        "VALUES ('test_repo', 'Test Repo', 'work', 'active', '[]', '2026-01-01', '2026-01-01')"
    )
    project_id = cur.lastrowid
    db.commit()

    sess = store.create_session(
        project_id=project_id,
        backend="opencode",
        repo_path=str(tmp_path),
        title="Test Session",
    )
    session_id = sess["session_id"]

    slash_inv = {"kind": "skill", "name": "pdftomd"}
    msg, run = store.start_queued_run(
        session_id=session_id,
        content="Convert PDF to MD",
        idempotency_key="key1",
        slash_invocation=slash_inv,
    )

    assert run["slash_invocation"] == slash_inv

    fetched_run = store.get_run(run["run_id"])
    assert fetched_run["slash_invocation"] == slash_inv


def test_slash_candidates_and_validation_errors(tmp_path, monkeypatch):
    from obsidian_ai_hub.database import get_db_connection
    from obsidian_ai_hub.web.routes.coding import get_slash_candidates, start_coding_run
    from fastapi import HTTPException

    db = get_db_connection()
    cur = db.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, keywords, created_at, updated_at) "
        "VALUES ('test_repo_2', 'Test Repo 2', 'work', 'active', '[]', '2026-01-01', '2026-01-01')"
    )
    project_id = cur.lastrowid
    db.commit()

    # Create session with skills tool disabled
    sess = store.create_session(
        project_id=project_id,
        backend="opencode",
        repo_path=str(tmp_path),
        title="No Skills Session",
        tool_ids=["web_search"],
    )
    session_id = sess["session_id"]

    res = get_slash_candidates(session_id)
    assert res["has_skills_tool"] is False
    assert res["candidates"] == []

    # Attempting to start run with slash_invocation when skills disabled returns 400
    req = StartCodingRunRequest(
        content="Convert PDF",
        slash_invocation=SlashInvocationModel(kind="skill", name="pdftomd"),
    )
    with pytest.raises(HTTPException) as exc_info:
        start_coding_run(session_id, req)
    assert exc_info.value.status_code == 400
    assert "skills ツールが無効" in exc_info.value.detail
