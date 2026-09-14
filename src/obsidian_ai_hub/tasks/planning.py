"""Task planner: turn a free-text request into a structured Plan or a HITL question.

The planner uses the existing Agent provider/model defaults; no Task-specific
model settings exist. It only offers the planner enabled capabilities,
registered agents, and valid projects. Unresolvable targets become an existing
HITL question; the resume handler is registered in the composition root in
Phase 4.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Any, Optional

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.utils.llm_client import generate_llm_response

logger = logging.getLogger(__name__)


TASK_RESOLVE_HANDLER = "tasks.resolve_target"

PLANNER_SYSTEM_PROMPT = """あなたは個人用タスクオーケストレーターのPlannerである。
自由文の依頼を、次に示すJSONだけ(前後の説明やコードフェンスなし)で返す。

Planの場合:
{"type": "plan", "purpose": "目的", "steps": [{"capability_key": "...", "title": "...",
"target": {"agent_id": "..."} または {"project_id": "..."} または {},
"inputs": {...}, "side_effects": "..."}], "completion_criteria": "..."}

対象を一意に解決できない場合:
{"type": "question", "question_text": "...", "choices": ["..."]}

規則:
- stepsのcapability_keyは提示された有効Capabilityだけを使う。
- specialist_agentのtarget.agent_idは提示されたAgent IDだけを使う。
- coding_cliのtarget.project_idは提示されたProject IDだけを使う。
- 提示にないCapability/Agent/Projectが必要ならPlanを作らずquestionを返す。
- 実行時にCapabilityや対象を作り直さない前提で、入力と対象をPlanに固定する。
"""


def default_provider_model() -> tuple[str, str]:
    """Return the existing Agent provider/model defaults."""
    provider = (getattr(config, "AGENT_PROVIDER", None) or "").strip() or "openai"
    model = (getattr(config, "AGENT_MODEL", None) or "").strip() or "gpt-4o"
    return provider, model


def collect_planner_context() -> dict[str, Any]:
    """Collect enabled capabilities, registered agents, and valid projects."""
    from obsidian_ai_hub.agents import store as agent_store

    capabilities = [
        {
            "capability_key": c["capability_key"],
            "adapter_kind": c["adapter_kind"],
            "approval_policy": c["approval_policy"],
        }
        for c in task_store.list_capabilities()
        if c["enabled"]
    ]
    agents = [
        {"agent_id": a["agent_id"], "name": a.get("name", "")}
        for a in agent_store.list_agents()
    ]
    projects = _valid_projects()
    return {"capabilities": capabilities, "agents": agents, "projects": projects}


def _valid_projects() -> list[dict[str, Any]]:
    from obsidian_ai_hub.coding.backend import validate_git_repo
    from obsidian_ai_hub.web.services import projects as project_service

    valid: list[dict[str, Any]] = []
    for project in project_service.list_projects():
        project_id = project.get("project_id")
        project_path = project.get("project_path")
        if not project_id or not project_path:
            continue
        try:
            git_root = validate_git_repo(str(project_path))
        except Exception:
            logger.warning(
                "Skipping project '%s': git root unresolvable (%s)",
                project_id,
                project_path,
            )
            continue
        valid.append(
            {
                "project_id": project_id,
                "name": project.get("name", ""),
                "git_root": git_root,
            }
        )
    return valid


def build_planner_prompt(prompt_text: str, context: dict[str, Any]) -> str:
    capability_lines = [
        f"- {c['capability_key']} ({c['adapter_kind']}, {c['approval_policy']}): "
        for c in context["capabilities"]
    ]
    agent_lines = [f"- {a['agent_id']}: {a['name']}" for a in context["agents"]]
    project_lines = [
        f"- {p['project_id']}: {p['name']} ({p['git_root']})"
        for p in context["projects"]
    ]
    return (
        f"依頼:\n{prompt_text}\n\n"
        f"有効Capability:\n" + "\n".join(capability_lines) + "\n\n"
        "登録済みAgent:\n" + "\n".join(agent_lines) + "\n\n"
        "有効Project:\n" + "\n".join(project_lines)
    )


def parse_planner_output(raw: str) -> dict[str, Any]:
    """Parse the planner LLM output. Raises ValueError when invalid."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        output = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner output is not valid JSON: {e}") from e
    if not isinstance(output, dict):
        raise ValueError("Planner output must be a JSON object.")
    output_type = output.get("type")
    if output_type == "plan":
        return _validate_plan_shape(output)
    if output_type == "question":
        return _validate_question_shape(output)
    raise ValueError(f"Planner output has unknown type: {output_type!r}.")


