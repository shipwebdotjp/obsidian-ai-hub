"""Runtime Orchestrator: dynamic agent loop over an approved Directional Plan.

The planner approves *direction* (purpose, strategy, allowed capabilities,
constraints, completion criteria). This loop generates each tool call's
detailed inputs at execution time from prior observations, validates every
action against the approval scope and the single-source Pydantic schema,
executes via the existing adapters, and records auditable events.

Exactly-once is NOT guaranteed: a crash between a side-effecting tool call
and its ``capability_completed`` event can replay that action on resume
(see Consequences in the ADR). Resume is deterministic best-effort keyed on
``action_index`` in ``capability_completed`` events.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.directional import (
    DEFAULT_MAX_ACTIONS,
    DirectionalPlan,
    approval_scope,
    is_directional_plan,
    parse_directional_plan,
)
from obsidian_ai_hub.tasks.execution import (
    DeviationReported,
    ExecutorOutcome,
    StepResult,
    TaskCancelled,
)
from obsidian_ai_hub.tasks.redaction import redact_text

logger = logging.getLogger(__name__)

OBSERVATION_LIMIT = 2000
MAX_SELF_CORRECTIONS = 2
MAX_REPEATS = 2

# Prompt-side observation budgets (chars). The newest observation keeps the
# largest window because the finish decision depends on its completion
# evidence; older observations are compressed progressively. The history
# section total is capped separately so long loops cannot blow up the prompt.
OBSERVATION_HEAD = 500
OBSERVATION_TAIL = 1500
OLDER_OBSERVATION_HEAD = 200
OLDER_OBSERVATION_TAIL = 600
HISTORY_TOTAL_BUDGET = 60000

ORCHESTRATOR_SYSTEM_PROMPT = """あなたはTask実行のRuntime Orchestratorである。
承認済みDirectional Planの目的・Capability範囲・制約の中で、次の一手を
次のJSONだけ(前後の説明やコードフェンスなし)で返す。

Capability呼び出しの場合:
{"action": "call_capability", "capability_key": "...",
 "target": {"agent_id": "..."} または {"project_id": ...} または {},
 "inputs": {...}, "reason": "この一手を選んだ理由"}

完了の場合:
{"action": "finish", "summary": "タスク全体の結果要約", "reason": "完了と判断した理由"}

規則:
- capability_keyは承認されたCapability範囲の中からのみ選ぶ。範囲外が必要なら
  finishせず、範囲外のCapabilityを選ばずに、現状の要約でfinishする
  (範囲外の実行は親がreapprovalへ回すため、自己判断で実行しない)。
- inputsは提示された入力schemaに従い、必須fieldをすべて含め、未知のキーを
  含めない。先行Observationの値を参照して具体値を生成する。
- specialist_agent/coding_cliではtargetに対象IDを入れ、inputs.taskに作業指示を書く。
- 秘密値 (APIキー、トークン等) をinputsやreasonに含めない。
- 同じCapability・同じinputsの反復は避け、進展がない場合はfinishする。
- 完了条件を満たした、またはこれ以上有効な一手がないと判断したらfinishする。
- 直前のObservationに完了条件の達成証拠（テスト結果・コミットSHA等）が具体的に
  含まれる場合は、同一内容の再検証のための追加呼び出しを避け、その証拠を引用して
  finishで要約する。独立した検証が真に必要な場合に限り、最小限の追加Actionに留める。
"""


class RuntimeAction(BaseModel):
    """Structured next-action output from the Runtime Orchestrator."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["call_capability", "finish"]
    capability_key: Optional[str] = None
    target: Optional[dict[str, Any]] = None
    inputs: Optional[dict[str, Any]] = None
    summary: Optional[str] = None
    reason: str = ""


ActionGenerator = Callable[[str], dict[str, Any]]
"""Injectable next-action source for tests: prompt text -> raw action dict."""


def _parse_action(raw: dict[str, Any]) -> RuntimeAction:
    try:
        return RuntimeAction.model_validate(raw)
    except Exception as exc:
        raise ValueError(f"Invalid orchestrator action: {exc}") from exc


class _ScopeViolation(ValueError):
    """Delegate target outside the approval-time allowlist."""


