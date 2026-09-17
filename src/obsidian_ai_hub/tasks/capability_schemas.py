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
    for key in ("minimum", "maximum", "minLength", "maxLength", "pattern"):
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
