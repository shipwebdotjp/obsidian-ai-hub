"""Unit and integration tests for Dedicated Coding Workspace v1."""

import asyncio
import json
import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.coding import acp, backend, store, service
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
                cur_id = int(line[len("id:") :].strip())
            except ValueError:
                cur_id = None
        elif line.startswith("data:"):
            raw = line[len("data:") :].strip()
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
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=git_repo, check=True)

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
            "backend": "opencode",
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
            return "<final_report>テスト成功を確認しました。完了です。</final_report>"
        return "解析結果です。\n<cli_request>\npytest\n</cli_request>"

    mock_cli_res = acp.AcpExecutionResult(
        acp_session_id="th_123",
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

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_generate_response,
        ),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            return_value=mock_cli_res,
        ),
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
    assert (
        len(detail["messages"]) == 5
    )  # user, orchestrator #1, cli_request, worker, orchestrator #2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][1]["role"] == "orchestrator"
    assert detail["messages"][2]["role"] == "cli_request"
    assert detail["messages"][3]["role"] == "worker"
    assert detail["messages"][4]["role"] == "orchestrator"
    assert detail["session"]["acp_session_id"] == "th_123"

    # 5. Delete session
    res = client.delete(f"/api/v1/coding/sessions/{sid}", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"


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
            "backend": "opencode",
            "title": "Max Iterations Session",
        },
    )
    sid = res.json()["session_id"]

    # Orchestrator always asks for CLI execution
    async def mock_generate_response(*args, **kwargs):
        return "まだ作業が必要です。\n<cli_request>\npytest --fix\n</cli_request>"

    mock_cli_res = acp.AcpExecutionResult(
        acp_session_id="th_max123",
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

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_generate_response,
        ),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            return_value=mock_cli_res,
        ) as mock_exec,
    ):
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
            "backend": "opencode",
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
        return "<final_report>エラーが発生したため原因を説明します。文法エラーを修正してください。</final_report>"

    mock_cli_res = acp.AcpExecutionResult(
        acp_session_id="th_err123",
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

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_generate_response,
        ),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            return_value=mock_cli_res,
        ),
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
    assert (
        len(messages) == 5
    )  # user, orch request, cli_request, worker error, orch final report
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
    session1 = store.create_session(pid, "opencode", repo, title="Default Tools Session")
    sid1 = session1["session_id"]
    eff_tools1 = store.get_effective_session_tool_ids(sid1)
    assert eff_tools1 == custom_defaults

    # 4. Create session with explicit custom tool_ids
    custom_session_tools = ["run_shell"]
    session2 = store.create_session(
        pid, "opencode", repo, title="Custom Tools Session", tool_ids=custom_session_tools
    )
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


def test_coding_tool_catalog_excludes_agent_delegate(test_project):
    # agent_delegate requires a parent AI-agent run (agent_id). A coding session
    # has no agent run, so the tool can only ever fail and must not be offered
    # or selectable.
    all_ids = store.get_all_available_tool_ids()
    assert "agent_delegate" not in all_ids
    assert "run_shell" in all_ids

    catalog_ids = [t["tool_id"] for t in store.list_available_coding_tools()]
    assert "agent_delegate" not in catalog_ids

    # User defaults never include it, and explicit selection is dropped.
    assert "agent_delegate" not in store.get_user_default_tool_ids()
    saved = store.update_user_default_tool_ids(["agent_delegate", "web_search"])
    assert saved == ["web_search"]

    session = store.create_session(
        test_project["project_id"],
        "opencode",
        test_project["repo_path"],
        title="Exclude Delegate",
    )
    updated = store.update_session_tool_ids(
        session["session_id"], ["agent_delegate", "web_search"]
    )
    assert updated == ["web_search"]


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
    res = client.put(
        "/api/v1/coding/defaults", headers=headers, json={"tool_ids": new_defaults}
    )
    assert res.status_code == 200
    assert res.json()["default_tool_ids"] == new_defaults

    # 3. Create session
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
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


