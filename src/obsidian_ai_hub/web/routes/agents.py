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


class StreamMessageRequest(BaseModel):
    content: str = Field(..., description="User message text")
    images: List[ImageAttachmentRequest] = Field(
        default_factory=list,
        description="Optional list of inline image attachments (base64 payloads).",
    )


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


# --- Conversation SSE Streaming Route ---


@router.post("/agent-sessions/{session_id}/messages/stream")
async def stream_session_message(
    session_id: str, req: StreamMessageRequest
) -> StreamingResponse:
    content = req.content.strip() if req.content else ""
    try:
        validated_images = _validate_images(req.images)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    # Empty user text is allowed only when at least one image attachment is
    # present — purely empty requests are still rejected.
    if not content and not validated_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message content must not be empty.",
        )

    try:
        stream_gen = agent_service.stream_session_message(
            session_id, content, images=validated_images or None
        )
        first_chunk = await stream_gen.__anext__()
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except StopAsyncIteration:
        async def empty_gen():
            return
            yield
        return StreamingResponse(empty_gen(), media_type="text/event-stream")

    async def full_gen():
        yield first_chunk
        async for chunk in stream_gen:
            yield chunk

    return StreamingResponse(full_gen(), media_type="text/event-stream")
