"""Adapter delegating a step to a one-shot child run of a registered AI Agent.

The agent configuration is re-read at execution time; the Task never
snapshots it. The existing agent worker executes the queued run; this
adapter only queues, watches, and summarizes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.adapters.child_runs import (
    build_task_session_title,
    find_prior_child_session,
    wait_for_child_run,
)
from obsidian_ai_hub.tasks.adapters.deviation import (
    DEVIATION_INSTRUCTION,
    build_revised_plan,
    parse_deviation_report,
    tail_text,
)
from obsidian_ai_hub.tasks.execution import (
    CANCEL_CERTAINTY_CANCELLED,
    CancellationEvidence,
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

        from obsidian_ai_hub.tasks.capability_schemas import (
            validate_capability_inputs,
            validate_capability_target,
        )

        task_id = str(task["task_id"])
        try:
            target = validate_capability_target(
                "specialist_agent", step.get("target")
            )
            step_inputs = validate_capability_inputs(
                "specialist_agent", step.get("inputs", {})
            )
        except ValueError as exc:
            raise ValueError(f"Step {step_index} {exc}") from exc
        step = dict(step, target=target, inputs=step_inputs)
        agent_id = target.get("agent_id")
        agent = agent_store.get_agent(str(agent_id)) if agent_id else None
        if agent is None:
            raise ValueError(
                f"Step {step_index} targets unregistered agent '{agent_id}'."
            )
        content = self._build_content(task, plan, step_index, step)
        session_id, session_reused = self._resolve_session(
            task_id, str(agent_id), step_inputs, step_index, step, plan
        )
        _, run = agent_store.start_queued_run(
            session_id,
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
                "session_id": session_id,
                "session_reused": session_reused,
                "agent_id": str(agent_id),
            },
        )
        final = wait_for_child_run(
            task_id,
            lambda: agent_store.get_run(run_id),
            lambda: self._request_child_cancel(task_id, run_id),
            agent_store.AGENT_TERMINAL_STATUSES,
            self.poll_interval,
            self.timeout_secs,
            waiting_statuses=frozenset({"waiting_user"}),
            on_first_wait=lambda waiting_run: self._notify_hitl_wait(
                task_id, step_index, run_id, str(agent_id), waiting_run
            ),
            child_kind="agent",
            child_run_id=run_id,
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
            raise TaskCancelled(
                f"Child agent run '{run_id}' was cancelled.",
                evidence=CancellationEvidence(
                    child_kind="agent",
                    child_run_id=run_id,
                    result_certainty=CANCEL_CERTAINTY_CANCELLED,
                ),
            )
        raise ValueError(
            f"Child agent run '{run_id}' ended with status '{status}': "
            f"{final.get('error_message') or 'no error message'}"
        )

    def _resolve_session(
        self,
        task_id: str,
        agent_id: str,
        step_inputs: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
        plan: dict[str, Any],
    ) -> tuple[str, bool]:
        """Return ``(session_id, reused)`` for this step.

        Additional agent requests inside the same task reuse the existing
        session for the same agent so follow-up runs keep the prior
        context. A new session is created only when the step explicitly
        asks for one (``fresh_session``), when no prior session exists, or
        when the prior session is gone, retargeted, or busy.
        """
        from obsidian_ai_hub.agents import store as agent_store

        if not step_inputs.get("fresh_session"):
            prior = find_prior_child_session(
                task_id,
                "agent",
                lambda payload: str(payload.get("agent_id") or "") == agent_id,
                lambda run_id: self._session_of_run(agent_store, run_id),
            )
            if prior is not None:
                session = agent_store.get_session(prior)
                if session is not None and str(
                    session.get("agent_id") or ""
                ) == agent_id:
                    if not self._session_has_active_run(agent_store, prior):
                        logger.info(
                            "Task %s reuses agent session %s (step %s)",
                            task_id,
                            prior,
                            step_index,
                        )
                        return prior, True
        session = agent_store.create_session(
            agent_id,
            title=build_task_session_title(task_id, step_index, step, plan),
        )
        return str(session["session_id"]), False

    @staticmethod
    def _session_of_run(agent_store: Any, run_id: str) -> Optional[str]:
        run = agent_store.get_run(run_id)
        if not run:
            return None
        return str(run.get("session_id") or "") or None

    @staticmethod
    def _session_has_active_run(agent_store: Any, session_id: str) -> bool:
        """Return True when the session still has a non-terminal run."""
        from obsidian_ai_hub.agents.store import AGENT_NON_TERMINAL_STATUSES

        try:
            runs = agent_store.list_runs(session_id)
        except Exception:
            # Unknown state: let start_queued_run's active-run guard decide.
            return False
        return any(
            str(run.get("status")) in AGENT_NON_TERMINAL_STATUSES for run in runs
        )

    @staticmethod
    def _request_child_cancel(task_id: str, run_id: str) -> None:
        """Request child cancel, including a linked HITL wait if any.

        A run parked in ``waiting_user`` has no live worker thread, so the
        plain cancel request (``cancelling``) would never reach a terminal
        status on its own. Cancelling the linked HITL run syncs the agent
        run to ``cancelled`` (checkpoint domain/run_id), letting the wait
        loop raise ``TaskCancelled`` instead of timing out.
        """
        from obsidian_ai_hub.agents import store as agent_store

        agent_store.request_cancel_run(run_id)
        try:
            latest = agent_store.get_run(run_id)
        except Exception:
            latest = None
        hitl_run_id = (latest or {}).get("hitl_run_id")
        if not hitl_run_id:
            return
        try:
            from obsidian_ai_hub.hitl import service as hitl_service

            hitl_service.cancel_run(str(hitl_run_id))
        except Exception:
            logger.warning(
                "Task %s failed to cancel linked HITL run %s for child %s",
                task_id,
                hitl_run_id,
                run_id,
                exc_info=True,
            )

    @staticmethod
    def _notify_hitl_wait(
        task_id: str,
        step_index: int,
        run_id: str,
        agent_id: str,
        waiting_run: dict[str, Any],
    ) -> None:
        """Record the child's HITL wait as a task event (HITL link included).

        The Task detail UI renders ``hitl_question_asked`` events generically:
        the ``hitl_run_id`` becomes a link to the HITL run plus its answer
        card, so no dedicated frontend display is needed.
        """
        hitl_run_id = waiting_run.get("hitl_run_id")
        task_store.append_task_event(
            task_id,
            "hitl_question_asked",
            {
                "step_index": step_index,
                "child_kind": "agent",
                "child_run_id": run_id,
                "hitl_run_id": str(hitl_run_id) if hitl_run_id else None,
                "agent_id": agent_id,
            },
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
