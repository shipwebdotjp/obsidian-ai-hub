"""Unit and integration tests for Dedicated Coding Workspace v1."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.coding import backend, store, service
from obsidian_ai_hub.coding.orchestrator import parse_cli_request
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def test_project(tmp_path):
    """Create a dummy project in DB pointing to a real Git repo."""
    # Initialize a temporary git repository
    git_repo = tmp_path / "test_repo"
    git_repo.mkdir()
    subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=git_repo, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=git_repo, check=True
    )
    # Create an initial commit so git status works cleanly
    (git_repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=git_repo, check=True
    )

    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    cursor = conn.execute(
        """
        INSERT INTO projects (
            normalized_name, display_name, domain, status, project_path, created_at, updated_at
        ) VALUES ('test-repo', 'Test Repo', 'personal', 'active', ?, datetime('now'), datetime('now'))
        """,
        (str(git_repo),),
    )
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {"project_id": project_id, "repo_path": str(git_repo)}


def test_parse_cli_request():
    raw = "調査結果です。\n<cli_request>\ncodex exec --fix\n</cli_request>\nご確認をお願いします。"
    clean, prompt = parse_cli_request(raw)
    assert clean == "調査結果です。\n\nご確認をお願いします。"
    assert prompt == "codex exec --fix"

    raw_no_tag = "単純な質問への回答です。"
    clean_no, prompt_no = parse_cli_request(raw_no_tag)
    assert clean_no == "単純な質問への回答です。"
    assert prompt_no is None


def test_validate_git_repo(test_project, tmp_path):
    valid_path = backend.validate_git_repo(test_project["repo_path"])
    assert valid_path == os.path.realpath(test_project["repo_path"])

    invalid_dir = tmp_path / "not_a_git_repo"
    invalid_dir.mkdir()
    with pytest.raises(ValueError):
        backend.validate_git_repo(invalid_dir)


def test_check_dirty_tree(test_project):
    repo = test_project["repo_path"]
    is_dirty, output = backend.check_dirty_tree(repo)
    assert not is_dirty
    assert output == ""

    # Make dirty
    with open(os.path.join(repo, "README.md"), "a") as f:
        f.write("dirty change\n")

    is_dirty, output = backend.check_dirty_tree(repo)
    assert is_dirty
    assert "README.md" in output


def test_coding_store_crud(test_project):
    pid = test_project["project_id"]
    repo = test_project["repo_path"]

    # Create session
    session = store.create_session(
        project_id=pid,
        backend="codex",
        repo_path=repo,
        title="Test Session",
    )
    sid = session["session_id"]
    assert session["backend"] == "codex"
    assert session["title"] == "Test Session"

    # Fetch session
    fetched = store.get_session(sid)
    assert fetched["session_id"] == sid

    # Add messages
    m1 = store.add_message(sid, role="user", content="Hello")
    assert m1["sequence"] == 1
    m2 = store.add_message(sid, role="orchestrator", content="Hi there")
    assert m2["sequence"] == 2

    messages = store.list_messages(sid)
    assert len(messages) == 2

    # Create run
    run = store.create_run(sid, user_message_id=m1["message_id"])
    rid = run["run_id"]
    assert run["status"] == "running"

    # Update run
    updated_run = store.update_run(
        rid, orchestrator_message_id=m2["message_id"], status="completed"
    )
    assert updated_run["status"] == "completed"

    # Test startup mark_interrupted_runs
    r2 = store.create_run(sid, user_message_id=m1["message_id"])
    count = store.mark_interrupted_runs_on_startup()
    assert count >= 1
    r2_fetched = store.get_run(r2["run_id"])
    assert r2_fetched["status"] == "interrupted"


def test_coding_api_endpoints(test_project):
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    # 1. List coding projects
    res = client.get("/api/v1/coding/projects", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    proj_item = next(
        p for p in data if p["project"]["project_id"] == test_project["project_id"]
    )
    assert proj_item["is_valid_git_repo"] is True

    # 2. Create session
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "codex",
            "title": "API Session",
        },
    )
    assert res.status_code == 200
    sess = res.json()
    sid = sess["session_id"]

    # 3. Get session detail
    res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    assert res.status_code == 200
    detail = res.json()
    assert detail["session"]["session_id"] == sid
    assert detail["messages"] == []

    # 4. Stream message with mocked orchestrator and CLI worker
    async def mock_stream_response(*args, **kwargs):
        yield "解析結果です。\n<cli_request>\npytest\n</cli_request>"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="ext_123",
        output="1 passed in 0.01s",
        exit_code=0,
    )

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.stream_response",
        side_effect=mock_stream_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.CodexCliBackend.execute",
        return_value=mock_cli_res,
    ):
        res = client.post(
            f"/api/v1/coding/sessions/{sid}/messages/stream",
            headers=headers,
            json={"content": "テストを実行してください"},
        )
        assert res.status_code == 200
        text = res.text
        assert "orchestrator_chunk" in text
        assert "worker_start" in text
        assert "worker_done" in text
        assert "done" in text

    # Verify updated detail
    res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    detail = res.json()
    assert len(detail["messages"]) == 3  # user, orchestrator, worker
    assert detail["session"]["external_session_id"] == "ext_123"

    # 5. Delete session
    res = client.delete(f"/api/v1/coding/sessions/{sid}", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"
