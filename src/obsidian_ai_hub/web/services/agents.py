"""Service layer for AI agent endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from obsidian_ai_hub.agents import registry, runtime, store


def _pinned_at_value(pinned: Optional[bool]) -> Optional[str]:
    if pinned is None:
        return None
    return datetime.now(timezone.utc).isoformat() if pinned else None


def list_agents() -> List[Dict[str, Any]]:
    return store.list_agents()


def create_agent(
    name: str,
    system_prompt: str,
    tool_ids: Optional[List[str]] = None,
    delegate_agent_ids: Optional[List[str]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    advanced_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return store.create_agent(
        name=name,
        system_prompt=system_prompt,
        tool_ids=tool_ids or [],
        delegate_agent_ids=delegate_agent_ids or [],
        provider=provider,
        model=model,
        advanced_params=advanced_params or {},
    )


def get_agent(agent_id: str) -> Dict[str, Any]:
    agent = store.get_agent(agent_id)
    if not agent:
        raise FileNotFoundError(f"Agent '{agent_id}' not found.")
    return agent


def update_agent(
    agent_id: str,
    name: Optional[str] = None,
    system_prompt: Optional[str] = None,
    tool_ids: Optional[List[str]] = None,
    delegate_agent_ids: Optional[List[str]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    advanced_params: Optional[Dict[str, Any]] = None,
    pinned: Optional[bool] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = dict(
        agent_id=agent_id,
        name=name,
        system_prompt=system_prompt,
        tool_ids=tool_ids,
        delegate_agent_ids=delegate_agent_ids,
        provider=provider,
        model=model,
        advanced_params=advanced_params,
    )
    if pinned is not None:
        kwargs["pinned_at"] = _pinned_at_value(pinned)
    return store.update_agent(**kwargs)


def delete_agent(agent_id: str) -> bool:
    deleted = store.delete_agent(agent_id)
    if not deleted:
        raise FileNotFoundError(f"Agent '{agent_id}' not found.")
    return True


def list_agent_tools() -> List[Dict[str, Any]]:
    return registry.list_available_tools()


def list_sessions(agent_id: str) -> List[Dict[str, Any]]:
    get_agent(agent_id)  # raises FileNotFoundError if agent missing
    return store.list_sessions(agent_id)


def search_messages(query: str) -> List[Dict[str, Any]]:
    return store.search_messages(query)


def create_session(agent_id: str, title: Optional[str] = None) -> Dict[str, Any]:
    return store.create_session(agent_id, title=title)


def get_session_detail(session_id: str) -> Dict[str, Any]:
    session = store.get_session(session_id)
    if not session:
        raise FileNotFoundError(f"Session '{session_id}' not found.")
    agent = get_agent(session["agent_id"])
    messages = store.list_messages(session_id)
    runs = store.list_runs(session_id)
    return {
        "session": session,
        "agent": agent,
        "messages": messages,
        "runs": runs,
    }


def update_session(
    session_id: str,
    title: Optional[str] = None,
    pinned: Optional[bool] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = dict(session_id=session_id)
    if title is not None:
        kwargs["title"] = title
    if pinned is not None:
        kwargs["pinned_at"] = _pinned_at_value(pinned)
    # Detect if no update field was supplied
    if "title" not in kwargs and "pinned_at" not in kwargs:
        session = store.get_session(session_id)
        if not session:
            raise FileNotFoundError(f"Session '{session_id}' not found.")
        return session
    return store.update_session(**kwargs)


def delete_session(session_id: str) -> bool:
    deleted = store.delete_session(session_id)
    if not deleted:
        raise FileNotFoundError(f"Session '{session_id}' not found.")
    return True


async def stream_session_message(
    session_id: str,
    content: str,
    images: Optional[List[Dict[str, Any]]] = None,
) -> AsyncGenerator[str, None]:
    session = store.get_session(session_id)
    if not session:
        raise FileNotFoundError(f"Session '{session_id}' not found.")
    agent = get_agent(session["agent_id"])

    normalized_attachments: List[Dict[str, Any]] = []
    if images:
        for item in images:
            if isinstance(item, dict):
                normalized_attachments.append(item)

    _user_msg, run = store.start_user_run(
        session_id, content, attachments=normalized_attachments or None
    )
    history_messages = store.list_messages(session_id)

    async for chunk in runtime.generate_agent_stream(
        agent=agent,
        session=session,
        run=run,
        history_messages=history_messages,
        user_content=content,
        attachments=normalized_attachments or None,
    ):
        yield chunk


# --- Prompt Templates ---


def list_prompt_templates(agent_id: str) -> List[Dict[str, Any]]:
    get_agent(agent_id)
    return store.list_prompt_templates(agent_id)


def create_prompt_template(
    agent_id: str, name: str, content: str
) -> Dict[str, Any]:
    return store.create_prompt_template(agent_id, name, content)


def get_prompt_template(template_id: str) -> Dict[str, Any]:
    tmpl = store.get_prompt_template(template_id)
    if not tmpl:
        raise FileNotFoundError(f"Template '{template_id}' not found.")
    return tmpl


def update_prompt_template(
    template_id: str,
    name: Optional[str] = None,
    content: Optional[str] = None,
    display_order: Optional[int] = None,
) -> Dict[str, Any]:
    return store.update_prompt_template(
        template_id, name=name, content=content, display_order=display_order
    )


def delete_prompt_template(template_id: str) -> bool:
    deleted = store.delete_prompt_template(template_id)
    if not deleted:
        raise FileNotFoundError(f"Template '{template_id}' not found.")
    return True
