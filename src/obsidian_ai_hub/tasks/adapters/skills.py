"""Adapter for the Agent Skills tool bundle (``skills`` capability).

The ``skills`` registry entry is a multi-tool bundle (``load_skill``,
``read_skill_resource``, ``run_skill_script``), not a single ``BaseTool``.
The saved step inputs select the skill tool by name; the remaining inputs
are validated by that tool's own ``args_schema`` at invoke time.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from obsidian_ai_hub.tasks.execution import StepResult

logger = logging.getLogger(__name__)

SUMMARY_LIMIT = 800


class SkillsAdapter:
    """Execute a saved step against one tool of the skills bundle."""

    def execute_step(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
    ) -> StepResult:
        from obsidian_ai_hub.agents.registry import TOOL_DEFINITIONS
        from obsidian_ai_hub.tasks.capability_schemas import (
            validate_capability_inputs,
        )
        from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

        capability_key = str(step.get("capability_key"))
        definition = {d.key: d for d in get_capability_definitions()}.get(
            capability_key
        )
        if definition is None or definition.adapter_kind != "skills":
            raise ValueError(
                f"Capability '{capability_key}' is not a skills capability."
            )
        meta = TOOL_DEFINITIONS.get(str(definition.registry_tool_id))
        if meta is None:
            raise ValueError("Registry tool 'skills' is not registered.")
        inputs = step.get("inputs")
        if not isinstance(inputs, dict):
            raise ValueError(
                f"Step {step_index} inputs must be an object, got {type(inputs).__name__}."
            )
        try:
            inputs = validate_capability_inputs(capability_key, inputs)
        except ValueError as exc:
            raise ValueError(f"Step {step_index} {exc}") from exc
        skill_name = str(inputs.get("skill") or "")
        factory = meta.get("get_tools")
        if not callable(factory):
            raise ValueError("Registry tool 'skills' has no tool factory.")
        tools = factory()
        by_name = {getattr(t, "name", ""): t for t in tools}
        tool = by_name.get(skill_name)
        if tool is None:
            raise ValueError(
                f"Step {step_index} selects unknown skill tool '{skill_name}'. "
                f"Available: {sorted(by_name)}."
            )
        args = {k: v for k, v in inputs.items() if k != "skill"}
        try:
            result = tool.invoke(args)
            result_str = (
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )
        except Exception as tool_exc:
            logger.exception(
                "Error executing skill tool '%s' for task %s",
                skill_name,
                task["task_id"],
            )
            raise ValueError(
                f"Skill tool '{skill_name}' failed: {tool_exc}"
            ) from tool_exc
        return StepResult(
            step_index=step_index,
            capability_key=capability_key,
            summary=result_str[:SUMMARY_LIMIT],
        )
