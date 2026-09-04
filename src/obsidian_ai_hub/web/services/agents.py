"""Service layer for AI agent endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from obsidian_ai_hub.agents import registry, store


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
    from obsidian_ai_hub.agents.ask_user import extract_session_ask_user_history

    session = store.get_session(session_id)
    if not session:
        raise FileNotFoundError(f"Session '{session_id}' not found.")
    agent = get_agent(session["agent_id"])
    messages = store.list_messages(session_id)
    runs = store.list_runs(session_id)
    active_run = store.get_active_run_for_session(session_id)
    ask_user_answer_history = extract_session_ask_user_history(runs)
    return {
        "session": session,
        "agent": agent,
        "messages": messages,
        "runs": runs,
        "active_run": active_run,
        "ask_user_answer_history": ask_user_answer_history,
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


def start_run(
    session_id: str,
    content: str,
    images: Optional[List[Dict[str, Any]]] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Queue an agent run and return it (202 contract)."""
    from obsidian_ai_hub.runs.instance import get_instance_id

    session = store.get_session(session_id)
    if not session:
        raise FileNotFoundError(f"Session '{session_id}' not found.")
    normalized: List[Dict[str, Any]] = []
    if images:
        for item in images:
            if isinstance(item, dict):
                normalized.append(item)
    _, run = store.start_queued_run(
        session_id=session_id,
        content=content,
        attachments=normalized or None,
        idempotency_key=idempotency_key,
        created_instance_id=get_instance_id(),
    )
    return run


def cancel_run(run_id: str) -> Dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise FileNotFoundError(f"Run '{run_id}' not found.")
    return store.request_cancel_run(run_id)


def get_run(run_id: str) -> Dict[str, Any]:
    run = store.get_run(run_id)
    if not run:
        raise FileNotFoundError(f"Run '{run_id}' not found.")
    return run


def list_run_events(
    run_id: str, after_id: int = 0, limit: int = 500
) -> List[Dict[str, Any]]:
    if store.get_run(run_id) is None:
        raise FileNotFoundError(f"Run '{run_id}' not found.")
    return store.list_run_events(run_id, after_id=after_id, limit=limit)


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
