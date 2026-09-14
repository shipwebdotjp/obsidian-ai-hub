"""Task Agent capability catalog, derived from the Agent Registry.

The Agent Registry (``agents.registry.TOOL_DEFINITIONS``) is the source of
truth: this module derives one Capability per registry tool at call time, so
adding a builtin tool (or a ``custom:*`` plugin file) exposes it to the Task
Agent without touching this module. The ``task_agent_capabilities`` table is
the source of truth only for ``enabled`` and ``approval_policy``; seeds and
the startup sync never overwrite those two columns.

Code-fixed safety boundary (see ``docs/task-agent/adr/``): the only tools
that never become capabilities are ``EXCLUDED_TOOL_IDS`` — ``ask_user``
(conversational only) and ``agent_delegate`` (covered by
``specialist_agent`` and requiring a parent agent run context).
Calendar/reminder create-proposal tools are capabilities: they never write
directly and only register an existing proposal HITL run, so the human
approval happens via that HITL. They default to ``auto`` so an auto-only
plan skips plan confirmation and the Runtime Worker registers the HITL via
the existing tool route. Everything else defaults to ``plan_required``
except the read/search tools and proposal tools in ``AUTO_POLICY_TOOL_IDS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class CapabilityDefinition:
    """A single code-defined capability."""

    key: str
    adapter_kind: str  # "registry_tool" | "memory" | "skills" | "agent" | "coding" | "research"
    label: str
    description: str
    default_approval_policy: str  # "auto" | "plan_required"
    registry_tool_id: str | None = None


EXCLUDED_TOOL_IDS: frozenset[str] = frozenset(
    {
        "ask_user",
        "agent_delegate",
    }
)

MEMORY_KIND_TOOL_IDS: frozenset[str] = frozenset({"memory_propose"})

SKILLS_TOOL_IDS: frozenset[str] = frozenset({"skills"})

AUTO_POLICY_TOOL_IDS: frozenset[str] = frozenset(
    {
        "web_search",
        "web_extract",
        "vault_search",
        "vault_read_file",
        "calendar_read",
        "reminders_read",
        "memory_search",
        "people_search",
        "people_get",
        "project_search",
        "project_get",
        # Proposal tools only register an existing HITL approval run and never
        # write directly, so auto execution still requires human approval via
        # that HITL. Defaulting to auto avoids a redundant plan confirmation.
        "calendar_create_proposal",
        "reminder_create_proposal",
    }
)

SPECIAL_DEFINITIONS: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        key="specialist_agent",
        adapter_kind="agent",
        label="専門Agent委譲",
        description="登録済みAI Agentを指定して一回限りの子runを作る。",
        default_approval_policy="plan_required",
    ),
    CapabilityDefinition(
        key="coding_cli",
        adapter_kind="coding",
        label="Coding CLI実行",
        description="登録済みProjectのGit rootで新規Coding session/runを作る。",
        default_approval_policy="plan_required",
    ),
    CapabilityDefinition(
        key="research_agent",
        adapter_kind="research",
        label="リサーチ実行",
        description="既存のリサーチ基盤でjobを作り、レポートを生成してVaultへ保存する。",
        default_approval_policy="plan_required",
    ),
)


def get_capability_definitions(
    tool_definitions: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> tuple[CapabilityDefinition, ...]:
    """Build the capability catalog from the Agent Registry.

    ``tool_definitions`` is injectable for tests; when omitted the live
    ``agents.registry.TOOL_DEFINITIONS`` is read fresh on every call so
    plugin reloads are picked up. Import is local to avoid a hard
    ``database -> capabilities -> agents.registry`` cycle.
    """
    if tool_definitions is None:
        from obsidian_ai_hub.agents import registry as agent_registry

        tool_definitions = agent_registry.TOOL_DEFINITIONS
    derived: list[CapabilityDefinition] = []
    for tool_id, meta in tool_definitions.items():
        if tool_id in EXCLUDED_TOOL_IDS:
            continue
        if tool_id in MEMORY_KIND_TOOL_IDS:
            adapter_kind = "memory"
        elif tool_id in SKILLS_TOOL_IDS:
            adapter_kind = "skills"
        else:
            adapter_kind = "registry_tool"
        policy = "auto" if tool_id in AUTO_POLICY_TOOL_IDS else "plan_required"
        label = meta.get("name") if isinstance(meta, Mapping) else None
        description = meta.get("description") if isinstance(meta, Mapping) else None
        derived.append(
            CapabilityDefinition(
                key=str(tool_id),
                adapter_kind=adapter_kind,
                label=str(label) if label else str(tool_id),
                description=str(description) if description else "",
                default_approval_policy=policy,
                registry_tool_id=str(tool_id),
            )
        )
    derived.extend(SPECIAL_DEFINITIONS)
    derived.sort(key=lambda d: d.key)
    return tuple(derived)


def get_capability_keys(
    tool_definitions: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> frozenset[str]:
    """Return the current capability keys (registry-derived)."""
    return frozenset(d.key for d in get_capability_definitions(tool_definitions))
