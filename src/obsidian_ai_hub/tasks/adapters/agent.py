"""Adapter delegating a step to a one-shot child run of a registered AI Agent.

The agent configuration is re-read at execution time; the Task never
snapshots it. The existing agent worker executes the queued run; this
adapter only queues, watches, and summarizes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.adapters.child_runs import wait_for_child_run
from obsidian_ai_hub.tasks.adapters.deviation import (
    DEVIATION_INSTRUCTION,
    build_revised_plan,
    parse_deviation_report,
    tail_text,
)
from obsidian_ai_hub.tasks.execution import (
    DeviationReported,
    StepResult,
    TaskCancelled,
)

logger = logging.getLogger(__name__)


class AgentAdapter:
    """Queue and watch a child agent run for one saved plan step."""

    def __init__(
        self, poll_interval: float = 2.0, timeout_secs: float = 1800.0
    ) -> None:
        self.poll_interval = poll_interval
        self.timeout_secs = timeout_secs

    def execute_step(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
    ) -> StepResult:
        from obsidian_ai_hub.agents import store as agent_store
        from obsidian_ai_hub.runs.instance import get_instance_id

        task_id = str(task["task_id"])
        target = step.get("target")
        if not isinstance(target, dict):
            raise ValueError(f"Step {step_index} target must be an object.")
        agent_id = target.get("agent_id")
        agent = agent_store.get_agent(str(agent_id)) if agent_id else None
        if agent is None:
            raise ValueError(
                f"Step {step_index} targets unregistered agent '{agent_id}'."
            )
        content = self._build_content(task, plan, step_index, step)
        session = agent_store.create_session(
            str(agent_id), title=f"Task {task_id} step {step_index}"
        )
        _, run = agent_store.start_queued_run(
            session["session_id"],
            content,
            created_instance_id=get_instance_id(),
        )
        run_id = str(run["run_id"])
        task_store.set_active_child(task_id, "agent", run_id)
        task_store.append_task_event(
            task_id,
            "child_run_started",
            {
                "step_index": step_index,
                "child_kind": "agent",
                "child_run_id": run_id,
                "agent_id": str(agent_id),
            },
        )
        final = wait_for_child_run(
            task_id,
            lambda: agent_store.get_run(run_id),
            lambda: agent_store.request_cancel_run(run_id),
            agent_store.AGENT_TERMINAL_STATUSES,
            self.poll_interval,
            self.timeout_secs,
        )
        status = str(final.get("status"))
        if status == "succeeded":
            text = self._final_text(agent_store, final, run_id)
            report = parse_deviation_report(text)
            if report is not None:
                raise DeviationReported(
                    build_revised_plan(plan.get("plan", {}), report),
                    report["reason"],
                )
            return StepResult(
                step_index=step_index,
                capability_key=str(step.get("capability_key")),
                summary=tail_text(text),
                child_kind="agent",
                child_run_id=run_id,
            )
        if status == "cancelled":
            raise TaskCancelled(f"Child agent run '{run_id}' was cancelled.")
        raise ValueError(
            f"Child agent run '{run_id}' ended with status '{status}': "
            f"{final.get('error_message') or 'no error message'}"
        )

    def _build_content(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
    ) -> str:
        plan_inner = plan.get("plan", {})
        return (
            f"TaskのPlan Step {step_index} を実行してください。\n"
            f"目的: {plan_inner.get('purpose', '')}\n"
            f"作業: {step.get('title', '')}\n"
            f"入力: {json.dumps(step.get('inputs', {}), ensure_ascii=False)}\n"
            f"想定副作用: {step.get('side_effects', '')}\n"
            f"完了条件: {plan_inner.get('completion_criteria', '')}\n\n"
            f"{DEVIATION_INSTRUCTION}"
        )

    def _final_text(self, agent_store: Any, final: dict[str, Any], run_id: str) -> str:
        message_id = final.get("assistant_message_id")
        if not message_id:
            raise ValueError(f"Child agent run '{run_id}' has no final message.")
        message = agent_store.get_message(str(message_id))
        if message is None:
            raise ValueError(f"Child agent run '{run_id}' final message missing.")
        return str(message.get("content") or "")