def _validate_plan_shape(output: dict[str, Any]) -> dict[str, Any]:
    purpose = output.get("purpose")
    steps = output.get("steps")
    completion_criteria = output.get("completion_criteria")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("Plan requires a non-blank purpose.")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Plan requires a non-empty steps list.")
    if not isinstance(completion_criteria, str) or not completion_criteria.strip():
        raise ValueError("Plan requires non-blank completion_criteria.")
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"Plan step {index} must be an object.")
        for field in ("capability_key", "title", "target", "inputs"):
            if field not in step:
                raise ValueError(f"Plan step {index} is missing '{field}'.")
        if not isinstance(step["target"], dict) or not isinstance(step["inputs"], dict):
            raise ValueError(f"Plan step {index} target/inputs must be objects.")
    return output


def _validate_question_shape(output: dict[str, Any]) -> dict[str, Any]:
    question_text = output.get("question_text")
    if not isinstance(question_text, str) or not question_text.strip():
        raise ValueError("Question requires non-blank question_text.")
    choices = output.get("choices")
    if choices is not None:
        if (
            not isinstance(choices, list)
            or not choices
            or not all(isinstance(c, str) and c.strip() for c in choices)
        ):
            raise ValueError("Question choices must be a non-empty list of strings.")
    return output


def validate_plan_targets(
    plan: dict[str, Any], context: dict[str, Any]
) -> dict[str, str]:
    """Check step capability/agent/project references. Returns policy snapshot."""
    enabled = {
        c["capability_key"]: c["approval_policy"] for c in context["capabilities"]
    }
    agent_ids = {a["agent_id"] for a in context["agents"]}
    project_ids = {p["project_id"] for p in context["projects"]}
    snapshot: dict[str, str] = {}
    for index, step in enumerate(plan["steps"]):
        key = step["capability_key"]
        if key not in enabled:
            raise ValueError(
                f"Plan step {index} uses unknown or disabled capability '{key}'."
            )
        snapshot[key] = enabled[key]
        target = step["target"]
        if key == "specialist_agent":
            agent_id = target.get("agent_id")
            if agent_id not in agent_ids:
                raise ValueError(
                    f"Plan step {index} targets unregistered agent '{agent_id}'."
                )
        elif key == "coding_cli":
            project_id = target.get("project_id")
            if project_id not in project_ids:
                raise ValueError(
                    f"Plan step {index} targets invalid project '{project_id}'."
                )
    return snapshot


