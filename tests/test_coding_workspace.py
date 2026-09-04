"""Unit and integration tests for Dedicated Coding Workspace v1."""

import asyncio
import json
import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.coding import backend, store, service
from obsidian_ai_hub.coding.orchestrator import parse_cli_request
from obsidian_ai_hub.runs.coding_worker import execute_coding_run
from obsidian_ai_hub.web.app import create_app


def _parse_coding_sse(text: str):
    """Parse reconnectable run SSE (id:/data:) into (event_names, payloads).

    Returns (events, payloads) where events is a list of event names and
    payloads is a list of (event_id, payload_dict, event_name).
    """
    payloads = []
    cur_id = None
    for line in text.splitlines():
        if line.startswith("id:"):
            try:
                cur_id = int(line[len("id:"):].strip())
            except ValueError:
                cur_id = None
        elif line.startswith("data:"):
            raw = line[len("data:"):].strip()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            evt = payload.get("event") or payload.get("event_type")
            payloads.append((cur_id, payload, evt))
            cur_id = None
    events = [e for _, _, e in payloads if e]
    return events, payloads


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

    # 4. Run message via reconnectable runs flow (POST runs 202 + worker + GET events)
    async def mock_generate_response(*args, **kwargs):
        # 1st call: request CLI, 2nd call: report completion
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "テスト成功を確認しました。完了です。"
        return "解析結果です。\n<cli_request>\npytest\n</cli_request>"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="th_123",
        output="1 passed in 0.01s",
        exit_code=0,
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "テストを実行してください"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.CodexCliBackend.execute",
        return_value=mock_cli_res,
    ):
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    text = res.text
    events, _payloads = _parse_coding_sse(text)
    assert "orchestrator_start" in events
    assert "orchestrator_message" in events
    assert "worker_start" in events
    assert "worker_done" in events
    assert "done" in events

    # Verify updated detail
    res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    detail = res.json()
    assert len(detail["messages"]) == 5  # user, orchestrator #1, cli_request, worker, orchestrator #2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][1]["role"] == "orchestrator"
    assert detail["messages"][2]["role"] == "cli_request"
    assert detail["messages"][3]["role"] == "worker"
    assert detail["messages"][4]["role"] == "orchestrator"
    assert detail["session"]["external_session_id"] == "th_123"

    # 5. Delete session
    res = client.delete(f"/api/v1/coding/sessions/{sid}", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"


def test_opencode_backend_initial_run(test_project):
    """Test initial OpenCode run without external_session_id."""
    be = backend.OpenCodeCliBackend()

    # Mock _run_subprocess with actual OpenCode event shape (sessionID and part.type == 'text')
    json_output = '{"sessionID": "ses_abc123", "part": {"type": "text", "text": "Execution completed"}}'
    with patch.object(be, "_run_subprocess", return_value=(0, json_output, "", False)) as mock_run:
        res = be.execute(test_project["repo_path"], "hello")
        assert res.external_session_id == "ses_abc123"
        assert res.output == "Execution completed"
        assert res.exit_code == 0
        assert not res.session_recreated
        assert res.diagnostics is not None
        assert res.diagnostics["cwd"] == os.path.realpath(test_project["repo_path"])
        assert res.diagnostics["returned_session_id"] == "ses_abc123"

        # Check argv passed to _run_subprocess: should not contain --session
        argv = mock_run.call_args[0][0]
        assert "--session" not in argv
        assert "--format" in argv
        assert "json" in argv
        assert "--auto" in argv
        assert "--dir" in argv
        dir_idx = argv.index("--dir")
        assert argv[dir_idx + 1] == os.path.realpath(test_project["repo_path"])


def test_opencode_backend_environment_isolation(test_project):
    """Test PWD canonicalization and OPENCODE_SERVER_* stripping."""
    be = backend.OpenCodeCliBackend()
    canonical_repo = backend.validate_git_repo(test_project["repo_path"])

    with patch.dict(
        os.environ,
        {
            "PWD": "/wrong/parent/dir",
            "OPENCODE_SERVER_PASSWORD": "secret_password",
            "OPENCODE_SERVER_USERNAME": "secret_user",
            "OPENCODE_PERMISSION": '{"file_read": "allow"}',
        },
    ):
        env = be._prepare_opencode_env(canonical_repo)
        assert env["PWD"] == canonical_repo
        assert "OPENCODE_SERVER_PASSWORD" not in env
        assert "OPENCODE_SERVER_USERNAME" not in env
        assert '"external_directory": "deny"' in env["OPENCODE_PERMISSION"]
        assert '"file_read": "allow"' in env["OPENCODE_PERMISSION"]


def test_opencode_backend_auto_flag_respects_config(test_project):
    """Test --auto is omitted when CODING_OPENCODE_AUTO_APPROVE is False."""
    be = backend.OpenCodeCliBackend()
    json_output = '{"sessionID": "ses_abc123", "part": {"type": "text", "text": "ok"}}'
    with patch("obsidian_ai_hub.coding.backend.CODING_OPENCODE_AUTO_APPROVE", False):
        with patch.object(be, "_run_subprocess", return_value=(0, json_output, "", False)) as mock_run:
            be.execute(test_project["repo_path"], "hello")
            argv = mock_run.call_args[0][0]
            assert "--auto" not in argv
    with patch("obsidian_ai_hub.coding.backend.CODING_OPENCODE_AUTO_APPROVE", True):
        with patch.object(be, "_run_subprocess", return_value=(0, json_output, "", False)) as mock_run:
            be.execute(test_project["repo_path"], "hello")
            argv = mock_run.call_args[0][0]
            assert "--auto" in argv


def test_opencode_backend_does_not_affect_codex_backend(test_project):
    """Ensure Codex backend is unaffected by OpenCode auto-approve flag."""
    be = backend.CodexCliBackend()
    json_lines = [
        '{"type": "thread.started", "thread_id": "th_abc123"}',
        '{"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}}',
    ]
    stdout_data = "\n".join(json_lines)
    with patch.object(be, "_run_subprocess", return_value=(0, stdout_data, "", False)) as mock_run:
        be.execute(test_project["repo_path"], "hello codex")
        argv = mock_run.call_args[0][0]
        assert "--auto" not in argv


def test_opencode_backend_continuation_run(test_project):
    """Test OpenCode continuation run with external_session_id."""
    be = backend.OpenCodeCliBackend()

    json_output = '{"session_id": "ses_abc123", "text": "Continuation response"}'
    with patch.object(be, "_run_subprocess", return_value=(0, json_output, "", False)) as mock_run:
        res = be.execute(test_project["repo_path"], "next prompt", external_session_id="ses_abc123")
        assert res.external_session_id == "ses_abc123"
        assert res.output == "Continuation response"
        assert not res.session_recreated

        # Check argv passed to _run_subprocess: should contain --session ses_abc123
        argv = mock_run.call_args[0][0]
        assert "--session" in argv
        sess_idx = argv.index("--session")
        assert argv[sess_idx + 1] == "ses_abc123"


def test_opencode_backend_session_not_found_recovery(test_project):
    """Test OpenCode recovery when Session not found occurs on continuation."""
    be = backend.OpenCodeCliBackend()

    # First run returns Session not found
    error_output = "\x1b[31mError: Session not found\x1b[0m"
    # Second run (retry) succeeds with new ses_new456
    retry_json_output = '{"session_id": "ses_new456", "text": "Recovered response"}'

    with patch.object(
        be,
        "_run_subprocess",
        side_effect=[
            (1, error_output, "", False),  # 1st call fails with Session not found
            (0, retry_json_output, "", False),  # 2nd call (retry) succeeds
        ],
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "retry prompt", external_session_id="ses_old123")
        assert res.external_session_id == "ses_new456"
        assert res.output == "Recovered response"
        assert res.exit_code == 0
        assert res.session_recreated is True

        assert mock_run.call_count == 2
        # First call has --session ses_old123
        argv1 = mock_run.call_args_list[0][0][0]
        assert "--session" in argv1
        # Second call has no --session
        argv2 = mock_run.call_args_list[1][0][0]
        assert "--session" not in argv2


def test_opencode_backend_session_not_found_retry_failure(test_project):
    """Test OpenCode when retry after Session not found also fails."""
    be = backend.OpenCodeCliBackend()

    error_output = "Session not found"
    retry_error_output = "Network error on retry"

    with patch.object(
        be,
        "_run_subprocess",
        side_effect=[
            (1, error_output, "", False),
            (1, "", retry_error_output, False),
        ],
    ):
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="ses_old123")
        assert res.external_session_id is None
        assert res.exit_code == 1
        assert res.error_message == retry_error_output
        assert res.session_recreated is True


