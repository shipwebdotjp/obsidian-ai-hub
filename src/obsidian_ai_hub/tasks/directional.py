"""Directional Plan models: approval scope without frozen tool inputs.

A Directional Plan approves *direction* (purpose, strategy, allowed
capabilities with per-capability intent, constraints, completion criteria)
while leaving each tool call's detailed inputs to the Runtime Orchestrator.

Legacy static plans (``{"purpose", "steps": [...]}``) keep executing through
the legacy step runner; this module only describes the new shape and the
compatibility helpers.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_MAX_ACTIONS = 10
MAX_ACTIONS_HARD_LIMIT = 30


class ProjectResolution(BaseModel):
    """Resolved main-target project of a v3 Directional Plan.

    A task targets either a single main project (``kind="project"``) or is a
    general task with no specific project (``kind="general"``). ``confidence``
    is a 0..1 *decision score* for the low-confidence HITL branch, not a
    statistical probability. Human selections (``source="user"``) carry no
    confidence. ``display_name`` is a snapshot shown in the plan detail even
    if the project is later renamed or deleted.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["project", "general"] = Field(
        description="主対象Projectか一般Taskか。"
    )
    project_id: Optional[int] = Field(
        default=None, description="主対象Project ID（general時はなし）。"
    )
    display_name: str = Field(
        default="", description="選定時点のProject表示名スナップショット。"
    )
    confidence: Optional[float] = Field(
        default=None,
        description="判断スコア 0..1。人間指定では付けない。",
    )
    rationale: str = Field(default="", description="選定の短い根拠。")
    source: Literal["inferred", "user"] = Field(
        default="inferred", description="選定元（Planner推定か人間指定）。"
    )

    @model_validator(mode="after")
    def _check_kind_fields(self) -> "ProjectResolution":
        if self.kind == "project":
            if self.project_id is None or int(self.project_id) <= 0:
                raise ValueError("project kind requires a positive project_id")
        elif self.project_id is not None:
            raise ValueError("general kind must not carry a project_id")
        if self.confidence is not None and not (
            0.0 <= float(self.confidence) <= 1.0
        ):
            raise ValueError("confidence must be between 0 and 1")
        return self


