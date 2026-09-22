"""Adapter delegating a step to a new Coding session/run in a Project Git root.

The existing coding worker executes the queued run under its repo lock and
cancel mechanism; this adapter only creates, watches, and summarizes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.adapters.child_runs import (
    build_task_session_title,
    find_prior_child_session,
    wait_for_child_run,
)
from obsidian_ai_hub.tasks.adapters.deviation import tail_text
from obsidian_ai_hub.tasks.execution import (
    CANCEL_CERTAINTY_CANCELLED,
    CancellationEvidence,
    StepResult,
    TaskCancelled,
)
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

CODING_BACKENDS = frozenset({"opencode"})


class CodingAdapter:
    """Queue and watch a child coding run for one saved plan step."""

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
        from obsidian_ai_hub.coding import store as coding_store
        from obsidian_ai_hub.coding.backend import validate_git_repo
        from obsidian_ai_hub.runs.instance import get_instance_id
        from obsidian_ai_hub.web.services.projects import get_project_detail

        from obsidian_ai_hub.tasks.capability_schemas import (
            validate_capability_inputs,
            validate_capability_target,
        )

        task_id = str(task["task_id"])
        try:
            target = validate_capability_target("coding_cli", step.get("target"))
            step_inputs = validate_capability_inputs(
                "coding_cli", step.get("inputs", {})
            )
        except ValueError as exc:
            raise ValueError(f"Step {step_index} {exc}") from exc
        step = dict(step, target=target, inputs=step_inputs)
        try:
            project_id = int(target.get("project_id"))
        except (TypeError, ValueError):
            raise ValueError(
                f"Step {step_index} targets invalid project "
                f"'{target.get('project_id')}'."
            )
        backend = str(target.get("backend") or config.CODING_DEFAULT_BACKEND)
        if backend not in CODING_BACKENDS:
            raise ValueError(f"Step {step_index} uses unknown backend '{backend}'.")
        project = get_project_detail(project_id)
        if project is None:
            raise ValueError(
                f"Step {step_index} targets unregistered project '{project_id}'."
            )
        repo_path = project.get("project_path")
        if not repo_path:
            raise ValueError(f"Project '{project_id}' has no project_path.")
        git_root = validate_git_repo(str(repo_path))
        content = self._build_content(task, plan, step_index, step)
        session_id, session_reused = self._resolve_session(
            task_id, project_id, backend, git_root, step_inputs, step_index, step, plan
        )
        _, run = coding_store.start_queued_run(
            session_id,
            content,
            created_instance_id=get_instance_id(),
        )
        run_id = str(run["run_id"])
        task_store.set_active_child(task_id, "coding", run_id)
        task_store.append_task_event(
            task_id,
            "child_run_started",
            {
                "step_index": step_index,
                "child_kind": "coding",
                "child_run_id": run_id,
                "session_id": session_id,
                "session_reused": session_reused,
                "project_id": project_id,
                "backend": backend,
            },
        )
        final = wait_for_child_run(
            task_id,
            lambda: coding_store.get_run(run_id),
            lambda: self._request_child_cancel(task_id, run_id),
            coding_store.CODING_TERMINAL_STATUSES,
            self.poll_interval,
            self.timeout_secs,
            waiting_statuses=frozenset({"waiting_user"}),
            on_first_wait=lambda waiting_run: self._notify_hitl_wait(
                task_id, step_index, run_id, project_id, backend, waiting_run
            ),
            child_kind="coding",
            child_run_id=run_id,
        )
        status = str(final.get("status"))
        if status == "completed":
            text = self._final_text(coding_store, session_id, run_id)
            return StepResult(
                step_index=step_index,
                capability_key=str(step.get("capability_key")),
                summary=tail_text(text),
                child_kind="coding",
                child_run_id=run_id,
            )
        if status == "cancelled":
            raise TaskCancelled(
                f"Child coding run '{run_id}' was cancelled.",
                evidence=CancellationEvidence(
                    child_kind="coding",
                    child_run_id=run_id,
                    result_certainty=CANCEL_CERTAINTY_CANCELLED,
                ),
            )
        raise ValueError(
            f"Child coding run '{run_id}' ended with status '{status}': "
            f"{final.get('error_message') or 'no error message'}"
        )

    def _resolve_session(
        self,
        task_id: str,
        project_id: int,
        backend: str,
        git_root: str,
        step_inputs: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
        plan: dict[str, Any],
    ) -> tuple[str, bool]:
        """Return ``(session_id, reused)`` for this step.

        Additional coding requests inside the same task reuse the existing
        session for the same project/backend so follow-up runs keep the
        prior context. A new session is created only when the step
        explicitly asks for one (``fresh_session``), when no prior session
        exists, or when the prior session is gone, retargeted, or busy.
        """
        from obsidian_ai_hub.coding import store as coding_store

        if not step_inputs.get("fresh_session"):
            prior = find_prior_child_session(
                task_id,
                "coding",
                lambda payload: self._same_coding_target(
                    payload, project_id, backend
                ),
                lambda run_id: self._session_of_run(coding_store, run_id),
            )
            if prior is not None:
                session = coding_store.get_session(prior)
                if (
                    session is not None
                    and int(session.get("project_id") or -1) == project_id
                    and str(session.get("backend") or "") == backend
                    and coding_store.get_active_run_for_session(prior) is None
                ):
                    logger.info(
                        "Task %s reuses coding session %s (step %s)",
                        task_id,
                        prior,
                        step_index,
                    )
                    return prior, True
        session = coding_store.create_session(
            project_id=project_id,
            backend=backend,
            repo_path=git_root,
            title=build_task_session_title(task_id, step_index, step, plan),
        )
        return str(session["session_id"]), False

    @staticmethod
    def _same_coding_target(
        payload: dict[str, Any], project_id: int, backend: str
    ) -> bool:
        try:
            if int(payload.get("project_id")) != project_id:
                return False
        except (TypeError, ValueError):
            return False
        recorded = payload.get("backend")
        return recorded is None or str(recorded) == backend

    @staticmethod
    def _session_of_run(coding_store: Any, run_id: str) -> Optional[str]:
        run = coding_store.get_run(run_id)
        if not run:
            return None
        return str(run.get("session_id") or "") or None

    @staticmethod
    def _request_child_cancel(task_id: str, run_id: str) -> None:
        """Request child cancel, including a linked HITL wait if any.

        A run parked in ``waiting_user`` has no live worker thread, so the
        plain cancel request (``cancelling``) would never reach a terminal
        status on its own. Cancelling the linked HITL run syncs the coding
        run to ``cancelled`` (checkpoint domain/run_id), letting the wait
        loop raise ``TaskCancelled`` instead of timing out.
        """
        from obsidian_ai_hub.coding import store as coding_store

        coding_store.request_cancel_run(run_id)
        try:
            latest = coding_store.get_run(run_id)
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
        project_id: int,
        backend: str,
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
                "child_kind": "coding",
                "child_run_id": run_id,
                "hitl_run_id": str(hitl_run_id) if hitl_run_id else None,
                "project_id": project_id,
                "backend": backend,
            },
        )

    def _build_content(
        self,
        task: dict[str, Any],
        plan: dict[str, Any],
        step_index: int,
        step: dict[str, Any],
    ) -> str:
        step_inputs = step.get("inputs", {}) or {}
        task_text = str(step_inputs.get("task") or "").strip()
        if task_text:
            return task_text

        plan_inner = plan.get("plan", {}) if isinstance(plan.get("plan"), dict) else {}
        purpose = str(plan_inner.get("purpose") or plan.get("purpose") or "").strip()
        return purpose

    def _final_text(self, coding_store: Any, session_id: str, run_id: str) -> str:
        messages = coding_store.list_messages(session_id)
        for message in reversed(messages):
            if str(message.get("role") or "") != "orchestrator":
                continue
            text = str(message.get("content") or "")
            if text.strip():
                return text
        raise ValueError(f"Child coding run '{run_id}' produced no messages.")
