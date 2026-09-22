"""Adapter running a research job through the existing research pipeline.

The saved step inputs (theme/mode/context/output_style) create or reuse a
research theme and submit the job to the shared background executor; the
existing ``execute_research_job_sync`` performs the report generation and
the Vault save. This adapter only submits, watches the research job, and
summarizes the report markdown.

Cancellation: research jobs have no cooperative cancel; on task cancel the
adapter keeps waiting until the job reaches a terminal status, then raises
``TaskCancelled``. The job itself finishes (and may publish its report to
the Vault) once started. When it finished successfully the report summary is
attached as ``CancellationEvidence.result_summary`` so the Workflow can store
adoptable evidence instead of discarding a completed result.
"""

from __future__ import annotations

import logging
import textwrap
from typing import Any

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.adapters.child_runs import wait_for_child_run
from obsidian_ai_hub.tasks.execution import (
    CANCEL_CERTAINTY_CANCELLED,
    CancellationEvidence,
    StepResult,
    TaskCancelled,
)

logger = logging.getLogger(__name__)

RESEARCH_TERMINAL_STATUSES = frozenset({"succeeded", "failed"})

SUMMARY_TITLE_LIMIT = 2000


class ResearchAdapter:
    """Submit and watch one research job for a saved plan step."""

    def __init__(
        self, poll_interval: float = 2.0, timeout_secs: float = 3600.0
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
        from obsidian_ai_hub.research.runner import (
            get_or_create_theme_and_job,
            submit_research_job_bg,
        )

        from obsidian_ai_hub.research import db as research_db
        from obsidian_ai_hub.tasks.capability_schemas import (
            validate_capability_inputs,
            validate_capability_target,
        )

        task_id = str(task["task_id"])
        try:
            validate_capability_target(
                str(step.get("capability_key")), step.get("target")
            )
            step_inputs = validate_capability_inputs(
                str(step.get("capability_key")), step.get("inputs", {})
            )
        except ValueError as exc:
            raise ValueError(f"Step {step_index} {exc}") from exc

        mode = str(step_inputs.get("mode") or "auto")
        theme_rec, job_rec = get_or_create_theme_and_job(
            theme=str(step_inputs["theme"]),
            mode=mode,
            context=step_inputs.get("context"),
            output_style=step_inputs.get("output_style"),
            project_id=step_inputs.get("project_id"),
        )
        theme_id = str(theme_rec["theme_id"])
        job_id = str(job_rec["job_id"])
        submit_research_job_bg(
            theme_id,
            job_id,
            mode=mode,
            output_style=step_inputs.get("output_style"),
            context=step_inputs.get("context"),
        )
        task_store.set_active_child(task_id, "research", job_id)
        task_store.append_task_event(
            task_id,
            "child_run_started",
            {
                "step_index": step_index,
                "child_kind": "research",
                "child_run_id": job_id,
                "theme_id": theme_id,
            },
        )
        try:
            final = wait_for_child_run(
                task_id,
                lambda: research_db.get_job(job_id),
                self._no_op_cancel,
                RESEARCH_TERMINAL_STATUSES,
                self.poll_interval,
                self.timeout_secs,
                child_kind="research",
                child_run_id=job_id,
            )
        except TaskCancelled as exc:
            # Research jobs cannot be cancelled; if the job finished before
            # the request landed, preserve its report so the caller can offer
            # an adoptable result instead of a bare unknown.
            evidence = exc.evidence
            if evidence.result_certainty != CANCEL_CERTAINTY_CANCELLED:
                finished = research_db.get_job(job_id)
                if finished is not None and str(finished.get("status")) == "succeeded":
                    raise TaskCancelled(
                        str(exc),
                        evidence=CancellationEvidence(
                            child_kind=evidence.child_kind,
                            child_run_id=evidence.child_run_id,
                            result_certainty=evidence.result_certainty,
                            result_summary=self._summary(job_id, finished),
                        ),
                    ) from exc
            raise
        status = str(final.get("status"))
        if status != "succeeded":
            err = str(final.get("error") or "unknown error")
            raise ValueError(f"Research job '{job_id}' failed: {err}")
        return StepResult(
            step_index=step_index,
            capability_key=str(step.get("capability_key")),
            summary=self._summary(job_id, final),
            child_kind="research",
            child_run_id=job_id,
        )

    @staticmethod
    def _no_op_cancel() -> None:
        # Research jobs cannot be cancelled cooperatively; the job runs to
        # completion and the wait loop raises TaskCancelled afterwards.
        return None

    @staticmethod
    def _summary(job_id: str, final: dict[str, Any]) -> str:
        title = str(final.get("generated_title") or "")
        markdown = str(final.get("markdown") or "")
        text = markdown if markdown.strip() else title
        excerpt = textwrap.shorten(
            " ".join(text.split()), width=SUMMARY_TITLE_LIMIT, placeholder="…"
        )
        return f"[title] {title}\n\n{excerpt}" if title.strip() else excerpt
