"""API routes for AI Agent management and conversation streaming."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.web.services import agents as agent_service

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_bearer_token)])


# --- Request Schemas ---


class CreateAgentRequest(BaseModel):
    name: str = Field(..., description="Agent display name")
    system_prompt: str = Field(..., description="System instructions for the agent")
    tool_ids: Optional[List[str]] = Field(
        default_factory=list, description="List of enabled tool IDs"
    )
    provider: Optional[str] = Field(
        default=None, description="LLM provider override"
    )
    model: Optional[str] = Field(default=None, description="LLM model override")


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = Field(default=None, description="Agent display name")
    system_prompt: Optional[str] = Field(
        default=None, description="System instructions"
    )
    tool_ids: Optional[List[str]] = Field(
        default=None, description="List of enabled tool IDs"
    )
    provider: Optional[str] = Field(default=None, description="LLM provider")
    model: Optional[str] = Field(default=None, description="LLM model")


class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(default=None, description="Session title")


class StreamMessageRequest(BaseModel):
    content: str = Field(..., description="User message text")


# --- Static Catalog Routes ---


@router.get("/agent-tools")
def list_agent_tools() -> Dict[str, Any]:
    tools = agent_service.list_agent_tools()
    return {"tools": tools}


# --- Agent CRUD Routes ---


@router.get("/agents")
def list_agents() -> Dict[str, Any]:
    agents = agent_service.list_agents()
    return {"agents": agents}


@router.post("/agents", status_code=status.HTTP_201_CREATED)
def create_agent(req: CreateAgentRequest) -> Dict[str, Any]:
    try:
        agent = agent_service.create_agent(
            name=req.name,
            system_prompt=req.system_prompt,
            tool_ids=req.tool_ids,
            provider=req.provider,
            model=req.model,
        )
        return {"agent": agent}
    except ValueError as e:
        msg = str(e)
        if "already exists" in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str) -> Dict[str, Any]:
    try:
        agent = agent_service.get_agent(agent_id)
        return {"agent": agent}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/agents/{agent_id}")
def update_agent(agent_id: str, req: UpdateAgentRequest) -> Dict[str, Any]:
    try:
        agent = agent_service.update_agent(
            agent_id=agent_id,
            name=req.name,
            system_prompt=req.system_prompt,
            tool_ids=req.tool_ids,
            provider=req.provider,
            model=req.model,
        )
        return {"agent": agent}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        msg = str(e)
        if "already exists" in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str) -> Dict[str, Any]:
    try:
        agent_service.delete_agent(agent_id)
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# --- Session Routes ---


@router.get("/agents/{agent_id}/sessions")
def list_sessions(agent_id: str) -> Dict[str, Any]:
    try:
        sessions = agent_service.list_sessions(agent_id)
        return {"sessions": sessions}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/agents/{agent_id}/sessions", status_code=status.HTTP_201_CREATED)
def create_session(agent_id: str, req: CreateSessionRequest) -> Dict[str, Any]:
    try:
        session = agent_service.create_session(agent_id, title=req.title)
        return {"session": session}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/agent-sessions/{session_id}")
def get_session_detail(session_id: str) -> Dict[str, Any]:
    try:
        detail = agent_service.get_session_detail(session_id)
        return detail
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/agent-sessions/{session_id}")
def delete_session(session_id: str) -> Dict[str, Any]:
    try:
        agent_service.delete_session(session_id)
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# --- Conversation SSE Streaming Route ---


@router.post("/agent-sessions/{session_id}/messages/stream")
async def stream_session_message(
    session_id: str, req: StreamMessageRequest
) -> StreamingResponse:
    content = req.content.strip() if req.content else ""
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content must not be empty.",
        )

    try:
        stream_gen = agent_service.stream_session_message(session_id, content)
        return StreamingResponse(stream_gen, media_type="text/event-stream")
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
