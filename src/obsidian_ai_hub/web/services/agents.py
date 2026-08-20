"""Service layer for AI agent endpoints."""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

from obsidian_ai_hub.agents import registry, runtime, store


def list_agents() -> List[Dict[str, Any]]:
    return store.list_agents()


def create_agent(
    name: str,
    system_prompt: str,
    tool_ids: Optional[List[str]] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    return store.create_agent(
        name=name,
        system_prompt=system_prompt,
        tool_ids=tool_ids or [],
        provider=provider,
        model=model,
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
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    return store.update_agent(
        agent_id=agent_id,
        name=name,
        system_prompt=system_prompt,
        tool_ids=tool_ids,
        provider=provider,
        model=model,
    )


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


def delete_session(session_id: str) -> bool:
    deleted = store.delete_session(session_id)
    if not deleted:
        raise FileNotFoundError(f"Session '{session_id}' not found.")
    return True


async def stream_session_message(
    session_id: str, content: str
) -> AsyncGenerator[str, None]:
    session = store.get_session(session_id)
    if not session:
        raise FileNotFoundError(f"Session '{session_id}' not found.")
    agent = get_agent(session["agent_id"])

    user_msg, run = store.start_user_run(session_id, content)
    history_messages = store.list_messages(session_id)

    async for chunk in runtime.generate_agent_stream(
        agent=agent,
        session=session,
        run=run,
        history_messages=history_messages,
        user_content=content,
    ):
        yield chunk