def test_opencode_backend_other_errors_do_not_retry(test_project):
    """Test that non-'Session not found' errors do not trigger retry."""
    be = backend.OpenCodeCliBackend()

    with patch.object(
        be,
        "_run_subprocess",
        return_value=(1, "", "Syntax error in script", False),
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="ses_old123")
        assert res.external_session_id == "ses_old123"
        assert res.exit_code == 1
        assert res.error_message == "Syntax error in script"
        assert res.session_recreated is False
        assert mock_run.call_count == 1


def test_opencode_stream_session_recreated_notification(test_project):
    """Test integration flow when session is recreated and notifications are included in SSE/messages."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    # Create OpenCode session
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "OpenCode Recovery Session",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]

    # Set old external_session_id
    store.update_session_external_id(sid, "ses_old999")

    async def mock_generate_response(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "確認しました。"
        return "解析結果です。\n<cli_request>\nopencode run test\n</cli_request>"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="ses_new888",
        output="Refactored code",
        exit_code=0,
        session_recreated=True,
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "コードを修正してください"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.OpenCodeCliBackend.execute",
        return_value=mock_cli_res,
    ):
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    text = res.text
    events, payloads = _parse_coding_sse(text)
    assert "worker_done" in events
    assert '"session_recreated": true' in text
    worker_dones = [p for _, p, e in payloads if e == "worker_done"]
    assert any(p.get("session_recreated") is True for p in worker_dones)

    # Verify updated session external_session_id
    detail_res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    detail = detail_res.json()
    assert detail["session"]["external_session_id"] == "ses_new888"

    # Verify notice in worker message
    worker_msg = next(m for m in detail["messages"] if m["role"] == "worker")
    assert "前の OpenCode セッションが見つからなかったため、新しいセッションへ切り替えて続行しました。" in worker_msg["content"]


def test_codex_backend_initial_run(test_project):
    """Test initial Codex run without external_session_id."""
    be = backend.CodexCliBackend()

    json_lines = [
        '{"type": "thread.started", "thread_id": "th_abc123"}',
        '{"type": "item.completed", "item": {"type": "agent_message", "text": "Initial answer from Codex"}}',
    ]
    stdout_data = "\n".join(json_lines)

    with patch.object(be, "_run_subprocess", return_value=(0, stdout_data, "", False)) as mock_run:
        res = be.execute(test_project["repo_path"], "hello codex")
        assert res.external_session_id == "th_abc123"
        assert res.output == "Initial answer from Codex"
        assert res.exit_code == 0
        assert not res.session_recreated

        argv = mock_run.call_args[0][0]
        assert "--session" not in argv
        assert "exec" in argv
        assert "--json" in argv
        assert "--sandbox" in argv
        assert "workspace-write" in argv


def test_codex_backend_continuation_run(test_project):
    """Test Codex continuation run with thread ID using resume."""
    be = backend.CodexCliBackend()

    json_lines = [
        '{"type": "item.completed", "item": {"agent_message": {"text": "Continuation response from Codex"}}}',
    ]
    stdout_data = "\n".join(json_lines)

    with patch.object(be, "_run_subprocess", return_value=(0, stdout_data, "", False)) as mock_run:
        res = be.execute(test_project["repo_path"], "next codex prompt", external_session_id="th_abc123")
        assert res.external_session_id == "th_abc123"
        assert res.output == "Continuation response from Codex"
        assert not res.session_recreated

        argv = mock_run.call_args[0][0]
        assert "--session" not in argv
        assert "resume" in argv
        assert "--json" in argv
        assert "th_abc123" in argv


def test_codex_backend_session_not_found_recovery(test_project):
    """Test Codex recovery when thread not found occurs on resume."""
    be = backend.CodexCliBackend()

    error_output = "Error: Thread not found"
    retry_json_lines = [
        '{"type": "thread.started", "thread_id": "th_new456"}',
        '{"type": "item.completed", "item": {"type": "agent_message", "text": "Recovered codex response"}}',
    ]
    retry_stdout = "\n".join(retry_json_lines)

    with patch.object(
        be,
        "_run_subprocess",
        side_effect=[
            (1, "", error_output, False),  # 1st call fails
            (0, retry_stdout, "", False),  # 2nd call (retry) succeeds
        ],
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "retry prompt", external_session_id="th_old123")
        assert res.external_session_id == "th_new456"
        assert res.output == "Recovered codex response"
        assert res.exit_code == 0
        assert res.session_recreated is True

        assert mock_run.call_count == 2
        argv1 = mock_run.call_args_list[0][0][0]
        assert "resume" in argv1
        argv2 = mock_run.call_args_list[1][0][0]
        assert "resume" not in argv2
        assert "--sandbox" in argv2


def test_codex_backend_session_not_found_retry_failure(test_project):
    """Test Codex when retry after session/thread not found also fails."""
    be = backend.CodexCliBackend()

    error_output = "Thread not found"
    retry_error_output = "Execution failed on retry"

    with patch.object(
        be,
        "_run_subprocess",
        side_effect=[
            (1, "", error_output, False),
            (1, "", retry_error_output, False),
        ],
    ):
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="th_old123")
        assert res.external_session_id is None
        assert res.exit_code == 1
        assert res.error_message == retry_error_output
        assert res.session_recreated is False


def test_codex_backend_other_errors_do_not_retry(test_project):
    """Test that non-'Thread not found' errors do not trigger retry."""
    be = backend.CodexCliBackend()

    with patch.object(
        be,
        "_run_subprocess",
        return_value=(1, "", "Syntax error in prompt", False),
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="th_old123")
        assert res.external_session_id == "th_old123"
        assert res.exit_code == 1
        assert res.error_message == "Syntax error in prompt"
        assert res.session_recreated is False
        assert mock_run.call_count == 1


def test_codex_backend_cancellation_retains_thread_id(test_project):
    """Test that thread_id extracted before cancellation is preserved."""
    be = backend.CodexCliBackend()

    json_lines = [
        '{"type": "thread.started", "thread_id": "th_cancelled789"}',
    ]
    stdout_data = "\n".join(json_lines)

    with patch.object(be, "_run_subprocess", return_value=(-1, stdout_data, "", True)):
        res = be.execute(test_project["repo_path"], "cancelled prompt")
        assert res.external_session_id == "th_cancelled789"
        assert res.cancelled is True


def test_codex_stream_session_recreated_notification(test_project):
    """Test integration flow when Codex session is recreated."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    # Create Codex session
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "codex",
            "title": "Codex Recovery Session",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]

    store.update_session_external_id(sid, "th_old999")

    async def mock_generate_response(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "確認完了。"
        return "解析結果です。\n<cli_request>\ncodex exec test\n</cli_request>"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="th_new888",
        output="Codex refactored code",
        exit_code=0,
        session_recreated=True,
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "コードを修正してください"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.CodexCliBackend.execute",
        return_value=mock_cli_res,
    ):
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    text = res.text
    events, payloads = _parse_coding_sse(text)
    assert "worker_done" in events
    assert '"session_recreated": true' in text
    worker_dones = [p for _, p, e in payloads if e == "worker_done"]
    assert any(p.get("session_recreated") is True for p in worker_dones)

    # Verify updated session external_session_id
    detail_res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    detail = detail_res.json()
    assert detail["session"]["external_session_id"] == "th_new888"

    # Verify notice in worker message for Codex
    worker_msg = next(m for m in detail["messages"] if m["role"] == "worker")
    assert "前の Codex セッションが見つからなかったため、新しいセッションへ切り替えて続行しました。" in worker_msg["content"]


