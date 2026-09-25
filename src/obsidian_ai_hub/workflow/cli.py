"""Thin CLI operations for Workflow (dispatched from ``main.py``).

These helpers reuse the same store / validation / worker as the Web API so an
agent or human can import, validate, publish and run a Workflow without
starting an HTTP client. Output is JSON on stdout (no ``[START]/[END]``
wrapper) and the return value is the process exit code.
"""

from __future__ import annotations

import functools
import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence

from obsidian_ai_hub.workflow import definition_package, store
from obsidian_ai_hub.workflow.checks import (
    agent_exists_check,
    capability_enabled_check,
)
from obsidian_ai_hub.workflow.graph_copy import renumber_graph
from obsidian_ai_hub.workflow.models import (
    RUN_TERMINAL_STATUSES,
    RUN_WAITING_STATUSES,
    apply_schema_defaults,
    validate_value_against_schema,
)
from obsidian_ai_hub.workflow.scheduling import requires_approval
from obsidian_ai_hub.workflow.validation import validate_graph

_WAIT_STOPS = RUN_TERMINAL_STATUSES | RUN_WAITING_STATUSES | {"interrupted"}


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _json_errors(fn):
    """Turn expected operation failures into a JSON payload + exit code 1."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> int:
        try:
            return fn(*args, **kwargs)
        except (OSError, ValueError, TimeoutError) as exc:
            _print({"success": False, "error": str(exc)})
            return 1

    return wrapper


def _errors(revision: dict[str, Any]) -> list[str]:
    return validate_graph(
        nodes=revision.get("nodes") or [],
        edges=revision.get("edges") or [],
        inputs_schema=revision.get("inputs_schema") or {},
        capability_enabled=capability_enabled_check(),
        agent_exists=agent_exists_check(),
    )


def _warnings(revision: dict[str, Any]) -> list[str]:
    from obsidian_ai_hub.workflow.checks import workflow_graph_warnings

    return workflow_graph_warnings(revision)


@_json_errors
def import_package(path: str) -> int:
    """Import a v1 definition package as a new Workflow + draft Revision."""
    raw = Path(path).read_bytes()
    fmt = "yaml" if str(path).lower().endswith((".yaml", ".yml")) else "json"
    package = definition_package.parse_package(raw, fmt)
    nodes, edges = definition_package.package_to_graph(package)
    new_nodes, new_edges = renumber_graph(nodes, edges)
    workflow = store.create_workflow_from_graph(
        package["name"],
        package["description"],
        package["inputs_schema"],
        new_nodes,
        new_edges,
    )
    revision = workflow["revision"]
    errors = _errors(revision)
    _print(
        {
            "workflow_id": workflow["workflow_id"],
            "revision_id": revision["revision_id"],
            "name": workflow["name"],
            "validation_errors": errors,
        }
    )
    return 1 if errors else 0


@_json_errors
def validate_revision(revision_id: str) -> int:
    revision = store.get_revision(revision_id)
    if revision is None:
        raise FileNotFoundError(f"Revision '{revision_id}' not found.")
    errors = _errors(revision)
    _print(
        {
            "revision_id": revision_id,
            "valid": not errors,
            "errors": errors,
            "warnings": _warnings(revision),
        }
    )
    return 0 if not errors else 1


@_json_errors
def publish_revision(revision_id: str) -> int:
    revision = store.get_revision(revision_id)
    if revision is None:
        raise FileNotFoundError(f"Revision '{revision_id}' not found.")
    errors = _errors(revision)
    if errors:
        _print({"published": False, "revision_id": revision_id, "errors": errors})
        return 1
    published = store.publish_revision(revision_id)
    _print(
        {
            "published": True,
            "revision_id": published["revision_id"],
            "version": published["version"],
            "status": published["status"],
        }
    )
    return 0


def parse_inputs(pairs: Optional[Sequence[str]]) -> dict[str, Any]:
    """Parse repeated ``NAME=VALUE`` flags (JSON value when parseable)."""
    inputs: dict[str, Any] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--workflow-input は NAME=VALUE 形式が必要です: {pair!r}")
        name, raw = pair.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError("--workflow-input の NAME が空です")
        try:
            inputs[name] = json.loads(raw)
        except ValueError:
            inputs[name] = raw
    return inputs


def _run_payload(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Workflow run '{run_id}' not found.")
    return {
        "run_id": run_id,
        "workflow_id": run.get("workflow_id"),
        "revision_id": run.get("revision_id"),
        "status": run.get("status"),
        "inputs": run.get("inputs"),
        "result_summary": run.get("result_summary"),
        "error_summary": run.get("error_summary"),
        "nodes": [
            {
                "node_id": node.get("node_id"),
                "status": node.get("status"),
                "output": node.get("output"),
                "error_summary": node.get("error_summary"),
                "child_kind": node.get("child_kind"),
                "child_run_id": node.get("child_run_id"),
            }
            for node in store.list_run_nodes(run_id)
        ],
    }


def _execute_until_done(run_id: str) -> None:
    from obsidian_ai_hub.workflow import worker

    instance_id = f"cli-{uuid.uuid4().hex[:8]}"
    while True:
        run = store.get_run(run_id)
        if run is None or str(run["status"]) != "queued":
            return
        if worker.process_one(instance_id, run_id=run_id):
            continue
        time.sleep(0.5)


def _wait_until_done(run_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = store.get_run(run_id)
        if run is None or str(run["status"]) in _WAIT_STOPS:
            return
        time.sleep(1.0)
    raise TimeoutError(f"Run '{run_id}' did not finish within {timeout} seconds")


@_json_errors
def run_revision(
    revision_id: str,
    inputs: dict[str, Any],
    *,
    approve: bool = False,
    wait: bool = False,
    execute: bool = False,
    timeout: float = 1800.0,
) -> int:
    """Create a Run; optionally approve, execute locally and/or wait.

    Exit code is 0 only for a ``completed`` run, 1 otherwise (validation
    failure, ``incomplete``/``failed``/``cancelled``, waiting state).
    """
    revision = store.get_revision(revision_id)
    if revision is None:
        raise FileNotFoundError(f"Revision '{revision_id}' not found.")
    workflow_id = str(revision["workflow_id"])
    merged = apply_schema_defaults(inputs, revision.get("inputs_schema") or {})
    input_errors = validate_value_against_schema(
        merged,
        revision.get("inputs_schema") or {},
        path="run.inputs",
        allow_expressions=True,
    )
    if input_errors:
        _print({"created": False, "errors": input_errors})
        return 1
    skip_approval = store.workflow_skip_approval(workflow_id)
    initial_status = (
        "waiting_approval"
        if requires_approval(revision.get("nodes") or [], skip_approval=skip_approval)
        else "queued"
    )
    run = store.create_run(
        workflow_id, revision_id, merged, initial_status=initial_status
    )
    run_id = str(run["run_id"])
    if skip_approval and requires_approval(revision.get("nodes") or []):
        store.append_event(
            run_id,
            "run_approval_skipped",
            {"reason": "workflow_skip_approval"},
        )
    if approve and str(run["status"]) == "waiting_approval":
        store.transition_run_status(run_id, "queued")
    if execute and str(store.get_run(run_id)["status"]) == "queued":
        _execute_until_done(run_id)
    if wait:
        current = store.get_run(run_id)
        if current is not None and str(current["status"]) not in _WAIT_STOPS:
            _wait_until_done(run_id, timeout)
    payload = _run_payload(run_id)
    _print(payload)
    return 0 if payload["status"] == "completed" else 1
