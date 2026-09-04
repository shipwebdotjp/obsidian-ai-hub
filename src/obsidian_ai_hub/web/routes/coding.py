"""FastAPI router for dedicated coding workspace."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from obsidian_ai_hub.agents import registry
from obsidian_ai_hub.coding import backend, service as coding_service, store as coding_store
from obsidian_ai_hub.web import service as web_service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

router = APIRouter(prefix="/coding", tags=["coding"])


class SessionCreateRequest(BaseModel):
    project_id: int
    backend: str = Field(description="'codex' or 'opencode'")
    title: Optional[str] = Field(default=None)
    tool_ids: Optional[List[str]] = Field(default=None, description="Optional custom tool IDs for session")


class UpdateToolsRequest(BaseModel):
    tool_ids: List[str] = Field(description="List of tool IDs to enable")


class UpdateSessionToolsRequest(BaseModel):
    tool_ids: Optional[List[str]] = Field(default=None, description="List of tool IDs, or None to reset to user default")


class MessageStreamRequest(BaseModel):
    content: str


@router.get("/defaults")
def get_coding_defaults(_=Depends(require_bearer_token)):
    """Get global user default tool settings and available tools for coding workspace."""
    default_ids = coding_store.get_user_default_tool_ids()
    available_tools = registry.list_available_tools()
    return {
        "default_tool_ids": default_ids,
        "available_tools": available_tools,
    }


@router.put("/defaults")
def update_coding_defaults(body: UpdateToolsRequest, _=Depends(require_bearer_token)):
    """Update global user default tool settings for coding workspace."""
    updated_ids = coding_store.update_user_default_tool_ids(body.tool_ids)
    available_tools = registry.list_available_tools()
    return {
        "default_tool_ids": updated_ids,
        "available_tools": available_tools,
    }


@router.get("/config")
def get_coding_config(_=Depends(require_bearer_token)):
    """Get coding workspace config (default backend)."""
    from obsidian_ai_hub.utils.config import CODING_DEFAULT_BACKEND

    backend = str(CODING_DEFAULT_BACKEND).strip().lower() if isinstance(CODING_DEFAULT_BACKEND, str) else "opencode"
    if backend not in ("codex", "opencode"):
        backend = "opencode"
    return {"default_backend": backend}


@router.get("/tools")
def list_available_coding_tools(_=Depends(require_bearer_token)):
    """List all available tools in registry."""
    return {"tools": registry.list_available_tools()}


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

    # Validate backend
    b_name = body.backend.lower().strip()
    if b_name not in ("codex", "opencode"):
        raise HTTPException(
            status_code=400,
            detail="バックエンドは 'codex' または 'opencode' を指定してください",
        )

    clean_title = (body.title or "").strip()
    session_title = clean_title if clean_title else "新しいコーディングセッション"

    try:
        session = coding_store.create_session(
            project_id=body.project_id,
            backend=b_name,
            repo_path=canonical_repo,
            title=session_title,
            tool_ids=body.tool_ids,
        )
        return session
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    session = coding_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    messages = coding_store.list_messages(session_id)
    active_run = coding_store.get_active_run_for_session(session_id)
    latest_run = coding_store.get_latest_run_for_session(session_id)
    effective_tool_ids = coding_store.get_effective_session_tool_ids(session_id)
    has_custom = session.get("tool_ids_json") is not None
    available_tools = registry.list_available_tools()
    orchestrator_tool_calls = coding_store.list_orchestrator_tool_calls_for_session(session_id)

    return {
        "session": session,
        "effective_tool_ids": effective_tool_ids,
        "has_custom_tools": has_custom,
        "available_tools": available_tools,
        "messages": messages,
        "active_run": active_run,
        "latest_run": latest_run,
        "orchestrator_tool_calls": orchestrator_tool_calls,
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, _=Depends(require_bearer_token)):
    """Delete a coding session."""
    deleted = coding_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    return {"status": "deleted", "session_id": session_id}


@router.post("/sessions/{session_id}/messages/stream")
async def stream_message(
    session_id: str,
    body: MessageStreamRequest,
    _=Depends(require_bearer_token),
):
    """Send user message and stream orchestrator / worker responses via SSE."""
    session = coding_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    if not body.content.strip():
        raise HTTPException(status_code=400, detail="メッセージ本文が空です")

    # Check if a run is already active
    active_run = coding_store.get_active_run_for_session(session_id)
    if active_run:
        raise HTTPException(
            status_code=409,
            detail="このセッションでは既に別の実行が進行中です",
        )

    return StreamingResponse(
        coding_service.run_coding_turn_stream(session_id, body.content),
        media_type="text/event-stream",
    )


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, _=Depends(require_bearer_token)):
    """Cancel an active run."""
    run = coding_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="実行が見つかりません")

    if run["status"] != "running":
        return {"status": "not_running", "run_id": run_id, "current_status": run["status"]}

    cancelled = coding_service.cancel_active_run(run_id)
    return {"status": "cancel_signalled" if cancelled else "not_found", "run_id": run_id}
