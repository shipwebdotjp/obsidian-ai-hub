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

from typing import Any

from obsidian_ai_hub.tasks.capability_schemas import (
    OUTPUT_CONTRACT_STRUCTURED,
    REFERENCE_POLICY_STRICT_FIELDS,
)

HITL_WAIT_KEY = "hitl_wait"

# Keys that exist only inside Workflow and are never exposed to the Task Agent
# capability catalog (``tasks/capabilities.py``).
WORKFLOW_ONLY_KEYS: frozenset[str] = frozenset({HITL_WAIT_KEY})

# Workflow-only capabilities are always enabled and never require plan
# approval; the human gate is the HITL question itself.
WORKFLOW_ONLY_APPROVAL: dict[str, str] = {HITL_WAIT_KEY: "auto"}

# Display metadata for workflow-only capabilities, kept next to the policy
# so a new key cannot be published with another capability's label.
WORKFLOW_ONLY_METADATA: dict[str, tuple[str, str]] = {
    HITL_WAIT_KEY: (
        "HITL確認",
        "既存HITLへ質問を登録し、回答まで待つ。",
    ),
}

# Workflow-only capabilities have no Pydantic args model, so their UI-facing
# input schema is defined here next to the policy/metadata. Shape mirrors the
# normalized schema returned by ``tasks.capability_schemas.ui_input_schema`` so
# the editor can render every capability the same way.
WORKFLOW_ONLY_INPUT_SCHEMA: dict[str, dict[str, Any]] = {
    HITL_WAIT_KEY: {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "HITL に登録する質問文。",
            },
            "question_type": {
                "type": "string",
                "enum": ["text", "select", "boolean"],
                "default": "text",
                "description": "回答UIの種別。select のときは choices を使う。",
            },
            "choices": {
                "type": "array",
                "items": {"type": "string"},
                "description": "question_type=select のときの選択肢。",
            },
        },
        "required": ["question"],
    }
}

# Output of a workflow-only capability (shape mirrors ``ui_output_schema``).
# ``hitl_wait.answer`` is the human-input boundary: normalized to a string
# and validated (P2). Additional properties are allowed by the runner shape
# but never referencable.
WORKFLOW_ONLY_OUTPUT_SCHEMA: dict[str, dict[str, Any]] = {
    HITL_WAIT_KEY: {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "HITL の回答値（文字列へ正規化）。",
            },
        },
        "required": ["answer"],
        "additionalProperties": True,
    }
}

# Workflow-only capabilities are ``structured`` (P1 ledger). ``hitl_wait`` is
# additionally in the strict-allowed set with the P2 read capabilities.
# Values reuse the ledger constants so the single source of truth cannot drift.
WORKFLOW_ONLY_CONTRACT_CLASS: dict[str, str] = {
    HITL_WAIT_KEY: OUTPUT_CONTRACT_STRUCTURED,
}

STRICT_ALLOWED_WORKFLOW_ONLY_KEYS: frozenset[str] = frozenset({HITL_WAIT_KEY})


def output_contract_class(key: str) -> str:
    """Return the workflow-visible output contract class for any capability."""
    if key in WORKFLOW_ONLY_CONTRACT_CLASS:
        return WORKFLOW_ONLY_CONTRACT_CLASS[key]
    from obsidian_ai_hub.tasks.capability_schemas import (
        output_contract_class as registry_contract_class,
    )

    return registry_contract_class(key)


def output_reference_policy(key: str) -> str:
    """Return ``strict_fields`` for structured, else ``forbidden``."""
    if key in WORKFLOW_ONLY_CONTRACT_CLASS:
        return REFERENCE_POLICY_STRICT_FIELDS
    from obsidian_ai_hub.tasks.capability_schemas import (
        output_reference_policy as registry_reference_policy,
    )

    return registry_reference_policy(key)


def is_strict_allowed(key: str) -> bool:
    """True when ``fail_on_output_mismatch: true`` may be set (P1/P2)."""
    if key in STRICT_ALLOWED_WORKFLOW_ONLY_KEYS:
        return True
    from obsidian_ai_hub.tasks.capability_schemas import (
        STRICT_ALLOWED_REGISTRY_KEYS,
    )

    return key in STRICT_ALLOWED_REGISTRY_KEYS


def workflow_output_schema(key: str) -> dict[str, Any] | None:
    """Return the declared output schema for any workflow capability."""
    if key in WORKFLOW_ONLY_OUTPUT_SCHEMA:
        return WORKFLOW_ONLY_OUTPUT_SCHEMA[key]
    from obsidian_ai_hub.tasks.capability_schemas import capability_output_schema

    return capability_output_schema(key)


def normalize_hitl_answer(answer: Any) -> str:
    """Coerce a human HITL answer to the ``hitl_wait.answer`` contract.

    The human-input boundary normalizes to a string so downstream strict
    nodes see a validated value: ``None`` becomes ``""``, booleans become
    ``"true"``/``"false"``, strings pass through, and other scalars or
    structured values become their compact JSON form.
    """
    if answer is None:
        return ""
    if isinstance(answer, bool):
        return "true" if answer else "false"
    if isinstance(answer, str):
        return answer
    if isinstance(answer, (int, float)):
        return str(answer)
    import json as _json

    return _json.dumps(answer, ensure_ascii=False, separators=(",", ":"))


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
