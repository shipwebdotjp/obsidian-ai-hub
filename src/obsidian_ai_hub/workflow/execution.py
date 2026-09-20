"""Deterministic workflow graph executor.

The engine walks a validated Node/Edge graph. Control flow is deterministic;
randomness only enters through ``NodeRunner`` implementations (Agent Node LLM
output is schema-validated before it can flow on). Waiting states
(``waiting_hitl`` / ``waiting_attention``) are persisted and the run is
requeued by an external handler; completed activations are reused on resume so
a node invocation never runs twice for the same activation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from obsidian_ai_hub.workflow import store as workflow_store
from obsidian_ai_hub.workflow.models import (
    MAX_ITERATIONS,
    evaluate_condition,
    resolve_value,
    validate_value_against_schema,
)

logger = logging.getLogger(__name__)

HITL_ANSWER_EVENT = "hitl_answer_received"
ATTENTION_EVENT = "attention_resolved"
HITL_HANDLER = "workflow.hitl_wait"


@dataclass(frozen=True)
class NodeOutcome:
    """Result of one node invocation."""

    status: str  # succeeded | failed | waiting_hitl | needs_attention
    output: dict[str, Any] = field(default_factory=dict)
    satisfied_effects: tuple[str, ...] = ()
    error: Optional[str] = None
    child_kind: Optional[str] = None
    child_run_id: Optional[str] = None
    hitl_run_id: Optional[str] = None


@dataclass(frozen=True)
class RunOutcome:
    """Terminal or waiting outcome of a whole run execution."""

    kind: str  # completed | incomplete | failed | waiting_hitl | waiting_attention
    result_summary: Optional[str] = None
    error_summary: Optional[str] = None
    hitl_run_id: Optional[str] = None


class NodeRunner(Protocol):
    """Executes one capability/agent node invocation."""

    def run(
        self, *, node: dict[str, Any], inputs: dict[str, Any], context: dict[str, Any]
    ) -> NodeOutcome: ...


def _edges_from(
    edges: list[dict[str, Any]], node_id: str, edge_kind: str
) -> list[dict[str, Any]]:
    matched = [
        e
        for e in edges
        if e["source_node_id"] == node_id and (e.get("edge_kind") or "normal") == edge_kind
    ]
    matched.sort(key=lambda e: int(e.get("order_index") or 0))
    return matched


class WorkflowEngine:
    """Execute a saved run snapshot once (or resume a waiting run)."""

    def __init__(
        self,
        runner: NodeRunner,
        *,
        conn: Any = None,
    ) -> None:
        self._runner = runner
        self._conn = conn
        self._declared_effects: set[str] = set()
        self._satisfied_effects: set[str] = set()

    def execute(self, run: dict[str, Any]) -> RunOutcome:
        run_id = str(run["run_id"])
        snapshot = run.get("graph_snapshot") or {}
        nodes = list(snapshot.get("nodes") or [])
        edges = list(snapshot.get("edges") or [])
        self._by_id = {str(n["node_id"]): n for n in nodes}
        self._edges = edges
        self._run = run
        self._run_inputs = run.get("inputs") or {}
        self._node_outputs: dict[str, Any] = {}
        self._declared_effects = set()
        self._satisfied_effects = set()
        self._top_ids = {
            nid for nid, n in self._by_id.items() if not n.get("parent_loop_node_id")
        }

        entry = self._entry_node(self._top_ids)
        if entry is None:
            return RunOutcome(
                kind="failed", error_summary="entry Node が見つかりません"
            )
        workflow_store.append_event(
            run_id, "run_started", {"entry_node_id": entry}, conn=self._conn
        )
        return self._walk(run_id, entry, scope="top")

    # --- graph walking -----------------------------------------------------

    def _entry_node(self, scope_ids: set[str]) -> Optional[str]:
        incoming = {nid: 0 for nid in scope_ids}
        for edge in self._edges:
            if (
                edge["source_node_id"] in scope_ids
                and edge["target_node_id"] in scope_ids
            ):
                incoming[edge["target_node_id"]] += 1
        entries = [nid for nid, count in incoming.items() if count == 0]
        return entries[0] if len(entries) == 1 else None

    def _walk(self, run_id: str, start: str, *, scope: str) -> RunOutcome:
        current: Optional[str] = start
        guard = 0
        while current is not None:
            guard += 1
            if guard > len(self._by_id) + 1:
                return RunOutcome(
                    kind="failed", error_summary="グラフ実行が上限を超えました"
                )
            node = self._by_id[current]
            node_type = node.get("node_type")
            if node_type == "terminal":
                return self._finish_terminal(run_id, node)
            if node_type == "loop":
                loop_outcome, current = self._run_loop(run_id, node)
                if loop_outcome is not None:
                    return loop_outcome
                if current is None:
                    return RunOutcome(
                        kind="failed",
                        error_summary=f"Node '{node['node_id']}' に outgoing Edge がありません",
                    )
                continue
            outcome = self._run_single_node(run_id, node)
            if outcome.status == "waiting_hitl":
                workflow_store.transition_run_status(
                    run_id, "waiting_hitl", conn=self._conn
                )
                return RunOutcome(kind="waiting_hitl", hitl_run_id=outcome.hitl_run_id)
            if outcome.status == "needs_attention":
                workflow_store.transition_run_status(
                    run_id, "waiting_attention", conn=self._conn
                )
                return RunOutcome(kind="waiting_attention")
            if outcome.status == "succeeded":
                current = self._next_target(node, success=True)
                if current is None:
                    return RunOutcome(
                        kind="failed",
                        error_summary=f"Node '{node['node_id']}' に outgoing Edge がありません",
                    )
                continue
            # failed
            current = self._next_target(node, success=False)
            if current is None:
                return RunOutcome(
                    kind="failed",
                    error_summary=outcome.error or "Node が失敗しました",
                )

    def _next_target(self, node: dict[str, Any], *, success: bool) -> Optional[str]:
        node_id = str(node["node_id"])
        kind = "normal" if success else "error"
        candidates = _edges_from(self._edges, node_id, kind)
        if not success:
            return str(candidates[0]["target_node_id"]) if candidates else None
        for edge in candidates:
            condition = edge.get("condition")
            if condition is None:
                return str(edge["target_node_id"])
            try:
                if self._evaluate(condition):
                    return str(edge["target_node_id"])
            except KeyError:
                continue
        return None

    def _finish_terminal(self, run_id: str, node: dict[str, Any]) -> RunOutcome:
        outcome = (node.get("config") or {}).get("outcome")
        if outcome == "failure":
            return RunOutcome(kind="failed", error_summary="failure Terminal に到達しました")
        if self._declared_effects <= self._satisfied_effects:
            return RunOutcome(
                kind="completed",
                result_summary=f"effects satisfied: {sorted(self._satisfied_effects)}",
            )
        missing = sorted(self._declared_effects - self._satisfied_effects)
        return RunOutcome(
            kind="incomplete", error_summary=f"effects not satisfied: {missing}"
        )

    # --- single node -------------------------------------------------------

    def _run_single_node(
        self,
        run_id: str,
        node: dict[str, Any],
        *,
        loop_state: Optional[dict[str, Any]] = None,
        loop_input: Optional[dict[str, Any]] = None,
        loop_iteration: Optional[int] = None,
        iteration_context: Optional[dict[str, Any]] = None,
    ) -> NodeOutcome:
        node_id = str(node["node_id"])
        config = node.get("config") or {}
        resolved = self._resolve_node_inputs(
            config.get("inputs") or {},
            loop_state=loop_state,
            loop_input=loop_input,
            loop_iteration=loop_iteration,
        )
        iteration_context = self._with_reexecute_context(
            run_id, node_id, iteration_context
        )
        activation_id = workflow_store.get_or_create_activation(
            run_id, node_id, iteration_context, conn=self._conn
        )

        resumed = self._resume_waiting_state(run_id, node, activation_id)
        if resumed is not None:
            if resumed.status == "succeeded":
                self._record_success(run_id, node, activation_id, 1, resumed)
            return resumed
        existing = workflow_store.get_latest_run_node(activation_id, conn=self._conn)
        if existing is not None and existing.get("status") == "succeeded":
            self._rehydrate_success(run_id, node, activation_id, existing)
            return NodeOutcome(status="succeeded", output=existing.get("output") or {})

        retry = config.get("retry") or {}
        max_attempts = int(retry.get("max_attempts") or 0)
        attempt = 1
        last_error: Optional[str] = None
        while attempt <= max_attempts + 1:
            workflow_store.upsert_run_node(
                run_id=run_id,
                node_id=node_id,
                activation_id=activation_id,
                attempt=attempt,
                status="running",
                inputs=resolved,
                conn=self._conn,
            )
            workflow_store.append_event(
                run_id,
                "node_started",
                {"node_id": node_id, "activation_id": activation_id, "attempt": attempt},
                conn=self._conn,
            )
            context = self._context(run_id, node, activation_id, attempt, iteration_context)
            try:
                outcome = self._runner.run(node=node, inputs=resolved, context=context)
            except Exception as exc:  # noqa: BLE001 - surfaced as node failure
                logger.exception("Workflow node '%s' crashed", node_id)
                outcome = NodeOutcome(status="failed", error=str(exc))
            if outcome.status in ("waiting_hitl", "needs_attention"):
                status = (
                    "waiting_hitl" if outcome.status == "waiting_hitl" else "needs_attention"
                )
                workflow_store.upsert_run_node(
                    run_id=run_id,
                    node_id=node_id,
                    activation_id=activation_id,
                    attempt=attempt,
                    status=status,
                    output=outcome.output,
                    error_summary=outcome.error,
                    conn=self._conn,
                )
                workflow_store.append_event(
                    run_id,
                    "node_needs_attention"
                    if status == "needs_attention"
                    else "hitl_question_asked",
                    {
                        "node_id": node_id,
                        "activation_id": activation_id,
                        "hitl_run_id": outcome.hitl_run_id,
                    },
                    conn=self._conn,
                )
                return outcome
            if outcome.status == "succeeded":
                self._record_success(run_id, node, activation_id, attempt, outcome)
                return outcome
            last_error = outcome.error or "Node failed"
            workflow_store.upsert_run_node(
                run_id=run_id,
                node_id=node_id,
                activation_id=activation_id,
                attempt=attempt,
                status="failed",
                error_summary=last_error,
                conn=self._conn,
            )
            workflow_store.append_event(
                run_id,
                "node_failed",
                {
                    "node_id": node_id,
                    "activation_id": activation_id,
                    "attempt": attempt,
                    "error": last_error,
                },
                conn=self._conn,
            )
            attempt += 1
        return NodeOutcome(status="failed", error=last_error)

    def _record_success(
        self,
        run_id: str,
        node: dict[str, Any],
        activation_id: str,
        attempt: int,
        outcome: NodeOutcome,
    ) -> None:
        node_id = str(node["node_id"])
        workflow_store.upsert_run_node(
            run_id=run_id,
            node_id=node_id,
            activation_id=activation_id,
            attempt=attempt,
            status="succeeded",
            output=outcome.output,
            conn=self._conn,
        )
        self._node_outputs[node_id] = outcome.output
        declared = self._declared_effects_for(node)
        self._declared_effects.update(declared)
        self._satisfied_effects.update(outcome.satisfied_effects)
        workflow_store.append_event(
            run_id,
            "node_completed",
            {
                "node_id": node_id,
                "activation_id": activation_id,
                "child_kind": outcome.child_kind,
                "child_run_id": outcome.child_run_id,
                "effects": sorted(outcome.satisfied_effects),
            },
            conn=self._conn,
        )

    def _declared_effects_for(self, node: dict[str, Any]) -> tuple[str, ...]:
        if node.get("node_type") != "capability":
            return ()
        key = (node.get("config") or {}).get("capability_key")
        if not key:
            return ()
        try:
            from obsidian_ai_hub.tasks.capabilities import get_capability_definitions

            for definition in get_capability_definitions():
                if definition.key == key:
                    return definition.satisfied_effects
        except Exception:
            logger.warning("Capability catalog unavailable for effects lookup")
        return ()

    def _with_reexecute_context(
        self,
        run_id: str,
        node_id: str,
        iteration_context: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """Force a new activation after a human ``reexecute`` decision."""
        count = 0
        for event in workflow_store.list_events(run_id, conn=self._conn):
            payload = event.get("payload") or {}
            if (
                event.get("event_type") == ATTENTION_EVENT
                and payload.get("node_id") == node_id
                and payload.get("decision") == "reexecute"
            ):
                count += 1
        if count == 0:
            return iteration_context
        context = dict(iteration_context or {})
        context["reexec"] = count
        return context

    def _effects_for_activation(self, run_id: str, activation_id: str) -> list[str]:
        effects: list[str] = []
        for event in workflow_store.list_events(run_id, conn=self._conn):
            payload = event.get("payload") or {}
            if (
                event.get("event_type") == "node_completed"
                and payload.get("activation_id") == activation_id
            ):
                effects.extend(payload.get("effects") or [])
        return effects

    def _rehydrate_success(
        self,
        run_id: str,
        node: dict[str, Any],
        activation_id: str,
        existing: dict[str, Any],
    ) -> None:
        node_id = str(node["node_id"])
        self._node_outputs[node_id] = existing.get("output") or {}
        self._declared_effects.update(self._declared_effects_for(node))
        self._satisfied_effects.update(
            self._effects_for_activation(run_id, activation_id)
        )

    def _resume_waiting_state(
        self, run_id: str, node: dict[str, Any], activation_id: str
    ) -> Optional[NodeOutcome]:
        """Return a terminal outcome when a persisted wait has been resolved."""
        existing = workflow_store.get_run_node(activation_id, conn=self._conn)
        if existing is None or existing.get("status") not in (
            "waiting_hitl",
            "needs_attention",
        ):
            return None
        events = workflow_store.list_events(run_id, conn=self._conn)
        if existing["status"] == "waiting_hitl":
            for event in reversed(events):
                payload = event.get("payload") or {}
                if (
                    event.get("event_type") == HITL_ANSWER_EVENT
                    and payload.get("activation_id") == activation_id
                ):
                    output = payload.get("answer") or {}
                    if not isinstance(output, dict):
                        output = {"answer": output}
                    return NodeOutcome(status="succeeded", output=output)
            return NodeOutcome(status="waiting_hitl", output=existing.get("output") or {})
        for event in reversed(events):
            payload = event.get("payload") or {}
            if (
                event.get("event_type") == ATTENTION_EVENT
                and payload.get("activation_id") == activation_id
            ):
                decision = payload.get("decision")
                if decision == "adopt":
                    return NodeOutcome(
                        status="succeeded", output=existing.get("output") or {}
                    )
                if decision == "fail":
                    return NodeOutcome(
                        status="failed", error="needs_attention を失敗として処理しました"
                    )
                return None
        return NodeOutcome(status="needs_attention")

    # --- loop --------------------------------------------------------------

    def _run_loop(
        self, run_id: str, loop_node: dict[str, Any]
    ) -> tuple[Optional[RunOutcome], Optional[str]]:
        loop_id = str(loop_node["node_id"])
        config = loop_node.get("config") or {}
        max_iterations = min(int(config.get("max_iterations") or 1), MAX_ITERATIONS)
        child_nodes = [
            n for n in self._by_id.values() if n.get("parent_loop_node_id") == loop_id
        ]
        child_ids = {str(n["node_id"]) for n in child_nodes}
        entry = str(config.get("entry_node_id") or "")
        initial_input = self._resolve_node_inputs(config.get("input_mapping") or {})

        completed = self._completed_loop_iterations(run_id, loop_id)
        state: dict[str, Any] = (
            completed[-1]["state"] if completed else dict(initial_input)
        )
        start = len(completed) + 1
        for iteration in range(start, max_iterations + 1):
            iteration_context = {"loop_node_id": loop_id, "iteration": iteration}
            workflow_store.append_event(
                run_id,
                "loop_iteration_started",
                {"loop_node_id": loop_id, "iteration": iteration},
                conn=self._conn,
            )
            iteration_outputs: dict[str, Any] = {}
            current: Optional[str] = entry
            guard = 0
            next_state: Optional[dict[str, Any]] = None
            while current is not None:
                guard += 1
                if guard > len(child_ids) + 1:
                    return (
                        RunOutcome(
                            kind="failed",
                            error_summary=f"Loop '{loop_id}' 子グラフが上限を超えました",
                        ),
                        None,
                    )
                child = self._by_id[current]
                if child.get("node_type") == "loop_result":
                    next_state = self._resolve_loop_result(
                        child,
                        state=state,
                        loop_input=initial_input,
                        iteration=iteration,
                        iteration_outputs=iteration_outputs,
                    )
                    break
                outcome = self._run_single_node(
                    run_id,
                    child,
                    loop_state=state,
                    loop_input=initial_input,
                    loop_iteration=iteration,
                    iteration_context=iteration_context,
                )
                if outcome.status in ("waiting_hitl", "needs_attention"):
                    workflow_store.transition_run_status(
                        run_id,
                        "waiting_hitl"
                        if outcome.status == "waiting_hitl"
                        else "waiting_attention",
                        conn=self._conn,
                    )
                    return (
                        RunOutcome(
                            kind=(
                                "waiting_hitl"
                                if outcome.status == "waiting_hitl"
                                else "waiting_attention"
                            ),
                            hitl_run_id=outcome.hitl_run_id,
                        ),
                        None,
                    )
                if outcome.status == "succeeded":
                    iteration_outputs[current] = outcome.output
                    current = self._next_target(child, success=True)
                    if current is None:
                        return (
                            RunOutcome(
                                kind="failed",
                                error_summary=(
                                    f"Loop 子 Node '{child['node_id']}' に "
                                    "outgoing Edge がありません"
                                ),
                            ),
                            None,
                        )
                    continue
                current = self._next_target(child, success=False)
                if current is None:
                    return (
                        RunOutcome(
                            kind="failed",
                            error_summary=outcome.error or "Loop 子 Node が失敗しました",
                        ),
                        None,
                    )
            if next_state is None:
                return (
                    RunOutcome(
                        kind="failed",
                        error_summary=f"Loop '{loop_id}' が loop_result に到達しませんでした",
                    ),
                    None,
                )
            state = next_state
            workflow_store.append_event(
                run_id,
                "loop_iteration_completed",
                {"loop_node_id": loop_id, "iteration": iteration, "state": state},
                conn=self._conn,
            )
            if not self._evaluate_loop_condition(config, state, initial_input, iteration):
                output = {
                    "final_state": state,
                    "iterations": iteration,
                    "exit_reason": "condition_satisfied",
                }
                self._complete_loop_node(run_id, loop_node, output)
                return None, self._next_target(loop_node, success=True)
            if iteration == max_iterations:
                output = {
                    "final_state": state,
                    "iterations": iteration,
                    "exit_reason": "max_iterations_reached",
                }
                self._complete_loop_node(run_id, loop_node, output)
                return (
                    RunOutcome(
                        kind="incomplete",
                        error_summary=f"Loop '{loop_id}' が上限 {max_iterations} に到達しました",
                    ),
                    None,
                )
        return (
            RunOutcome(kind="incomplete", error_summary=f"Loop '{loop_id}' が未完了です"),
            None,
        )

    def _complete_loop_node(
        self, run_id: str, loop_node: dict[str, Any], output: dict[str, Any]
    ) -> None:
        node_id = str(loop_node["node_id"])
        activation_id = workflow_store.get_or_create_activation(
            run_id, node_id, None, conn=self._conn
        )
        workflow_store.upsert_run_node(
            run_id=run_id,
            node_id=node_id,
            activation_id=activation_id,
            attempt=1,
            status="succeeded",
            output=output,
            conn=self._conn,
        )
        self._node_outputs[node_id] = output

    def _completed_loop_iterations(
        self, run_id: str, loop_id: str
    ) -> list[dict[str, Any]]:
        events = workflow_store.list_events(run_id, conn=self._conn)
        completed = []
        for event in events:
            payload = event.get("payload") or {}
            if (
                event.get("event_type") == "loop_iteration_completed"
                and payload.get("loop_node_id") == loop_id
            ):
                completed.append(payload)
        return completed

    def _resolve_loop_result(
        self,
        node: dict[str, Any],
        *,
        state: dict[str, Any],
        loop_input: dict[str, Any],
        iteration: int,
        iteration_outputs: dict[str, Any],
    ) -> dict[str, Any]:
        mapping = (node.get("config") or {}).get("output_mapping") or {}
        resolved = resolve_value(
            mapping,
            run_inputs=self._run_inputs,
            node_outputs=iteration_outputs,
            loop_state=state,
            loop_input=loop_input,
            loop_iteration=iteration,
        )
        return resolved if isinstance(resolved, dict) else {}

    def _evaluate_loop_condition(
        self,
        config: dict[str, Any],
        state: dict[str, Any],
        loop_input: dict[str, Any],
        iteration: int,
    ) -> bool:
        condition = config.get("continuation_condition")
        if not isinstance(condition, dict):
            return False
        try:
            return evaluate_condition(
                condition,
                lambda path: resolve_value(
                    {"$ref": path},
                    run_inputs=self._run_inputs,
                    node_outputs={},
                    loop_state=state,
                    loop_input=loop_input,
                    loop_iteration=iteration,
                ),
            )
        except KeyError as exc:
            raise ValueError(
                f"Loop 継続条件の参照を解決できません: {exc}"
            ) from exc

    # --- helpers -----------------------------------------------------------

    def _resolve_node_inputs(
        self,
        value: dict[str, Any],
        *,
        loop_state: Optional[dict[str, Any]] = None,
        loop_input: Optional[dict[str, Any]] = None,
        loop_iteration: Optional[int] = None,
    ) -> dict[str, Any]:
        resolved = resolve_value(
            value,
            run_inputs=self._run_inputs,
            node_outputs=self._node_outputs,
            loop_state=loop_state,
            loop_input=loop_input,
            loop_iteration=loop_iteration,
        )
        return resolved if isinstance(resolved, dict) else {}

    def _evaluate(self, condition: dict[str, Any]) -> bool:
        return evaluate_condition(
            condition,
            lambda path: resolve_value(
                {"$ref": path},
                run_inputs=self._run_inputs,
                node_outputs=self._node_outputs,
            ),
        )

    def _context(
        self,
        run_id: str,
        node: dict[str, Any],
        activation_id: str,
        attempt: int,
        iteration_context: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "workflow_id": self._run.get("workflow_id"),
            "revision_id": self._run.get("revision_id"),
            "node_id": str(node["node_id"]),
            "activation_id": activation_id,
            "retry_count": attempt - 1,
            "loop_context": iteration_context,
        }


def validate_agent_output(
    output: Any, schema: Optional[dict[str, Any]]
) -> list[str]:
    """Validate an Agent Node's parsed JSON output against its schema."""
    if not isinstance(schema, dict):
        return []
    if not isinstance(output, dict):
        return ["Agent 出力が object ではありません"]
    return validate_value_against_schema(output, schema, path="agent_output")


def parse_json_object(text: str) -> Optional[dict[str, Any]]:
    """Best-effort parse of a JSON object from an LLM/tool text result."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = json.loads(stripped)
    except (TypeError, ValueError):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            value = json.loads(stripped[start : end + 1])
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, dict) else None
