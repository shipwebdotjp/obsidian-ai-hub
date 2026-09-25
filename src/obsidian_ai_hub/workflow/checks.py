"""DB-backed checks shared by the Workflow API and CLI.

``validation.validate_graph`` stays pure; callers supply the capability and
agent existence checks. Both the Web routes and the CLI need the same
production checks, so they live here instead of in either caller.
"""

from __future__ import annotations

from typing import Any, Callable


def capability_enabled_check() -> Callable[[str], bool]:
    """Return a predicate for ``task_agent_capabilities`` enablement.

    Workflow-only keys are always enabled. Keys outside the workflow catalog
    are never valid.
    """
    from obsidian_ai_hub.tasks import store as task_store
    from obsidian_ai_hub.workflow.capabilities import (
        is_workflow_only,
        workflow_capability_keys,
    )

    enabled = {
        str(c["capability_key"]): bool(c["enabled"])
        for c in task_store.list_capabilities()
    }
    valid_keys = workflow_capability_keys()
    return lambda key: key in valid_keys and (
        is_workflow_only(key) or enabled.get(key, False)
    )


def agent_exists_check() -> Callable[[str], bool]:
    """Return a predicate for Agent existence."""
    from obsidian_ai_hub.agents import store as agent_store

    return lambda agent_id: agent_store.get_agent(agent_id) is not None


def workflow_graph_warnings(revision: dict[str, Any]) -> list[str]:
    """Return non-blocking warnings for a revision (read-only classification)."""
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
    from obsidian_ai_hub.workflow.validation import collect_graph_warnings

    read_only = {d.key: d.read_only for d in get_capability_definitions()}
    return collect_graph_warnings(
        nodes=revision.get("nodes") or [],
        read_only=lambda key: read_only.get(key, False),
    )
