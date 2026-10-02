"""Single source of truth for Capability input schemas.

``CapabilityDefinition`` never hand-duplicates required keys. This module
lazily resolves the Pydantic ``args_schema`` behind each registry tool (or a
local Target/Inputs model for ``specialist_agent`` / ``coding_cli``) and
derives both the Planner-facing compact schema and the runtime
``model_validate()`` check from the same object.

Top-level imports stay light on purpose: the heavy agent registry is only
imported inside functions so ``tasks/capabilities.py`` never gains a hard
dependency cycle.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# --- Delegate target/input models (code-defined, Pydantic single source) ---
#
# Responsibility split (matches the stored plan shape):
# - ``target``: *which* registered object to run against (agent / project).
# - ``inputs``: hint text handed to the child run (executed at run time from
#   the latest agent/project settings; never a frozen tool argument list).


class SpecialistAgentTarget(BaseModel):
    """Which AI Agent to delegate to (type-level check only).

    Registry membership and the approval-time allowlist are enforced by
    callers (adapters verify existence; the orchestrator enforces
    ``allowed_agent_ids`` per action).
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(
        description="委譲先のエージェントID（例: 'agent_xxx'）。承認範囲内のIDを指定すること。"
    )


class SpecialistAgentInputs(BaseModel):
    """Hint handed to the child agent run (not a frozen tool call)."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(
        default="",
        description="子エージェントに実行させる具体的なタスク内容。空ならPlanの目的・方針を使う。",
    )
    fresh_session: bool = Field(
        default=False,
        description="同一タスク内の既存セッション再利用をやめ、新規セッションで実行したい場合のみtrue。",
    )


class CodingTarget(BaseModel):
    """Which registered project (and backend) to run the Coding CLI in."""

    model_config = ConfigDict(extra="forbid")

    # Non-strict int so the planner's JSON string form ("1") still coerces;
    # canonical normalization keeps the DB-canonical int.
    project_id: int = Field(
        description="プロジェクトID（例: 1）。登録済みProjectのみ指定可能。"
    )
    backend: Optional[Literal["opencode"]] = Field(
        default=None,
        description="Coding backend。省略時は既定backend（opencode固定）。",
    )


class CodingInputs(BaseModel):
    """Hint handed to the child coding run."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(
        default="",
        description="子Coding runへの作業指示ヒント。空ならPlanの目的・方針を使う。",
    )
    fresh_session: bool = Field(
        default=False,
        description="同一タスク内の既存セッション再利用をやめ、新規セッションで実行したい場合のみtrue。",
    )


class ResearchAgentInputs(BaseModel):
    """Inputs for the existing research pipeline (no target needed)."""

    model_config = ConfigDict(extra="forbid")

    theme: str = Field(
        min_length=1,
        description="調査テーマ。既存の承認済みテーマと重複すればそのテーマを再利用する。",
    )
    mode: Optional[Literal["auto", "internal", "web", "deep", "project"]] = Field(
        default=None,
        description="調査モード。省略時はauto(自動ルーティング)。projectはコードベース調査。",
    )
    context: Optional[str] = Field(
        default=None,
        description="自分の前提知識や調査理由の補足文脈。テーマのdirectionとしても使われる。",
    )
    output_style: Optional[str] = Field(
        default=None,
        description="出力長スタイル(short/long等)。省略時は既定。",
    )
    project_id: Optional[int] = Field(
        default=None,
        description="projectモードで調査する対象Project ID。",
    )


class SkillInputs(BaseModel):
    """Select one tool of the skills bundle; the rest is per-tool args.

    The chosen skill tool validates its own arguments at invoke time via its
    ``args_schema``, so unknown extra keys are allowed here and forwarded.
    """

    model_config = ConfigDict(extra="allow")

    skill: Literal["load_skill", "read_skill_resource", "run_skill_script"] = Field(
        description="実行するskillツール名。"
    )


_DELEGATE_TARGET_MODELS: dict[str, type[BaseModel]] = {
    "specialist_agent": SpecialistAgentTarget,
    "coding_cli": CodingTarget,
}

_DELEGATE_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "specialist_agent": SpecialistAgentInputs,
    "coding_cli": CodingInputs,
    "skills": SkillInputs,
    "research_agent": ResearchAgentInputs,
}


def _capability_registry_tool_id(capability_key: str) -> str | None:
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

    for definition in get_capability_definitions():
        if definition.key == capability_key:
            return definition.registry_tool_id
    return None


def _tool_definitions() -> dict[str, Any]:
    # Looked up fresh on every call: tests monkeypatch TOOL_DEFINITIONS and
    # plugins can reload it, so caching the dict object would go stale.
    from obsidian_ai_hub.agents import registry as agent_registry

    return agent_registry.TOOL_DEFINITIONS


