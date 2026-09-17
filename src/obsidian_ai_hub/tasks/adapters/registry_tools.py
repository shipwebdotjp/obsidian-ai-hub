"""Adapter for registry-derived Task capabilities and ``memory_propose``.

Only capability keys from the registry-derived catalog
(``tasks/capabilities.py``) resolve; anything outside it (``ask_user``,
``agent_delegate``) is refused. Calendar/reminder create-proposal
capabilities resolve here and execute via the existing Registry tool route
(``tool.invoke``), which registers the existing proposal HITL run; the
adapter never bypasses that tool boundary. Steps run with their saved
inputs; inputs are never rebuilt here. Every call is validated against the
single-source Pydantic model (``tasks/capability_schemas.py``) immediately
before ``tool.invoke``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
from obsidian_ai_hub.tasks.execution import StepResult

logger = logging.getLogger(__name__)

READ_ONLY_KINDS = frozenset({"registry_tool"})
CONTEXT_KINDS = frozenset({"memory"})

# Registry tools that need the synthetic Task context (no agent run exists).
# ``memory_propose`` is context-bound by adapter kind; research proposal is a
# registry tool but must receive the Task ID so candidate registration is
# idempotent per Task (``task:<task_id>``), not per theme name.
# ``register_one_shot_job`` records the Task-derived IDs as its source so the
# registration origin is never spoofable via step inputs.
TASK_CONTEXT_TOOL_IDS = frozenset({"research_theme_propose", "register_one_shot_job"})


def _task_context(task: dict[str, Any]) -> dict[str, Any]:
    """Synthetic trusted context for context-bound Task capabilities.

    ``task_id`` is the primary idempotency key for research proposals; the
    agent/run/session fields keep memory proposal behavior unchanged.
    """
    task_id = str(task["task_id"])
    return {
        "task_id": task_id,
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
        definition = {d.key: d for d in get_capability_definitions()}.get(
            str(capability_key)
        )
        if definition is None or definition.adapter_kind not in (
            READ_ONLY_KINDS | CONTEXT_KINDS
        ):
            raise ValueError(f"Capability '{capability_key}' is not a Task capability.")
        tool_id = definition.registry_tool_id
        meta = TOOL_DEFINITIONS.get(str(tool_id))
        if meta is None:
            raise ValueError(f"Registry tool '{tool_id}' is not registered.")
        inputs = step.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError(
                f"Step {step_index} inputs must be an object, got {type(inputs).__name__}."
            )
        from obsidian_ai_hub.tasks.capability_schemas import (
            validate_capability_inputs,
        )

        try:
            inputs = validate_capability_inputs(str(capability_key), inputs)
        except ValueError as exc:
            raise ValueError(f"Step {step_index} {exc}") from exc
        needs_context = (
            definition.adapter_kind in CONTEXT_KINDS
            or str(tool_id) in TASK_CONTEXT_TOOL_IDS
        )
        if needs_context:
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
        # No uniform head cut here: the Runtime Orchestrator applies the
        # capability-specific detail window and derives the history gist
        # (``tasks/observation.py``).
        return StepResult(
            step_index=step_index,
            capability_key=str(capability_key),
            summary=result_str,
        )
