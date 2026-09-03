"""CLI implementation for Coding Orchestrator single-turn execution (--coding)."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from obsidian_ai_hub.coding import backend, service, store
from obsidian_ai_hub.utils import config


def _classify_error_type(exc: Exception, message: str = "") -> str:
    name = type(exc).__name__ if exc else "CodingError"
    msg_lower = (message or "").lower()
    if "project" in msg_lower and "not found" in msg_lower:
        return "ProjectNotFound"
    if "session" in msg_lower and "not found" in msg_lower:
        return "SessionNotFound"
    if "is not a valid git repository" in message or "is not a valid git repository" in msg_lower:
        return "GitRepoInvalid"
    if "同一リポジトリで別のコーディング実行が進行中" in message:
        return "RepoBusy"
    if "orchestrator" in msg_lower:
        return "OrchestratorError"
    return name


async def _collect_coding_result(
    session_id: str,
    prompt: str,
    json_output: bool,
) -> Dict[str, Any]:
    """Consume run_coding_turn_stream SSE and return structured result.

    Returns dict with keys: ok, response_text, session, run, git_status, error, done_data
    """
    final_response_text = ""
    done_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    run_id: Optional[str] = None
    git_status: Optional[Dict[str, Any]] = None
    worker_done_payload: Optional[Dict[str, Any]] = None
    orchestrator_messages = []

    # For text mode, emit progress to stderr
    def stderr_write(msg: str):
        if not json_output:
            sys.stderr.write(msg)
            sys.stderr.flush()

    async for chunk in service.run_coding_turn_stream(session_id, prompt):
        # chunk is "data: {...}\n\n"
        for line in chunk.splitlines():
            if not line.startswith("data:"):
                continue
            payload_str = line[len("data:"):].strip()
            if payload_str.startswith(" "):
                payload_str = payload_str[1:]
            try:
                data = json.loads(payload_str)
            except json.JSONDecodeError:
                continue

            evt = data.get("event")
            if evt == "start":
                run_id = data.get("run_id")
                if not json_output:
                    stderr_write(f"[run] run_id={run_id}\n")
                    if data.get("is_dirty"):
                        stderr_write(f"[git] dirty_summary={data.get('dirty_summary')}\n")
            elif evt == "orchestrator_start":
                phase = data.get("phase", "")
                stderr_write(f"[orchestrator] phase={phase}\n")
            elif evt == "orchestrator_message":
                msg = data.get("message", {})
                if msg.get("role") == "orchestrator":
                    orchestrator_messages.append(msg)
                    final_response_text = msg.get("content", "") or ""
                    # run id may be in latest run, but keep as is
                stderr_write(f"[orchestrator_message] phase={data.get('phase','')}\n")
            elif evt == "cli_request":
                msg = data.get("message", {})
                stderr_write(f"[cli_request] {msg.get('content','')[:200]}\n")
            elif evt == "worker_start":
                stderr_write(f"[worker_start] attempt={data.get('attempt')} backend={data.get('backend')} prompt={str(data.get('prompt',''))[:100]}\n")
            elif evt == "worker_done":
                worker_done_payload = data
                git_status = data.get("git_status", git_status)
                stderr_write(f"[worker_done] attempt={data.get('attempt')} exit_code={data.get('exit_code')} session_recreated={data.get('session_recreated')}\n")
                if data.get("diagnostics"):
                    stderr_write(f"[diagnostics] {json.dumps(data.get('diagnostics'), ensure_ascii=False)[:500]}\n")
            elif evt == "done":
                done_data = data
                run_id = data.get("run_id", run_id)
                git_status = data.get("git_status", git_status)
                stderr_write(f"[done] run_id={run_id} status={data.get('status')} git_status={json.dumps(git_status, ensure_ascii=False) if git_status else '{}'}\n")
                if data.get("session_title"):
                    stderr_write(f"[session_title] {data.get('session_title')}\n")
            elif evt == "error":
                error_message = data.get("message", "Unknown error")
                stderr_write(f"[error] {error_message}\n")
            elif evt == "cancelled":
                error_message = data.get("message", "Cancelled")
                stderr_write(f"[cancelled] {error_message}\n")

    # Fetch fresh session/run after stream
    session = store.get_session(session_id)
    run = store.get_run(run_id) if run_id else None
    # Fallback git_status from backend if not provided
    if git_status is None and session:
        try:
            git_status = backend.get_git_status(session.get("repo_path"))
        except Exception:
            git_status = None

    # Determine ok and error
    ok = True
    err_type = None
    err_msg = error_message
    if error_message:
        ok = False
        err_type = _classify_error_type(RuntimeError(error_message), error_message)
    elif done_data and done_data.get("status") not in (None, "completed"):
        # done status indicates failure
        status = done_data.get("status")
        if status in ("failed", "cancelled", "interrupted"):
            ok = False
            err_msg = f"Run status: {status}"
            err_type = status.capitalize()
    elif run and run.get("status") not in (None, "completed", "running"):
        status = run.get("status")
        if status in ("failed", "cancelled", "interrupted"):
            ok = False
            err_msg = run.get("error_message") or f"Run status: {status}"
            err_type = _classify_error_type(RuntimeError(err_msg), err_msg)

    # If still ok but no final response, treat as empty?
    # final_response_text may be empty string; that's not necessarily error for CLI contract
    return {
        "ok": ok,
        "response_text": final_response_text,
        "session": session,
        "run": run,
        "run_id": run_id,
        "git_status": git_status,
        "done_data": done_data,
        "error_message": err_msg,
        "error_type": err_type,
        "worker_done": worker_done_payload,
    }


def _create_new_session(project_id: int) -> Dict[str, Any]:
    """Create a new coding session for project_id using default backend."""
    from obsidian_ai_hub.web.services.projects import get_project_detail

    project = get_project_detail(project_id)
    if not project:
        raise FileNotFoundError(f"Project {project_id} not found")
    project_path = project.get("project_path")
    if not project_path:
        raise ValueError("プロジェクトに project_path が設定されていません")
    canonical_repo = backend.validate_git_repo(project_path)
    backend_name = str(config.CODING_DEFAULT_BACKEND).strip().lower()
    if backend_name not in ("codex", "opencode"):
        raise ValueError(
            f"Invalid CODING_DEFAULT_BACKEND '{config.CODING_DEFAULT_BACKEND}' (expected 'codex' or 'opencode')"
        )
    session = store.create_session(
        project_id=project_id,
        backend=backend_name,
        repo_path=canonical_repo,
        title=service.DEFAULT_CODING_SESSION_TITLE,
    )
    return session


def _get_resume_session(session_id: str) -> Dict[str, Any]:
    session = store.get_session(session_id)
    if not session:
        raise FileNotFoundError(f"Session '{session_id}' not found")
    # Optionally validate repo still valid; service will also validate but we give early error
    try:
        backend.validate_git_repo(session.get("repo_path"))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return session


def main_coding(
    project_id: Optional[int],
    resume_session: Optional[str],
    prompt: str,
    json_output: bool = False,
) -> None:
    """Entry point for --coding CLI.

    Handles session creation/resumption, turn execution, output separation,
    and execution_logger integration. Exits with appropriate code on failure.
    """
    import sys

    # Determine session
    session: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    # For execution_logger, we need a run_id for the CLI command itself
    cli_run_id = str(uuid.uuid4())
    from obsidian_ai_hub.utils import execution_logger

    token = execution_logger.current_run_id.set(cli_run_id)
    # Prepare cmd_args for logging (truncate prompt)
    cmd_args = {
        "project_id": project_id,
        "resume_session": resume_session,
        "json": json_output,
        "prompt": prompt[:2000] if prompt else "",
    }
    execution_logger.start_command_run(cli_run_id, "coding", cmd_args)

    try:
        # Session resolution with proper error handling
        try:
            if resume_session:
                session = _get_resume_session(resume_session)
                session_id = session["session_id"]
            else:
                assert project_id is not None
                session = _create_new_session(project_id)
                session_id = session["session_id"]
                if not json_output:
                    sys.stderr.write(f"[session] session_id={session_id} project_id={session.get('project_id')} title={session.get('title')} backend={session.get('backend')}\n")
                    sys.stderr.flush()
                else:
                    # In json mode, avoid duplicate stderr for session? Still minimal to stderr? Spec says json mode error details not duplicated to stderr, but session creation is success info. Keep stderr quiet in json mode for success path except fatal.
                    pass
        except FileNotFoundError as exc:
            msg = str(exc)
            err_type = _classify_error_type(exc, msg)
            if json_output:
                out = {
                    "ok": False,
                    "error": {"type": err_type, "message": msg},
                    "session": None,
                    "run": None,
                }
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                # Do not duplicate to stderr per spec
                execution_logger.fail_command_run(cli_run_id, exc)
                sys.exit(1)
            else:
                sys.stderr.write(f"Error: {msg}\n")
                sys.stderr.flush()
                execution_logger.fail_command_run(cli_run_id, exc)
                sys.exit(1)
        except ValueError as exc:
            msg = str(exc)
            err_type = _classify_error_type(exc, msg)
            # Distinguish git invalid vs project path missing -> still exit 1
            if json_output:
                out = {
                    "ok": False,
                    "error": {"type": err_type, "message": msg},
                    "session": None,
                    "run": None,
                }
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                execution_logger.fail_command_run(cli_run_id, exc)
                sys.exit(1)
            else:
                sys.stderr.write(f"Error: {msg}\n")
                sys.stderr.flush()
                execution_logger.fail_command_run(cli_run_id, exc)
                sys.exit(1)
        except Exception as exc:
            msg = str(exc)
            err_type = _classify_error_type(exc, msg)
            if json_output:
                out = {
                    "ok": False,
                    "error": {"type": err_type, "message": msg},
                    "session": None,
                    "run": None,
                }
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                execution_logger.fail_command_run(cli_run_id, exc)
                sys.exit(1)
            else:
                sys.stderr.write(f"Error: {msg}\n")
                sys.stderr.flush()
                execution_logger.fail_command_run(cli_run_id, exc)
                sys.exit(1)

        assert session_id is not None

        # Execute turn
        try:
            result = asyncio.run(_collect_coding_result(session_id, prompt, json_output))
        except Exception as exc:
            msg = str(exc)
            err_type = _classify_error_type(exc, msg)
            if json_output:
                out = {
                    "ok": False,
                    "error": {"type": err_type, "message": msg},
                    "session": {"id": session_id, "project_id": session.get("project_id"), "title": session.get("title")} if session else None,
                    "run": None,
                }
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                execution_logger.fail_command_run(cli_run_id, exc)
                sys.exit(1)
            else:
                sys.stderr.write(f"Error: {msg}\n")
                sys.stderr.flush()
                execution_logger.fail_command_run(cli_run_id, exc)
                sys.exit(1)

        # Handle result
        if json_output:
            # Build json output (single object)
            fresh_session = result.get("session") or session
            run = result.get("run")
            git_status = result.get("git_status")
            if result.get("ok"):
                # success json
                sess_obj = None
                if fresh_session:
                    sess_obj = {
                        "id": fresh_session.get("session_id"),
                        "project_id": fresh_session.get("project_id"),
                        "title": fresh_session.get("title"),
                    }
                run_obj = None
                if run:
                    run_obj = {
                        "id": run.get("run_id"),
                        "status": run.get("status"),
                        "git_status": git_status,
                    }
                elif result.get("run_id"):
                    run_obj = {
                        "id": result.get("run_id"),
                        "status": result.get("done_data", {}).get("status", "completed") if result.get("done_data") else "completed",
                        "git_status": git_status,
                    }
                out = {
                    "ok": True,
                    "response": result.get("response_text", ""),
                    "session": sess_obj,
                    "run": run_obj,
                }
                # Also include top-level git_status for convenience if not in run
                if git_status and (not run_obj or not run_obj.get("git_status")):
                    out["git_status"] = git_status
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                execution_logger.succeed_command_run(cli_run_id, out)
            else:
                # failure json, keep same session/run info if available
                fresh_session = result.get("session") or session
                run = result.get("run")
                sess_obj = None
                if fresh_session:
                    sess_obj = {
                        "id": fresh_session.get("session_id"),
                        "project_id": fresh_session.get("project_id"),
                        "title": fresh_session.get("title"),
                    }
                run_obj = None
                if run:
                    run_obj = {
                        "id": run.get("run_id"),
                        "status": run.get("status"),
                        "git_status": result.get("git_status"),
                    }
                elif result.get("run_id"):
                    run_obj = {
                        "id": result.get("run_id"),
                        "status": "failed",
                        "git_status": result.get("git_status"),
                    }
                out = {
                    "ok": False,
                    "error": {
                        "type": result.get("error_type") or "CodingError",
                        "message": result.get("error_message") or "Coding execution failed",
                    },
                    "session": sess_obj,
                    "run": run_obj,
                }
                if result.get("response_text"):
                    out["response"] = result.get("response_text")
                sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                # Do not duplicate to stderr per spec (json mode normal error details not duplicated)
                execution_logger.fail_command_run(cli_run_id, RuntimeError(result.get("error_message") or "Coding execution failed"))
                sys.exit(1)
        else:
            # Text mode
            if result.get("ok"):
                # stdout: final orchestrator response only
                resp = result.get("response_text", "")
                sys.stdout.write(resp)
                if resp and not resp.endswith("\n"):
                    sys.stdout.write("\n")
                sys.stdout.flush()
                # stderr already contains progress; also add final session/run summary
                fresh_session = result.get("session") or session
                run = result.get("run")
                git_status = result.get("git_status")
                if fresh_session:
                    sys.stderr.write(f"[session] id={fresh_session.get('session_id')} project_id={fresh_session.get('project_id')} title={fresh_session.get('title')}\n")
                if run:
                    sys.stderr.write(f"[run] id={run.get('run_id')} status={run.get('status')}\n")
                elif result.get("run_id"):
                    sys.stderr.write(f"[run] id={result.get('run_id')} status={result.get('done_data', {}).get('status','completed')}\n")
                if git_status:
                    sys.stderr.write(f"[git_status] {json.dumps(git_status, ensure_ascii=False)}\n")
                sys.stderr.flush()
                execution_logger.succeed_command_run(cli_run_id, {"session_id": session_id, "run_id": result.get("run_id"), "response": resp[:500]})
            else:
                # runtime failure: stderr already has error, also add structured error to stderr
                msg = result.get("error_message") or "Coding execution failed"
                err_type = result.get("error_type") or "CodingError"
                sys.stderr.write(f"[error] type={err_type} message={msg}\n")
                # Also ensure we have session/run info in stderr
                fresh_session = result.get("session") or session
                if fresh_session:
                    sys.stderr.write(f"[session] id={fresh_session.get('session_id')} project_id={fresh_session.get('project_id')} title={fresh_session.get('title')}\n")
                if result.get("git_status"):
                    sys.stderr.write(f"[git_status] {json.dumps(result.get('git_status'), ensure_ascii=False)}\n")
                sys.stderr.flush()
                # In text mode, do not output to stdout (keep contract) – leave stdout empty or maybe not?
                execution_logger.fail_command_run(cli_run_id, RuntimeError(msg))
                sys.exit(1)
    finally:
        execution_logger.current_run_id.reset(token)