def resolve_input_model(capability_key: str) -> type[BaseModel] | None:
    """Return the Pydantic model for LLM-visible inputs, or None if unknown."""
    if capability_key in _DELEGATE_INPUT_MODELS:
        return _DELEGATE_INPUT_MODELS[capability_key]
    tool_id = _capability_registry_tool_id(capability_key)
    if tool_id is None:
        return None
    meta = _tool_definitions().get(tool_id)
    if not meta:
        return None
    # Explicit model override (used by tests and future providers).
    override = meta.get("input_model")
    if isinstance(override, type) and issubclass(override, BaseModel):
        return override
    factory = meta.get("get_tool_with_context")
    try:
        if callable(factory):
            # Context-bound factory: the closure captures trusted_ctx but the
            # visible args_schema stays the same, so pass an empty dict purely
            # to read the schema (never executed here).
            tool = factory({})
        else:
            get_tool = meta.get("get_tool")
            if not callable(get_tool):
                return None
            tool = get_tool()
    except Exception:
        logger.warning("Failed to build tool for schema: %s", capability_key)
        return None
    schema = getattr(tool, "args_schema", None)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    return None


def resolve_target_model(capability_key: str) -> type[BaseModel] | None:
    """Return the Pydantic model for the step target, if any."""
    return _DELEGATE_TARGET_MODELS.get(capability_key)


def resolve_json_schema(capability_key: str) -> dict[str, Any] | None:
    """Return the full JSON Schema for a capability's inputs, if resolvable."""
    model = resolve_input_model(capability_key)
    if model is None:
        return None
    try:
        return model.model_json_schema()
    except Exception:
        logger.warning("Failed to build JSON schema for %s", capability_key)
        return None


# UI-facing normalization of Pydantic JSON Schema.
#
# The Workflow editor renders one form field per leaf. Pydantic emits
# ``anyOf: [X, {"type": "null"}]`` for ``Optional`` and ``$defs``/``$ref`` for
# nested models, neither of which a simple renderer can consume. This layer
# flattens those into a single, stable shape while leaving the schema itself as
# the single source of truth (no hand-duplicated field lists).
_UI_PASSTHROUGH_KEYS = (
    "description",
    "title",
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "minItems",
    "maxItems",
)


