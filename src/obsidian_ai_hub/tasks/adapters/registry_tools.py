"""Adapter for fixed-allowlist Registry tools and ``memory_propose``.

Only capability keys defined in ``tasks/capabilities.py`` resolve; anything
else (``run_shell``, Skills, plugins, write proposals) is refused. Steps run
with their saved inputs; inputs are never rebuilt here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from obsidian_ai_hub.tasks.capabilities import CAPABILITY_DEFINITIONS
from obsidian_ai_hub.tasks.execution import StepResult

logger = logging.getLogger(__name__)

SUMMARY_LIMIT = 800

_DEFINITIONS_BY_KEY = {d.key: d for d in CAPABILITY_DEFINITIONS}

READ_ONLY_KINDS = frozenset({"registry_tool"})
CONTEXT_KINDS = frozenset({"memory"})


def _task_context(task: dict[str, Any]) -> dict[str, Any]:
    """Synthetic trusted context for ``memory_propose`` (no agent run exists)."""
    task_id = str(task["task_id"])
    return {
        "agent_id": f"task-agent:{task_id}",
        "session_id": task_id,
        "run_id": task_id,
        "user_message_id": f"{task_id}-prompt",
        "user_content": str(task.get("prompt_text") or ""),
    }


class RegistryToolExecutor:
    """Execute saved plan steps backed by existing Registry tools."""

    def execute_step(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
    ) -> StepResult:
        from obsidian_ai_hub.agents.registry import TOOL_DEFINITIONS

        capability_key = step.get("capability_key")
        definition = _DEFINITIONS_BY_KEY.get(str(capability_key))
        if definition is None or definition.adapter_kind not in (
            READ_ONLY_KINDS | CONTEXT_KINDS
        ):
            raise ValueError(
                f"Capability '{capability_key}' is not an allowlisted Registry tool."
            )
        tool_id = definition.registry_tool_id
        meta = TOOL_DEFINITIONS.get(str(tool_id))
        if meta is None:
            raise ValueError(f"Registry tool '{tool_id}' is not registered.")
        inputs = step.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError(
                f"Step {step_index} inputs must be an object, got {type(inputs).__name__}."
            )
        if definition.adapter_kind in CONTEXT_KINDS:
            factory = meta.get("get_tool_with_context")
            tool = factory(_task_context(task)) if factory else meta["get_tool"]()
        else:
            tool = meta["get_tool"]()
        try:
            result = tool.invoke(dict(inputs))
            result_str = (
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )
        except Exception as tool_exc:
            logger.exception(
                "Error executing Registry tool '%s' for task %s",
                tool_id,
                task["task_id"],
            )
            raise ValueError(
                f"Registry tool '{tool_id}' failed: {tool_exc}"
            ) from tool_exc
        return StepResult(
            step_index=step_index,
            capability_key=str(capability_key),
            summary=result_str[:SUMMARY_LIMIT],
        )
