"""FastAPI router for dedicated coding workspace."""

import asyncio
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from typing import Literal
from pydantic import BaseModel, Field

from obsidian_ai_hub.coding import (
    backend,
    service as coding_service,
    store as coding_store,
)
from obsidian_ai_hub.utils.config import (
    CODING_OPENCODE_MODEL,
    get_available_coding_models,
    resolve_coding_model,
)
from obsidian_ai_hub.web import service as web_service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

router = APIRouter(prefix="/coding", tags=["coding"])


class SessionCreateRequest(BaseModel):
    project_id: int
    backend: str = Field(description="'opencode' (fixed; the workspace is OpenCode-only)")
    title: Optional[str] = Field(default=None)
    opencode_model: Optional[str] = Field(
        default=None,
        description="OpenCode model; must be in coding.acp.opencode_models",
    )
    tool_ids: Optional[List[str]] = Field(
        default=None, description="Optional custom tool IDs for session"
    )
    transport: Optional[str] = Field(
        default="acp", description="'acp' (fixed; Direct CLI is retired)"
    )


class UpdateToolsRequest(BaseModel):
    tool_ids: List[str] = Field(description="List of tool IDs to enable")


class UpdateSessionToolsRequest(BaseModel):
    tool_ids: Optional[List[str]] = Field(
        default=None, description="List of tool IDs, or None to reset to user default"
    )


class UpdateSessionTitleRequest(BaseModel):
    title: str = Field(description="New session title")


class SlashInvocationModel(BaseModel):
    kind: Literal["skill"]
    name: str


class StartCodingRunRequest(BaseModel):
    content: str
    slash_invocation: Optional[SlashInvocationModel] = None


@router.get("/defaults")
def get_coding_defaults(_=Depends(require_bearer_token)):
    """Get global user default tool settings and available tools for coding workspace."""
    default_ids = coding_store.get_user_default_tool_ids()
    available_tools = coding_store.list_available_coding_tools()
    return {
        "default_tool_ids": default_ids,
        "available_tools": available_tools,
    }


@router.put("/defaults")
def update_coding_defaults(body: UpdateToolsRequest, _=Depends(require_bearer_token)):
    """Update global user default tool settings for coding workspace."""
    updated_ids = coding_store.update_user_default_tool_ids(body.tool_ids)
    available_tools = coding_store.list_available_coding_tools()
    return {
        "default_tool_ids": updated_ids,
        "available_tools": available_tools,
    }


class UpdateSessionModelRequest(BaseModel):
    opencode_model: str = Field(description="New OpenCode model (allowlisted only)")


@router.get("/config")
def get_coding_config(_=Depends(require_bearer_token)):
    """Get coding workspace config (default backend, OpenCode model)."""
    return {
        "default_backend": "opencode",
        "opencode_model": CODING_OPENCODE_MODEL,
        "available_models": get_available_coding_models(),
    }


@router.get("/tools")
def list_available_coding_tools(_=Depends(require_bearer_token)):
    """List all tools available to the coding workspace."""
    return {"tools": coding_store.list_available_coding_tools()}


