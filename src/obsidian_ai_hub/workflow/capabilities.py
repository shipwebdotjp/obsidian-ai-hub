"""Workflow-specific capability catalog.

Workflow exposes the registry-derived Task capabilities plus workflow-only
pseudo capabilities such as ``hitl_wait``. Keeping the catalog here means the
Task Agent planner never gains ``hitl_wait`` as a selectable action, while the
Workflow validator and UI can present it. Approval policy and enablement are
still read from ``task_agent_capabilities`` for registry capabilities;
workflow-only capabilities carry their own fixed defaults.

See ``docs/workflow/specification.md`` §7 and §10.
"""

from __future__ import annotations

HITL_WAIT_KEY = "hitl_wait"

# Keys that exist only inside Workflow and are never exposed to the Task Agent
# capability catalog (``tasks/capabilities.py``).
WORKFLOW_ONLY_KEYS: frozenset[str] = frozenset({HITL_WAIT_KEY})

# Workflow-only capabilities are always enabled and never require plan
# approval; the human gate is the HITL question itself.
WORKFLOW_ONLY_APPROVAL: dict[str, str] = {HITL_WAIT_KEY: "auto"}


def workflow_capability_keys() -> frozenset[str]:
    """Return all capability keys selectable in a Workflow revision."""
    from obsidian_ai_hub.tasks.capabilities import get_capability_keys

    return get_capability_keys() | WORKFLOW_ONLY_KEYS


def is_workflow_capability(key: str) -> bool:
    return key in workflow_capability_keys()


def is_workflow_only(key: str) -> bool:
    return key in WORKFLOW_ONLY_KEYS


def default_approval_policy(key: str) -> str:
    """Return the code default policy (``auto`` or ``plan_required``)."""
    if key in WORKFLOW_ONLY_APPROVAL:
        return WORKFLOW_ONLY_APPROVAL[key]
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

    for definition in get_capability_definitions():
        if definition.key == key:
            return definition.default_approval_policy
    return "plan_required"