def _deref(node: Any, defs: dict[str, Any]) -> Any:
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 32:
        ref = node.get("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            return {"x-unsupported": True}
        target = defs.get(ref[len("#/$defs/") :])
        if not isinstance(target, dict):
            return {"x-unsupported": True}
        node = target
        seen += 1
    return node


def _normalize_ui_schema(
    node: Any, defs: dict[str, Any], *, depth: int = 0
) -> dict[str, Any]:
    if depth > 12 or not isinstance(node, dict):
        return {"x-unsupported": True}
    node = _deref(node, defs)
    if not isinstance(node, dict) or node.get("x-unsupported"):
        return {"x-unsupported": True}

    for combiner in ("anyOf", "oneOf"):
        branches = node.get(combiner)
        if isinstance(branches, list):
            non_null = [
                branch
                for branch in branches
                if not (isinstance(branch, dict) and branch.get("type") == "null")
            ]
            if len(non_null) != 1:
                return {"x-unsupported": True}
            merged = dict(non_null[0])
            for key in ("default", "description", "title"):
                if key not in merged and key in node:
                    merged[key] = node[key]
            result = _normalize_ui_schema(merged, defs, depth=depth + 1)
            if result.get("x-unsupported"):
                return result
            if len(non_null) != len(branches):
                result["nullable"] = True
            return result

    stype = node.get("type")
    if isinstance(stype, list):
        non_null_types = [t for t in stype if t != "null"]
        if len(non_null_types) != 1:
            return {"x-unsupported": True}
        node = dict(node)
        node["type"] = non_null_types[0]
        if len(non_null_types) != len(stype):
            node["nullable"] = True
        stype = non_null_types[0]

    out: dict[str, Any] = {}
    if isinstance(stype, str):
        out["type"] = stype
    if node.get("nullable"):
        out["nullable"] = True
    if isinstance(node.get("enum"), list):
        out["enum"] = list(node["enum"])
    elif "const" in node:
        # Pydantic emits ``const`` (not ``enum``) for a single-value Literal.
        out["enum"] = [node["const"]]
    for key in _UI_PASSTHROUGH_KEYS:
        if key in node:
            out[key] = node[key]

    if stype == "object":
        props = node.get("properties")
        if isinstance(props, dict):
            out["properties"] = {
                name: _normalize_ui_schema(spec, defs, depth=depth + 1)
                for name, spec in props.items()
            }
        required = node.get("required")
        if isinstance(required, list):
            out["required"] = [r for r in required if isinstance(r, str)]
        additional = node.get("additionalProperties")
        if isinstance(additional, bool):
            out["additionalProperties"] = additional
        elif isinstance(additional, dict):
            out["additionalProperties"] = _normalize_ui_schema(
                additional, defs, depth=depth + 1
            )
    elif stype == "array":
        if "items" in node:
            out["items"] = _normalize_ui_schema(
                node["items"], defs, depth=depth + 1
            )
    elif stype is None and "enum" not in out:
        return {"x-unsupported": True}
    return out


# Code-owned UI widget hints. The Workflow editor renders a dedicated control
# for these fields instead of a free-text input; the capability schema stays the
# single source of truth for the field set. ``x-ui`` is advisory: an unknown
# widget degrades to the default control.
_FIELD_WIDGETS: dict[str, dict[str, str]] = {
    "vault_read_file": {"relative_path": "vault_path"},
    "vault_write_file": {"relative_path": "vault_path"},
    "specialist_agent": {"agent_id": "agent"},
    "coding_cli": {"project_id": "project"},
    "research_agent": {"project_id": "project"},
    "activity_search": {"project_id": "project"},
    "project_get": {"project_id": "project"},
    "people_get": {"person_id": "person"},
    "people_relations_walk": {"person_id": "person"},
}

_DATE_FIELDS = frozenset(
    {"start_date", "end_date", "reference_date", "due_date", "date"}
)
_DATETIME_FIELDS = frozenset({"run_at"})


def field_widget(
    capability_key: str, name: str, spec: dict[str, Any]
) -> str | None:
    """Return the UI widget hint for one capability field, if any."""
    explicit = _FIELD_WIDGETS.get(capability_key, {}).get(name)
    if explicit:
        return explicit
    if spec.get("type") == "string":
        if name in _DATETIME_FIELDS:
            return "datetime"
        if name in _DATE_FIELDS or name.endswith("_date"):
            return "date"
    return None


def get_input_field_contract(capability_key: str, field_name: str) -> dict[str, Any]:
    """Return field-level input contract metadata (accepted_value_kinds)."""
    allowed_narrative = ALLOWED_NARRATIVE_INPUT_FIELDS.get(capability_key, set())
    if field_name in allowed_narrative:
        return {"accepted_value_kinds": [VALUE_KIND_STRUCTURED, VALUE_KIND_NARRATIVE]}
    return {"accepted_value_kinds": [VALUE_KIND_STRUCTURED]}


def get_output_field_contract(capability_key: str, field_path: str) -> dict[str, Any]:
    """Return field-level output contract metadata (value_kind, allowed_uses)."""
    per_key = _MIXED_OUTPUT_FIELD_CONTRACTS.get(capability_key)
    if per_key is not None:
        exact = per_key.get(field_path)
        if exact is not None:
            return {
                "value_kind": exact["value_kind"],
                "allowed_uses": exact["allowed_uses"],
            }
        if field_path.startswith("receipt."):
            return {
                "value_kind": VALUE_KIND_RECEIPT,
                "allowed_uses": ALLOWED_USES_NONE,
            }
        if field_path.startswith("narrative."):
            return {
                "value_kind": VALUE_KIND_NARRATIVE,
                "allowed_uses": ALLOWED_USES_PAYLOAD,
            }
        return {
            "value_kind": OUTPUT_CONTRACT_OPAQUE,
            "allowed_uses": ALLOWED_USES_NONE,
        }

    contract_class = output_contract_class(capability_key)
    if contract_class == OUTPUT_CONTRACT_STRUCTURED:
        return {
            "value_kind": VALUE_KIND_STRUCTURED,
            "allowed_uses": ALLOWED_USES_ALL,
        }
    if contract_class == OUTPUT_CONTRACT_RECEIPT:
        return {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        }
    return {
        "value_kind": OUTPUT_CONTRACT_OPAQUE,
        "allowed_uses": ALLOWED_USES_NONE,
    }


def _apply_field_widgets(
    capability_key: str, schema: dict[str, Any]
) -> dict[str, Any]:
    props = schema.get("properties")
    if isinstance(props, dict):
        for name, spec in props.items():
            if isinstance(spec, dict):
                widget = field_widget(capability_key, name, spec)
                if widget:
                    spec["x-ui"] = widget
                contract = get_input_field_contract(capability_key, name)
                spec["x-accepted-value-kinds"] = contract["accepted_value_kinds"]
    return schema


def ui_input_schema(capability_key: str) -> dict[str, Any] | None:
    """Return the UI-facing (normalized) JSON Schema for a capability's inputs.

    Thin wrapper over :func:`resolve_json_schema` so the Workflow editor never
    hand-duplicates field metadata. Unknown shapes are marked
    ``{"x-unsupported": true}`` so the frontend can fall back to a raw editor.
    """
    schema = resolve_json_schema(capability_key)
    if not isinstance(schema, dict):
        return None
    defs = schema.get("$defs")
    normalized = _normalize_ui_schema(
        schema, defs if isinstance(defs, dict) else {}
    )
    if not isinstance(normalized, dict) or normalized.get("x-unsupported"):
        return None
    return _apply_field_widgets(capability_key, normalized)


def capability_has_target(capability_key: str) -> bool:
    """True when the capability takes a delegate ``target`` (agent/project)."""
    return resolve_target_model(capability_key) is not None


def ui_target_schema(capability_key: str) -> dict[str, Any] | None:
    """Return the UI-facing (normalized) JSON Schema for a capability target."""
    model = resolve_target_model(capability_key)
    if model is None:
        return None
    try:
        schema = model.model_json_schema()
    except Exception:
        logger.warning("Failed to build target JSON schema for %s", capability_key)
        return None
    if not isinstance(schema, dict):
        return None
    defs = schema.get("$defs")
    normalized = _normalize_ui_schema(
        schema, defs if isinstance(defs, dict) else {}
    )
    if not isinstance(normalized, dict) or normalized.get("x-unsupported"):
        return None
    return _apply_field_widgets(capability_key, normalized)


# Code-owned output contracts (P1: contract ledger).
#
# Every builtin capability is classified into exactly one output contract
# class (see ``docs/workflow/adr/capability-input-output-contracts.md`` and
# its amendments):
# - ``structured``: stable data the Workflow may pass downstream as typed
#   references. References are ``strict_fields``: only declared fields, and
#   only from a node with ``fail_on_output_mismatch: true``.
# - ``receipt``: write/proposal/job-registration results. The schema is kept
#   for audit/display, but P3 まで後続 Node・条件・pipe・テンプレートからは
#   参照できない (``forbidden``).
# - ``mixed``: delegation results (``coding_cli``, ``specialist_agent``,
#   ``research_agent``) that publish an observed ``receipt`` alongside a
#   free-text ``narrative``. Field-level ``value_kind`` / ``allowed_uses``
#   contracts come from ``get_output_field_contract``.
# - ``opaque``: plugin, Skills, external providers and not-yet-structured
#   read/search outputs. No typed field references (``forbidden``) and no
#   synthetic ``summary`` fallback.
#
# Dynamic plugins (``custom:*`` without an explicit registration, ``skills``)
# default to ``opaque``. ``hitl_wait`` is workflow-only and ``structured``;
# see ``workflow/capabilities.py``.
OUTPUT_CONTRACT_STRUCTURED = "structured"
OUTPUT_CONTRACT_RECEIPT = "receipt"
OUTPUT_CONTRACT_MIXED = "mixed"
OUTPUT_CONTRACT_OPAQUE = "opaque"

VALUE_KIND_STRUCTURED = "structured"
VALUE_KIND_RECEIPT = "receipt"
VALUE_KIND_NARRATIVE = "narrative"

ALLOWED_USES_ALL = [
    "condition",
    "identifier",
    "path",
    "command",
    "url",
    "destination",
    "target",
    "loop_state",
    "payload",
]
ALLOWED_USES_CONDITION = ["condition"]
ALLOWED_USES_PAYLOAD = ["payload"]
ALLOWED_USES_NONE: list[str] = []

REFERENCE_POLICY_STRICT_FIELDS = "strict_fields"
REFERENCE_POLICY_FORBIDDEN = "forbidden"

MIXED_CAPABILITY_KEYS: frozenset[str] = frozenset(
    {"coding_cli", "specialist_agent", "research_agent"}
)

# Field-level value-kind contracts for ``mixed`` capabilities. Each entry maps
# an output field path (relative to ``output``) to its ``value_kind`` and
# ``allowed_uses``. Unknown ``receipt.*`` / ``narrative.*`` tails fall back to
# receipt-without-uses / narrative-payload in :func:`get_output_field_contract`;
# anything outside those namespaces is ``opaque``.
_MIXED_OUTPUT_FIELD_CONTRACTS: dict[str, dict[str, dict[str, Any]]] = {
    "coding_cli": {
        "receipt.status": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_CONDITION,
        },
        "receipt.report_truncated": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_CONDITION,
        },
        "receipt.child_run_id": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        },
        "receipt.session_id": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        },
        "narrative.text": {
            "value_kind": VALUE_KIND_NARRATIVE,
            "allowed_uses": ALLOWED_USES_PAYLOAD,
        },
    },
    "specialist_agent": {
        "receipt.status": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_CONDITION,
        },
        "receipt.child_run_id": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        },
        "receipt.session_id": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        },
        "receipt.agent_id": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        },
        "narrative.text": {
            "value_kind": VALUE_KIND_NARRATIVE,
            "allowed_uses": ALLOWED_USES_PAYLOAD,
        },
    },
    "research_agent": {
        "receipt.status": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_CONDITION,
        },
        "receipt.is_published": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_CONDITION,
        },
        "receipt.job_id": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        },
        "receipt.theme_id": {
            "value_kind": VALUE_KIND_RECEIPT,
            "allowed_uses": ALLOWED_USES_NONE,
        },
        "narrative.text": {
            "value_kind": VALUE_KIND_NARRATIVE,
            "allowed_uses": ALLOWED_USES_PAYLOAD,
        },
    },
}