def test_coding_session_title_update_api(test_project):
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "Before Title",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]

    # Update title (trims whitespace) and persists on refetch
    res = client.put(
        f"/api/v1/coding/sessions/{sid}",
        headers=headers,
        json={"title": "  After Title  "},
    )
    assert res.status_code == 200
    assert res.json()["session"]["title"] == "After Title"

    res = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers)
    assert res.status_code == 200
    assert res.json()["session"]["title"] == "After Title"

    # Blank-only title is rejected
    res = client.put(
        f"/api/v1/coding/sessions/{sid}",
        headers=headers,
        json={"title": "   "},
    )
    assert res.status_code == 400

    # Unknown session returns 404
    res = client.put(
        "/api/v1/coding/sessions/cses_missing",
        headers=headers,
        json={"title": "New Title"},
    )
    assert res.status_code == 404


def test_coding_session_create_rejects_retired_backend_and_transport(test_project):
    """API session creation accepts only backend=opencode + transport=acp."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    pid = test_project["project_id"]

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": pid, "backend": "codex", "title": "Retired"},
    )
    assert res.status_code == 400

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": pid, "backend": "opencode", "transport": "direct_cli"},
    )
    assert res.status_code == 400

    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": pid, "backend": "opencode", "transport": "acp"},
    )
    assert res.status_code == 200
    assert res.json()["backend"] == "opencode"
    assert res.json()["transport"] == "acp"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (None, True),
        ("", True),
        ("   ", True),
        (service.DEFAULT_CODING_SESSION_TITLE, True),
        ("Task task_bde93d76a598 step 2", True),
        ("ユーザー指定のタイトル", False),
        ("Capability入力スキーマ二重定義の調査", False),
    ],
)
def test_coding_title_generation_eligibility(title, expected):
    assert service._should_update_coding_title(title) is expected


@pytest.mark.anyio
async def test_orchestrator_tool_restriction(test_project):
    """Test that Orchestrator binds only permitted tools and respects tool restrictions."""
    from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator

    # Case A: empty tool_ids -> bind_tools is not called / no tools available
    orch_empty = CodingOrchestrator(tool_ids=[])

    mock_ai_msg = MagicMock()
    mock_ai_msg.content = "No tools used."
    mock_ai_msg.tool_calls = []

    with patch(
        "obsidian_ai_hub.coding.orchestrator.create_langchain_llm"
    ) as mock_create_llm:
        mock_llm = MagicMock()
        mock_with = MagicMock()
        mock_with.ainvoke = AsyncMock(return_value=mock_ai_msg)
        mock_llm.bind_tools.return_value = mock_with
        mock_llm.ainvoke = AsyncMock(return_value=mock_ai_msg)
        mock_create_llm.return_value = mock_llm

        resp = await orch_empty.generate_response(
            [], test_project["repo_path"], "codex"
        )
        assert resp == "No tools used."
        mock_llm.bind_tools.assert_called_once()
        bound_tools = mock_llm.bind_tools.call_args[0][0]
        assert [t.name for t in bound_tools] == ["ask_user"]

    # Case B: specified tool_ids -> bind_tools receives only permitted BaseTools
    orch_permitted = CodingOrchestrator(tool_ids=["web_search"])
    with patch(
        "obsidian_ai_hub.coding.orchestrator.create_langchain_llm"
    ) as mock_create_llm:
        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        mock_llm_with_tools.ainvoke = AsyncMock(return_value=mock_ai_msg)
        mock_llm.bind_tools.return_value = mock_llm_with_tools
        mock_create_llm.return_value = mock_llm

        resp = await orch_permitted.generate_response(
            [], test_project["repo_path"], "codex"
        )
        assert resp == "No tools used."
        mock_llm.bind_tools.assert_called_once()
        bound_tools = mock_llm.bind_tools.call_args[0][0]
        tool_names = [t.name for t in bound_tools]
        assert "web_search" in tool_names
        assert "run_shell" not in tool_names


# --- P0/P1 regression tests for session recreation carry-over & diagnostics ---


def test_acp_title_generation_preserves_explicit_title(test_project):
    """ACP title generation must not overwrite a user-supplied title."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "ユーザー指定のタイトル",
        },
    )
    sid = res.json()["session_id"]

    async def mock_generate_response(*args, **kwargs):
        if any(h.get("role") == "worker" for h in kwargs.get("history", [])):
            return "<final_report>完了しました。</final_report>"
        return "解析\n<cli_request>\nopencode exec test\n</cli_request>"

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "実装して"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_generate_response,
        ),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            return_value=acp.AcpExecutionResult(
                acp_session_id="acp_title_456", output="worker output", exit_code=0
            ),
        ),
        patch("obsidian_ai_hub.agents.runtime.generate_session_title") as mock_title,
    ):
        asyncio.run(execute_coding_run(run_id))

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    assert '"session_title"' not in res.text
    mock_title.assert_not_called()
    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["session"]["title"] == "ユーザー指定のタイトル"


