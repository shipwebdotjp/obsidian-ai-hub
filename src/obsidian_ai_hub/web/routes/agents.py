"""API routes for AI Agent management and conversation streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from obsidian_ai_hub.web.routes.deps import require_bearer_token
from obsidian_ai_hub.web.services import agents as agent_service

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_bearer_token)])


# --- Request Schemas ---


class ReasoningParamsRequest(BaseModel):
    effort: Optional[str] = Field(default=None, description="reasoning.effort (e.g. low/medium/high)")

    model_config = {"extra": "forbid"}


class AdvancedParamsRequest(BaseModel):
    max_tokens: Optional[int] = Field(
        default=None, ge=1, description="max_tokens (mapped to max_output_tokens/max_completion_tokens/num_predict by provider)"
    )
    reasoning: Optional[ReasoningParamsRequest] = Field(
        default=None, description="Reasoning config"
    )

    model_config = {"extra": "forbid"}


class CreateAgentRequest(BaseModel):
    name: str = Field(..., description="Agent display name")
    system_prompt: str = Field(..., description="System instructions for the agent")
    tool_ids: Optional[List[str]] = Field(
        default_factory=list, description="List of enabled tool IDs"
    )
    delegate_agent_ids: Optional[List[str]] = Field(
        default_factory=list, description="List of allowed delegate target agent IDs"
    )
    provider: Optional[str] = Field(
        default=None, description="LLM provider override"
    )
    model: Optional[str] = Field(default=None, description="LLM model override")
    advanced_params: Optional[AdvancedParamsRequest] = Field(
        default=None, description="Advanced LLM params (max_tokens, reasoning.effort)"
    )


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = Field(default=None, description="Agent display name")
    system_prompt: Optional[str] = Field(
        default=None, description="System instructions"
    )
    tool_ids: Optional[List[str]] = Field(
        default=None, description="List of enabled tool IDs"
    )
    delegate_agent_ids: Optional[List[str]] = Field(
        default=None, description="List of allowed delegate target agent IDs"
    )
    provider: Optional[str] = Field(default=None, description="LLM provider")
    model: Optional[str] = Field(default=None, description="LLM model")
    advanced_params: Optional[AdvancedParamsRequest] = Field(
        default=None, description="Advanced LLM params (max_tokens, reasoning.effort)"
    )
    pinned: Optional[bool] = Field(default=None, description="Pin state for the agent")


class CreatePromptTemplateRequest(BaseModel):
    name: str = Field(..., description="Template name")
    content: str = Field(..., description="Template content (plain text)")


class UpdatePromptTemplateRequest(BaseModel):
    name: Optional[str] = Field(default=None, description="Template name")
    content: Optional[str] = Field(default=None, description="Template content")
    display_order: Optional[int] = Field(default=None, description="Display order")


class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(default=None, description="Session title")


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = Field(default=None, description="Session title")
    pinned: Optional[bool] = Field(default=None, description="Pin state for the session")


# Limits for inline image attachments to keep requests bounded and avoid
# surprising provider payloads. ``data`` is the base64 payload body WITHOUT
# the ``data:<mime>;base64,`` prefix; the route restores the data URL when
# passing the attachment to the runtime, which then embeds it as a multimodal
# LangChain HumanMessage block.
MAX_AGENT_IMAGE_COUNT = 5
MAX_AGENT_IMAGE_BYTES = 8 * 1024 * 1024  # raw bytes per image (~10.6MB encoded)


class ImageAttachmentRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Original file name")
    mime_type: str = Field(..., description="MIME type (must start with 'image/')")
    data: str = Field(..., description="Base64-encoded image bytes (no prefix)")

    model_config = {"extra": "forbid"}


class SlashInvocationRequest(BaseModel):
    kind: str = Field(..., description="Invocation kind ('skill')")
    name: str = Field(..., min_length=1, description="Target name (e.g. skill name)")

    model_config = {"extra": "forbid"}


def _decode_base64_payload(data: str) -> bytes:
    import base64

    try:
        return base64.b64decode(data, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Attachment data is not valid base64.") from exc


def _validate_images(images: List[ImageAttachmentRequest]) -> List[Dict[str, Any]]:
    if len(images) > MAX_AGENT_IMAGE_COUNT:
        raise ValueError(
            f"At most {MAX_AGENT_IMAGE_COUNT} images can be attached to one message."
        )
    validated: List[Dict[str, Any]] = []
    for idx, image in enumerate(images):
        if not image.mime_type.lower().startswith("image/"):
            raise ValueError(
                f"Attachment #{idx + 1} ({image.name}) must have an 'image/*' MIME type."
            )
        raw = _decode_base64_payload(image.data)
        if len(raw) > MAX_AGENT_IMAGE_BYTES:
            raise ValueError(
                f"Attachment #{idx + 1} ({image.name}) exceeds the {MAX_AGENT_IMAGE_BYTES // (1024 * 1024)}MB limit."
            )
        validated.append(
            {
                "name": image.name,
                "mime_type": image.mime_type,
                "data": image.data,
            }
        )
    return validated


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
        adv = req.advanced_params.model_dump(exclude_none=True) if req.advanced_params else None
        agent = agent_service.create_agent(
            name=req.name,
            system_prompt=req.system_prompt,
            tool_ids=req.tool_ids,
            delegate_agent_ids=req.delegate_agent_ids,
            provider=req.provider,
            model=req.model,
            advanced_params=adv,
        )
        return {"agent": agent}
    except ValueError as e:
        msg = str(e)
        if "already exists" in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from e


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str) -> Dict[str, Any]:
    try:
        agent = agent_service.get_agent(agent_id)
        return {"agent": agent}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.patch("/agents/{agent_id}")
def update_agent(agent_id: str, req: UpdateAgentRequest) -> Dict[str, Any]:
    try:
        # Use model_fields_set to detect explicit null vs absent for advanced_params
        adv = None
        if "advanced_params" in req.model_fields_set:
            adv = req.advanced_params.model_dump(exclude_none=True) if req.advanced_params else {}
        pinned = req.pinned if "pinned" in req.model_fields_set else None
        agent = agent_service.update_agent(
            agent_id=agent_id,
            name=req.name,
            system_prompt=req.system_prompt,
            tool_ids=req.tool_ids,
            delegate_agent_ids=req.delegate_agent_ids,
            provider=req.provider,
            model=req.model,
            advanced_params=adv,
            pinned=pinned,
        )
        return {"agent": agent}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        msg = str(e)
        if "already exists" in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from e


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str) -> Dict[str, Any]:
    try:
        agent_service.delete_agent(agent_id)
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


# --- Session Routes ---


@router.get("/agents/{agent_id}/sessions")
def list_sessions(agent_id: str) -> Dict[str, Any]:
    try:
        sessions = agent_service.list_sessions(agent_id)
        return {"sessions": sessions}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/agents/{agent_id}/sessions", status_code=status.HTTP_201_CREATED)
def create_session(agent_id: str, req: CreateSessionRequest) -> Dict[str, Any]:
    try:
        session = agent_service.create_session(agent_id, title=req.title)
        return {"session": session}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/agent-sessions/search")
def search_session_messages(q: str) -> Dict[str, Any]:
    try:
        return {"results": agent_service.search_messages(q)}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/agent-sessions/{session_id}")
def get_session_detail(session_id: str) -> Dict[str, Any]:
    try:
        detail = agent_service.get_session_detail(session_id)
        return detail
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/agent-sessions/{session_id}/slash-candidates")
def get_slash_candidates(session_id: str) -> Dict[str, Any]:
    try:
        return agent_service.get_slash_candidates(session_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.patch("/agent-sessions/{session_id}")
def update_session(session_id: str, req: UpdateSessionRequest) -> Dict[str, Any]:
    try:
        pinned = req.pinned if "pinned" in req.model_fields_set else None
        session = agent_service.update_session(
            session_id=session_id,
            title=req.title,
            pinned=pinned,
        )
        return {"session": session}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/agent-sessions/{session_id}")
def delete_session(session_id: str) -> Dict[str, Any]:
    try:
        agent_service.delete_session(session_id)
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        # Active run guard: require explicit cancel first.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e


# --- Prompt Template Routes ---


@router.get("/agents/{agent_id}/prompt-templates")
def list_prompt_templates(agent_id: str) -> Dict[str, Any]:
    try:
        templates = agent_service.list_prompt_templates(agent_id)
        return {"templates": templates}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post(
    "/agents/{agent_id}/prompt-templates", status_code=status.HTTP_201_CREATED
)
def create_prompt_template(
    agent_id: str, req: CreatePromptTemplateRequest
) -> Dict[str, Any]:
    try:
        tmpl = agent_service.create_prompt_template(agent_id, req.name, req.content)
        return {"template": tmpl}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/agent-prompt-templates/{template_id}")
def get_prompt_template(template_id: str) -> Dict[str, Any]:
    try:
        tmpl = agent_service.get_prompt_template(template_id)
        return {"template": tmpl}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.patch("/agent-prompt-templates/{template_id}")
def update_prompt_template(
    template_id: str, req: UpdatePromptTemplateRequest
) -> Dict[str, Any]:
    try:
        tmpl = agent_service.update_prompt_template(
            template_id,
            name=req.name,
            content=req.content,
            display_order=req.display_order,
        )
        return {"template": tmpl}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/agent-prompt-templates/{template_id}")
def delete_prompt_template(template_id: str) -> Dict[str, Any]:
    try:
        agent_service.delete_prompt_template(template_id)
        return {"success": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


# --- Reconnectable Run Routes (docs/run-sse) ---


class StartAgentRunRequest(BaseModel):
    content: str = Field(..., description="User message text")
    images: List[ImageAttachmentRequest] = Field(
        default_factory=list,
        description="Optional list of inline image attachments (base64 payloads).",
    )
    slash_invocation: Optional[SlashInvocationRequest] = Field(
        default=None, description="Optional slash invocation"
    )


@router.post("/agent-sessions/{session_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def start_agent_run(
    session_id: str,
    req: StartAgentRunRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> Dict[str, Any]:
    content = req.content.strip() if req.content else ""
    try:
        validated_images = _validate_images(req.images)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    if not content and not validated_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content must not be empty.",
        )

    slash_inv = req.slash_invocation.model_dump() if req.slash_invocation else None
    if slash_inv:
        if slash_inv.get("kind") != "skill":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Kind must be 'skill'.",
            )
        try:
            session = agent_service.get_session_detail(session_id)["session"]
            agent = agent_service.get_agent(session["agent_id"])
            if "skills" not in agent.get("tool_ids", []):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="skills ツールが無効なエージェントです。",
                )
            from obsidian_ai_hub.agents.skills import discover_skills
            skill_index = discover_skills()
            if not skill_index.get_skill(slash_inv["name"]):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Skill '{slash_inv['name']}' は存在しません。",
                )
        except FileNotFoundError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    try:
        run = agent_service.start_run(
            session_id,
            content,
            images=validated_images or None,
            idempotency_key=idempotency_key,
            slash_invocation=slash_inv,
        )
        return {"run": run}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        msg = str(e)
        if "conflict" in msg.lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from e
        if "active" in msg.lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg) from e


@router.get("/agent-runs/{run_id}/events")
async def subscribe_agent_run_events(
    run_id: str,
    request: Request,
    last_event_id: Optional[str] = Query(default=None, alias="last_event_id"),
    last_event_id_header: Optional[str] = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    from obsidian_ai_hub.agents import store as agent_store
    from obsidian_ai_hub.runs.events import (
        format_sse,
        heartbeat_sse,
        is_terminal_event,
        parse_last_event_id,
    )

    try:
        run = agent_service.get_run(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    raw_cursor = last_event_id_header if last_event_id_header is not None else last_event_id
    cursor = parse_last_event_id(raw_cursor)

    async def event_gen():
        nonlocal cursor
        # Client sends last *applied* ID; server replays event_id > cursor.
        # Worker writes terminal status before the terminal event, so a poll
        # in that window must not close before the event lands (grace polls).
        idle_cycles = 0
        terminal_empty_polls = 0
        try:
            while True:
                if await request.is_disconnected():
                    break
                events = await asyncio.to_thread(
                    agent_store.list_run_events, run_id, cursor, 200
                )
                if events:
                    idle_cycles = 0
                    terminal_empty_polls = 0
                    for ev in events:
                        eid = int(ev["event_id"])
                        payload = dict(ev.get("payload") or {})
                        # Ensure type field present for frontend folding.
                        payload.setdefault("type", ev.get("event_type"))
                        yield format_sse(eid, payload)
                        cursor = eid
                        if is_terminal_event(str(ev.get("event_type") or ""), payload):
                            return
                    # After replay, check terminal run with terminal event.
                    current = await asyncio.to_thread(agent_store.get_run, run_id)
                    if current is not None and str(current.get("status")) in (
                        "succeeded",
                        "failed",
                        "cancelled",
                        "interrupted",
                    ):
                        last_type = str(events[-1].get("event_type") or "")
                        last_payload = dict(events[-1].get("payload") or {})
                        if is_terminal_event(last_type, last_payload):
                            return
                else:
                    current = await asyncio.to_thread(agent_store.get_run, run_id)
                    if current is not None and str(current.get("status")) in (
                        "succeeded",
                        "failed",
                        "cancelled",
                        "interrupted",
                    ):
                        # Grace period for the terminal event (status lands
                        # first). History remains via detail API after expiry.
                        terminal_empty_polls += 1
                        if terminal_empty_polls >= 10:
                            return
                    else:
                        terminal_empty_polls = 0
                    # waiting_user pauses with user_question as last event;
                    # keep the stream open briefly then close so the client
                    # does not poll forever (it will resubscribe on demand).
                    if current is not None and str(current.get("status")) == "waiting_user":
                        return
                    idle_cycles += 1
                    # ~15s heartbeat (0.5s * 30).
                    if idle_cycles >= 30:
                        idle_cycles = 0
                        yield heartbeat_sse()
                try:
                    await asyncio.sleep(0.5)
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            # Subscriber disconnect must not mutate the run.
            return

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/agent-runs/{run_id}/cancel")
def cancel_agent_run(run_id: str) -> Dict[str, Any]:
    try:
        run = agent_service.cancel_run(run_id)
        return {"run": run}
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