def _enforce_target_scope(
    capability_key: str, target: dict[str, Any], scope: dict[str, Any]
) -> None:
    """Reject delegate targets outside the approval-time allowlist.

    Raises ``_ScopeViolation`` when the orchestrator aims at an agent/project
    the approved plan never allowed. Handled like other validation errors
    (limited self-correction), except exhaustion routes to deviation /
    reapproval instead of failure so a human can approve the new target.
    """
    if capability_key == "specialist_agent":
        allowed = set(scope.get("allowed_agent_ids") or [])
        agent_id = target.get("agent_id")
        if agent_id not in allowed:
            raise _ScopeViolation(
                f"specialist_agent target '{agent_id}' is outside the approved "
                f"agent scope {sorted(allowed)}."
            )
    elif capability_key == "coding_cli":
        allowed_ids = set()
        for candidate in scope.get("allowed_project_ids") or []:
            try:
                allowed_ids.add(int(candidate))
            except (TypeError, ValueError):
                continue
        try:
            project_id = int(target.get("project_id"))
        except (TypeError, ValueError):
            raise ValueError(
                f"coding_cli target project '{target.get('project_id')}' is invalid."
            )
        if project_id not in allowed_ids:
            raise _ScopeViolation(
                f"coding_cli target project '{project_id}' is outside the "
                f"approved project scope {sorted(allowed_ids)}."
            )