ALLOWED_NARRATIVE_INPUT_FIELDS: dict[str, set[str]] = {
    "vault_write_file": {"content"},
    "calendar_create_proposal": {"title", "location", "content"},
    "reminder_create_proposal": {"title", "content"},
    "gmail_create_draft": {"body_text", "subject"},
}

# First structured targets (P2). ``hitl_wait`` lives in workflow-only and is
# added by ``workflow/capabilities.py``.
STRUCTURED_CAPABILITY_KEYS: frozenset[str] = frozenset(
    {
        "vault_read_file",
        "calendar_read",
        "reminders_read",
        "periodic_note_read",
        "research_context_snapshot",
        "summary_search",
    }
)

# Effectful capabilities whose output is a completion receipt (P3 まで参照不可).
RECEIPT_CAPABILITY_KEYS: frozenset[str] = frozenset(
    {
        "vault_write_file",
        "calendar_create_proposal",
        "reminder_create_proposal",
        "research_theme_propose",
        "register_one_shot_job",
        "register_one_shot_workflow_job",
        "register_recurring_job",
        "register_recurring_workflow_job",
        "image_generate",
        "image_edit",
        "run_shell",
        "memory_propose",
        "gmail_create_draft",
    }
)

# Capabilities allowed to set ``fail_on_output_mismatch: true`` (P1/P2).
# Structured reads plus workflow-only ``hitl_wait`` (checked in validation
# via ``workflow/capabilities.py``). Writes, external operations and receipts
# are rejected.
STRICT_ALLOWED_REGISTRY_KEYS: frozenset[str] = frozenset(
    STRUCTURED_CAPABILITY_KEYS
)


