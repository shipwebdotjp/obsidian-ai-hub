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

from obsidian_ai_hub.workflow.execution import (
    HITL_HANDLER,
    NodeOutcome,
    parse_json_object,
    validate_agent_output,
)

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
        raise ValueError(f"Node type '{node_type}' は NodeRunner では実行できません")

    # --- capability --------------------------------------------------------

    def _run_capability(
        self, node: dict[str, Any], inputs: dict[str, Any], context: dict[str, Any]
    ) -> NodeOutcome:
        if self._executor is None:
            from obsidian_ai_hub.tasks.adapters import get_default_executor

            self._executor = get_default_executor(poll_interval=self.poll_interval)
        key = (node.get("config") or {}).get("capability_key")
        step = {"capability_key": key, "inputs": inputs}
        task = {"task_id": str(context["run_id"]), "prompt_text": ""}
        plan = {"plan": {"purpose": "", "completion_criteria": ""}}
        result = self._executor.execute_step(task, plan, 0, step)
        output = parse_json_object(result.summary)
        if output is None:
            output = {"summary": result.summary}
        return NodeOutcome(
            status="succeeded",
            output=output,
            satisfied_effects=tuple(result.satisfied_effects or ()),
            child_kind=result.child_kind,
            child_run_id=result.child_run_id,
        )

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
            agent_id, title=f"Workflow {context['run_id']}"[:60]
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
        final = self._wait_for_agent_run(str(context["run_id"]), run_id)
        status = str(final.get("status"))
        if status != "succeeded":
            return NodeOutcome(
                status="failed",
                error=f"Agent run '{run_id}' ended with status '{status}'",
            )
        message_id = final.get("assistant_message_id")
        message = agent_store.get_message(str(message_id)) if message_id else None
        text = str((message or {}).get("content") or "")
        parsed = parse_json_object(text)
        if parsed is None:
            return NodeOutcome(
                status="failed",
                error="Agent 出力を JSON object として解釈できません",
                child_kind="agent",
                child_run_id=run_id,
            )
        errors = validate_agent_output(parsed, output_schema)
        if errors:
            return NodeOutcome(
                status="failed",
                error="Agent 出力が schema に一致しません: " + "; ".join(errors),
                child_kind="agent",
                child_run_id=run_id,
            )
        return NodeOutcome(
            status="succeeded",
            output=parsed,
            child_kind="agent",
            child_run_id=run_id,
        )

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
            time.sleep(self.poll_interval)

    @staticmethod
    def _build_agent_content(inputs: dict[str, Any], output_schema: Any) -> str:
        schema_text = json.dumps(output_schema or {}, ensure_ascii=False)
        return (
            "以下の入力に対して作業し、結果を JSON object のみで出力してください。\n"
            f"入力: {json.dumps(inputs, ensure_ascii=False)}\n"
            f"期待する JSON Schema: {schema_text}\n"
            "出力は JSON 以外のテキストを含めないでください。"
        )

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
