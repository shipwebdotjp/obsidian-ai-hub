"""Default node runners: real Capability, Agent and HITL node execution.

The engine is executor-agnostic; tests inject fakes. This module wires the
production paths to the existing Task capability adapters and the Agent/HITL
stores. See ``docs/workflow/specification.md`` §8–§10.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from obsidian_ai_hub.tasks.execution import (
    CANCEL_CERTAINTY_CANCELLED,
    CANCEL_CERTAINTY_COMPLETED,
    CANCEL_CERTAINTY_UNKNOWN,
)
from obsidian_ai_hub.workflow.execution import (
    HITL_HANDLER,
    NodeOutcome,
    parse_json_object,
    validate_agent_output,
)
from obsidian_ai_hub.workflow.llm_node import generate_llm_json

logger = logging.getLogger(__name__)

HITL_CAPABILITY_KEY = "hitl_wait"


class DefaultNodeRunner:
    """Execute capability, agent and ``hitl_wait`` nodes."""

    def __init__(self, poll_interval: float = 2.0, timeout_secs: float = 1800.0) -> None:
        self.poll_interval = poll_interval
        self.timeout_secs = timeout_secs
        self._executor: Any = None

    def run(
        self, *, node: dict[str, Any], inputs: dict[str, Any], context: dict[str, Any]
    ) -> NodeOutcome:
        node_type = node.get("node_type")
        if node_type == "capability":
            key = (node.get("config") or {}).get("capability_key")
            if key == HITL_CAPABILITY_KEY:
                return self._run_hitl_wait(inputs, context)
            return self._run_capability(node, inputs, context)
        if node_type == "agent":
            return self._run_agent(node, inputs, context)
        if node_type == "llm":
            return self._run_llm(node, inputs, context)
        raise ValueError(f"Node type '{node_type}' は NodeRunner では実行できません")

    # --- capability --------------------------------------------------------

    def _run_capability(
        self, node: dict[str, Any], inputs: dict[str, Any], context: dict[str, Any]
    ) -> NodeOutcome:
        if self._executor is None:
            from obsidian_ai_hub.tasks.adapters import get_default_executor

            self._executor = get_default_executor(poll_interval=self.poll_interval)
        from obsidian_ai_hub.tasks import store as task_store
        from obsidian_ai_hub.tasks.execution import TaskCancelled
        from obsidian_ai_hub.workflow import store as workflow_store

        key = (node.get("config") or {}).get("capability_key")
        # Task adapters record child linkage (``set_active_child`` /
        # ``child_run_started`` events) and watch cancellation against a Task
        # row, so the bridge owns a short-lived Task for this node execution.
        # Creation and the departure from ``queued`` share one transaction so
        # a concurrent Task worker can never observe (and claim) the bridge
        # row. The row is ``origin='workflow'`` so the Task Agent list excludes
        # it, and ends terminal so the 30-day task retention purges it.
        run_id = str(context["run_id"])
        node_id = str(node.get("node_id"))
        activation_id = str(context["activation_id"])
        attempt = int(context.get("attempt") or 1)
        prompt = f"Workflow run {run_id} node {node_id} ({key})"
        with task_store.auto_connection() as (bridge_conn, _):
            with bridge_conn:
                bridge = task_store.create_task(
                    prompt,
                    conn=bridge_conn,
                    origin=task_store.TASK_ORIGIN_WORKFLOW,
                )
                bridge_id = str(bridge["task_id"])
                task_store.transition_task_status(bridge_id, "planning", conn=bridge_conn)
                task_store.transition_task_status(bridge_id, "running", conn=bridge_conn)
        # Persist the in-flight reference before any external call so a
        # concurrent cancel can find and stop this bridge. If the run already
        # moved to ``cancelling`` we never start the external operation.
        workflow_store.set_run_node_bridge(
            run_id=run_id,
            node_id=node_id,
            activation_id=activation_id,
            attempt=attempt,
            bridge_task_id=bridge_id,
        )
        if self._workflow_cancelling(run_id):
            self._cancel_bridge_task(bridge_id)
            return NodeOutcome(
                status="cancelled",
                result_certainty=CANCEL_CERTAINTY_CANCELLED,
            )
        # The Task Step contract requires ``target`` to be an object. Target-
        # based capabilities (``specialist_agent`` / ``coding_cli``) carry it in
        # ``config.target``; every other capability ignores the empty object.
        config = node.get("config") or {}
        target = config.get("target")
        step = {
            "capability_key": key,
            "target": target if isinstance(target, dict) else {},
            "inputs": inputs,
        }
        task = {"task_id": bridge_id, "prompt_text": ""}
        plan = {"plan": {"purpose": "", "completion_criteria": ""}}
        try:
            result = self._executor.execute_step(task, plan, 0, step)
        except TaskCancelled as exc:
            self._cancel_bridge_task(bridge_id)
            evidence = exc.evidence
            output = (
                {"summary": evidence.result_summary}
                if evidence.result_summary
                else {}
            )
            return NodeOutcome(
                status="cancelled",
                output=output,
                child_kind=evidence.child_kind,
                child_run_id=evidence.child_run_id,
                result_certainty=evidence.result_certainty,
                error=(
                    None
                    if evidence.result_certainty == CANCEL_CERTAINTY_CANCELLED
                    else "取消要求後に外部処理の結果を確認できません"
                ),
            )
        except Exception:
            try:
                task_store.transition_task_status(bridge_id, "failed")
            except Exception:
                logger.warning("Bridge task '%s' bookkeeping failed", bridge_id)
            raise
        try:
            task_store.transition_task_status(bridge_id, "completed")
        except Exception:
            # Bookkeeping must never turn a completed, possibly
            # side-effecting node into a failure (which a retry could
            # execute twice).
            logger.warning("Bridge task '%s' bookkeeping failed", bridge_id)
        output = parse_json_object(result.summary)
        if output is None:
            output = {"summary": result.summary}
        mismatch_errors = self._output_mismatch_errors(str(key), output, context)
        if mismatch_errors and bool(config.get("fail_on_output_mismatch")):
            # Strict mode: the capability ran, but its result cannot be trusted
            # as the declared output. Nothing downstream may consume it.
            return NodeOutcome(
                status="failed",
                error=(
                    "Capability 出力が strict 検証に失敗しました: "
                    + "; ".join(mismatch_errors)
                ),
                child_kind=result.child_kind,
                child_run_id=result.child_run_id,
            )
        return NodeOutcome(
            status="succeeded",
            output=output,
            satisfied_effects=tuple(result.satisfied_effects or ()),
            child_kind=result.child_kind,
            child_run_id=result.child_run_id,
        )

    @staticmethod
    def _output_mismatch_errors(
        key: str, output: dict[str, Any], context: dict[str, Any]
    ) -> list[str]:
        """Return output-contract violations and record them as an event.

        A top-level ``error`` key counts as a violation because every
        registry-tool wrapper reports failure that way (for example
        ``vault_read_file`` returns ``{"error": "File not found"}`` with a
        successful tool status). Declared schemas allow additional properties,
        so the schema check alone would miss that shape.
        """
        from obsidian_ai_hub.tasks.capability_schemas import (
            capability_output_schema,
        )
        from obsidian_ai_hub.workflow import store as workflow_store
        from obsidian_ai_hub.workflow.models import validate_value_against_schema

        errors: list[str] = []
        if "error" in output:
            errors.append(f"capability がエラーを返しました: {output['error']!r}")
        schema = capability_output_schema(key)
        if schema:
            errors.extend(
                validate_value_against_schema(output, schema, path="output")
            )
        if not errors:
            return []
        workflow_store.append_event(
            str(context["run_id"]),
            "capability_output_schema_mismatch",
            {
                "node_id": context.get("node_id"),
                "activation_id": context.get("activation_id"),
                "capability_key": key,
                "errors": errors,
            },
        )
        return errors

    @staticmethod
    def _workflow_cancelling(run_id: str) -> bool:
        from obsidian_ai_hub.workflow import store as workflow_store

        run = workflow_store.get_run(run_id)
        return run is not None and str(run.get("status")) == "cancelling"

    @staticmethod
    def _cancel_bridge_task(bridge_id: str) -> None:
        """Move the short-lived bridge Task to ``cancelled`` if not terminal.

        Also runs when a concurrent cancel already put the bridge into
        ``cancelling``; the terminal transition is the same either way.
        """
        from obsidian_ai_hub.tasks import store as task_store

        try:
            task = task_store.get_task(bridge_id)
            if task is None:
                return
            status = str(task.get("status"))
            if status in task_store.TASK_TERMINAL_STATUSES:
                return
            if status == "running":
                task_store.transition_task_status(bridge_id, "cancelling")
            task_store.transition_task_status(bridge_id, "cancelled")
        except Exception:
            logger.warning("Bridge task '%s' cancel bookkeeping failed", bridge_id)

    # --- agent -------------------------------------------------------------

    def _run_agent(
        self, node: dict[str, Any], inputs: dict[str, Any], context: dict[str, Any]
    ) -> NodeOutcome:
        from obsidian_ai_hub.agents import store as agent_store
        from obsidian_ai_hub.runs.instance import get_instance_id
        from obsidian_ai_hub.tasks.directional import fingerprint_agent_config
        from obsidian_ai_hub.workflow import store as workflow_store

        config = node.get("config") or {}
        agent_id = str(config.get("agent_id") or "")
        output_schema = config.get("output_schema")
        agent = agent_store.get_agent(agent_id)
        if agent is None:
            return NodeOutcome(status="failed", error=f"Agent '{agent_id}' が存在しません")
        content = self._build_agent_content(inputs, output_schema)
        session = agent_store.create_session(
            agent_id, title=f"Workflow {context['run_id']}"[:60], source="workflow"
        )
        session_id = str(session["session_id"])
        _, run = agent_store.start_queued_run(
            session_id, content, created_instance_id=get_instance_id()
        )
        run_id = str(run["run_id"])
        workflow_store.append_event(
            str(context["run_id"]),
            "agent_config_fingerprint",
            {
                "node_id": context["node_id"],
                "activation_id": context["activation_id"],
                "agent_id": agent_id,
                "fingerprint": fingerprint_agent_config(agent).model_dump(),
                "child_run_id": run_id,
            },
        )
        workflow_run_id = str(context["run_id"])
        final = self._wait_for_agent_run(workflow_run_id, run_id)
        status = str(final.get("status"))
        cancel_requested = self._workflow_cancelling(workflow_run_id)
        if status == "cancelled":
            return NodeOutcome(
                status="cancelled",
                child_kind="agent",
                child_run_id=run_id,
                result_certainty=CANCEL_CERTAINTY_CANCELLED,
            )
        if status == "succeeded":
            message_id = final.get("assistant_message_id")
            message = (
                agent_store.get_message(str(message_id)) if message_id else None
            )
            text = str((message or {}).get("content") or "")
            parsed = parse_json_object(text)
            if parsed is None:
                return self._agent_cancel_or_fail(
                    cancel_requested,
                    run_id,
                    "Agent 出力を JSON object として解釈できません",
                    CANCEL_CERTAINTY_UNKNOWN,
                )
            errors = validate_agent_output(parsed, output_schema)
            if errors:
                return self._agent_cancel_or_fail(
                    cancel_requested,
                    run_id,
                    "Agent 出力が schema に一致しません: " + "; ".join(errors),
                    CANCEL_CERTAINTY_UNKNOWN,
                )
            if cancel_requested:
                # The child finished before the cancel could stop it. Keep the
                # output so the human can adopt it, but never silently continue.
                return NodeOutcome(
                    status="cancelled",
                    output=parsed,
                    child_kind="agent",
                    child_run_id=run_id,
                    result_certainty=CANCEL_CERTAINTY_COMPLETED,
                )
            return NodeOutcome(
                status="succeeded",
                output=parsed,
                child_kind="agent",
                child_run_id=run_id,
            )
        return self._agent_cancel_or_fail(
            cancel_requested,
            run_id,
            f"Agent run '{run_id}' ended with status '{status}'",
            CANCEL_CERTAINTY_UNKNOWN,
        )

    @staticmethod
    def _agent_cancel_or_fail(
        cancel_requested: bool,
        run_id: str,
        error: str,
        certainty: str,
    ) -> NodeOutcome:
        if cancel_requested:
            return NodeOutcome(
                status="cancelled",
                error=error,
                child_kind="agent",
                child_run_id=run_id,
                result_certainty=certainty,
            )
        return NodeOutcome(status="failed", error=error)

    def _wait_for_agent_run(
        self, workflow_run_id: str, agent_run_id: str
    ) -> Any:
        """Poll a child agent run without the Task-mode cancel coupling.

        ``tasks.adapters.child_runs.wait_for_child_run`` resolves a Task id via
        ``task_store.get_task``; a workflow run id is never present there, so
        the wait is implemented here against the agent store and the workflow
        run status.
        """
        import time

        from obsidian_ai_hub.agents import store as agent_store
        from obsidian_ai_hub.workflow import store as workflow_store

        deadline = time.monotonic() + self.timeout_secs
        while True:
            run = agent_store.get_run(agent_run_id)
            if run is None:
                raise ValueError(f"Agent child run '{agent_run_id}' disappeared")
            status = str(run.get("status"))
            if status in agent_store.AGENT_TERMINAL_STATUSES:
                return run
            if status == "waiting_user":
                deadline = time.monotonic() + self.timeout_secs
            elif time.monotonic() > deadline:
                raise TimeoutError(
                    f"Agent child run '{agent_run_id}' timed out"
                )
            workflow_run = workflow_store.get_run(workflow_run_id)
            if workflow_run is not None and str(workflow_run.get("status")) == "cancelling":
                agent_store.request_cancel_run(agent_run_id)
                self._cancel_agent_hitl(agent_run_id)
            time.sleep(self.poll_interval)

    @staticmethod
    def _cancel_agent_hitl(agent_run_id: str) -> None:
        """Cancel a HITL wait that a ``waiting_user`` child is parked on."""
        from obsidian_ai_hub.agents import store as agent_store

        try:
            latest = agent_store.get_run(agent_run_id)
        except Exception:
            return
        hitl_run_id = (latest or {}).get("hitl_run_id")
        if not hitl_run_id:
            return
        try:
            from obsidian_ai_hub.hitl import service as hitl_service

            hitl_service.cancel_run(str(hitl_run_id))
        except Exception:
            logger.warning(
                "Failed to cancel linked HITL run %s for agent child %s",
                hitl_run_id,
                agent_run_id,
                exc_info=True,
            )

    @staticmethod
    def _build_agent_content(inputs: dict[str, Any], output_schema: Any) -> str:
        schema_text = json.dumps(output_schema or {}, ensure_ascii=False)
        return (
            "以下の入力に対して作業し、結果を JSON object のみで出力してください。\n"
            f"入力: {json.dumps(inputs, ensure_ascii=False)}\n"
            f"期待する JSON Schema: {schema_text}\n"
            "出力は JSON 以外のテキストを含めないでください。"
        )

    # --- llm ---------------------------------------------------------------

    def _run_llm(
        self, node: dict[str, Any], inputs: dict[str, Any], context: dict[str, Any]
    ) -> NodeOutcome:
        """Send one non-conversational LLM request and validate its JSON output.

        No tools are bound and no Agent session/message/run is created. The
        request is never sent after a cancel is requested; a cancel that lands
        while the API call is in flight cannot abort it, so the output is kept
        and the engine stops the run without starting the next node.
        """
        config = node.get("config") or {}
        run_id = str(context["run_id"])
        if self._workflow_cancelling(run_id):
            return NodeOutcome(
                status="cancelled",
                result_certainty=CANCEL_CERTAINTY_CANCELLED,
            )
        response = generate_llm_json(
            provider=str(config.get("provider") or ""),
            model=str(config.get("model") or ""),
            system_prompt=str(config.get("system_prompt") or ""),
            inputs=inputs,
            output_schema=config.get("output_schema"),
            max_tokens=int(config.get("max_tokens") or 0),
            reasoning_effort=config.get("reasoning_effort"),
            session_id=str(context["activation_id"]),
        )
        parsed = parse_json_object(response)
        if parsed is None:
            return NodeOutcome(
                status="failed",
                error="LLM 出力を JSON object として解釈できません",
            )
        errors = validate_agent_output(parsed, config.get("output_schema"))
        if errors:
            return NodeOutcome(
                status="failed",
                error="LLM 出力が schema に一致しません: " + "; ".join(errors),
            )
        return NodeOutcome(status="succeeded", output=parsed)

    # --- hitl wait ---------------------------------------------------------

    def _run_hitl_wait(
        self, inputs: dict[str, Any], context: dict[str, Any]
    ) -> NodeOutcome:
        from obsidian_ai_hub.hitl.service import register_run_and_questions

        hitl_run_id = f"whitl_{uuid.uuid4().hex}"
        question = str(inputs.get("question") or "確認してください")
        question_type = str(inputs.get("question_type") or "text")
        choices = inputs.get("choices")
        question_data: dict[str, Any] = {
            "question_key": "workflow_answer",
            "question_type": question_type,
            "display_text": question,
            "title": "Workflow 確認",
            "prompt": question,
            "is_required": 1,
        }
        if isinstance(choices, list):
            question_data["choices"] = choices
        checkpoint = json.dumps(
            {
                "run_id": context["run_id"],
                "node_id": context["node_id"],
                "activation_id": context["activation_id"],
            },
            ensure_ascii=False,
        )
        register_run_and_questions(
            run_id=hitl_run_id,
            handler=HITL_HANDLER,
            checkpoint=checkpoint,
            question_set_id="workflow_question",
            questions_data=[question_data],
            title="Workflow 確認",
            display_type="ワークフロー",
        )
        return NodeOutcome(
            status="waiting_hitl",
            output={},
            hitl_run_id=hitl_run_id,
        )