def mixed_output_field_contracts(capability_key: str) -> dict[str, Any] | None:
    """Return the JSON-serializable field contract table for a mixed key.

    Maps each declared output field path to ``{"value_kind", "allowed_uses"}``.
    Returns ``None`` for non-mixed capabilities. The Workflow capability API
    and designer catalog expose this so the editor can offer exactly the
    bindable ``receipt`` / ``narrative`` fields.
    """
    per_key = _MIXED_OUTPUT_FIELD_CONTRACTS.get(capability_key)
    if per_key is None:
        return None
    return {
        field_path: {
            "value_kind": entry["value_kind"],
            "allowed_uses": list(entry["allowed_uses"]),
        }
        for field_path, entry in per_key.items()
    }


def output_contract_class(capability_key: str) -> str:
    """Return the code-owned output contract class for a registry capability.

    ``mixed`` capabilities (``coding_cli``, ``specialist_agent``,
    ``research_agent``) publish an observed ``receipt`` alongside a free-text
    ``narrative``; field-level contracts come from
    :func:`get_output_field_contract`. Unknown keys and dynamic plugins
    (``custom:*``, ``skills``) default to ``opaque`` unless an explicit
    contract registration exists.
    """
    if capability_key in STRUCTURED_CAPABILITY_KEYS:
        return OUTPUT_CONTRACT_STRUCTURED
    if capability_key in RECEIPT_CAPABILITY_KEYS:
        return OUTPUT_CONTRACT_RECEIPT
    if capability_key in MIXED_CAPABILITY_KEYS:
        return OUTPUT_CONTRACT_MIXED
    return OUTPUT_CONTRACT_OPAQUE


def output_reference_policy(capability_key: str) -> str:
    """Return ``strict_fields`` for structured, else ``forbidden``."""
    if output_contract_class(capability_key) == OUTPUT_CONTRACT_STRUCTURED:
        return REFERENCE_POLICY_STRICT_FIELDS
    return REFERENCE_POLICY_FORBIDDEN


def _object_output(
    properties: dict[str, Any],
    description: str = "",
    required: list[str] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        schema["required"] = list(required)
    if description:
        schema["description"] = description
    return schema

# Shared by image_generate / image_edit: a short summary plus media references.
_IMAGE_OUTPUT_SCHEMA: dict[str, Any] = _object_output(
    {
        "summary": {"type": "string"},
        "model": {"type": "string"},
        "images": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "media_type": {"type": "string"},
                    "media_id": {"type": "string"},
                    "url": {"type": "string"},
                    "download_url": {"type": "string"},
                    "mime_type": {"type": "string"},
                    # Dimensions are best-effort metadata; null is allowed.
                    "width": {"type": ["integer", "null"]},
                    "height": {"type": ["integer", "null"]},
                    "filename": {"type": "string"},
                },
            },
        },
    }
)