def test_coding_turn_max_cli_iterations_cap(test_project):
    """Test that CLI execution is capped at the configured per-turn limit."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "codex",
            "title": "Max Iterations Session",
        },
    )
    sid = res.json()["session_id"]

    # Orchestrator always asks for CLI execution
    async def mock_generate_response(*args, **kwargs):
        return "まだ作業が必要です。\n<cli_request>\npytest --fix\n</cli_request>"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="th_max123",
        output="Execution attempt done",
        exit_code=0,
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "無限ループを検証してください"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.CodexCliBackend.execute",
        return_value=mock_cli_res,
    ) as mock_exec:
        asyncio.run(execute_coding_run(run_id))
        assert mock_exec.call_count == service.MAX_CLI_ITERATIONS

    # Check session detail messages
    detail_res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    detail = detail_res.json()
    messages = detail["messages"]

    # 1 user, (orchestrator, cli_request, worker) triplet per CLI call, then a final
    # orchestrator message that reports the limit.
    assert len(messages) == 3 * service.MAX_CLI_ITERATIONS + 2
    final_orch_msg = messages[-1]
    assert final_orch_msg["role"] == "orchestrator"
    assert service.CLI_LIMIT_REACHED_NOTICE in final_orch_msg["content"]


def test_coding_turn_non_zero_exit_code_passed_to_review(test_project):
    """Test that a non-zero exit code CLI output is passed to orchestrator review rather than instantly failing."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "codex",
            "title": "Error Recovery Session",
        },
    )
    sid = res.json()["session_id"]

    async def mock_generate_response(*args, **kwargs):
        history = kwargs.get("history", [])
        worker_msgs = [h for h in history if h.get("role") == "worker"]
        if not worker_msgs:
            return "実行します。\n<cli_request>\npython script.py\n</cli_request>"
        # Review phase receives worker error message
        assert "SyntaxError" in worker_msgs[0]["content"]
        return "エラーが発生したため原因を説明します。文法エラーを修正してください。"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="th_err123",
        output="SyntaxError: invalid syntax on line 4",
        exit_code=1,
        error_message="Command failed with exit code 1",
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "スクリプトを実行してください"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.CodexCliBackend.execute",
        return_value=mock_cli_res,
    ):
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    text = res.text
    events, payloads = _parse_coding_sse(text)
    assert "done" in events
    done_payloads = [p for _, p, e in payloads if e == "done"]
    assert done_payloads and done_payloads[-1].get("status") == "completed"
    assert 'status": "completed"' in text

    detail_res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    detail = detail_res.json()
    messages = detail["messages"]
    assert len(messages) == 5  # user, orch request, cli_request, worker error, orch final report
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "orchestrator"
    assert messages[2]["role"] == "cli_request"
    assert messages[3]["role"] == "worker"
    assert messages[4]["role"] == "orchestrator"
    assert "SyntaxError" in messages[3]["content"]


def test_coding_tools_and_user_defaults(test_project):
    pid = test_project["project_id"]
    repo = test_project["repo_path"]

    # 1. Test get_user_default_tool_ids fallback to all tools when unconfigured
    all_tools = store.get_all_available_tool_ids()
    defaults = store.get_user_default_tool_ids()
    assert set(defaults) == set(all_tools)

    # 2. Update user default tools
    custom_defaults = ["web_search", "vault_search"]
    saved_defaults = store.update_user_default_tool_ids(custom_defaults)
    assert saved_defaults == custom_defaults

    # Verify updated default tool IDs
    fetched_defaults = store.get_user_default_tool_ids()
    assert fetched_defaults == custom_defaults

    # 3. Create session without explicit tool_ids -> initial session tools should inherit user defaults
    session1 = store.create_session(pid, "codex", repo, title="Default Tools Session")
    sid1 = session1["session_id"]
    eff_tools1 = store.get_effective_session_tool_ids(sid1)
    assert eff_tools1 == custom_defaults

    # 4. Create session with explicit custom tool_ids
    custom_session_tools = ["run_shell"]
    session2 = store.create_session(pid, "codex", repo, title="Custom Tools Session", tool_ids=custom_session_tools)
    sid2 = session2["session_id"]
    eff_tools2 = store.get_effective_session_tool_ids(sid2)
    assert eff_tools2 == custom_session_tools

    # 5. Update session tool_ids
    store.update_session_tool_ids(sid1, ["web_extract", "people_search"])
    eff_tools1_updated = store.get_effective_session_tool_ids(sid1)
    assert eff_tools1_updated == ["web_extract", "people_search"]

    # 6. Reset session tool_ids to user defaults (set to None)
    store.update_session_tool_ids(sid1, None)
    eff_tools1_reset = store.get_effective_session_tool_ids(sid1)
    assert eff_tools1_reset == custom_defaults


def test_coding_tools_api_endpoints(test_project):
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    # 1. GET /coding/defaults
    res = client.get("/api/v1/coding/defaults", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "default_tool_ids" in data
    assert "available_tools" in data

    # 2. PUT /coding/defaults
    new_defaults = ["web_search", "web_extract"]
    res = client.put("/api/v1/coding/defaults", headers=headers, json={"tool_ids": new_defaults})
    assert res.status_code == 200
    assert res.json()["default_tool_ids"] == new_defaults

    # 3. Create session
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "codex",
            "title": "Tools Session",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]

    # Check GET /coding/sessions/{session_id} includes effective tools
    res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    assert res.status_code == 200
    detail = res.json()
    assert detail["effective_tool_ids"] == new_defaults
    assert detail["has_custom_tools"] is True  # created with initial user defaults

    # 4. PUT /coding/sessions/{session_id}/tools
    res = client.put(
        f"/api/v1/coding/sessions/{sid}/tools",
        headers=headers,
        json={"tool_ids": ["run_shell"]},
    )
    assert res.status_code == 200
    updated_detail = res.json()
    assert updated_detail["effective_tool_ids"] == ["run_shell"]
    assert updated_detail["has_custom_tools"] is True

    # 5. Reset session tools to defaults (tool_ids: null)
    res = client.put(
        f"/api/v1/coding/sessions/{sid}/tools",
        headers=headers,
        json={"tool_ids": None},
    )
    assert res.status_code == 200
    reset_detail = res.json()
    assert reset_detail["effective_tool_ids"] == new_defaults
    assert reset_detail["has_custom_tools"] is False


def test_coding_config_endpoint(test_project, monkeypatch):
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    from obsidian_ai_hub.utils import config

    # default should be opencode (or codex if config overridden) - ensure normalized
    res = client.get("/api/v1/coding/config", headers=headers)
    assert res.status_code == 200
    assert res.json()["default_backend"] in ("codex", "opencode")

    # codex via config
    monkeypatch.setattr(config, "CODING_DEFAULT_BACKEND", "codex")
    res = client.get("/api/v1/coding/config", headers=headers)
    assert res.status_code == 200
    assert res.json()["default_backend"] == "codex"

    # whitespace and uppercase normalized
    monkeypatch.setattr(config, "CODING_DEFAULT_BACKEND", "  CODEX ")
    res = client.get("/api/v1/coding/config", headers=headers)
    assert res.json()["default_backend"] == "codex"

    # invalid falls back to opencode
    monkeypatch.setattr(config, "CODING_DEFAULT_BACKEND", "invalid_backend")
    res = client.get("/api/v1/coding/config", headers=headers)
    assert res.json()["default_backend"] == "opencode"

    # opencode explicit
    monkeypatch.setattr(config, "CODING_DEFAULT_BACKEND", "opencode")
    res = client.get("/api/v1/coding/config", headers=headers)
    assert res.json()["default_backend"] == "opencode"


def test_opencode_extract_title_from_export_json():
    be = backend.OpenCodeCliBackend()
    # Valid title
    assert be._extract_title_from_export_json('{"info": {"title": "git push結果報告"}}') == "git push結果報告"
    # Whitespace trimmed
    assert be._extract_title_from_export_json('{"info": {"title": "  hello  "}}') == "hello"
    # Empty after strip
    assert be._extract_title_from_export_json('{"info": {"title": "   "}}') is None
    # Missing title
    assert be._extract_title_from_export_json('{"info": {}}') is None
    # Missing info
    assert be._extract_title_from_export_json('{"other": 123}') is None
    # Invalid JSON
    assert be._extract_title_from_export_json('not json') is None
    # Non-dict root
    assert be._extract_title_from_export_json('[]') is None
    # Title not string
    assert be._extract_title_from_export_json('{"info": {"title": 123}}') is None