def plan_task(
    task_id: str, conn: Optional[sqlite3.Connection] = None
) -> dict[str, Any]:
    """Run the planner for a claimed (``planning``) task.

    Returns ``{"outcome": "waiting_approval" | "running" | "waiting_user", ...}``.
    Invalid planner output fails the task immediately (``planning`` -> ``failed``).
    """
    with task_store.auto_connection(conn) as (active_conn, _):
        task = task_store.get_task(task_id, conn=active_conn)
        if task is None:
            raise FileNotFoundError(f"Task '{task_id}' not found.")
    context = collect_planner_context()
    provider, model = default_provider_model()
    try:
        raw = generate_llm_response(
            provider,
            model,
            build_planner_prompt(str(task["prompt_text"]), context),
            system_prompt=PLANNER_SYSTEM_PROMPT,
            session_id=f"task-plan-{task_id}",
        )
        output = parse_planner_output(raw)
        snapshot: Optional[dict[str, str]] = None
        if output["type"] == "plan":
            snapshot = validate_plan_targets(output, context)
    except Exception as exc:
        _fail_task(task_id, exc, conn=conn)
        raise ValueError(f"Planner failed for task '{task_id}': {exc}") from exc

    # HITL registration commits on its own connection (register_run_and_questions
    # uses `with conn:`), so it must not join the task transaction below. If the
    # task left planning in the meantime, the question run stays orphaned until
    # the Phase 4 cancel API cancels linked HITL runs.
    hitl_run_id: Optional[str] = None
    if output["type"] == "question":
        hitl_run_id = _register_target_question_hitl(task_id, task, output)

    with task_store.auto_connection(conn) as (active_conn, is_generated):

        def _do() -> dict[str, Any]:
            _require_planning(task_id, conn=active_conn)
            if output["type"] == "question":
                assert hitl_run_id is not None
                task_store.append_task_event(
                    task_id,
                    "hitl_question_asked",
                    {"hitl_run_id": hitl_run_id, "question_set_id": "target"},
                    conn=active_conn,
                )
                updated = task_store.transition_task_status(
                    task_id, "waiting_user", conn=active_conn
                )
                return {
                    "outcome": "waiting_user",
                    "task": updated,
                    "hitl_run_id": hitl_run_id,
                }
            assert snapshot is not None
            plan_record = task_store.create_plan(
                task_id,
                {
                    "purpose": output["purpose"],
                    "steps": output["steps"],
                    "completion_criteria": output["completion_criteria"],
                },
                snapshot,
                conn=active_conn,
            )
            task_store.append_task_event(
                task_id,
                "plan_created",
                {"plan_id": plan_record["plan_id"], "version": plan_record["version"]},
                conn=active_conn,
            )
            if any(policy == "plan_required" for policy in snapshot.values()):
                updated = task_store.transition_task_status(
                    task_id, "waiting_approval", conn=active_conn
                )
                return {
                    "outcome": "waiting_approval",
                    "task": updated,
                    "plan": plan_record,
                }
            updated = task_store.transition_task_status(
                task_id, "running", conn=active_conn
            )
            return {"outcome": "running", "task": updated, "plan": plan_record}

        if is_generated:
            with active_conn:
                return _do()
        else:
            return _do()


def _fail_task(
    task_id: str, exc: Exception, conn: Optional[sqlite3.Connection] = None
) -> None:
    with task_store.auto_connection(conn) as (active_conn, is_generated):

        def _do() -> None:
            task_store.transition_task_status(
                task_id, "failed", error_summary=str(exc), conn=active_conn
            )
            task_store.append_task_event(
                task_id, "note", {"text": f"planner failed: {exc}"}, conn=active_conn
            )

        if is_generated:
            with active_conn:
                _do()
        else:
            _do()


def _require_planning(task_id: str, conn: sqlite3.Connection) -> None:
    """Raise unless the task is still in ``planning`` (LLM calls take time)."""
    current = task_store.get_task(task_id, conn=conn)
    if current is None:
        raise FileNotFoundError(f"Task '{task_id}' not found.")
    if str(current["status"]) != "planning":
        raise ValueError(
            f"Task '{task_id}' is no longer in 'planning' (now '{current['status']}')."
        )


def _register_target_question_hitl(
    task_id: str,
    task: dict[str, Any],
    output: dict[str, Any],
) -> str:
    from obsidian_ai_hub.hitl.service import register_run_and_questions

    hitl_run_id = f"tasks_{task_id}_{uuid.uuid4().hex[:8]}"
    question_text = str(output["question_text"]).strip()
    choices = output.get("choices")
    if choices:
        question: dict[str, Any] = {
            "question_key": "target",
            "question_type": "select",
            "display_text": question_text,
            "title": "Taskの対象確認",
            "prompt": question_text,
            "choices": [{"value": choice, "label": choice} for choice in choices],
            "is_required": 1,
        }
    else:
        question = {
            "question_key": "target",
            "question_type": "text",
            "display_text": question_text,
            "title": "Taskの対象確認",
            "prompt": question_text,
            "is_required": 1,
        }
    register_run_and_questions(
        run_id=hitl_run_id,
        handler=TASK_RESOLVE_HANDLER,
        checkpoint=json.dumps({"task_id": task_id}, ensure_ascii=False),
        question_set_id="target",
        questions_data=[question],
        title="Taskの対象確認",
        description=str(task["prompt_text"])[:200],
        display_type="task_target_question",
    )
    return hitl_run_id