# Fetch-state values for Calendar/Reminders P2 outputs. ``ok`` means both
# Apple and recurring sources were read; any other value marks a partial
# result that stays observable in lenient mode but fails strict nodes.
FETCH_STATUS_OK = "ok"

_OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    # --- structured (P2): referencable only via strict fields ---
    "vault_read_file": _object_output(
        {"relative_path": {"type": "string"}, "content": {"type": "string"}},
        required=["relative_path", "content"],
    ),
    "periodic_note_read": _object_output(
        {
            "period_type": {"type": "string"},
            "reference_date": {"type": "string"},
            "relative_path": {"type": "string"},
            "content": {"type": "string"},
            "truncated": {"type": "boolean"},
        },
        required=[
            "period_type",
            "reference_date",
            "relative_path",
            "content",
            "truncated",
        ],
    ),
    "calendar_read": _object_output(
        {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "all_day": {"type": "boolean"},
                        "source": {"type": "string"},
                    },
                    "required": ["title", "start", "end", "all_day", "source"],
                    "additionalProperties": True,
                },
            },
            "apple_status": {"type": "string"},
            "recurring_status": {"type": "string"},
        },
        required=["events", "apple_status", "recurring_status"],
    ),
    "reminders_read": _object_output(
        {
            "reminders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "due": {"type": "string"},
                        "source": {"type": "string"},
                    },
                    "required": ["title", "due", "source"],
                    "additionalProperties": True,
                },
            },
            "apple_status": {"type": "string"},
            "recurring_status": {"type": "string"},
        },
        required=["reminders", "apple_status", "recurring_status"],
    ),
    "research_context_snapshot": _object_output(
        {
            "recent_activities": {"type": "array", "items": {"type": "object"}},
            "existing_themes": {"type": "array", "items": {"type": "object"}},
            "recent_feedback": {"type": "array", "items": {"type": "object"}},
            "daily_notes": {"type": "array", "items": {"type": "object"}},
            "latest_weekly_note": {"type": "object"},
        },
        required=[
            "recent_activities",
            "existing_themes",
            "recent_feedback",
            "daily_notes",
            "latest_weekly_note",
        ],
    ),
    "summary_search": _object_output(
        {
            "requested_range": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "required": ["start_date", "end_date"],
            },
            "granularity": {"type": "string"},
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "period_type": {"type": "string"},
                        "period_key": {"type": "string"},
                        "period_start": {"type": "string"},
                        "period_end": {"type": "string"},
                        "summary_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "topics": {"type": "array", "items": {"type": "string"}},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "kind": {"type": ["string", "null"]},
                                    "body": {"type": ["string", "null"]},
                                },
                            },
                        },
                        "project_ids": {"type": "array", "items": {"type": "integer"}},
                        "projects": {"type": "array", "items": {"type": "string"}},
                        "people": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "person_id": {"type": ["string", "null"]},
                                    "name": {"type": ["string", "null"]},
                                    "note": {"type": ["string", "null"]},
                                },
                            },
                        },
                        "mood": {"type": ["string", "null"]},
                        "sleep_hours": {"type": ["number", "null"]},
                        "matched_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "entry_truncated": {"type": "boolean"},
                    },
                    "required": [
                        "period_type",
                        "period_key",
                        "period_start",
                        "period_end",
                        "summary_id",
                        "summary",
                        "matched_fields",
                        "entry_truncated",
                    ],
                },
            },
            "coverage": {
                "type": "object",
                "properties": {
                    "requested_days": {"type": "integer"},
                    "source_covered_days": {"type": "integer"},
                    "source_missing_days": {"type": "integer"},
                    "filter_matched_days": {"type": "integer"},
                    "filter_unmatched_days": {"type": "integer"},
                    "returned_days": {"type": "integer"},
                    "source_missing_ranges": {"type": "array", "items": {"type": "object"}},
                    "filter_unmatched_ranges": {"type": "array", "items": {"type": "object"}},
                    "returned_ranges": {"type": "array", "items": {"type": "object"}},
                    "ranges_truncated": {
                        "type": "object",
                        "properties": {
                            "source_missing": {"type": "boolean"},
                            "filter_unmatched": {"type": "boolean"},
                            "returned": {"type": "boolean"},
                        },
                        "required": ["source_missing", "filter_unmatched", "returned"],
                    },
                },
                "required": [
                    "requested_days",
                    "source_covered_days",
                    "source_missing_days",
                    "filter_matched_days",
                    "filter_unmatched_days",
                    "returned_days",
                    "source_missing_ranges",
                    "filter_unmatched_ranges",
                    "returned_ranges",
                    "ranges_truncated",
                ],
            },
            "truncated": {"type": "boolean"},
            "next_request": {"type": ["object", "null"]},
        },
        required=[
            "requested_range",
            "granularity",
            "entries",
            "coverage",
            "truncated",
            "next_request",
        ],
    ),
    # --- receipt (P3 まで参照不可; schema は監査・表示用に維持) ---
    "calendar_create_proposal": _object_output(
        {
            "status": {"type": "string"},
            "hitl_run_id": {"type": "string"},
            "message": {"type": "string"},
            "event": {"type": "object"},
        }
    ),
    "reminder_create_proposal": _object_output(
        {
            "status": {"type": "string"},
            "hitl_run_id": {"type": "string"},
            "message": {"type": "string"},
            "reminder": {"type": "object"},
        }
    ),
    "image_generate": _IMAGE_OUTPUT_SCHEMA,
    "image_edit": _IMAGE_OUTPUT_SCHEMA,
    "run_shell": _object_output(
        {
            "exit_code": {"type": "integer"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "timeout": {"type": "boolean"},
        }
    ),
    "register_one_shot_job": _object_output(
        {
            "job_id": {"type": "string"},
            "status": {"type": "string"},
            "run_at_utc": {"type": "string"},
        }
    ),
    "register_one_shot_workflow_job": _object_output(
        {"job_id": {"type": "string"}}
    ),
    "register_recurring_job": _object_output({"job_id": {"type": "string"}}),
    "register_recurring_workflow_job": _object_output(
        {"job_id": {"type": "string"}}
    ),
    "research_theme_propose": _object_output(
        {"theme_id": {"type": "string"}, "hitl_run_id": {"type": "string"}}
    ),
    "vault_write_file": _object_output(
        {
            "relative_path": {"type": "string"},
            "bytes_written": {"type": "integer"},
            "overwritten": {"type": "boolean"},
        }
    ),
    "memory_propose": _object_output(
        {
            "status": {"type": "string"},
            "memory_id": {"type": "string"},
            "message": {"type": "string"},
        }
    ),
    "gmail_create_draft": _object_output(
        {
            "status": {"type": "string"},
            "request_key": {"type": "string"},
            "gmail_draft_id": {"type": ["string", "null"]},
            "gmail_message_id": {"type": ["string", "null"]},
            "gmail_thread_id": {"type": ["string", "null"]},
            "reused_receipt": {"type": "boolean"},
            "receipt_persisted": {"type": "boolean"},
        }
    ),
}

