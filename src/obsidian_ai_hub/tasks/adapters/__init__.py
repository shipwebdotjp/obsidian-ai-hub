"""Composite StepExecutor dispatching saved steps by adapter kind."""

from __future__ import annotations

from typing import Any, Optional

from obsidian_ai_hub.tasks.adapters.agent import AgentAdapter
from obsidian_ai_hub.tasks.adapters.coding import CodingAdapter
from obsidian_ai_hub.tasks.adapters.registry_tools import RegistryToolExecutor
from obsidian_ai_hub.tasks.adapters.research import ResearchAdapter
from obsidian_ai_hub.tasks.adapters.skills import SkillsAdapter
from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
from obsidian_ai_hub.tasks.execution import StepExecutor, StepResult


def _definitions_by_key() -> dict[str, Any]:
    # Looked up fresh on every dispatch: the catalog is registry-derived and
    # plugin reloads must be picked up.
    return {d.key: d for d in get_capability_definitions()}


class CompositeExecutor:
    """Dispatch steps to the adapter matching the capability's adapter kind."""

    def __init__(self, poll_interval: float = 2.0) -> None:
        self._adapters = {
            "registry_tool": RegistryToolExecutor(),
            "memory": RegistryToolExecutor(),
            "skills": SkillsAdapter(),
            "agent": AgentAdapter(poll_interval=poll_interval),
            "coding": CodingAdapter(poll_interval=poll_interval),
            "research": ResearchAdapter(poll_interval=poll_interval),
        }

    def execute_step(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
    ) -> StepResult:
        capability_key = str(step.get("capability_key"))
        definition = _definitions_by_key().get(capability_key)
        if definition is None:
            raise ValueError(f"Capability '{capability_key}' is not a Task capability.")
        adapter: Optional[StepExecutor] = self._adapters.get(definition.adapter_kind)
        if adapter is None:
            raise ValueError(f"No adapter connected for capability '{capability_key}'.")
        return adapter.execute_step(task, plan, step_index, step)


def get_default_executor(poll_interval: float = 2.0) -> CompositeExecutor:
    """Build the production executor used by the Task worker."""
    return CompositeExecutor(poll_interval=poll_interval)