def test_opencode_fetch_title_success_and_failures():
    be = backend.OpenCodeCliBackend()
    valid_json = '{"info": {"title": "Fetched Title"}}'
    # Success (file-based stdout)
    with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
        def _write_valid(cmd, stdout=None, stderr=None, text=None, timeout=None):
            if stdout is not None and hasattr(stdout, "write"):
                stdout.write(valid_json)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = _write_valid
        assert be.fetch_opencode_session_title("ses_abc123") == "Fetched Title"
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][0] in ("opencode", backend.CODING_OPENCODE_CLI_PATH)
        assert "export" in mock_run.call_args[0][0]
        assert "ses_abc123" in mock_run.call_args[0][0]
        # Must use file handle for stdout, not PIPE/capture_output
        assert "stdout" in mock_run.call_args[1]
        assert mock_run.call_args[1]["stdout"] is not subprocess.PIPE
        assert mock_run.call_args[1].get("capture_output") is not True
        assert mock_run.call_args[1].get("timeout") == 10

    # Large JSON (~200KB) must also be handled via file without truncation
    large_payload = "x" * 200_000
    large_json = '{"info": {"title": "Large Title"}, "payload": "' + large_payload + '"}'
    with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
        def _write_large(cmd, stdout=None, stderr=None, text=None, timeout=None):
            if stdout is not None and hasattr(stdout, "write"):
                stdout.write(large_json)
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = _write_large
        # _extract will succeed on the large payload's title (leading JSON part)
        # we patch extract to verify file content length is large
        with patch.object(backend.OpenCodeCliBackend, "_extract_title_from_export_json", return_value="Large Title") as mock_extract:
            assert be.fetch_opencode_session_title("ses_large") == "Large Title"
            # confirm file content was large (extract called with large string)
            assert mock_extract.call_args is not None
            assert len(mock_extract.call_args[0][0]) > 100_000
            assert mock_run.call_args[1]["stdout"] is not subprocess.PIPE

    # Non-zero exit -> None with warning
    with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="not found")
        with patch("obsidian_ai_hub.coding.backend.logger.warning") as mock_warn:
            assert be.fetch_opencode_session_title("ses_bad") is None
            assert mock_warn.call_count == 1
            assert "non_zero_exit" in str(mock_warn.call_args)
    # Empty stdout -> None with warning
    with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
        def _write_empty(cmd, stdout=None, stderr=None, text=None, timeout=None):
            if stdout is not None and hasattr(stdout, "write"):
                stdout.write("   ")
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = _write_empty
        with patch("obsidian_ai_hub.coding.backend.logger.warning") as mock_warn:
            assert be.fetch_opencode_session_title("ses_abc") is None
            assert "empty_output" in str(mock_warn.call_args)
    # Invalid JSON -> None with warning
    with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
        def _write_invalid(cmd, stdout=None, stderr=None, text=None, timeout=None):
            if stdout is not None and hasattr(stdout, "write"):
                stdout.write("not json")
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = _write_invalid
        with patch("obsidian_ai_hub.coding.backend.logger.warning") as mock_warn:
            assert be.fetch_opencode_session_title("ses_abc") is None
            assert "json_parse_or_missing_title" in str(mock_warn.call_args)
    # Empty title -> None with warning
    with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
        def _write_empty_title(cmd, stdout=None, stderr=None, text=None, timeout=None):
            if stdout is not None and hasattr(stdout, "write"):
                stdout.write('{"info": {"title": "  "}}')
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = _write_empty_title
        with patch("obsidian_ai_hub.coding.backend.logger.warning") as mock_warn:
            assert be.fetch_opencode_session_title("ses_abc") is None
            assert "json_parse_or_missing_title" in str(mock_warn.call_args)
    # Timeout -> None with warning
    import subprocess as sp

    with patch("obsidian_ai_hub.coding.backend.subprocess.run", side_effect=sp.TimeoutExpired(cmd="opencode export", timeout=10)):
        with patch("obsidian_ai_hub.coding.backend.logger.warning") as mock_warn:
            assert be.fetch_opencode_session_title("ses_abc") is None
            assert "timeout" in str(mock_warn.call_args).lower()
    # None / empty input
    assert be.fetch_opencode_session_title("") is None
    assert be.fetch_opencode_session_title(None) is None  # type: ignore[arg-type]


