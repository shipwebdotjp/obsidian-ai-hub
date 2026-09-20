"""Workflow worker: claim queued runs and drive the graph engine serially."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.execution import RunOutcome, WorkflowEngine

logger = logging.getLogger(__name__)

_TERMINAL_KINDS = frozenset({"completed", "incomplete", "failed"})


def process_one(instance_id: str, runner: object = None) -> bool:
    """Claim and execute at most one queued run. Returns False when idle."""
    claimed = workflow_store.claim_run(instance_id)
    if claimed is None:
        return False
    run_id = str(claimed["run_id"])
    if runner is None:
        from obsidian_ai_hub.workflow.runners import DefaultNodeRunner

        runner = DefaultNodeRunner()
    try:
        outcome = WorkflowEngine(runner).execute(claimed)
    except Exception as exc:  # noqa: BLE001 - record and fail the run
        logger.exception("Workflow run %s crashed", run_id)
        workflow_store.transition_run_status(
            run_id, "failed", error_summary=str(exc)
        )
        return True
    _apply_outcome(run_id, outcome)
    return True


def _apply_outcome(run_id: str, outcome: RunOutcome) -> None:
    if outcome.kind not in _TERMINAL_KINDS:
        # waiting_hitl / waiting_attention were already persisted by the engine.
        return
    workflow_store.transition_run_status(
        run_id,
        outcome.kind,
        result_summary=outcome.result_summary,
        error_summary=outcome.error_summary,
    )
    workflow_store.append_event(
        run_id,
        "run_status_changed",
        {
            "status": outcome.kind,
            "result_summary": outcome.result_summary,
            "error_summary": outcome.error_summary,
        },
    )


async def workflow_worker_loop(
    instance_id: str,
    stop_event: asyncio.Event,
    poll_interval: float = 0.5,
    runner: Optional[object] = None,
) -> None:
    """Poll claims serially until ``stop_event`` is set."""
    while not stop_event.is_set():
        try:
            did_work = await asyncio.to_thread(process_one, instance_id, runner)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Workflow worker iteration failed")
            did_work = False
        if not did_work:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                continue