@router.get("/git-status")
def get_git_status(repo_path: str, _=Depends(require_bearer_token)):
    """Get git status information for a repository path."""
    try:
        canonical_repo = backend.validate_git_repo(repo_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return backend.get_git_status(canonical_repo)


@router.get("/projects")
def list_coding_projects(_=Depends(require_bearer_token)):
    """List projects with git repository validation status for coding workspace."""
    all_projects = web_service.list_projects()
    result = []
    for proj in all_projects:
        project_path = proj.get("project_path")
        is_valid = False
        repo_path = None
        error_msg = None

        if project_path:
            try:
                repo_path = backend.validate_git_repo(project_path)
                is_valid = True
            except ValueError as exc:
                error_msg = str(exc)
        else:
            error_msg = "プロジェクトの project_path が設定されていません"

        result.append(
            {
                "project": proj,
                "is_valid_git_repo": is_valid,
                "repo_path": repo_path,
                "error_message": error_msg,
            }
        )
    return result


@router.get("/sessions")
def list_sessions(project_id: int, _=Depends(require_bearer_token)):
    """List sessions for a specific project."""
    return coding_store.list_sessions_by_project(project_id)


@router.post("/sessions")
def create_session(
    body: SessionCreateRequest,
    _=Depends(require_bearer_token),
):
    """Create a coding session for a project with selected backend."""
    # Retrieve project
    project = web_service.get_project_detail(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="プロジェクトが見つかりません")

    project_path = project.get("project_path")
    if not project_path:
        raise HTTPException(
            status_code=400,
            detail="プロジェクトに project_path が設定されていません",
        )

    try:
        canonical_repo = backend.validate_git_repo(project_path)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"無効なGitリポジトリパスです: {str(exc)}",
        )

    # Validate backend (OpenCode-only; Codex is retired)
    b_name = body.backend.lower().strip()
    if b_name != "opencode":
        raise HTTPException(
            status_code=400,
            detail="バックエンドは 'opencode' を指定してください",
        )

    clean_title = (body.title or "").strip()
    session_title = clean_title if clean_title else "新しいコーディングセッション"

    clean_transport = (body.transport or "acp").lower().strip()
    if clean_transport != "acp":
        raise HTTPException(
            status_code=400,
            detail="トランスポートは 'acp' を指定してください（直接CLIは廃止されました）",
        )

    if body.opencode_model not in (None, ""):
        try:
            resolve_coding_model(body.opencode_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    try:
        session = coding_store.create_session(
            project_id=body.project_id,
            backend=b_name,
            repo_path=canonical_repo,
            title=session_title,
            tool_ids=body.tool_ids,
            transport=clean_transport,
            opencode_model=body.opencode_model,
        )
        return session
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/sessions/{session_id}")
def update_session_title(
    session_id: str,
    body: UpdateSessionTitleRequest,
    _=Depends(require_bearer_token),
):
    """Update a coding session title."""
    session = coding_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    try:
        coding_store.update_session_title(session_id, body.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="セッションが見つかりません"
        ) from exc
    return get_session_detail(session_id)


@router.put("/sessions/{session_id}/model")
def update_session_model(
    session_id: str,
    body: UpdateSessionModelRequest,
    _=Depends(require_bearer_token),
):
    """Change the session's OpenCode model (allowlisted only; active runs keep their frozen model)."""
    session = coding_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    try:
        coding_store.update_session_model(session_id, body.opencode_model)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return get_session_detail(session_id)


@router.put("/sessions/{session_id}/tools")
def update_session_tools(
    session_id: str,
    body: UpdateSessionToolsRequest,
    _=Depends(require_bearer_token),
):
    """Update custom tool settings for a coding session, or reset to defaults if tool_ids is None."""
    session = coding_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    coding_store.update_session_tool_ids(session_id, body.tool_ids)
    return get_session_detail(session_id)


@router.get("/sessions/{session_id}")
def get_session_detail(session_id: str, _=Depends(require_bearer_token)):
    """Get session details along with effective tool settings, message history, tool calls, and active/latest run state."""
    from obsidian_ai_hub.agents.ask_user import extract_session_ask_user_history

    session = coding_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    messages = coding_store.list_messages(session_id)
    active_run = coding_store.get_active_run_for_session(session_id)
    latest_run = coding_store.get_latest_run_for_session(session_id)
    runs = coding_store.list_runs_for_session(session_id)
    effective_tool_ids = coding_store.get_effective_session_tool_ids(session_id)
    has_custom = session.get("tool_ids_json") is not None
    available_tools = coding_store.list_available_coding_tools()
    orchestrator_tool_calls = coding_store.list_orchestrator_tool_calls_for_session(
        session_id
    )
    ask_user_answer_history = extract_session_ask_user_history(runs)

    return {
        "session": session,
        "effective_model": coding_store.get_effective_session_model(session),
        "available_models": get_available_coding_models(),
        "effective_tool_ids": effective_tool_ids,
        "has_custom_tools": has_custom,
        "available_tools": available_tools,
        "messages": messages,
        "runs": runs,
        "active_run": active_run,
        "latest_run": latest_run,
        "orchestrator_tool_calls": orchestrator_tool_calls,
        "ask_user_answer_history": ask_user_answer_history,
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, _=Depends(require_bearer_token)):
    """Delete a coding session."""
    try:
        deleted = coding_store.delete_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    return {"status": "deleted", "session_id": session_id}


@router.get("/sessions/{session_id}/slash-candidates")
def get_slash_candidates(session_id: str, _=Depends(require_bearer_token)):
    """Get slash invocation candidates for a coding session."""
    session = coding_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    effective_tools = coding_store.get_effective_session_tool_ids(session_id)
    has_skills = "skills" in effective_tools

    candidates: list[dict[str, Any]] = []
    if has_skills:
        try:
            from obsidian_ai_hub.agents.skills import discover_skills

            index = discover_skills()
            for skill in index.list_skills():
                candidates.append(
                    {
                        "kind": "skill",
                        "name": skill.name,
                        "description": skill.description,
                    }
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to discover skills for slash candidates: %s", exc)

    return {
        "candidates": candidates,
        "has_skills_tool": has_skills,
    }


@router.post("/sessions/{session_id}/runs", status_code=202)
def start_coding_run(
    session_id: str,
    body: StartCodingRunRequest,
    _=Depends(require_bearer_token),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Queue a coding run and return 202 with the run (reconnectable SSE)."""
    from obsidian_ai_hub.runs.instance import get_instance_id

    session = coding_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    if not (body.content or "").strip():
        raise HTTPException(status_code=400, detail="メッセージ本文が空です")

    slash_dict = body.slash_invocation.model_dump() if body.slash_invocation else None
    if slash_dict and slash_dict.get("kind") == "skill":
        effective_tools = coding_store.get_effective_session_tool_ids(session_id)
        if "skills" not in effective_tools:
            raise HTTPException(
                status_code=400,
                detail="skills ツールが無効なセッションではスキルを呼び出せません",
            )
        from obsidian_ai_hub.agents.skills import discover_skills

        index = discover_skills()
        skill_name = slash_dict["name"]
        if not index.get_skill(skill_name):
            raise HTTPException(
                status_code=400,
                detail=f"指定されたスキル '{skill_name}' は存在しません",
            )

    try:
        _, run = coding_store.start_queued_run(
            session_id=session_id,
            content=body.content,
            idempotency_key=idempotency_key,
            created_instance_id=get_instance_id(),
            slash_invocation=slash_dict,
        )
        return {"run": run}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        msg = str(exc)
        if "conflict" in msg.lower() or "active" in msg.lower() or "進行中" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=400, detail=msg)


@router.get("/runs/{run_id}/events")
async def subscribe_coding_run_events(
    run_id: str,
    request: Request,
    _=Depends(require_bearer_token),
    last_event_id: Optional[str] = Query(default=None, alias="last_event_id"),
    last_event_id_header: Optional[str] = Header(default=None, alias="Last-Event-ID"),
):
    """Replay coding event log (event_id > cursor) then follow until terminal."""
    from obsidian_ai_hub.runs.events import (
        format_sse,
        heartbeat_sse,
        is_terminal_event,
        parse_last_event_id,
    )

    run = coding_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="実行が見つかりません")
    raw_cursor = (
        last_event_id_header if last_event_id_header is not None else last_event_id
    )
    cursor = parse_last_event_id(raw_cursor)

    async def event_gen():
        nonlocal cursor
        idle_cycles = 0
        terminal_empty_polls = 0
        try:
            while True:
                if await request.is_disconnected():
                    break
                events = await asyncio.to_thread(
                    coding_store.list_run_events, run_id, cursor, 200
                )
                if events:
                    idle_cycles = 0
                    terminal_empty_polls = 0
                    for ev in events:
                        eid = int(ev["event_id"])
                        payload = dict(ev.get("payload") or {})
                        payload.setdefault("event", ev.get("event_type"))
                        yield format_sse(eid, payload)
                        cursor = eid
                        if is_terminal_event(str(ev.get("event_type") or ""), payload):
                            return
                    current = await asyncio.to_thread(coding_store.get_run, run_id)
                    if current is not None and str(current.get("status")) in (
                        "completed",
                        "failed",
                        "cancelled",
                        "interrupted",
                    ):
                        last_type = str(events[-1].get("event_type") or "")
                        last_payload = dict(events[-1].get("payload") or {})
                        if is_terminal_event(last_type, last_payload):
                            return
                else:
                    current = await asyncio.to_thread(coding_store.get_run, run_id)
                    if current is not None and str(current.get("status")) in (
                        "completed",
                        "failed",
                        "cancelled",
                        "interrupted",
                    ):
                        terminal_empty_polls += 1
                        if terminal_empty_polls >= 10:
                            return
                    else:
                        terminal_empty_polls = 0
                    if (
                        current is not None
                        and str(current.get("status")) == "waiting_user"
                    ):
                        return
                    idle_cycles += 1
                    if idle_cycles >= 30:
                        idle_cycles = 0
                        yield heartbeat_sse()
                try:
                    await asyncio.sleep(0.5)
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, _=Depends(require_bearer_token)):
    """Request cancellation for a queued/running/waiting run (same state contract)."""
    run = coding_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="実行が見つかりません")

    status = str(run.get("status") or "")
    if status in ("completed", "failed", "cancelled", "interrupted"):
        return {
            "run": run,
            "status": "not_running",
            "run_id": run_id,
            "current_status": status,
        }

    try:
        updated = coding_store.request_cancel_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Notify the owning worker (CLI process group stop); the worker holds the
    # repo lock and cancel registration until CLI completes.
    coding_service.cancel_active_run(run_id)
    return {"run": updated, "status": "cancel_signalled", "run_id": run_id}