def test_opencode_fetch_title_tempfile_cleanup_on_success_and_failure(tmp_path):
    """Ensure temp file is cleaned up on success, non-zero exit, and invalid JSON."""
    be = backend.OpenCodeCliBackend()
    import tempfile
    import pathlib

    # Track created temp files via NamedTemporaryFile mock
    created_paths = []

    orig_ntf = tempfile.NamedTemporaryFile

    def tracking_ntf(*args, **kwargs):
        kwargs["delete"] = False
        tf = orig_ntf(*args, **kwargs)
        created_paths.append(pathlib.Path(tf.name))
        return tf

    valid_json = '{"info": {"title": "Cleanup Title"}}'

    with patch("tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
        with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
            def _write(cmd, stdout=None, stderr=None, text=None, timeout=None):
                if stdout is not None and hasattr(stdout, "write"):
                    stdout.write(valid_json)
                return MagicMock(returncode=0, stderr="")

            mock_run.side_effect = _write
            assert be.fetch_opencode_session_title("ses_ok") == "Cleanup Title"
            assert len(created_paths) == 1
            assert not created_paths[0].exists(), "temp file should be removed after success"

    created_paths.clear()
    with patch("tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
        with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            assert be.fetch_opencode_session_title("ses_fail") is None
            assert len(created_paths) == 1
            assert not created_paths[0].exists(), "temp file should be removed after non-zero exit"

    created_paths.clear()
    with patch("tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
        with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
            def _write_bad(cmd, stdout=None, stderr=None, text=None, timeout=None):
                if stdout is not None and hasattr(stdout, "write"):
                    stdout.write("not json")
                return MagicMock(returncode=0, stderr="")

            mock_run.side_effect = _write_bad
            assert be.fetch_opencode_session_title("ses_bad_json") is None
            assert len(created_paths) == 1
            assert not created_paths[0].exists(), "temp file should be removed after invalid JSON"


def test_opencode_fetch_title_never_uses_capture_output():
    """Regression: stdout must be a file handle, never PIPE/capture_output."""
    be = backend.OpenCodeCliBackend()
    with patch("obsidian_ai_hub.coding.backend.subprocess.run") as mock_run:
        def _write(cmd, stdout=None, stderr=None, text=None, timeout=None, capture_output=None):
            assert capture_output is not True, "capture_output=True must not be used (pipe truncation)"
            assert stdout is not subprocess.PIPE, "stdout=PIPE must not be used"
            assert stdout is not None and hasattr(stdout, "write"), "stdout must be file handle"
            stdout.write('{"info": {"title": "No Pipe"}}')
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = _write
        assert be.fetch_opencode_session_title("ses_nopipe") == "No Pipe"


def test_opencode_title_sync_updates_default_title(test_project):
    """Title sync should update default title via export and emit session_title in done event."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    # Create session with default title
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "opencode", "title": "新しいコーディングセッション"},
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]
    assert res.json()["title"] == "新しいコーディングセッション"

    async def mock_generate_response(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "完了しました。"
        return "解析結果です。\n<cli_request>\nopencode run test\n</cli_request>"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="ses_fetch123",
        output="worker output",
        exit_code=0,
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "タイトル取得テスト"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.OpenCodeCliBackend.execute",
        return_value=mock_cli_res,
    ), patch(
        "obsidian_ai_hub.coding.backend.OpenCodeCliBackend.fetch_opencode_session_title",
        return_value="git push結果報告",
    ) as mock_fetch:
        asyncio.run(execute_coding_run(run_id))
        mock_fetch.assert_called_once_with("ses_fetch123")

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    text = res.text
    assert '"session_title": "git push結果報告"' in text
    _, payloads = _parse_coding_sse(text)
    done_payloads = [p for _, p, e in payloads if e == "done"]
    assert done_payloads and done_payloads[-1].get("session_title") == "git push結果報告"

    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["session"]["title"] == "git push結果報告"
    assert detail["session"]["external_session_id"] == "ses_fetch123"


def test_opencode_title_sync_does_not_overwrite_custom_title(test_project):
    """Custom user title must not be overwritten by export title."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "opencode", "title": "My Custom Title"},
    )
    sid = res.json()["session_id"]
    assert res.json()["title"] == "My Custom Title"

    async def mock_generate_response(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "完了しました。"
        return "解析\n<cli_request>\nopencode test\n</cli_request>"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="ses_custom999",
        output="out",
        exit_code=0,
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "カスタムタイトル保持テスト"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.OpenCodeCliBackend.execute",
        return_value=mock_cli_res,
    ), patch(
        "obsidian_ai_hub.coding.backend.OpenCodeCliBackend.fetch_opencode_session_title",
        return_value="Exported Title Should Not Win",
    ) as mock_fetch:
        asyncio.run(execute_coding_run(run_id))
        mock_fetch.assert_not_called()

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    # done event should NOT contain session_title when not updated
    assert '"session_title"' not in res.text

    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["session"]["title"] == "My Custom Title"


def test_opencode_title_sync_skips_on_fetch_failure(test_project):
    """Fetch failure / empty title must not break turn and must not update title."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "opencode", "title": "新しいコーディングセッション"},
    )
    sid = res.json()["session_id"]

    async def mock_generate_response(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "完了しました。"
        return "x\n<cli_request>\nopencode test\n</cli_request>"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="ses_fail123",
        output="out",
        exit_code=0,
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "失敗時スキップテスト"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.OpenCodeCliBackend.execute",
        return_value=mock_cli_res,
    ), patch(
        "obsidian_ai_hub.coding.backend.OpenCodeCliBackend.fetch_opencode_session_title",
        return_value=None,
    ):
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    assert '"session_title"' not in res.text

    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    # Title remains default because fetch returned None
    assert detail["session"]["title"] == "新しいコーディングセッション"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (None, True),
        ("", True),
        ("   ", True),
        (service.DEFAULT_CODING_SESSION_TITLE, True),
        ("ユーザー指定のタイトル", False),
    ],
)
def test_coding_title_generation_eligibility(title, expected):
    assert service._should_update_coding_title(title) is expected


def test_codex_title_generation_updates_default_title(test_project):
    """Codex default titles use the app's AI Agents title generator."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "codex"},
    )
    sid = res.json()["session_id"]

    async def mock_generate_response(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "完了しました。"
        return "解析結果です。\n<cli_request>\ncodex exec test\n</cli_request>"

    mock_cli_res = backend.CodingBackendResult(
        external_session_id="thread_123", output="Codex worker output", exit_code=0
    )
    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "Codexで実装して"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.CodexCliBackend.execute", return_value=mock_cli_res
    ), patch(
        "obsidian_ai_hub.agents.runtime.generate_session_title",
        return_value="Codex生成タイトル",
    ) as mock_title:
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    assert '"session_title": "Codex生成タイトル"' in res.text
    _, payloads = _parse_coding_sse(res.text)
    done_payloads = [p for _, p, e in payloads if e == "done"]
    assert done_payloads and done_payloads[-1].get("session_title") == "Codex生成タイトル"
    mock_title.assert_called_once_with(
        user_content="Codexで実装して", assistant_content="Codex worker output"
    )
    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["session"]["title"] == "Codex生成タイトル"


def test_codex_title_generation_preserves_explicit_title(test_project):
    """Codex title generation must not overwrite a user-supplied title."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "codex",
            "title": "ユーザー指定のタイトル",
        },
    )
    sid = res.json()["session_id"]

    async def mock_generate_response(*args, **kwargs):
        if any(h.get("role") == "worker" for h in kwargs.get("history", [])):
            return "完了しました。"
        return "解析\n<cli_request>\ncodex exec test\n</cli_request>"

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "実装して"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.CodexCliBackend.execute",
        return_value=backend.CodingBackendResult(
            external_session_id="thread_456", output="worker output", exit_code=0
        ),
    ), patch("obsidian_ai_hub.agents.runtime.generate_session_title") as mock_title:
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    assert '"session_title"' not in res.text
    mock_title.assert_not_called()
    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["session"]["title"] == "ユーザー指定のタイトル"


def test_codex_title_generation_failure_does_not_fail_turn(test_project):
    """A title LLM failure leaves the default title and completes the Codex turn."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "codex"},
    )
    sid = res.json()["session_id"]

    async def mock_generate_response(*args, **kwargs):
        if any(h.get("role") == "worker" for h in kwargs.get("history", [])):
            return "完了しました。"
        return "解析\n<cli_request>\ncodex exec test\n</cli_request>"

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "実装して"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_generate_response,
    ), patch(
        "obsidian_ai_hub.coding.backend.CodexCliBackend.execute",
        return_value=backend.CodingBackendResult(
            external_session_id="thread_789", output="worker output", exit_code=0
        ),
    ), patch(
        "obsidian_ai_hub.agents.runtime.generate_session_title",
        side_effect=RuntimeError("title LLM unavailable"),
    ):
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    events, _payloads = _parse_coding_sse(res.text)
    assert "done" in events
    assert '"event": "done"' in res.text
    assert '"session_title"' not in res.text
    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["session"]["title"] == "新しいコーディングセッション"


@pytest.mark.anyio
async def test_orchestrator_tool_restriction(test_project):
    """Test that Orchestrator binds only permitted tools and respects tool restrictions."""
    from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator

    # Case A: empty tool_ids -> bind_tools is not called / no tools available
    orch_empty = CodingOrchestrator(tool_ids=[])

    mock_ai_msg = MagicMock()
    mock_ai_msg.content = "No tools used."
    mock_ai_msg.tool_calls = []

    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm") as mock_create_llm:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_ai_msg)
        mock_create_llm.return_value = mock_llm

        resp = await orch_empty.generate_response([], test_project["repo_path"], "codex")
        assert resp == "No tools used."
        mock_llm.bind_tools.assert_not_called()

    # Case B: specified tool_ids -> bind_tools receives only permitted BaseTools
    orch_permitted = CodingOrchestrator(tool_ids=["web_search"])
    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm") as mock_create_llm:
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        mock_llm_with_tools.ainvoke = AsyncMock(return_value=mock_ai_msg)
        mock_llm.bind_tools.return_value = mock_llm_with_tools
        mock_create_llm.return_value = mock_llm

        resp = await orch_permitted.generate_response([], test_project["repo_path"], "codex")
        assert resp == "No tools used."
        mock_llm.bind_tools.assert_called_once()
        bound_tools = mock_llm.bind_tools.call_args[0][0]
        tool_names = [t.name for t in bound_tools]
        assert "web_search" in tool_names
        assert "run_shell" not in tool_names


# --- P0/P1 regression tests for session recreation carry-over & diagnostics ---


def test_opencode_backend_session_not_found_case_insensitive(test_project):
    """P0-3: lower-case 'session not found' must trigger retry."""
    be = backend.OpenCodeCliBackend()
    error_output = "Error: session not found (lower case)"
    retry_json = '{"sessionID": "ses_new_ci", "part": {"type": "text", "text": "recovered ci"}}'
    with patch.object(
        be,
        "_run_subprocess",
        side_effect=[
            (1, error_output, "", False),
            (0, retry_json, "", False),
        ],
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="ses_old_ci")
        assert res.session_recreated is True
        assert res.external_session_id == "ses_new_ci"
        assert mock_run.call_count == 2


def test_opencode_backend_session_not_found_diagnostics_preserves_old_id(test_project):
    """P0-2: diagnostics must keep requested old id, new id, recreated flag, first attempt snippet."""
    be = backend.OpenCodeCliBackend()
    first_stderr = "Error: Session not found for ses_old123 " + "x" * 600  # >500 chars
    retry_json = '{"sessionID": "ses_new456", "part": {"type": "text", "text": "ok"}}'
    with patch.object(
        be,
        "_run_subprocess",
        side_effect=[
            (1, "", first_stderr, False),
            (0, retry_json, "", False),
        ],
    ):
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="ses_old123")
        assert res.session_recreated is True
        diag = res.diagnostics
        assert diag is not None
        assert diag["requested_session_id"] == "ses_old123"
        assert diag["returned_session_id"] == "ses_new456"
        assert diag["session_recreated"] is True
        assert diag["first_attempt_exit_code"] == 1
        # snippet is truncated to 500 and does not contain prompt (prompt is not in stderr)
        assert "first_attempt_stderr_snippet" in diag
        assert len(diag["first_attempt_stderr_snippet"]) <= 500
        assert "Session not found" in diag["first_attempt_stderr_snippet"] or "session not found" in diag["first_attempt_stderr_snippet"].lower()
        assert diag["exit_code"] == 0