def test_acp_title_generation_failure_does_not_fail_turn(test_project):
    """A title LLM failure leaves the default title and completes the ACP turn."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={"project_id": test_project["project_id"], "backend": "opencode"},
    )
    sid = res.json()["session_id"]

    async def mock_generate_response(*args, **kwargs):
        if any(h.get("role") == "worker" for h in kwargs.get("history", [])):
            return "<final_report>完了しました。</final_report>"
        return "解析\n<cli_request>\nopencode exec test\n</cli_request>"

    res = client.post(
        f"/api/v1/coding/sessions/{sid}/runs",
        headers=headers,
        json={"content": "実装して"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_generate_response,
        ),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            return_value=acp.AcpExecutionResult(
                acp_session_id="acp_title_789", output="worker output", exit_code=0
            ),
        ),
        patch(
            "obsidian_ai_hub.agents.runtime.generate_session_title",
            side_effect=RuntimeError("title LLM unavailable"),
        ),
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


def test_coding_turn_carries_recreated_session_id_to_next_cli(test_project):
    """P0-1: after ACP session recreation, next worker turn must use the new ACP id."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "Carryover",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]
    store.update_session_acp_id(sid, "ses_old_carry", "opencode_acp")

    # Orchestrator will request two CLI executions in same turn
    async def mock_gen(*args, **kwargs):
        history = kwargs.get("history", [])
        worker_count = sum(1 for h in history if h.get("role") == "worker")
        if worker_count == 0:
            return "first\n<cli_request>\nfirst cli\n</cli_request>"
        elif worker_count == 1:
            return "second\n<cli_request>\nsecond cli\n</cli_request>"
        else:
            return "<final_report>done</final_report>"

    # First CLI recreates session, second should receive new id
    first_res = acp.AcpExecutionResult(
        acp_session_id="ses_new_carry",
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
    second_res = acp.AcpExecutionResult(
        acp_session_id="ses_new_carry",
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

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_gen,
        ),
        patch("obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn") as mock_exec,
    ):
        mock_exec.side_effect = [first_res, second_res]
        asyncio.run(execute_coding_run(run_id))
        # Verify backend was called with correct session ids
        assert mock_exec.call_count == 2
        first_call_kwargs = mock_exec.call_args_list[0][1]
        second_call_kwargs = mock_exec.call_args_list[1][1]
        # first call uses old id, second uses new id
        assert first_call_kwargs["acp_session_id"] == "ses_old_carry"
        assert second_call_kwargs["acp_session_id"] == "ses_new_carry"

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    events, _payloads = _parse_coding_sse(res.text)
    assert events.count("worker_done") == 2

    # DB must have been updated to new id
    detail = client.get(f"/api/v1/coding/sessions/{sid}", headers=headers).json()
    assert detail["session"]["acp_session_id"] == "ses_new_carry"