# Opaque capabilities (plugin / Skills / not-yet-structured reads, Agent /
# Coding / Research delegation outputs) intentionally have no entry above.
# ``capability_output_schema`` returns ``None`` for them and ``ui_output_schema``
# returns ``None`` as well (no synthetic ``summary`` fallback).


def capability_output_schema(capability_key: str) -> dict[str, Any] | None:
    """Return the declared output schema, or ``None`` when opaque/undeclared."""
    return _OUTPUT_SCHEMAS.get(capability_key)


def ui_output_schema(capability_key: str) -> dict[str, Any] | None:
    """Return the UI-facing normalized output schema, or ``None`` for opaque.

    Structured and receipt schemas are normalized for display/audit. Opaque
    capabilities return ``None`` (no synthetic ``summary`` fallback) so the
    reference picker offers no typed candidates.
    """
    raw = capability_output_schema(capability_key)
    if raw is None:
        return None
    defs = raw.get("$defs")
    normalized = _normalize_ui_schema(
        raw, defs if isinstance(defs, dict) else {}
    )
    if not isinstance(normalized, dict) or normalized.get("x-unsupported"):
        return None
    return normalized


def strict_completeness_errors(
    capability_key: str, output: dict[str, Any]
) -> list[str]:
    """Return P2 fetch-completeness violations for strict nodes.

    Calendar/Reminders merge Apple + recurring sources. A partial result stays
    observable in lenient mode, but a strict node must fail instead of letting
    a partial list flow into downstream decisions or side effects.
    """
    if capability_key == "calendar_read":
        errors: list[str] = []
        if output.get("apple_status") != FETCH_STATUS_OK:
            errors.append(
                "calendar_read の Apple 取得が不完全です "
                f"(apple_status={output.get('apple_status')!r})"
            )
        if output.get("recurring_status") != FETCH_STATUS_OK:
            errors.append(
                "calendar_read の recurring 取得が不完全です "
                f"(recurring_status={output.get('recurring_status')!r})"
            )
        return errors
    if capability_key == "reminders_read":
        errors = []
        if output.get("apple_status") != FETCH_STATUS_OK:
            errors.append(
                "reminders_read の Apple 取得が不完全です "
                f"(apple_status={output.get('apple_status')!r})"
            )
        if output.get("recurring_status") != FETCH_STATUS_OK:
            errors.append(
                "reminders_read の recurring 取得が不完全です "
                f"(recurring_status={output.get('recurring_status')!r})"
            )
        return errors
    if capability_key == "summary_search":
        errors = []
        if output.get("truncated") is True:
            errors.append(
                "summary_search の結果が予算制限により切詰められています (truncated=true)"
            )
        entries = output.get("entries") or []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("entry_truncated") is True:
                    errors.append(
                        f"summary_search のエントリー ({entry.get('period_key')}) の本文が切詰められています"
                    )
                    break
        return errors
    return []