def test_opencode_backend_missing_session_id_flag(test_project):
    """P1-1: initial success without ses_... must set missing_session_id and warn."""
    be = backend.OpenCodeCliBackend()
    # Valid JSON but no session id anywhere (no ses_ in output)
    json_output = '{"part": {"type": "text", "text": "hello without session"}}'
    with patch.object(be, "_run_subprocess", return_value=(0, json_output, "", False)):
        with patch.object(backend.logger, "warning") as mock_warn:
            res = be.execute(test_project["repo_path"], "hello")
            assert res.exit_code == 0
            assert res.diagnostics is not None
            assert res.diagnostics.get("missing_session_id") is True
            # Warning should have been emitted
            assert mock_warn.call_count >= 1
            assert any("missing_session_id" in str(c) or "without session id" in str(c).lower() for c in mock_warn.call_args_list)


def test_opencode_diagnostics_normal_has_session_recreated_false(test_project):
    """Ensure normal path includes session_recreated=False for backward compat."""
    be = backend.OpenCodeCliBackend()
    json_output = '{"sessionID": "ses_abc999", "part": {"type": "text", "text": "ok"}}'
    with patch.object(be, "_run_subprocess", return_value=(0, json_output, "", False)):
        res = be.execute(test_project["repo_path"], "hello")
        assert res.diagnostics is not None
        assert res.diagnostics["session_recreated"] is False
        assert res.diagnostics["requested_session_id"] is None
        assert res.diagnostics["returned_session_id"] == "ses_abc999"


def test_coding_turn_carries_recreated_session_id_to_next_cli(test_project):
    """P0-1: after Session not found recreation, next CLI in same turn must use new external id."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "opencode", "title": "Carryover"},
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]
    store.update_session_external_id(sid, "ses_old_carry")

    # Orchestrator will request two CLI executions in same turn
    async def mock_gen(*args, **kwargs):
        history = kwargs.get("history", [])
        worker_count = sum(1 for h in history if h.get("role") == "worker")
        if worker_count == 0:
            return "first\n<cli_request>\nfirst cli\n</cli_request>"
        elif worker_count == 1:
            return "second\n<cli_request>\nsecond cli\n</cli_request>"
        else:
            return "done"

    # First CLI recreates session, second should receive new id
    first_res = backend.CodingBackendResult(
        external_session_id="ses_new_carry",
        output="first out",
        exit_code=0,
        session_recreated=True,
        diagnostics={
            "cwd": test_project["repo_path"],
            "requested_session_id": "ses_old_carry",
            "returned_session_id": "ses_new_carry",
            "tool_call_count": 1,
            "tool_failure_count": 0,
            "structured_error": None,
            "auto_rejected_permission": False,
            "exit_code": 0,
            "model": "test",
            "variant": "なし",
            "session_recreated": True,
            "first_attempt_exit_code": 1,
            "first_attempt_stderr_snippet": "Session not found",
        },
    )
    second_res = backend.CodingBackendResult(
        external_session_id="ses_new_carry",
        output="second out",
        exit_code=0,
        session_recreated=False,
        diagnostics={
            "cwd": test_project["repo_path"],
            "requested_session_id": "ses_new_carry",
            "returned_session_id": "ses_new_carry",
            "tool_call_count": 1,
            "tool_failure_count": 0,
            "structured_error": None,
            "auto_rejected_permission": False,
            "exit_code": 0,
            "model": "test",
            "variant": "なし",
            "session_recreated": False,
        },
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "carryover test"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_gen,
    ), patch("obsidian_ai_hub.coding.backend.OpenCodeCliBackend.execute") as mock_exec:
        mock_exec.side_effect = [first_res, second_res]
        asyncio.run(execute_coding_run(run_id))
        # Verify backend was called with correct session ids
        assert mock_exec.call_count == 2
        first_call_kwargs = mock_exec.call_args_list[0][1]
        second_call_kwargs = mock_exec.call_args_list[1][1]
        # first call uses old id, second uses new id
        assert first_call_kwargs["external_session_id"] == "ses_old_carry"
        assert second_call_kwargs["external_session_id"] == "ses_new_carry"

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    events, _payloads = _parse_coding_sse(res.text)
    assert events.count("worker_done") == 2

    # DB must have been updated to new id
    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["session"]["external_session_id"] == "ses_new_carry"


def test_worker_messages_not_orphaned_within_same_run(test_project):
    """P1-2: multiple worker messages in same run must remain traceable."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "opencode", "title": "Multi Worker"},
    )
    sid = res.json()["session_id"]

    async def mock_gen(*args, **kwargs):
        history = kwargs.get("history", [])
        workers = [h for h in history if h.get("role") == "worker"]
        if len(workers) == 0:
            return "a\n<cli_request>\ncli1\n</cli_request>"
        elif len(workers) == 1:
            return "b\n<cli_request>\ncli2\n</cli_request>"
        else:
            return "final"

    r1 = backend.CodingBackendResult(external_session_id="ses_m1", output="o1", exit_code=0, diagnostics={"cwd": test_project["repo_path"], "requested_session_id": None, "returned_session_id": "ses_m1", "tool_call_count": 0, "tool_failure_count": 0, "structured_error": None, "auto_rejected_permission": False, "exit_code": 0, "model": "test", "variant": "なし", "session_recreated": False})
    r2 = backend.CodingBackendResult(external_session_id="ses_m1", output="o2", exit_code=0, diagnostics={"cwd": test_project["repo_path"], "requested_session_id": "ses_m1", "returned_session_id": "ses_m1", "tool_call_count": 0, "tool_failure_count": 0, "structured_error": None, "auto_rejected_permission": False, "exit_code": 0, "model": "test", "variant": "なし", "session_recreated": False})

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "multi"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_gen,
    ), patch("obsidian_ai_hub.coding.backend.OpenCodeCliBackend.execute", side_effect=[r1, r2]):
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    events, _payloads = _parse_coding_sse(res.text)
    assert events.count("worker_done") == 2

    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    messages = [m for m in detail["messages"] if m["role"] == "worker"]
    assert len(messages) == 2
    # run_id should be same for both workers (single run)
    run_id = detail["latest_run"]["run_id"]
    # Check store helper returns both
    worker_list = store.list_worker_messages_for_run(run_id)
    assert len(worker_list) == 2
    # Also check coding_messages.run_id column via direct query (if migration applied)
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        cur = conn.execute("PRAGMA table_info(coding_messages)")
        cols = [r["name"] for r in cur.fetchall()]
        if "run_id" in cols:
            cur2 = conn.execute("SELECT count(*) as c FROM coding_messages WHERE run_id = ? AND role = 'worker'", (run_id,))
            assert cur2.fetchone()["c"] == 2
            cur_all = conn.execute("SELECT count(*) as c FROM coding_messages WHERE run_id = ?", (run_id,))
            assert cur_all.fetchone()["c"] == 8
            # v30以降は二重書き込みしないため junction は 0
            cur3 = conn.execute("SELECT count(*) as c FROM coding_run_worker_messages WHERE run_id = ?", (run_id,))
            assert cur3.fetchone()["c"] == 0
        else:
            # migration前は junction のみ
            cur3 = conn.execute("SELECT count(*) as c FROM coding_run_worker_messages WHERE run_id = ?", (run_id,))
            assert cur3.fetchone()["c"] == 2
    finally:
        conn.close()


def test_worker_messages_fallback_via_junction_when_no_run_id_column(test_project):
    """migration前互換: run_id列がない場合はjunctionで全件追跡できる."""
    # Force fallback path by mocking helper to return False
    with patch("obsidian_ai_hub.coding.store._has_run_id_column", return_value=False):
        # create session/run via real store
        from obsidian_ai_hub.coding import store as s

        session = s.create_session(
            project_id=test_project["project_id"],
            backend="opencode",
            repo_path=test_project["repo_path"],
            title="FallbackCheck",
        )
        sid = session["session_id"]
        # create a dummy user message to anchor run
        umsg = s.add_message(sid, role="user", content="hello")
        run = s.create_run(sid, user_message_id=umsg["message_id"])
        rid = run["run_id"]
        # add two worker messages via fallback path (junction)
        w1 = s.add_message(sid, role="worker", content="w1", run_id=rid)
        w2 = s.add_message(sid, role="worker", content="w2", run_id=rid)
        # list via helper should return both despite messages.run_id being NULL in this mocked path
        lst = s.list_worker_messages_for_run(rid)
        # Note: list_worker_messages_for_run also uses _has_run_id_column, so mock affects its preference
        # need to keep mock active to force junction read
        assert len(lst) == 2
        assert {m["message_id"] for m in lst} == {w1["message_id"], w2["message_id"]}

    # also verify real v30 path still works after mock context exits
    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    try:
        cur = conn.execute("PRAGMA table_info(coding_messages)")
        cols2 = [r["name"] for r in cur.fetchall()]
        assert "run_id" in cols2
    finally:
        conn.close()