def test_worker_messages_not_orphaned_within_same_run(test_project):
    """P1-2: multiple worker messages in same run must remain traceable."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "Multi Worker",
        },
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
            return "<final_report>final</final_report>"

    r1 = acp.AcpExecutionResult(
        acp_session_id="ses_m1",
        output="o1",
        exit_code=0,
        diagnostics={
            "cwd": test_project["repo_path"],
            "requested_session_id": None,
            "returned_session_id": "ses_m1",
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
    r2 = acp.AcpExecutionResult(
        acp_session_id="ses_m1",
        output="o2",
        exit_code=0,
        diagnostics={
            "cwd": test_project["repo_path"],
            "requested_session_id": "ses_m1",
            "returned_session_id": "ses_m1",
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
        json={"content": "multi"},
    )
    assert res.status_code == 202
    run_id = res.json()["run"]["run_id"]

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_gen,
        ),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            side_effect=[r1, r2],
        ),
    ):
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
            cur2 = conn.execute(
                "SELECT count(*) as c FROM coding_messages WHERE run_id = ? AND role = 'worker'",
                (run_id,),
            )
            assert cur2.fetchone()["c"] == 2
            cur_all = conn.execute(
                "SELECT count(*) as c FROM coding_messages WHERE run_id = ?", (run_id,)
            )
            assert cur_all.fetchone()["c"] == 8
            # v30以降は二重書き込みしないため junction は 0
            cur3 = conn.execute(
                "SELECT count(*) as c FROM coding_run_worker_messages WHERE run_id = ?",
                (run_id,),
            )
            assert cur3.fetchone()["c"] == 0
        else:
            # migration前は junction のみ
            cur3 = conn.execute(
                "SELECT count(*) as c FROM coding_run_worker_messages WHERE run_id = ?",
                (run_id,),
            )
            assert cur3.fetchone()["c"] == 2
    finally:
        conn.close()


# --- Fix for OpenCode "session not found" false positive (minimal spec) ---


def test_coding_turn_picks_up_acp_session_id_updated_before_first_cli(
    test_project,
):
    """High回帰: 初回ACP直前にDBが更新された場合、cli_count==1 で正しくDB値を採用すること."""
    app = create_app(token="test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    res = client.post(
        "/api/v1/coding/sessions",
        headers=headers,
        json={
            "project_id": test_project["project_id"],
            "backend": "opencode",
            "title": "ExternalIdSync",
        },
    )
    assert res.status_code == 200
    sid = res.json()["session_id"]
    # 初期外部IDを古い値でセット
    store.update_session_acp_id(sid, "ses_old_external", "opencode_acp")

    async def mock_gen(*args, **kwargs):
        history = kwargs.get("history", [])
        if any(h.get("role") == "worker" for h in history):
            return "<final_report>完了しました。</final_report>"
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
            sess["acp_session_id"] = "ses_old_external"
            return sess
        # 2回目以降: 初回CLI直前の db_session 取得 -> 新しいID
        sess = dict(sess)
        sess["acp_session_id"] = "ses_new_external"
        return sess

    mock_result = acp.AcpExecutionResult(
        acp_session_id="ses_new_external",
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

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.CodingOrchestrator.generate_response",
            side_effect=mock_gen,
        ),
        patch("obsidian_ai_hub.coding.store.get_session", side_effect=fake_get_session),
        patch(
            "obsidian_ai_hub.coding.acp.AcpClientBackend.execute_turn",
            return_value=mock_result,
        ) as mock_exec,
    ):
        asyncio.run(execute_coding_run(run_id))
        # backend にはDB更新後の新しいIDが渡されていること（到達不能バグでは古いIDが渡る）
        assert mock_exec.call_count == 1
        assert mock_exec.call_args[1]["acp_session_id"] == "ses_new_external"

    res = client.get(f"/api/v1/coding/runs/{run_id}/events", headers=headers)
    assert res.status_code == 200
    events, _payloads = _parse_coding_sse(res.text)
    assert "done" in events


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

    with (
        patch(
            "obsidian_ai_hub.coding.orchestrator.create_langchain_llm",
            return_value=mock_llm,
        ),
        patch(
            "obsidian_ai_hub.agents.registry.resolve_tools_with_context",
            return_value=[mock_tool],
        ),
    ):
        events = []
        with pytest.raises(RuntimeError, match="Tool execution crashed"):
            async for evt in orchestrator.generate_response_events(
                history=[],
                repo_path=test_project["repo_path"],
                backend_name="opencode",
                phase="initial",
                phase_turn=1,
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