class AgentConfigSnapshot(BaseModel):
    """Approval-time fingerprint of one delegate Agent's execution config.

    Only a SHA-256 of the system prompt is stored (never the prompt text),
    plus the fields that change child-run behavior. Compared at execution
    start; a mismatch routes the task to ``waiting_reapproval`` instead of
    silently running under a new config.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(description="登録済みAgent ID。")
    name: str = Field(default="", description="承認時点のAgent表示名。")
    system_prompt_sha256: str = Field(
        default="", description="承認時点のsystem promptのSHA-256。"
    )
    tool_ids: list[str] = Field(
        default_factory=list, description="承認時点の有効tool ID。"
    )
    provider: Optional[str] = Field(
        default=None, description="承認時点のprovider（未設定はNone）。"
    )
    model: Optional[str] = Field(
        default=None, description="承認時点のmodel（未設定はNone）。"
    )
    delegate_agent_ids: list[str] = Field(
        default_factory=list, description="承認時点の委譲先Agent ID。"
    )
    updated_at: str = Field(default="", description="承認時点のAgent更新時刻。")


def fingerprint_agent_config(agent: dict[str, Any]) -> AgentConfigSnapshot:
    """Build a snapshot from a live agent record. Never raises on shapes."""
    agent_id = str(agent.get("agent_id") or "")
    prompt = str(agent.get("system_prompt") or "")
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else ""
    tool_ids = sorted(str(t) for t in (agent.get("tool_ids") or []) if t)
    delegates = sorted(str(t) for t in (agent.get("delegate_agent_ids") or []) if t)
    provider = agent.get("provider")
    model = agent.get("model")
    return AgentConfigSnapshot(
        agent_id=agent_id,
        name=str(agent.get("name") or ""),
        system_prompt_sha256=digest,
        tool_ids=tool_ids,
        provider=str(provider) if provider else None,
        model=str(model) if model else None,
        delegate_agent_ids=delegates,
        updated_at=str(agent.get("updated_at") or ""),
    )


def find_agent_config_drift(
    saved: dict[str, Any], current: dict[str, AgentConfigSnapshot]
) -> list[str]:
    """Return sorted agent_ids whose live config differs from the snapshot.

    ``saved`` is the plan's ``agent_config_snapshot`` mapping. Missing live
    records (deleted agents) count as drift. Empty ``saved`` means "no
    baseline" (pre-snapshot plans) and never drifts, preserving old behavior.
    """
    if not saved:
        return []
    drifted: list[str] = []
    for agent_id, entry in saved.items():
        live = current.get(str(agent_id))
        if live is None:
            drifted.append(str(agent_id))
            continue
        try:
            baseline = AgentConfigSnapshot.model_validate(entry)
        except Exception:
            drifted.append(str(agent_id))
            continue
        if baseline != live:
            drifted.append(str(agent_id))
    return sorted(drifted)


class PlanDirective(BaseModel):
    """One approved capability plus its rough intent within the plan."""

    model_config = ConfigDict(extra="forbid")

    capability_key: str = Field(description="承認済みCapabilityキー。")
    intent: str = Field(
        default="",
        description="そのCapabilityを何のために使うかの大まかな意図。詳細引数は含めない。",
    )


class DirectionalPlan(BaseModel):
    """Validated Directional Plan (plan_version 2 or 3).

    Version 3 plans always carry a ``project_resolution``: the task's
    main-target project or an explicit "general" classification. Version 2
    plans (pre-resolution) stay readable and executable.
    """

    model_config = ConfigDict(extra="forbid")

    plan_version: Literal[2, 3] = Field(default=2)
    purpose: str = Field(description="タスクの目的。承認対象の中心。")
    strategy: str = Field(
        default="",
        description="実行方針の概要。詳細な手順書ではない。",
    )
    capabilities: list[PlanDirective] = Field(
        description="承認されたCapabilityの集合。各Capabilityの大まかな意図付き。"
    )
    # Approval-time snapshots bounding delegate targets. The orchestrator
    # enforces membership per action; scope-outside targets go to reapproval.
    # Empty means "no delegate target approved".
    allowed_agent_ids: list[str] = Field(
        default_factory=list,
        description="specialist_agentが委譲可能な登録済みAgent IDの承認範囲。空なら委譲不可。",
    )
    allowed_project_ids: list[int] = Field(
        default_factory=list,
        description="coding_cliが実行可能な登録済みProject IDの承認範囲。空なら実行不可。",
    )
    # Approval-time fingerprint of delegate Agent configs in the allowed
    # scope. Empty means "no baseline" (pre-snapshot plans, or plans without
    # specialist_agent) and disables drift detection. Keyed by agent_id.
    agent_config_snapshot: dict[str, AgentConfigSnapshot] = Field(
        default_factory=dict,
        description="承認時点の委譲先Agent設定の指紋。空なら差分検出しない。",
    )
    constraints: str = Field(
        default="",
        description="主要な制約（触れてはならない範囲、守るべき条件など）。",
    )
    completion_criteria: str = Field(description="完了条件。")
    max_actions: int = Field(
        default=DEFAULT_MAX_ACTIONS,
        ge=1,
        le=MAX_ACTIONS_HARD_LIMIT,
        description="Runtime Orchestratorの最大Action数。無限ループ防止の必須上限。",
    )
    # Version 3 only: the task's main-target project (or "general").
    # Mandatory for plan_version 3; absent (or None) for version 2.
    project_resolution: Optional[ProjectResolution] = Field(
        default=None,
        description="主対象Projectの解決結果。v3では必須、v2ではなし。",
    )

    @model_validator(mode="after")
    def _check_version_resolution(self) -> "DirectionalPlan":
        if self.plan_version == 3 and self.project_resolution is None:
            raise ValueError("plan_version 3 requires project_resolution")
        if self.plan_version == 2 and self.project_resolution is not None:
            raise ValueError("plan_version 2 must not carry project_resolution")
        return self

    @field_validator("purpose", "completion_criteria")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("capabilities")
    @classmethod
    def _non_empty_capabilities(cls, value: list[PlanDirective]) -> list[PlanDirective]:
        if not value:
            raise ValueError("capabilities must not be empty")
        keys = [d.capability_key for d in value]
        if len(set(keys)) != len(keys):
            raise ValueError("capabilities must not contain duplicates")
        return value


def plan_format(plan_inner: Any) -> Literal["directional", "legacy", "unknown"]:
    """Classify a stored plan inner dict without raising."""
    if not isinstance(plan_inner, dict):
        return "unknown"
    if isinstance(plan_inner.get("capabilities"), list) and isinstance(
        plan_inner.get("purpose"), str
    ):
        # Directional plans always carry an explicit version marker; legacy
        # plans carry "steps".
        if plan_inner.get("plan_version") in (2, 3) or "steps" not in plan_inner:
            return "directional"
    if isinstance(plan_inner.get("steps"), list):
        return "legacy"
    return "unknown"


def parse_directional_plan(plan_inner: dict[str, Any]) -> DirectionalPlan:
    """Validate a stored directional plan inner dict. Raises ValueError."""
    try:
        return DirectionalPlan.model_validate(plan_inner)
    except Exception as exc:
        raise ValueError(f"Invalid directional plan: {exc}") from exc


def approval_scope(plan: DirectionalPlan) -> dict[str, Any]:
    """Return the approval boundary derived from a directional plan."""
    scope: dict[str, Any] = {
        "purpose": plan.purpose,
        "capability_keys": sorted(d.capability_key for d in plan.capabilities),
        "intents": {d.capability_key: d.intent for d in plan.capabilities},
        "constraints": plan.constraints,
        "completion_criteria": plan.completion_criteria,
        "max_actions": plan.max_actions,
        "allowed_agent_ids": list(plan.allowed_agent_ids or []),
        "allowed_project_ids": list(plan.allowed_project_ids or []),
    }
    if plan.project_resolution is not None:
        scope["project_resolution"] = plan.project_resolution.model_dump()
    return scope


def is_directional_plan(plan_inner: Any) -> bool:
    return plan_format(plan_inner) == "directional"


def legacy_steps(plan_inner: Any) -> Optional[list[dict[str, Any]]]:
    steps = plan_inner.get("steps") if isinstance(plan_inner, dict) else None
    return steps if isinstance(steps, list) else None