def test_worker_messages_junction_failure_propagates_exception(test_project):
    """migration前: junction書き込み失敗は例外として伝播し、握りつぶされない."""
    import sqlite3

    from obsidian_ai_hub.coding import store as s
    from obsidian_ai_hub.database import get_db_connection as real_get_conn

    # add_message fallback path propagates junction error
    with patch("obsidian_ai_hub.coding.store._has_run_id_column", return_value=False):
        session = s.create_session(
            project_id=test_project["project_id"],
            backend="opencode",
            repo_path=test_project["repo_path"],
            title="FailureCheck",
        )
        sid = session["session_id"]
        umsg = s.add_message(sid, role="user", content="hello2")
        run = s.create_run(sid, user_message_id=umsg["message_id"])
        rid = run["run_id"]

        with patch("obsidian_ai_hub.coding.store.get_db_connection") as mock_get_conn:

            class ConnProxy:
                def __init__(self, real):
                    self._real = real

                def execute(self, sql, params=()):
                    if "coding_run_worker_messages" in sql and "INSERT" in sql:
                        raise sqlite3.OperationalError("injected junction failure")
                    return self._real.execute(sql, params)

                def __getattr__(self, name):
                    return getattr(self._real, name)

            def fake_conn_factory():
                return ConnProxy(real_get_conn())

            mock_get_conn.side_effect = fake_conn_factory
            try:
                s.add_message(sid, role="worker", content="should fail", run_id=rid)
                assert False, "expected sqlite3.Error not raised"
            except sqlite3.Error as exc:
                assert "injected junction failure" in str(exc)

    # append_run_worker_message also propagates
    with patch("obsidian_ai_hub.coding.store._has_run_id_column", return_value=False):
        session2 = s.create_session(
            project_id=test_project["project_id"],
            backend="opencode",
            repo_path=test_project["repo_path"],
            title="FailureCheck2",
        )
        sid2 = session2["session_id"]
        umsg2 = s.add_message(sid2, role="user", content="hello3")
        run2 = s.create_run(sid2, user_message_id=umsg2["message_id"])
        rid2 = run2["run_id"]
        w = s.add_message(sid2, role="worker", content="w", run_id=rid2)
        with patch("obsidian_ai_hub.coding.store.get_db_connection") as mock_get_conn2:

            class ConnProxy2:
                def __init__(self, real):
                    self._real = real

                def execute(self, sql, params=()):
                    if "coding_run_worker_messages" in sql and "INSERT" in sql:
                        raise sqlite3.OperationalError("injected append failure")
                    return self._real.execute(sql, params)

                def __getattr__(self, name):
                    return getattr(self._real, name)

            def fake_conn_factory2():
                return ConnProxy2(real_get_conn())

            mock_get_conn2.side_effect = fake_conn_factory2
            try:
                s.append_run_worker_message(rid2, w["message_id"])
                assert False, "expected sqlite3.Error not raised"
            except sqlite3.Error as exc2:
                assert "injected append failure" in str(exc2)


# --- Fix for OpenCode "session not found" false positive (minimal spec) ---


def test_opencode_backend_false_positive_tool_output_ignored_on_success(test_project):
    """Regression: exit 0 + tool output containing 'session not found' must NOT trigger fallback."""
    be = backend.OpenCodeCliBackend()
    # Valid sessionID plus a JSON tool line whose output contains the literal
    # that previously caused false positive (backend.py itself).
    success_json = (
        '{"sessionID": "ses_old123", "part": {"type": "text", "text": "normal output"}}\n'
        '{"type": "tool", "tool": "read", "part": {"type": "tool", "output": "src/obsidian_ai_hub/coding/backend.py line 956: if \\"session not found\\" in clean_combined.lower()"}}'
    )
    with patch.object(
        be, "_run_subprocess", return_value=(0, success_json, "", False)
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="ses_old123")
        assert mock_run.call_count == 1
        assert res.session_recreated is False
        assert res.external_session_id == "ses_old123"
        assert res.exit_code == 0
        # fallback_trigger must not be set on normal path
        assert res.diagnostics is not None
        assert "fallback_trigger" not in res.diagnostics
        assert res.diagnostics["requested_session_id"] == "ses_old123"
        assert res.diagnostics["returned_session_id"] == "ses_old123"


def test_opencode_backend_false_positive_stdout_plain_ignored_on_success(test_project):
    """Regression: plain stdout containing 'session not found' with exit 0 must NOT fallback."""
    be = backend.OpenCodeCliBackend()
    success_json = (
        '{"sessionID": "ses_old123", "part": {"type": "text", "text": "Session not found is mentioned in docs but run succeeded"}}'
    )
    # Even if stdout plain line contains the phrase outside JSON, exit 0 prevents fallback.
    # Construct stdout where a non-JSON line contains phrase.
    mixed_stdout = success_json + "\nSession not found in prior analysis (plain line)"
    with patch.object(
        be, "_run_subprocess", return_value=(0, mixed_stdout, "", False)
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="ses_old123")
        assert mock_run.call_count == 1
        assert res.session_recreated is False
        assert res.exit_code == 0


def test_opencode_backend_true_session_not_found_via_structured_error(test_project):
    """True not-found via structured_error: exit !=0 + JSON error event triggers retry."""
    be = backend.OpenCodeCliBackend()
    # structured_error is produced from JSON line with type error
    error_json = '{"type": "error", "error": "Session not found: ses_old123"}'
    retry_json = '{"sessionID": "ses_new999", "part": {"type": "text", "text": "recovered via structured"}}'
    with patch.object(
        be,
        "_run_subprocess",
        side_effect=[
            (1, error_json, "", False),
            (0, retry_json, "", False),
        ],
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="ses_old123")
        assert mock_run.call_count == 2
        assert res.session_recreated is True
        assert res.external_session_id == "ses_new999"
        assert res.exit_code == 0
        assert res.diagnostics is not None
        assert res.diagnostics["fallback_trigger"] == "structured_error"
        assert res.diagnostics["first_attempt_exit_code"] == 1
        assert "Session not found" in res.diagnostics["first_attempt_stderr_snippet"]
        # ensure retry used no --session
        argv2 = mock_run.call_args_list[1][0][0]
        assert "--session" not in argv2


def test_opencode_backend_true_session_not_found_via_stderr(test_project):
    """True not-found via stderr: exit !=0 + stderr contains phrase triggers retry."""
    be = backend.OpenCodeCliBackend()
    first_stderr = "Error: Session not found for ses_old123"
    retry_json = '{"sessionID": "ses_new888", "part": {"type": "text", "text": "recovered via stderr"}}'
    with patch.object(
        be,
        "_run_subprocess",
        side_effect=[
            (1, "", first_stderr, False),
            (0, retry_json, "", False),
        ],
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="ses_old123")
        assert mock_run.call_count == 2
        assert res.session_recreated is True
        assert res.external_session_id == "ses_new888"
        assert res.diagnostics["fallback_trigger"] == "stderr"
        assert res.diagnostics["first_attempt_exit_code"] == 1


def test_codex_backend_false_positive_tool_output_ignored_on_success(test_project):
    """Codex: exit 0 + JSON tool output containing 'thread not found' must NOT trigger fallback."""
    be = backend.CodexCliBackend()
    success_json = (
        '{"type": "thread.started", "thread_id": "th_old123"}\n'
        '{"type": "tool", "tool": "read", "output": "if \\"thread not found\\" in clean_combined"}'
    )
    with patch.object(
        be, "_run_subprocess", return_value=(0, success_json, "", False)
    ) as mock_run:
        res = be.execute(test_project["repo_path"], "prompt", external_session_id="th_old123")
        assert mock_run.call_count == 1
        assert res.session_recreated is False
        assert res.external_session_id == "th_old123"
        assert res.exit_code == 0