def _compact_field(name: str, spec: dict[str, Any], required: set[str]) -> str:
    parts = [name]
    raw_type = spec.get("type")
    items = spec.get("items")
    any_of = spec.get("anyOf")
    if raw_type:
        if raw_type == "array" and isinstance(items, dict):
            parts.append(f"array<{items.get('type', 'string')}>")
        else:
            parts.append(str(raw_type))
    elif isinstance(any_of, list):
        non_null = [t for t in any_of if t.get("type") != "null"]
        if len(non_null) == 1 and non_null[0].get("type"):
            inner = non_null[0]
            if inner.get("type") == "array":
                sub = inner.get("items", {})
                parts.append(f"array<{sub.get('type', 'string')}>|null")
            else:
                parts.append(f"{inner.get('type')}|null")
        else:
            parts.append("object")
    if name in required:
        parts.append("required")
    else:
        default = spec.get("default")
        parts.append(f"optional(default={default!r})")
    details: list[str] = []
    if spec.get("description"):
        details.append(str(spec["description"]))
    enum = spec.get("enum")
    if not enum and isinstance(any_of, list):
        for branch in any_of:
            if isinstance(branch, dict) and branch.get("enum"):
                enum = branch["enum"]
                break
    if enum:
        details.append(f"enum={list(enum)}")
    for key in (
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
    ):
        if spec.get(key) is not None:
            details.append(f"{key}={spec[key]}")
    if details:
        parts.append("— " + " ".join(details))
    return " ".join(parts)


def compact_schema_text(capability_key: str) -> str | None:
    """Compact Planner-facing schema text derived from the single source."""
    schema = resolve_json_schema(capability_key)
    if not schema:
        return None
    required = set(schema.get("required") or [])
    properties = schema.get("properties") or {}
    lines = []
    for name, spec in properties.items():
        if isinstance(spec, dict):
            lines.append("  - " + _compact_field(name, spec, required))
    forbid = schema.get("additionalProperties") is False
    header = (
        f"{capability_key} inputs ({'required: ' + ', '.join(sorted(required)) if required else 'no required fields'}; unknown keys forbidden)"
        if forbid
        else (f"{capability_key} inputs")
    )
    return header + "\n" + "\n".join(lines) if lines else header


def validate_capability_inputs(capability_key: str, inputs: Any) -> dict[str, Any]:
    """Validate raw inputs against the single-source model.

    Returns the validated (and default-filled) dict. Raises ``ValueError``
    when the capability is unknown, the schema is unresolvable, or the
    inputs violate the model (missing required, unknown keys with
    ``extra="forbid"``, enum/range/pattern violations, ...).
    """
    model = resolve_input_model(capability_key)
    if model is None:
        raise ValueError(
            f"Capability '{capability_key}' has no resolvable input schema."
        )
    if not isinstance(inputs, dict):
        raise ValueError(f"Capability '{capability_key}' inputs must be an object.")
    try:
        validated = model.model_validate(inputs)
    except Exception as exc:
        raise ValueError(
            f"Capability '{capability_key}' inputs invalid: {exc}"
        ) from exc
    # exclude_none keeps the legacy wire shape (callers omit unset optionals;
    # tool functions apply their own defaults) while still injecting
    # non-None defaults such as limit=5.
    dumped = validated.model_dump(mode="json", exclude_none=True)
    if not isinstance(dumped, dict):
        raise ValueError(
            f"Capability '{capability_key}' inputs did not validate to an object."
        )
    return dumped


def validate_capability_target(capability_key: str, target: Any) -> dict[str, Any]:
    """Validate a delegate target (agent/project). No-op for registry tools."""
    model = resolve_target_model(capability_key)
    if model is None:
        if not isinstance(target, dict):
            raise ValueError("Step target must be an object.")
        return dict(target)
    if not isinstance(target, dict):
        raise ValueError("Step target must be an object.")
    try:
        validated = model.model_validate(target)
    except Exception as exc:
        raise ValueError(
            f"Capability '{capability_key}' target invalid: {exc}"
        ) from exc
    dumped = validated.model_dump(mode="json", exclude_none=True)
    if not isinstance(dumped, dict):
        raise ValueError("Step target did not validate to an object.")
    return dumped


def clear_schema_cache() -> None:
    """Test hook (no-op): definitions are always looked up fresh."""
    return None
