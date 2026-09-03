"""Tests for coding single-turn CLI (coding/cli.py)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from unittest.mock import patch

import pytest

from obsidian_ai_hub.coding import backend, service, store


@pytest.fixture
def test_project(tmp_path):
    """Create a dummy project with a real Git repo."""
    git_repo = tmp_path / "test_repo"
    git_repo.mkdir()
    subprocess.run(["git", "init"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=git_repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=git_repo, check=True)
    (git_repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=git_repo, check=True)

    from obsidian_ai_hub.database import get_db_connection

    conn = get_db_connection()
    cur = conn.execute(
        """
        INSERT INTO projects (
            normalized_name, display_name, domain, status, project_path, created_at, updated_at
        ) VALUES ('test-repo-cli', 'Test Repo CLI', 'personal', 'active', ?, datetime('now'), datetime('now'))
        """,
        (str(git_repo),),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return {"project_id": pid, "repo_path": str(git_repo)}


def _mock_success_stream(session_id: str, prompt: str):
    """Return an async generator yielding success SSE chunks."""
    import json as _json

    async def _gen():
        yield f"data: {_json.dumps({'event': 'start', 'run_id': 'crun_abc123', 'is_dirty': False, 'dirty_summary': None}, ensure_ascii=False)}\n\n"
        yield f"data: {_json.dumps({'event': 'orchestrator_message', 'phase': 'initial', 'message': {'message_id': 'cmsg_1', 'session_id': session_id, 'sequence': 2, 'role': 'orchestrator', 'content': '応答本文テスト', 'created_at': '2026-09-06T00:00:00+09:00'}}, ensure_ascii=False)}\n\n"
        yield f"data: {_json.dumps({'event': 'done', 'run_id': 'crun_abc123', 'status': 'completed', 'git_status': {'branch': 'main', 'ahead': 0, 'behind': 0, 'insertions': 1, 'deletions': 0}}, ensure_ascii=False)}\n\n"

    return _gen()


def _mock_error_stream(session_id: str, prompt: str):
    async def _gen():
        import json as _json

        yield f"data: {_json.dumps({'event': 'start', 'run_id': 'crun_err123', 'is_dirty': False, 'dirty_summary': None}, ensure_ascii=False)}\n\n"
        yield f"data: {_json.dumps({'event': 'error', 'message': 'Session not found'}, ensure_ascii=False)}\n\n"

    return _gen()


def test_coding_normal_mode_stdout_stderr_separation(test_project, capsys):
    from obsidian_ai_hub.coding.cli import main_coding

    # Create a session for resume path to test separation via new session path
    # Use new session creation inside main_coding, so we only need project_id
    with patch.object(service, "run_coding_turn_stream", side_effect=_mock_success_stream):
        # main_coding will create a new session; we need to allow it to succeed
        # It will call asyncio.run; our mock returns async generator
        try:
            main_coding(project_id=test_project["project_id"], resume_session=None, prompt="hello", json_output=False)
        except SystemExit as e:
            pytest.fail(f"should not exit, got {e.code}")

    captured = capsys.readouterr()
    # stdout should contain only response body
    assert "応答本文テスト" in captured.out
    # stdout should not contain progress markers
    assert "[session]" not in captured.out
    assert "[run]" not in captured.out
    # stderr should contain meta
    assert "[session]" in captured.err or "[run]" in captured.err or "[git_status]" in captured.err


def test_coding_json_mode_single_parseable_json(test_project, capsys):
    from obsidian_ai_hub.coding.cli import main_coding

    with patch.object(service, "run_coding_turn_stream", side_effect=_mock_success_stream):
        try:
            main_coding(project_id=test_project["project_id"], resume_session=None, prompt="hello json", json_output=True)
        except SystemExit as e:
            pytest.fail(f"should not exit on success, got {e.code}")

    captured = capsys.readouterr()
    # stdout should be single JSON
    lines = [l for l in captured.out.strip().splitlines() if l.strip()]
    # Find JSON object (might be indented multi-line, but main_coding writes single line)
    json_text = captured.out.strip()
    data = json.loads(json_text)
    assert data["ok"] is True
    assert "response" in data
    assert data["response"] == "応答本文テスト"
    assert "session" in data
    assert data["session"]["project_id"] == test_project["project_id"]
    assert "run" in data
    assert data["run"]["id"] == "crun_abc123"
    assert data["run"]["status"] == "completed"
    assert data["run"]["git_status"]["branch"] == "main"
    # stderr should not contain duplicate error details (and for success, stderr is mostly quiet)
    # In json mode, stderr should not contain response body duplicated
    assert "応答本文テスト" not in captured.err or "[session]" not in captured.err  # allow minimal, but not polluted


def test_coding_json_mode_runtime_failure_ok_false(test_project, capsys):
    from obsidian_ai_hub.coding.cli import main_coding

    # Simulate error stream: first create a session then error on turn
    # For new session, creation succeeds but turn yields error event
    # Our _mock_error_stream will yield start then error; service will not yield done
    # main_coding should output ok:false and exit 1
    with patch.object(service, "run_coding_turn_stream", side_effect=_mock_error_stream):
        with pytest.raises(SystemExit) as exc:
            main_coding(project_id=test_project["project_id"], resume_session=None, prompt="fail me", json_output=True)
        assert exc.value.code == 1

    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["ok"] is False
    assert "error" in data
    assert "type" in data["error"]
    assert "message" in data["error"]
    # stderr should not duplicate error details in json mode (per spec)
    # Our implementation suppresses stderr duplication for json mode
    assert captured.err.strip() == "" or "Error:" not in captured.err


def test_coding_text_mode_runtime_failure_exit_1_and_stderr(test_project, capsys):
    from obsidian_ai_hub.coding.cli import main_coding

    with patch.object(service, "run_coding_turn_stream", side_effect=_mock_error_stream):
        with pytest.raises(SystemExit) as exc:
            main_coding(project_id=test_project["project_id"], resume_session=None, prompt="fail text", json_output=False)
        assert exc.value.code == 1

    captured = capsys.readouterr()
    # stdout should not contain response (or empty)
    # stderr should contain error info
    assert "error" in captured.err.lower() or "Session not found" in captured.err


def test_coding_resume_uses_existing_session(test_project, capsys):
    from obsidian_ai_hub.coding.cli import main_coding

    # Create a session via store
    sess = store.create_session(
        project_id=test_project["project_id"],
        backend="codex",
        repo_path=test_project["repo_path"],
        title="Existing Session",
    )
    sid = sess["session_id"]

    # Mock stream to verify prompt is passed and response returned
    captured_prompt = {}

    def _mock_stream_capture(session_id, prompt):
        captured_prompt["prompt"] = prompt
        captured_prompt["session_id"] = session_id
        return _mock_success_stream(session_id, prompt)

    with patch.object(service, "run_coding_turn_stream", side_effect=_mock_stream_capture):
        try:
            main_coding(project_id=None, resume_session=sid, prompt="resume hello", json_output=False)
        except SystemExit as e:
            pytest.fail(f"resume should succeed, got exit {e.code}")

    assert captured_prompt["prompt"] == "resume hello"
    assert captured_prompt["session_id"] == sid
    captured = capsys.readouterr()
    assert "応答本文テスト" in captured.out


def test_coding_resume_session_not_found_json(test_project, capsys):
    from obsidian_ai_hub.coding.cli import main_coding

    with pytest.raises(SystemExit) as exc:
        main_coding(project_id=None, resume_session="cses_notfound", prompt="hi", json_output=True)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["ok"] is False
    assert data["error"]["type"] == "SessionNotFound"


def test_coding_project_not_found_json(test_project, capsys):
    from obsidian_ai_hub.coding.cli import main_coding

    with pytest.raises(SystemExit) as exc:
        main_coding(project_id=999999, resume_session=None, prompt="hi", json_output=True)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["ok"] is False
    assert "ProjectNotFound" in data["error"]["type"] or "not found" in data["error"]["message"].lower()


def test_coding_git_repo_invalid_error(test_project, tmp_path, capsys):
    from obsidian_ai_hub.coding.cli import main_coding
    from obsidian_ai_hub.database import get_db_connection

    # Create project with invalid repo path
    bad_path = str(tmp_path / "nonexistent_repo")
    conn = get_db_connection()
    cur = conn.execute(
        "INSERT INTO projects (normalized_name, display_name, domain, status, project_path, created_at, updated_at) VALUES ('bad-repo', 'Bad Repo', 'personal', 'active', ?, datetime('now'), datetime('now'))",
        (bad_path,),
    )
    bad_pid = cur.lastrowid
    conn.commit()
    conn.close()

    with pytest.raises(SystemExit) as exc:
        main_coding(project_id=bad_pid, resume_session=None, prompt="hi", json_output=True)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["ok"] is False
    assert "GitRepoInvalid" in data["error"]["type"] or "git" in data["error"]["message"].lower()


def test_coding_execution_logger_records_success(test_project, capsys):
    from obsidian_ai_hub.coding.cli import main_coding
    from obsidian_ai_hub.utils import execution_logger

    with patch.object(service, "run_coding_turn_stream", side_effect=_mock_success_stream):
        main_coding(project_id=test_project["project_id"], resume_session=None, prompt="log test", json_output=False)

    # Check last command log
    items, total = execution_logger.list_execution_logs(kind="command")
    assert total >= 1
    # Find coding entry
    coding_items = [i for i in items if i["name"] == "coding"]
    assert len(coding_items) >= 1
    detail = execution_logger.get_command_run_detail(coding_items[0]["id"])
    assert detail is not None
    assert detail["status"] == "succeeded"
    capsys.readouterr()


def test_coding_execution_logger_records_failure(test_project, capsys):
    from obsidian_ai_hub.coding.cli import main_coding
    from obsidian_ai_hub.utils import execution_logger

    with patch.object(service, "run_coding_turn_stream", side_effect=_mock_error_stream):
        with pytest.raises(SystemExit):
            main_coding(project_id=test_project["project_id"], resume_session=None, prompt="fail log", json_output=False)

    items, total = execution_logger.list_execution_logs(kind="command")
    coding_items = [i for i in items if i["name"] == "coding"]
    assert len(coding_items) >= 1
    # The most recent failed run should be among them; find one with failed status
    failed = [execution_logger.get_command_run_detail(i["id"]) for i in coding_items]
    assert any(d and d["status"] == "failed" for d in failed)
    capsys.readouterr()


def test_coding_default_backend_is_opencode_when_unspecified(test_project, monkeypatch):
    from obsidian_ai_hub.utils import config
    from obsidian_ai_hub.coding import cli as coding_cli

    # Ensure default is opencode (config.test.yml has no coding.default_backend)
    monkeypatch.setattr(config, "CODING_DEFAULT_BACKEND", "opencode")
    # Also ensure cli sees same value (cli reads config at runtime)
    with patch.object(service, "run_coding_turn_stream", side_effect=_mock_success_stream):
        # Use main_coding which will create session via _create_new_session
        from obsidian_ai_hub.coding.cli import main_coding

        main_coding(project_id=test_project["project_id"], resume_session=None, prompt="default backend", json_output=True)
    # Verify last created session uses opencode
    from obsidian_ai_hub.coding import store as coding_store

    sessions = coding_store.list_sessions_by_project(test_project["project_id"])
    assert len(sessions) >= 1
    latest = sessions[0]  # ordered by created_at DESC
    assert latest["backend"] == "opencode"


def test_coding_default_backend_codex_via_config(test_project, monkeypatch):
    from obsidian_ai_hub.utils import config

    monkeypatch.setattr(config, "CODING_DEFAULT_BACKEND", "codex")
    with patch.object(service, "run_coding_turn_stream", side_effect=_mock_success_stream):
        from obsidian_ai_hub.coding.cli import main_coding

        main_coding(project_id=test_project["project_id"], resume_session=None, prompt="codex backend", json_output=True)

    from obsidian_ai_hub.coding import store as coding_store

    sessions = coding_store.list_sessions_by_project(test_project["project_id"])
    assert len(sessions) >= 1
    latest = sessions[0]
    assert latest["backend"] == "codex"


def test_coding_resume_ignores_default_backend(test_project, monkeypatch, capsys):
    from obsidian_ai_hub.utils import config

    # Create session with opencode explicitly
    sess = store.create_session(
        project_id=test_project["project_id"],
        backend="opencode",
        repo_path=test_project["repo_path"],
        title="Resume Backend Test",
    )
    sid = sess["session_id"]
    assert sess["backend"] == "opencode"

    # Change default to codex, resume should still use opencode
    monkeypatch.setattr(config, "CODING_DEFAULT_BACKEND", "codex")

    def _capture(session_id, prompt):
        # Verify that resume does not create new session with codex
        # Just return success stream
        return _mock_success_stream(session_id, prompt)

    with patch.object(service, "run_coding_turn_stream", side_effect=_capture):
        from obsidian_ai_hub.coding.cli import main_coding

        main_coding(project_id=None, resume_session=sid, prompt="resume check", json_output=False)

    # Session backend should remain opencode
    refreshed = store.get_session(sid)
    assert refreshed["backend"] == "opencode"
    capsys.readouterr()


def test_coding_invalid_backend_raises(test_project, monkeypatch, capsys):
    from obsidian_ai_hub.utils import config
    from obsidian_ai_hub.coding import cli as coding_cli

    monkeypatch.setattr(config, "CODING_DEFAULT_BACKEND", "invalid_backend")

    # _create_new_session should raise ValueError for invalid backend
    with pytest.raises(ValueError, match="Invalid CODING_DEFAULT_BACKEND"):
        coding_cli._create_new_session(test_project["project_id"])

    # Via main_coding, invalid should result in ok:false exit 1 json
    with pytest.raises(SystemExit) as exc:
        coding_cli.main_coding(project_id=test_project["project_id"], resume_session=None, prompt="invalid", json_output=True)
    assert exc.value.code == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["ok"] is False
    assert "Invalid" in data["error"]["message"] or "CODING_DEFAULT_BACKEND" in data["error"]["message"]