def test_coding_turn_picks_up_external_session_id_updated_before_first_cli(test_project):
    """High回帰: 初回CLI直前にDBが更新された場合、到達不能だった cli_count==0 分岐が cli_count==1 で正しくDB値を採用すること."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "opencode", "title": "ExternalIdSync"},
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]
    # 初期外部IDを古い値でセット
    store.update_session_external_id(sid, "ses_old_external")

    async def mock_gen(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "完了しました。"
        return "解析\n<cli_request>\nfirst cli\n</cli_request>"

    # DB更新を模擬: ワーカー開始後の初回 store.get_session 呼び出しで新しいIDを返す
    real_get_session = store.get_session
    call_count = {"n": 0}

    def fake_get_session(session_id, conn=None):
        # session_id が対象のときのみ介入、それ以外は素通し
        if session_id != sid:
            return real_get_session(session_id, conn=conn)
        call_count["n"] += 1
        sess = real_get_session(session_id, conn=conn)
        if sess is None:
            return None
        # 1回目: execute_coding_run の冒頭 session 取得 -> 古いIDのまま
        if call_count["n"] == 1:
            sess = dict(sess)
            sess["external_session_id"] = "ses_old_external"
            return sess
        # 2回目以降: 初回CLI直前の db_session 取得 -> 新しいID
        sess = dict(sess)
        sess["external_session_id"] = "ses_new_external"
        return sess

    mock_result = backend.CodingBackendResult(
        external_session_id="ses_new_external",
        output="ok after sync",
        exit_code=0,
        diagnostics={
            "cwd": test_project["repo_path"],
            "requested_session_id": "ses_new_external",
            "returned_session_id": "ses_new_external",
            "tool_call_count": 0,
            "tool_failure_count": 0,
            "structured_error": None,
            "auto_rejected_permission": False,
            "exit_code": 0,
            "model": "test",
            "variant": "なし",
            "session_recreated": False,
        },
    )

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "外部ID同期テスト"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with patch(
        "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
        side_effect=mock_gen,
    ), patch("obsidian_ai_hub.coding.store.get_session", side_effect=fake_get_session), patch(
        "obsidian_ai_hub.coding.backend.OpenCodeCliBackend.execute", return_value=mock_result
    ) as mock_exec:
        asyncio.run(execute_coding_run(run_id))
        # backend にはDB更新後の新しいIDが渡されていること（到達不能バグでは古いIDが渡る）
        assert mock_exec.call_count == 1
        assert mock_exec.call_args[1]["external_session_id"] == "ses_new_external"

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    events, _payloads = _parse_coding_sse(res.text)
    assert "done" in events


@pytest.mark.anyio
async def test_orchestrator_tool_call_event_generation(test_project):
    """Test CodingOrchestrator.generate_response_events emits detected, start, end, and text events."""
    from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator

    orchestrator = CodingOrchestrator(tool_ids=["web_search"])

    # Mock tool call in LLM response
    mock_tc = {"name": "web_search", "args": {"query": "test query"}, "id": "call_llm_123"}
    mock_res1 = MagicMock()
    mock_res1.tool_calls = [mock_tc]
    mock_res2 = MagicMock()
    mock_res2.tool_calls = None
    mock_res2.content = "最終応答"

    bound_llm = MagicMock()
    bound_llm.ainvoke = AsyncMock(side_effect=[mock_res1, mock_res2])
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = bound_llm

    mock_tool = MagicMock()
    mock_tool.name = "web_search"
    mock_tool.invoke.return_value = "A" * 25000  # Truncation test (> 20000 chars)

    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", return_value=mock_llm), \
         patch("obsidian_ai_hub.agents.registry.resolve_tools_with_context", return_value=[mock_tool]):

        events = []
        async for evt in orchestrator.generate_response_events(
            history=[], repo_path=test_project["repo_path"], backend_name="opencode", phase="initial", phase_turn=1
        ):
            events.append(evt)

        # Check event types order: detected -> start -> end -> text
        event_types = [e["type"] for e in events]
        assert event_types == ["detected", "start", "end", "text"]

        detected = events[0]
        assert detected["call_key"] == "1:1:0"
        assert detected["tool_name"] == "web_search"

        start = events[1]
        assert start["call_key"] == "1:1:0"
        assert start["provider_call_id"] == "call_llm_123"
        assert start["args"] == {"query": "test query"}

        end = events[2]
        assert end["status"] == "succeeded"
        # SSE live result truncated to 2000 chars
        assert len(end["result"]) <= 2000
        assert end["result"].endswith("...（ライブ表示用に省略）")
        # DB full result truncated to 20000 chars
        assert len(end["full_result"]) <= 20000
        assert end["full_result"].endswith("...（保存表示用に省略）")
        # raw_result is un-truncated
        assert len(end["raw_result"]) == 25000

        text = events[3]
        assert text["content"] == "最終応答"


@pytest.mark.anyio
async def test_orchestrator_tool_call_exception_handling(test_project):
    """Test tool invocation exception emits end event with failed status before re-raising."""
    from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator

    orchestrator = CodingOrchestrator(tool_ids=["web_search"])

    mock_tc = {"name": "web_search", "args": {}, "id": "call_err"}
    mock_res1 = MagicMock()
    mock_res1.tool_calls = [mock_tc]

    bound_llm = MagicMock()
    bound_llm.ainvoke = AsyncMock(return_value=mock_res1)
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = bound_llm

    mock_tool = MagicMock()
    mock_tool.name = "web_search"
    mock_tool.invoke.side_effect = RuntimeError("Tool execution crashed")

    with patch("obsidian_ai_hub.coding.orchestrator.create_langchain_llm", return_value=mock_llm), \
         patch("obsidian_ai_hub.agents.registry.resolve_tools_with_context", return_value=[mock_tool]):

        events = []
        with pytest.raises(RuntimeError, match="Tool execution crashed"):
            async for evt in orchestrator.generate_response_events(
                history=[], repo_path=test_project["repo_path"], backend_name="opencode", phase="initial", phase_turn=1
            ):
                events.append(evt)

        assert len(events) == 3  # detected, start, end
        end = events[2]
        assert end["type"] == "end"
        assert end["status"] == "failed"
        assert end["error"] == "Tool execution crashed"


def test_mark_interrupted_tool_calls_on_startup(test_project):
    """Test mark_interrupted_runs_on_startup marks lingering running tool calls as interrupted."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "opencode"},
    )
    sid = res.json()["session_id"]

    user_msg = store.add_message(sid, "user", "run query")
    run = store.create_run(sid, user_msg["message_id"])

    # Create running tool call
    store.create_orchestrator_tool_call(
        call_id="cotc_test123",
        run_id=run["run_id"],
        phase="initial",
        phase_turn=1,
        iteration=1,
        call_index=0,
        call_key="1:1:0",
        tool_name="web_search",
        args={"q": "test"},
        status="running",
    )

    count = store.mark_interrupted_runs_on_startup()
    assert count >= 1

    tc = store.get_orchestrator_tool_call("cotc_test123")
    assert tc is not None
    assert tc["status"] == "interrupted"
    assert tc["error"] == "Interrupted due to server restart"


def test_coding_session_detail_returns_orchestrator_tool_calls(test_project):
    """Test GET /sessions/{session_id} includes orchestrator_tool_calls in response."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "opencode"},
    )
    sid = res.json()["session_id"]

    user_msg = store.add_message(sid, "user", "test prompt")
    run = store.create_run(sid, user_msg["message_id"])
    store.update_message_run_id(user_msg["message_id"], run["run_id"])

    store.create_orchestrator_tool_call(
        call_id="cotc_999",
        run_id=run["run_id"],
        phase="initial",
        phase_turn=1,
        iteration=1,
        call_index=0,
        call_key="1:1:0",
        tool_name="vault_search",
        args={"query": "hello"},
        status="succeeded",
    )

    detail_res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert "orchestrator_tool_calls" in detail
    tcs = detail["orchestrator_tool_calls"]
    assert len(tcs) == 1
    assert tcs[0]["call_id"] == "cotc_999"
    assert tcs[0]["tool_name"] == "vault_search"
    assert tcs[0]["args"] == {"query": "hello"}
