"""Adapter delegating a step to a new Coding session/run in a Project Git root.

The existing coding worker executes the queued run under its repo lock and
cancel mechanism; this adapter only creates, watches, and summarizes.
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
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

CODING_BACKENDS = frozenset({"codex", "opencode"})


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

        task_id = str(task["task_id"])
        target = step.get("target")
        if not isinstance(target, dict):
            raise ValueError(f"Step {step_index} target must be an object.")
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
        session = coding_store.create_session(
            project_id=project_id,
            backend=backend,
            repo_path=git_root,
            title=f"Task {task_id} step {step_index}",
        )
        _, run = coding_store.start_queued_run(
            session["session_id"],
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
                "project_id": project_id,
                "backend": backend,
            },
        )
        final = wait_for_child_run(
            task_id,
            lambda: coding_store.get_run(run_id),
            lambda: coding_store.request_cancel_run(run_id),
            coding_store.CODING_TERMINAL_STATUSES,
            self.poll_interval,
            self.timeout_secs,
        )
        status = str(final.get("status"))
        if status == "completed":
            text = self._final_text(coding_store, session["session_id"], run_id)
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
                child_kind="coding",
                child_run_id=run_id,
            )
        if status == "cancelled":
            raise TaskCancelled(f"Child coding run '{run_id}' was cancelled.")
        raise ValueError(
            f"Child coding run '{run_id}' ended with status '{status}': "
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

    def _final_text(self, coding_store: Any, session_id: str, run_id: str) -> str:
        messages = coding_store.list_messages(session_id)
        worker_texts = [
            str(m.get("content") or "") for m in messages if m.get("role") == "worker"
        ]
        if worker_texts:
            return worker_texts[-1]
        if messages:
            return str(messages[-1].get("content") or "")
        raise ValueError(f"Child coding run '{run_id}' produced no messages.")