def _truncate(text: str, limit: int = OBSERVATION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(truncated)"


def _truncate_observation(
    text: str, head: int = OBSERVATION_HEAD, tail: int = OBSERVATION_TAIL
) -> str:
    """Truncate a child-run observation while preserving its conclusion.

    Child results report evidence (test counts, commit SHAs) at the end, so
    head-only truncation drops exactly what the finish decision needs. Keep
    both ends within the same overall budget as the prompt history slot.
    """
    if len(text) <= head + tail:
        return text
    omitted = len(text) - head - tail
    return text[:head] + f"\n...({omitted} chars omitted)...\n" + text[-tail:]


def _compress_history_lines(
    history: list[dict[str, Any]], budget: int = HISTORY_TOTAL_BUDGET
) -> list[str]:
    """Render history lines within a total char budget.

    The newest action always keeps its full observation budget. When the
    section overflows, the oldest actions collapse to one-line summaries
    first. Redaction happens before rendering so secrets never enter the
    prompt regardless of compression.
    """
    rendered: list[tuple[int, str, str]] = []
    for position, item in enumerate(history):
        is_latest = position == len(history) - 1
        safe_inputs = redact_text(_canonical_inputs(item.get("inputs")))
        action_line = (
            f"- Action {item.get('action_index')}: "
            f"{item.get('capability_key')} "
            f"inputs={_truncate(safe_inputs, 500)}"
        )
        safe_observation = redact_text(str(item.get("observation") or ""))
        if is_latest:
            observation_line = _truncate_observation(
                safe_observation, OBSERVATION_HEAD, OBSERVATION_TAIL
            )
        else:
            observation_line = _truncate_observation(
                safe_observation, OLDER_OBSERVATION_HEAD, OLDER_OBSERVATION_TAIL
            )
        rendered.append(
            (int(item.get("action_index") or 0), action_line, observation_line)
        )
    total = sum(len(action) + len(observation) for _, action, observation in rendered)
    index = 0
    while total > budget and index < len(rendered) - 1:
        action_index, action_line, observation_line = rendered[index]
        summary = (
            f"  Observation: (older action {action_index} observation "
            f"{len(observation_line)} chars, omitted for budget)"
        )
        total -= len(observation_line) - len(summary)
        rendered[index] = (action_index, action_line, summary)
        index += 1
    lines: list[str] = []
    for _, action_line, observation_line in rendered:
        lines.append(action_line)
        if observation_line.startswith("  Observation:"):
            lines.append(observation_line)
        else:
            lines.append(f"  Observation: {observation_line}")
    return lines


def _canonical_inputs(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(value)


def _completed_actions(task_id: str, conn: Any = None) -> list[dict[str, Any]]:
    """Reload auditable completed actions for resume (no re-execution).

    Deduplicates by ``action_index`` (keeps the first record) so gaps or
    duplicate events can never cause a replay or an index collision.
    """
    seen: dict[int, dict[str, Any]] = {}
    for event in task_store.list_task_events(task_id, conn=conn):
        if event.get("event_type") != "capability_completed":
            continue
        payload = event.get("payload") or {}
        try:
            index = int(payload.get("action_index"))
        except (TypeError, ValueError):
            continue
        seen.setdefault(index, payload)
    return [seen[index] for index in sorted(seen)]


def build_orchestrator_prompt(
    task: dict[str, Any],
    plan: DirectionalPlan,
    scope: dict[str, Any],
    schemas: dict[str, str | None],
    history: list[dict[str, Any]],
    correction: str | None = None,
) -> str:
    lines = [
        f"依頼:\n{redact_text(str(task.get('prompt_text') or ''))}",
        "",
        f"承認済み目的:\n{plan.purpose}",
    ]
    if plan.strategy:
        lines += ["", f"実行方針:\n{plan.strategy}"]
    lines += ["", "承認されたCapability範囲:"]
    for directive in plan.capabilities:
        lines.append(f"- {directive.capability_key}: {directive.intent or '(意図なし)'}")
        schema_text = schemas.get(directive.capability_key)
        if schema_text:
            indented = "\n".join(f"    {l}" for l in str(schema_text).splitlines())
            lines.append(indented)
    if plan.constraints:
        lines += ["", f"制約:\n{plan.constraints}"]
    if plan.allowed_agent_ids:
        lines += [
            "",
            "委譲可能なAgent ID (specialist_agentのtarget.agent_idはこの中からのみ):",
            "  " + ", ".join(plan.allowed_agent_ids),
        ]
    if plan.allowed_project_ids:
        lines += [
            "",
            "実行可能なProject ID (coding_cliのtarget.project_idはこの中からのみ):",
            "  " + ", ".join(str(p) for p in plan.allowed_project_ids),
        ]
    lines += ["", f"完了条件:\n{plan.completion_criteria}"]
    if history:
        lines += ["", "過去のActionとObservation:"]
        lines += _compress_history_lines(history)
    else:
        lines += ["", "過去のActionとObservation: なし(最初の一手)"]
    if correction:
        lines += ["", f"直前の出力への修正指示:\n{correction}"]
    return "\n".join(lines)


def _default_generator(
    task_id: str, action_index: int
) -> ActionGenerator:
    from obsidian_ai_hub.tasks.planning import default_provider_model
    from obsidian_ai_hub.utils.llm_client import generate_llm_response

    provider, model = default_provider_model()

    def _generate(prompt: str) -> dict[str, Any]:
        raw = generate_llm_response(
            provider,
            model,
            prompt,
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            session_id=f"task-orch-{task_id}-{action_index}",
        )
        text = raw.strip()
        if text.startswith("```"):
            parts = text.splitlines()
            if parts and parts[0].startswith("```"):
                parts = parts[1:]
            if parts and parts[-1].strip().startswith("```"):
                parts = parts[:-1]
            text = "\n".join(parts).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Orchestrator returned non-JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Orchestrator output must be a JSON object.")
        return parsed

    return _generate


def run_directional_plan(
    task_id: str,
    plan_record: dict[str, Any],
    executor: Any = None,
    action_generator: ActionGenerator | None = None,
    conn: Any = None,
) -> ExecutorOutcome:
    """Run the approved directional plan as a dynamic agent loop."""
    from obsidian_ai_hub.tasks.adapters import get_default_executor
    from obsidian_ai_hub.tasks.capability_schemas import (
        compact_schema_text,
        validate_capability_inputs,
        validate_capability_target,
    )

    task = task_store.get_task(task_id, conn=conn)
    if task is None:
        raise FileNotFoundError(f"Task '{task_id}' not found.")
    plan_inner = plan_record.get("plan") or {}
    if not is_directional_plan(plan_inner):
        return ExecutorOutcome(
            kind="failed", error_summary="current plan is not a directional plan"
        )
    try:
        plan = parse_directional_plan(dict(plan_inner))
    except ValueError as exc:
        return ExecutorOutcome(kind="failed", error_summary=str(exc))

    scope = approval_scope(plan)
    allowed = set(scope["capability_keys"])
    max_actions = plan.max_actions or DEFAULT_MAX_ACTIONS
    schemas = {key: compact_schema_text(key) for key in allowed}

    active_executor = executor or get_default_executor()
    completed = _completed_actions(task_id, conn=conn)
    history: list[dict[str, Any]] = [
        {
            "action_index": int(p.get("action_index")),
            "capability_key": str(p.get("capability_key", "")),
            "target": p.get("target") or {},
            "inputs": p.get("inputs"),
            "observation": str(p.get("observation") or p.get("summary") or ""),
        }
        for p in completed
    ]
    next_index = (
        max(item["action_index"] for item in history) + 1 if history else 0
    )
    if next_index >= max_actions:
        return ExecutorOutcome(
            kind="failed",
            error_summary=f"最大Action数({max_actions})に到達済みのため再開できない",
        )

    corrections = 0
    repeats = 0
    last_signature: str | None = None
    if history:
        last = history[-1]
        last_signature = f"{last['capability_key']}:{_canonical_inputs(last['inputs'])}"
    pending_correction: str | None = None

    while next_index < max_actions:
        current = task_store.get_task(task_id, conn=conn)
        if current is not None and str(current.get("status")) == "cancelling":
            task_store.clear_active_child(task_id, conn=conn)
            raise TaskCancelled("Task was cancelled during orchestration.")

        prompt = build_orchestrator_prompt(
            task, plan, scope, schemas, history, pending_correction
        )
        pending_correction = None
        generate = action_generator or _default_generator(task_id, next_index)
        try:
            raw_action = generate(prompt)
        except Exception as exc:
            logger.exception("Orchestrator generation failed for task %s", task_id)
            return ExecutorOutcome(
                kind="failed", error_summary=f"orchestrator generation failed: {exc}"
            )
        try:
            action = _parse_action(raw_action)
        except ValueError as exc:
            corrections += 1
            task_store.append_task_event(
                task_id,
                "note",
                {
                    "text": f"orchestrator action {next_index} parse error: {exc}",
                    "action_index": next_index,
                },
                conn=conn,
            )
            if corrections > MAX_SELF_CORRECTIONS:
                return ExecutorOutcome(
                    kind="failed",
                    error_summary=f"orchestrator output invalid after {MAX_SELF_CORRECTIONS} corrections: {exc}",
                )
            pending_correction = (
                "前回の出力は構造として不正だった。JSON objectで "
                f"action/call_capability/finish形式を守ること。誤り: {exc}"
            )
            continue

        if action.action == "finish":
            summary = (action.summary or "").strip()
            if not summary:
                corrections += 1
                if corrections > MAX_SELF_CORRECTIONS:
                    return ExecutorOutcome(
                        kind="failed",
                        error_summary="finish action requires a non-blank summary",
                    )
                pending_correction = (
                    "finishには非空のsummaryが必要。結果要約を入れてfinishすること。"
                )
                continue
            task_store.clear_active_child(task_id, conn=conn)
            return ExecutorOutcome(kind="completed", result_summary=summary)

        # call_capability path
        capability_key = str(action.capability_key or "")
        if capability_key not in allowed:
            task_store.append_task_event(
                task_id,
                "note",
                {
                    "text": (
                        f"orchestrator requested out-of-scope capability "
                        f"'{capability_key}'; stopping for reapproval"
                    ),
                    "action_index": next_index,
                    "capability_key": capability_key,
                },
                conn=conn,
            )
            task_store.clear_active_child(task_id, conn=conn)
            return ExecutorOutcome(
                kind="deviation",
                deviation_reason=(
                    f"Approval scope外のCapability '{capability_key}' が要求された"
                ),
            )

        raw_target = action.target if action.target is not None else {}
        raw_inputs = action.inputs if action.inputs is not None else {}
        try:
            validated_target = validate_capability_target(capability_key, raw_target)
            validated_inputs = validate_capability_inputs(capability_key, raw_inputs)
            _enforce_target_scope(capability_key, validated_target, scope)
        except ValueError as exc:
            corrections += 1
            task_store.append_task_event(
                task_id,
                "note",
                {
                    "text": f"orchestrator action {next_index} validation error: {exc}",
                    "action_index": next_index,
                    "capability_key": capability_key,
                },
                conn=conn,
            )
            if corrections > MAX_SELF_CORRECTIONS:
                if isinstance(exc, _ScopeViolation):
                    # Persistent scope violation: let a human approve the new
                    # target instead of failing the task outright.
                    task_store.clear_active_child(task_id, conn=conn)
                    return ExecutorOutcome(
                        kind="deviation",
                        deviation_reason=str(exc),
                    )
                return ExecutorOutcome(
                    kind="failed",
                    error_summary=(
                        f"action validation failed after "
                        f"{MAX_SELF_CORRECTIONS} corrections: {exc}"
                    ),
                )
            pending_correction = (
                "前回のinputs/targetは入力モデル検証に失敗した。schemaに従い "
                f"必須field・型・enum・未知キーを見直すこと。誤り: {exc}"
            )
            continue

        signature = f"{capability_key}:{_canonical_inputs(validated_inputs)}"
        if signature == last_signature:
            repeats += 1
            if repeats >= MAX_REPEATS:
                return ExecutorOutcome(
                    kind="failed",
                    error_summary="同一Capability・同一入力の反復を検出したため停止",
                )
            pending_correction = (
                "直前と同一Capability・同一入力の反復を検出。入力を変えるか、"
                "完了しているならfinishすること。"
            )
            # Do not execute the duplicate; ask for a revised action.
            continue

        step = {
            "capability_key": capability_key,
            "target": validated_target,
            "inputs": validated_inputs,
            "title": action.reason or capability_key,
        }
        try:
            result: StepResult = active_executor.execute_step(
                task, plan_record, next_index, step
            )
        except TaskCancelled:
            # The worker owns the cancelling -> cancelled transition.
            raise
        except DeviationReported as dev:
            # A child run needs out-of-plan work. Mirror the legacy runner:
            # persist the completed actions plus the reported steps as the
            # next (legacy-shaped) plan version and yield to reapproval.
            revised_steps = []
            for item in history:
                revised_steps.append(
                    {
                        "capability_key": item["capability_key"],
                        "title": f"Action {item['action_index']} (completed)",
                        "target": item.get("target") or {},
                        "inputs": item["inputs"] or {},
                        "side_effects": "already executed",
                    }
                )
            reported = dev.revised_plan.get("steps") if isinstance(
                dev.revised_plan, dict
            ) else None
            if isinstance(reported, list):
                revised_steps.extend(reported)
            revised = task_store.create_plan(
                task_id,
                {
                    "purpose": plan.purpose,
                    "steps": revised_steps,
                    "completion_criteria": plan.completion_criteria,
                },
                dict(plan_record.get("approval_policy_snapshot") or {}),
                conn=conn,
            )
            task_store.append_task_event(
                task_id,
                "note",
                {
                    "text": f"deviation reported: {dev.reason}",
                    "revised_plan_id": revised["plan_id"],
                },
                conn=conn,
            )
            task_store.clear_active_child(task_id, conn=conn)
            return ExecutorOutcome(
                kind="deviation",
                revised_plan=dev.revised_plan,
                deviation_reason=dev.reason,
            )
        except Exception as exc:
            logger.exception("Orchestrated action failed for task %s", task_id)
            task_store.clear_active_child(task_id, conn=conn)
            task_store.append_task_event(
                task_id,
                "note",
                {
                    "text": f"orchestrator action {next_index} tool failed: {exc}",
                    "action_index": next_index,
                    "capability_key": capability_key,
                },
                conn=conn,
            )
            return ExecutorOutcome(kind="failed", error_summary=str(exc))

        observation = _truncate(str(result.summary or ""))
        # Match the legacy runner order (execution.py): record the active
        # child before the completion event so a crash between the two never
        # orphans a running child run from cancellation propagation.
        if result.child_kind and result.child_run_id:
            task_store.set_active_child(
                task_id, result.child_kind, result.child_run_id, conn=conn
            )
        task_store.append_task_event(
            task_id,
            "capability_completed",
            {
                "action_index": next_index,
                "step_index": next_index,
                "capability_key": result.capability_key,
                "target": validated_target,
                "inputs": validated_inputs,
                "summary": result.summary,
                "observation": observation,
                "child_kind": result.child_kind,
                "child_run_id": result.child_run_id,
            },
            conn=conn,
        )
        history.append(
            {
                "action_index": next_index,
                "capability_key": result.capability_key,
                "target": validated_target,
                "inputs": validated_inputs,
                "observation": observation,
            }
        )
        last_signature = signature
        next_index += 1
        corrections = 0
        repeats = 0

    return ExecutorOutcome(
        kind="failed",
        error_summary=f"最大Action数({max_actions})に到達したため停止",
    )
