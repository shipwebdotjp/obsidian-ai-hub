"""Turn preparation and execution helpers for AI Agents (CLI & Web)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from obsidian_ai_hub.agents import store


def prepare_session_turn(
    agent_id: str,
    prompt: str,
    resume_session_id: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Prepare an agent conversation turn by creating or verifying a session,
    starting a user run with a user message, and returning the session, agent,
    run, and history messages.

    Args:
        agent_id: ID of the agent to communicate with.
        prompt: User message prompt text.
        resume_session_id: Optional existing session_id to resume.
        attachments: Optional list of attachment dictionaries (e.g. images).

    Returns:
        Tuple of (session_dict, agent_dict, run_dict, history_messages_list)

    Raises:
        FileNotFoundError: If agent or session is not found.
        ValueError: If resume session belongs to a different agent_id or prompt is empty.
    """
    agent = store.get_agent(agent_id)
    if not agent:
        raise FileNotFoundError(f"Agent '{agent_id}' not found.")

    if resume_session_id:
        session = store.get_session(resume_session_id)
        if not session:
            raise FileNotFoundError(f"Session '{resume_session_id}' not found.")
        if session["agent_id"] != agent_id:
            raise ValueError(
                f"Session '{resume_session_id}' belongs to agent '{session['agent_id']}', "
                f"not '{agent_id}'."
            )
    else:
        session = store.create_session(agent_id)

    session_id = session["session_id"]
    _user_msg, run = store.start_user_run(
        session_id=session_id,
        content=prompt,
        attachments=attachments,
    )
    history_messages = store.list_messages(session_id)

    return session, agent, run, history_messages
