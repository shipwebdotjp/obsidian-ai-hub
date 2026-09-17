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

TARGET_CONFIDENCE_THRESHOLD = 0.75
"""Adopt an inferred target resolution at/above this decision score.

Below the threshold the plan is not saved and a HITL question with all
valid projects plus "general" is registered instead. This is a branching
score for the human question, not a statistical probability.
"""

HISTORY_FRAGMENT_LIMIT = 300
"""Max chars per coding-history fragment (session title / user request)."""

PROJECT_HISTORY_LIMIT = 800
"""Max chars of coding history rendered per project."""

TOTAL_HISTORY_LIMIT = 12000
"""Max chars of coding history rendered across all projects."""

PLANNER_SYSTEM_PROMPT = """あなたは個人用タスクオーケストレーターのPlannerである。
自由文の依頼を、次に示すJSONだけ(前後の説明やコードフェンスなし)で返す。
あなたが作るのはDirectional Planである: 承認対象は全体の方向性・目的・
許可するCapability範囲・主要な制約であり、個々のツール呼び出しの詳細入力
(inputs)を事前確定しない。詳細入力はRuntime Orchestratorが実行時に生成する。

Planの場合:
{"type": "plan", "plan_version": 3, "purpose": "目的", "strategy": "実行方針の概要",
 "capabilities": [{"capability_key": "...", "intent": "そのCapabilityを使う大まかな意図"}],
 "constraints": "主要な制約(触れてはならない範囲など)",
 "completion_criteria": "完了条件", "max_actions": 8,
 "project_resolution": {"kind": "project", "project_id": 1,
   "display_name": "Obsidian AI Hub", "confidence": 0.9,
   "rationale": "依頼文にProject名が含まれる", "source": "inferred"}}

  対象解決: project_resolutionは必須で、Taskの主対象を1件だけ選ぶ。
  特定Projectの作業なら {"kind": "project", "project_id": <数値ID>}、
  特定Projectに属さない一般作業なら {"kind": "general"} とする。
  複数repoにまたがる作業は想定しない（別Taskに分ける運用）。
  confidenceは0から1の判断スコアであり、統計的確率ではない。
  0.75以上は自動採択、未満は人間に質問されPlanは作り直しになる。
  曖昧な場合は低めに付け、勝手に高く見積もらない。
  display_nameは提示されたProject名の写し、rationaleは短い根拠、
  sourceは常に "inferred" とする。

  委譲対象の扱い: specialist_agent / coding_cli の具体的な対象ID
  (agent_id / project_id) はPlanに書かない。specialist_agentを使うなら
  intentにどのAgentを使うかの目安を書き、coding_cliを使うならどのProjectを
  使うかの目安を書く。project_resolutionで選んだProjectだけが実行範囲に
  なる。登録済みAgentが一つもないのにspecialist_agentを、有効Projectが
  ないのにcoding_cliを選んではならない。その場合はquestionを返す。
  kind=generalのPlanにcoding_cliを含めてはならない。

  対象を一意に解決できない場合(question以外で解決できない場合):
  {"type": "question", "question_text": "...",
   "options": [{"value": "project:1", "label": "Project 1: Obsidian AI Hub"},
               {"value": "agent:agent_1", "label": "Helper"}]}

  規則:
  - capabilitiesのcapability_keyは提示された有効Capabilityだけを使う。
  - 各capabilityのintentには詳細な引数値ではなく大まかな用途を書く。
    inputsの具体値 (query/content等) をPlanに固定してはならない。
  - specialist_agentを使う場合はintentにどのAgentを使うかの目安を書く。
    最終的なagent_id解決はRuntime Orchestratorが行うが、提示されたAgent IDの範囲を超えてはならない。
  - coding_cliを使う場合はintentにどのProjectを使うかの目安を書く。
    提示にないProjectが必要ならPlanを作らずquestionを返す。
  - research_agentを使う場合はintentにどのテーマを調査するかの目安を書く。
    targetは空でよい。theme/mode/contextの具体値はPlanに固定しない。
  - 依頼文に登録済みProjectの名前・キーワードが含まれる場合、または直近の
    Coding履歴と一致する場合は対象が確定している。その場合は該当Projectを
    高いconfidenceで選び、intentに明記したPlanを作る。
  - 直近Coding履歴は推定材料であり、依頼文と無関係なら無視してよい。
    対象が曖昧ならconfidenceを下げ、一般作業と判断できる場合のみ
    kind=generalにする。
  - 提示にないCapability/Agent/Projectが必要ならPlanを作らずquestionを返す。
    optionsに挙げられる対象は提示された有効Project/Agentだけを使う。
    optionsのvalueは "project:<project_id>"、"agent:<agent_id>"、または自由文テキストとし、
    labelは人間に表示する文言とする。
  - 承認対象は方向性とCapability範囲である。Planに詳細inputsを含めない。
  - max_actionsは1以上30以下の整数で、省略時は8とする。
    まだActionを実行していないため完了済みは0である。max_actionsには実行予定の
    Action数にfinishの1枠を含めて明示する(読取り4回なら5)。
  - 依頼または完了条件でresearch_theme_proposeによる提案が必須の場合、
    提案(research_theme_propose)と完了(finish)の2枠を必ず残す。例えば読取りに
    4回使うPlanならmax_actions=6とする。読取りActionに枠を使い切ってはならない。
  - 以前の質問と回答がある場合、その回答は確定事項である。回答に従って対象を確定し
    Planを作り、回答済みの質問を再質問してはならない。
    回答にコメントが付いている場合、そのコメントも確定事項として尊重する。
  - 過去の却下Planと差戻し理由がある場合、それらは確定の制約である。
    差戻し理由に反するPlan（同じCapability構成・同じ委譲先の繰り返しなど）を
    再提案してはならない。
  - 質問は依頼文から対象がまったく推定できないときだけ使う。
  """


def default_provider_model() -> tuple[str, str]:
    """Return the existing Agent provider/model defaults."""
    provider = (getattr(config, "AGENT_PROVIDER", None) or "").strip() or "openai"
    model = (getattr(config, "AGENT_MODEL", None) or "").strip() or "gpt-4o"
    return provider, model


def collect_planner_context() -> dict[str, Any]:
    """Collect enabled capabilities, registered agents, and valid projects.

    Capability entries carry the code-defined label/description plus a
    compact input schema derived from the single-source Pydantic model
    (``tasks/capability_schemas.py``). No runtime-injected values
    (``trusted_ctx``, API keys, session ids) are ever included.
    """
    from obsidian_ai_hub.agents import store as agent_store
    from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
    from obsidian_ai_hub.tasks.capability_schemas import compact_schema_text

    catalog = {d.key: d for d in get_capability_definitions()}
    capabilities = []
    for c in task_store.list_capabilities():
        if not c["enabled"]:
            continue
        key = c["capability_key"]
        definition = catalog.get(key)
        capabilities.append(
            {
                "capability_key": key,
                "adapter_kind": c["adapter_kind"],
                "approval_policy": c["approval_policy"],
                "label": definition.label if definition else key,
                "description": definition.description if definition else "",
                "input_schema": compact_schema_text(key),
            }
        )
    agents = [
        {"agent_id": a["agent_id"], "name": a.get("name", "")}
        for a in agent_store.list_agents()
    ]
    projects = _valid_projects()
    _attach_project_histories(projects)
    return {"capabilities": capabilities, "agents": agents, "projects": projects}


def list_valid_projects() -> list[dict[str, Any]]:
    """Return the valid Git projects offered to the planner (public alias)."""
    return _valid_projects()


def _attach_project_histories(projects: list[dict[str, Any]]) -> None:
    """Attach each valid project's latest coding sessions to the context.

    Each entry gains ``recent_sessions``: up to 3 ``{"title",
    "latest_user_request"}`` dicts, newest first. Fragments are redacted and
    truncated (300 chars each, 800 per project, 12,000 total) so the planner
    sees only titles and user requests — never worker replies or run logs.
    """
    from obsidian_ai_hub.coding import store as coding_store
    from obsidian_ai_hub.tasks.redaction import redact_text

    remaining = TOTAL_HISTORY_LIMIT
    for project in projects:
        if remaining <= 0:
            project["recent_sessions"] = []
            continue
        try:
            project_id = int(project.get("project_id"))
        except (TypeError, ValueError):
            project["recent_sessions"] = []
            continue
        # History is only a planner hint: a coding-store hiccup must not
        # fail the whole planning round (mirrors _valid_projects skipping
        # unresolvable projects with a warning).
        try:
            sessions = coding_store.list_sessions_by_project(project_id)[:3]
            latest_messages = [
                coding_store.get_latest_user_message(
                    str(session.get("session_id") or "")
                )
                for session in sessions
            ]
        except Exception:
            logger.warning(
                "Skipping coding history for project '%s'",
                project_id,
                exc_info=True,
            )
            project["recent_sessions"] = []
            continue
        budget = min(PROJECT_HISTORY_LIMIT, remaining)
        entries: list[dict[str, str]] = []
        used = 0
        for session, latest in zip(sessions, latest_messages):
            if used >= budget:
                break
            title = redact_text(str(session.get("title") or ""))[
                :HISTORY_FRAGMENT_LIMIT
            ]
            request = (
                redact_text(str((latest or {}).get("content") or ""))[
                    :HISTORY_FRAGMENT_LIMIT
                ]
                if latest is not None
                else ""
            )
            if not title and not request:
                continue
            fitted = _fit_history_pair(title, request, budget - used)
            if fitted is None:
                break
            entries.append(fitted)
            used += len(fitted["title"]) + len(fitted["latest_user_request"])
        project["recent_sessions"] = entries
        remaining -= used


def _fit_history_pair(
    title: str, request: str, room: int
) -> Optional[dict[str, str]]:
    """Fit one session's fragments into the remaining per-project budget.

    Trims the request first, then the title; returns None when nothing fits.
    """
    if room <= 0:
        return None
    if len(title) + len(request) <= room:
        return {"title": title, "latest_user_request": request}
    trimmed_request = request[: max(0, room - len(title))]
    if len(title) + len(trimmed_request) <= room and (
        title or trimmed_request
    ):
        return {"title": title, "latest_user_request": trimmed_request}
    trimmed_title = title[:room]
    if trimmed_title:
        return {"title": trimmed_title, "latest_user_request": ""}
    return None


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
                # NOTE: the projects table carries display_name /
                # normalized_name — there is no "name" column. Reading
                # project.get("name") always yields "" and leaves the
                # planner with nameless projects.
                "name": str(
                    project.get("display_name") or project.get("normalized_name") or ""
                ),
                "keywords": list(project.get("keywords") or []),
                "git_root": git_root,
            }
        )
    return valid


def build_planner_prompt(
    prompt_text: str,
    context: dict[str, Any],
    qa_history: Optional[list[dict[str, Any]]] = None,
    rejection_history: Optional[list[dict[str, Any]]] = None,
    forced_resolution: Optional[dict[str, Any]] = None,
) -> str:
    capability_lines = []
    for c in context["capabilities"]:
        header = (
            f"- {c['capability_key']} ({c['adapter_kind']}, {c['approval_policy']}): "
            f"{c.get('label', '')} {c.get('description', '')}".rstrip()
        )
        capability_lines.append(header)
        schema_text = c.get("input_schema")
        if schema_text:
            # Indent the compact schema so the planner sees field-level
            # requirements without a second hand-written source.
            indented = "\n".join(
                f"    {line}" for line in str(schema_text).splitlines()
            )
            capability_lines.append(indented)
        else:
            capability_lines.append(
                "    (入力schema: 解決不可のCapabilityはPlanに含めないこと)"
            )
    agent_lines = [f"- {a['agent_id']}: {a['name']}" for a in context["agents"]]
    project_lines = []
    for p in context["projects"]:
        keywords = ", ".join(str(k) for k in (p.get("keywords") or []))
        suffix = f" [キーワード: {keywords}]" if keywords else ""
        project_lines.append(
            f"- {p['project_id']}: {p.get('name', '')} ({p['git_root']}){suffix}"
        )
    prompt = (
        f"依頼:\n{prompt_text}\n\n"
        f"有効Capability:\n" + "\n".join(capability_lines) + "\n\n"
        "登録済みAgent:\n" + "\n".join(agent_lines) + "\n\n"
        "有効Project:\n" + "\n".join(project_lines) + "\n\n"
        "Action予算: 完了済み0 / 残数はPlanのmax_actionsで決める"
        "(未指定時は8、finishの1枠を必ず含める)。"
    )
    history_section = _render_project_history_section(context.get("projects") or [])
    if history_section:
        prompt += (
            "\n\n直近のCoding履歴(各Projectの題名と最新user依頼、推定材料。\n"
            "依頼文と無関係なら無視してよい):\n" + history_section
        )
    if forced_resolution:
        prompt += _render_forced_resolution_section(forced_resolution)
    if qa_history:
        qa_lines = []
        for index, round in enumerate(qa_history, start=1):
            question = str(round.get("question") or "(質問文を取得できませんでした)")
            answer = round.get("answer")
            answer_text = "(未回答)" if answer is None else _format_answer(answer)
            line = f"- 第{index}回 質問: {question} / 回答: {answer_text}"
            comment = round.get("comment")
            if isinstance(comment, str) and comment.strip():
                line += f" / コメント: {comment.strip()}"
            qa_lines.append(line)
        prompt += "\n\n以前の質問と回答(確定事項):\n" + "\n".join(qa_lines)
    if rejection_history:
        rejection_lines = []
        for entry in rejection_history:
            version = entry.get("version")
            purpose = str(entry.get("purpose") or "")
            capabilities = entry.get("capabilities") or []
            capability_keys = ", ".join(
                str(c) for c in capabilities if str(c).strip()
            )
            reason = str(entry.get("reason") or "")
            line = f"- v{version} 目的: {purpose}"
            if capability_keys:
                line += f" / Capability: {capability_keys}"
            if reason.strip():
                line += f" / 差戻し理由: {reason.strip()}"
            rejection_lines.append(line)
        prompt += "\n\n過去の却下Planと差戻し理由(確定の制約):\n" + "\n".join(
            rejection_lines
        )
    return prompt


def _render_project_history_section(projects: list[dict[str, Any]]) -> str:
    """Render redacted recent-session history lines for the planner prompt."""
    lines: list[str] = []
    for project in projects:
        sessions = project.get("recent_sessions") or []
        if not sessions:
            continue
        try:
            project_id = int(project.get("project_id"))
        except (TypeError, ValueError):
            continue
        name = str(project.get("name") or "")
        lines.append(f"- {project_id}: {name}")
        for session in sessions:
            title = str(session.get("title") or "")
            request = str(session.get("latest_user_request") or "")
            fragment = " / ".join(part for part in (title, request) if part)
            if fragment:
                lines.append(f"  - 題名・最新依頼: {fragment}")
    return "\n".join(lines)


def _render_forced_resolution_section(forced: dict[str, Any]) -> str:
    """Render a human-selected target as a non-negotiable planner input."""
    if forced.get("kind") == "project":
        try:
            project_id = int(forced.get("project_id"))
        except (TypeError, ValueError):
            return ""
        name = str(forced.get("display_name") or "")
        return (
            "\n\n確定済みの対象(人間指定、変更不可):\n"
            f"- 主対象Project: {name} (project:{project_id})\n"
            "project_resolutionは必ず "
            f'{{"kind": "project", "project_id": {project_id}, "source": "user"}} '
            "とし、confidenceは付けないこと。"
        )
    return (
        "\n\n確定済みの対象(人間指定、変更不可):\n"
        "- 一般Task（特定Projectなし）\n"
        'project_resolutionは必ず {"kind": "general", "source": "user"} '
        "とし、confidenceは付けず、coding_cliを含めないこと。"
    )


def _format_answer(answer: Any) -> str:
    if isinstance(answer, str):
        return answer
    try:
        return json.dumps(answer, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(answer)


def get_task_qa_history(task_id: str) -> list[dict[str, Any]]:
    """Return past target Q&A rounds oldest-first for replanning context.

    Each round is ``{"hitl_run_id": str|None, "question": str, "answer": Any,
    "comment": str|None}`` with ``answer`` None until the matching
    ``hitl_question_answered`` event. ``comment`` carries the free-text
    comment attached to the answer, if any (old events without it yield None).
    """
    from obsidian_ai_hub.hitl import store as hitl_store

    rounds: list[dict[str, Any]] = []
    for event in task_store.list_task_events(task_id):
        event_type = event.get("event_type")
        payload = event.get("payload") or {}
        if event_type == "hitl_question_asked":
            rounds.append(
                {
                    "hitl_run_id": payload.get("hitl_run_id"),
                    "question": _lookup_question_text(
                        hitl_store,
                        payload.get("hitl_run_id"),
                        payload.get("question_set_id") or "target",
                    ),
                    "answer": None,
                    "comment": None,
                }
            )
        elif event_type == "hitl_question_answered":
            for round in reversed(rounds):
                if round["answer"] is None and round["hitl_run_id"] == payload.get(
                    "hitl_run_id"
                ):
                    round["answer"] = payload.get("answer")
                    comment = payload.get("comment")
                    round["comment"] = (
                        str(comment)
                        if isinstance(comment, str) and comment.strip()
                        else None
                    )
                    break
    return rounds


def get_task_rejection_history(
    task_id: str, limit: int = 3
) -> list[dict[str, Any]]:
    """Return rejected plans newest-first (capped) for replanning context.

    Each entry is ``{"plan_id": str, "version": int, "reason": str|None,
    "purpose": str, "capabilities": list[str]}``. Plans without a stored
    rejection reason still appear so the planner can see what was already
    refused; the detailed inputs are intentionally excluded (directional
    plans never freeze them).
    """
    try:
        plans = task_store.list_plans(task_id)
    except Exception:
        logger.warning("Failed to load plans for task %s", task_id)
        return []
    rejected = [p for p in plans if p.get("status") == "rejected"]
    rejected.sort(key=lambda p: int(p.get("version") or 0), reverse=True)
    history: list[dict[str, Any]] = []
    for plan_record in rejected[: max(1, limit)]:
        inner = plan_record.get("plan") or {}
        capabilities: list[str] = []
        raw_capabilities = inner.get("capabilities")
        if isinstance(raw_capabilities, list):
            for entry in raw_capabilities:
                if isinstance(entry, dict) and entry.get("capability_key"):
                    capabilities.append(str(entry["capability_key"]))
        elif isinstance(inner.get("steps"), list):
            for step in inner["steps"]:
                if isinstance(step, dict) and step.get("capability_key"):
                    capabilities.append(str(step["capability_key"]))
        reason = plan_record.get("rejection_reason")
        history.append(
            {
                "plan_id": plan_record.get("plan_id"),
                "version": plan_record.get("version"),
                "reason": str(reason) if isinstance(reason, str) else None,
                "purpose": str(inner.get("purpose") or ""),
                "capabilities": capabilities,
            }
        )
    return history


def _lookup_question_text(
    hitl_store: Any, hitl_run_id: Any, question_set_id: str
) -> str:
    if not hitl_run_id:
        return ""
    try:
        questions = hitl_store.get_questions_by_set(str(hitl_run_id), question_set_id)
    except Exception:
        logger.warning("Failed to load HITL questions for %s", hitl_run_id)
        return ""
    if not questions:
        return ""
    first = questions[0]
    return str(
        first.get("display_text") or first.get("prompt") or first.get("title") or ""
    )


def parse_selection_value(value: Any) -> Optional[dict[str, Any]]:
    """Normalize a target selection to ``{"kind", "project_id"}``.

    Accepted internal values are ``"project:<int>"`` and ``"general"``; a
    bare positive integer string is also accepted as a project id. Anything
    else (unknown prefixes, blanks, non-strings) yields None.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text == "general":
        return {"kind": "general", "project_id": None}
    candidate = text
    if candidate.startswith("project:"):
        candidate = candidate.split(":", 1)[1].strip()
    try:
        project_id = int(candidate)
    except (TypeError, ValueError):
        return None
    if project_id <= 0:
        return None
    return {"kind": "project", "project_id": project_id}


def validate_target_project(project_id: Any) -> tuple[str, str]:
    """Return ``(display_name, git_root)`` for a selectable project.

    Raises ValueError when the project is missing, has no path, or its Git
    root is unresolvable (deleted or invalid).
    """
    from obsidian_ai_hub.coding.backend import validate_git_repo
    from obsidian_ai_hub.web.services import projects as project_service

    try:
        pid = int(project_id)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"Invalid project id '{project_id}'.")
    if pid <= 0:
        raise ValueError(f"Invalid project id '{project_id}'.")
    project = project_service.get_project_detail(pid)
    if project is None:
        raise ValueError(f"Project '{pid}' no longer exists.")
    project_path = project.get("project_path")
    if not project_path:
        raise ValueError(f"Project '{pid}' has no project_path.")
    try:
        git_root = validate_git_repo(str(project_path))
    except Exception as exc:
        raise ValueError(f"Project '{pid}' git root is invalid: {exc}") from exc
    name = str(project.get("display_name") or project.get("normalized_name") or "")
    return name, git_root


def record_target_resolution_selection(
    task_id: str,
    *,
    kind: str,
    project_id: Optional[int] = None,
    display_name: str = "",
    via: str = "api",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Persist a human-selected target as a ``target_resolution_selected`` event.

    Invalid or deleted projects are rejected with ValueError and no event is
    appended. Human selections carry no confidence.
    """
    if kind == "project":
        name, _git_root = validate_target_project(project_id)
        payload: dict[str, Any] = {
            "kind": "project",
            "project_id": int(project_id),  # type: ignore[arg-type]
            "display_name": display_name.strip() or name,
            "source": "user",
            "set_via": via,
        }
    elif kind == "general":
        payload = {
            "kind": "general",
            "project_id": None,
            "display_name": "",
            "source": "user",
            "set_via": via,
        }
    else:
        raise ValueError(f"Unknown target kind: '{kind}'.")
    event_id = task_store.append_task_event(
        task_id, "target_resolution_selected", payload, conn=conn
    )
    return {"event_id": event_id, **payload}


def get_forced_target_resolution(task_id: str) -> Optional[dict[str, Any]]:
    """Return the latest human-selected target for replanning, if any.

    The forced input wins over any planner inference; malformed events are
    skipped so an older valid selection still applies.
    """
    forced: Optional[dict[str, Any]] = None
    for event in task_store.list_task_events(task_id):
        if event.get("event_type") != "target_resolution_selected":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        kind = payload.get("kind")
        if kind == "project":
            try:
                project_id = int(payload.get("project_id"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if project_id <= 0:
                continue
            forced = {
                "kind": "project",
                "project_id": project_id,
                "display_name": str(payload.get("display_name") or ""),
            }
        elif kind == "general":
            forced = {"kind": "general", "project_id": None, "display_name": ""}
    return forced


def _fallback_general_resolution() -> dict[str, Any]:
    return {
        "kind": "general",
        "project_id": None,
        "display_name": "",
        "confidence": 0.0,
        "rationale": "対象を解決できなかったため一般Task扱い",
        "source": "inferred",
    }


def _coerce_confidence(value: Any) -> Optional[float]:
    try:
        confidence = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not (0.0 <= confidence <= 1.0):
        return None
    return confidence


def normalize_planner_resolution(
    raw: Any, forced: Optional[dict[str, Any]] = None
) -> tuple[dict[str, Any], bool]:
    """Normalize planner output into a v3 resolution dict.

    Returns ``(resolution, missing_or_invalid)``. A forced human selection
    wins unconditionally (source "user", no confidence). Missing, malformed,
    or out-of-range planner output becomes an inferred general resolution
    with confidence 0.0 — never a planner failure.
    """
    if forced is not None:
        if forced.get("kind") == "project":
            return {
                "kind": "project",
                "project_id": int(forced["project_id"]),
                "display_name": str(forced.get("display_name") or ""),
                "confidence": None,
                "rationale": "人間が選択した対象",
                "source": "user",
            }, False
        return {
            "kind": "general",
            "project_id": None,
            "display_name": "",
            "confidence": None,
            "rationale": "人間が選択した一般Task",
            "source": "user",
        }, False
    if not isinstance(raw, dict):
        return _fallback_general_resolution(), True
    kind = raw.get("kind")
    confidence = _coerce_confidence(raw.get("confidence"))
    if kind == "project":
        try:
            project_id = int(raw.get("project_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            project_id = None
        if (
            project_id is None
            or project_id <= 0
            or confidence is None
        ):
            return _fallback_general_resolution(), True
        return {
            "kind": "project",
            "project_id": project_id,
            "display_name": str(raw.get("display_name") or ""),
            "confidence": confidence,
            "rationale": str(raw.get("rationale") or ""),
            "source": "inferred",
        }, False
    if kind == "general":
        if confidence is None:
            return _fallback_general_resolution(), True
        return {
            "kind": "general",
            "project_id": None,
            "display_name": "",
            "confidence": confidence,
            "rationale": str(raw.get("rationale") or ""),
            "source": "inferred",
        }, False
    return _fallback_general_resolution(), True


def _project_display_name(
    projects: list[dict[str, Any]], project_id: int
) -> Optional[str]:
    for project in projects:
        try:
            candidate = int(project.get("project_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if candidate == project_id:
            return str(project.get("name") or "")
    return None


def build_target_question_output(
    resolution: dict[str, Any], projects: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a target question output for a low-confidence resolution.

    All valid projects stay selectable plus a "general" option; internal
    values are ``"project:<int>"`` or ``"general"``. The inferred top
    candidate's score and rationale go into the question text and its own
    option label.
    """
    from obsidian_ai_hub.tasks.redaction import redact_text

    options: list[dict[str, str]] = []
    for project in projects:
        try:
            project_id = int(project.get("project_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if project_id <= 0:
            continue
        name = str(project.get("name") or "")
        label = f"{name}（Project {project_id}）" if name else f"Project {project_id}"
        if resolution.get("kind") == "project" and resolution.get(
            "project_id"
        ) == project_id:
            details: list[str] = []
            confidence = resolution.get("confidence")
            if isinstance(confidence, (int, float)):
                details.append(f"推定スコア {float(confidence):.2f}")
            # The rationale may echo user text: redact like question_text so
            # configured secrets never persist in HITL choices.
            rationale = redact_text(
                str(resolution.get("rationale") or "").strip()
            )
            if rationale:
                details.append(rationale[:100])
            if details:
                label += " [" + " / ".join(details) + "]"
        options.append({"value": f"project:{project_id}", "label": label})
    options.append(
        {"value": "general", "label": "一般Task（Projectを特定しない）"}
    )
    if resolution.get("kind") == "project":
        project_id = resolution.get("project_id")
        name = _project_display_name(projects, project_id) or str(
            resolution.get("display_name") or project_id
        )
        estimated = f"「{name}」(project:{project_id})"
    else:
        estimated = "一般Taskの可能性"
    summary = f"{estimated}"
    confidence = resolution.get("confidence")
    if isinstance(confidence, (int, float)):
        summary += f" スコア {float(confidence):.2f}"
    rationale = redact_text(str(resolution.get("rationale") or "").strip())
    if rationale:
        summary += f" 根拠: {rationale[:200]}"
    question_text = (
        "このTaskの主対象Projectを特定できませんでした"
        f"（推定: {summary}）。"
        "対象のProject、または一般Taskを選んでください。"
    )
    return {
        "type": "question",
        "question_text": redact_text(question_text),
        "options": options,
    }


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
        # Directional plans carry "capabilities"; legacy static plans carry
        # "steps". Both parse here; legacy stays readable for old tasks.
        if isinstance(output.get("capabilities"), list):
            return _validate_directional_shape(output)
        if isinstance(output.get("steps"), list):
            return _validate_plan_shape(output)
        raise ValueError(
            "Plan requires either 'capabilities' (directional) or 'steps' (legacy)."
        )
    if output_type == "question":
        return _validate_question_shape(output)
    raise ValueError(f"Planner output has unknown type: {output_type!r}.")


def _validate_directional_shape(output: dict[str, Any]) -> dict[str, Any]:
    """Validate the planner's directional plan JSON (no frozen inputs).

    The target resolution is NOT validated here: missing or malformed
    output falls back to a safe inferred general resolution later
    (``normalize_planner_resolution``), never a planner failure.
    """
    from obsidian_ai_hub.tasks.directional import (
        MAX_ACTIONS_HARD_LIMIT,
        DirectionalPlan,
    )

    try:
        plan = DirectionalPlan.model_validate(
            {
                "plan_version": 2,
                "purpose": output.get("purpose"),
                "strategy": output.get("strategy", ""),
                "capabilities": output.get("capabilities"),
                "allowed_agent_ids": output.get("allowed_agent_ids", []),
                "allowed_project_ids": output.get("allowed_project_ids", []),
                "constraints": output.get("constraints", ""),
                "completion_criteria": output.get("completion_criteria"),
                "max_actions": output.get("max_actions", 8),
                # The planner never forges the delegate config fingerprint;
                # validate_directional_plan stamps the authoritative snapshot.
                # Any LLM-supplied value is discarded here.
            }
        )
    except Exception as exc:
        raise ValueError(f"Invalid directional plan: {exc}") from exc
    if plan.max_actions is not None and not (
        1 <= int(plan.max_actions) <= MAX_ACTIONS_HARD_LIMIT
    ):
        raise ValueError("Plan max_actions must be between 1 and 30.")
    # A supplied resolution marks a v3 plan; the normalized form (and the
    # version stamp) is finalized after the low-confidence branch decision.
    output["plan_version"] = 3 if output.get("project_resolution") is not None else 2
    output["purpose"] = plan.purpose
    output["strategy"] = plan.strategy
    output["capabilities"] = [d.model_dump() for d in plan.capabilities]
    output["allowed_agent_ids"] = list(plan.allowed_agent_ids or [])
    output["allowed_project_ids"] = list(plan.allowed_project_ids or [])
    output["constraints"] = plan.constraints
    output["completion_criteria"] = plan.completion_criteria
    output["max_actions"] = plan.max_actions
    output.pop("steps", None)
    output.pop("agent_config_snapshot", None)
    return output


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
    options = output.get("options")
    choices = output.get("choices")
    if options is not None:
        if not isinstance(options, list) or not options:
            raise ValueError("Question options must be a non-empty list.")
        normalized = []
        for index, option in enumerate(options):
            if not isinstance(option, dict):
                raise ValueError(f"Question option {index} must be an object.")
            value = option.get("value")
            label = option.get("label")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Question option {index} needs a non-blank value.")
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f"Question option {index} needs a non-blank label.")
            normalized.append({"value": value.strip(), "label": label.strip()})
        output["options"] = normalized
    elif choices is not None:
        if (
            not isinstance(choices, list)
            or not choices
            or not all(isinstance(c, str) and c.strip() for c in choices)
        ):
            raise ValueError("Question choices must be a non-empty list of strings.")
        output["options"] = [{"value": c.strip(), "label": c.strip()} for c in choices]
    else:
        output["options"] = []
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
            raw_project_id = target.get("project_id")
            matched: Any = None
            for candidate in project_ids:
                if (
                    candidate == raw_project_id
                    or str(candidate) == str(raw_project_id).strip()
                ):
                    matched = candidate
                    break
            if matched is None:
                raise ValueError(
                    f"Plan step {index} targets invalid project '{raw_project_id}'."
                )
            # Normalize the saved plan to the DB-canonical id type: the DB
            # project_id is an integer, but the planner returns JSON where
            # the id may arrive as a string ("1" vs 1).
            target["project_id"] = matched
            backend = target.get("backend")
            if backend is not None and backend != "opencode":
                raise ValueError(f"Plan step {index} uses unknown backend '{backend}'.")
    return snapshot


def validate_directional_plan(
    plan: dict[str, Any], context: dict[str, Any]
) -> dict[str, str]:
    """Validate a directional plan's approval scope. Returns policy snapshot.

    Checks that every planned capability is enabled and has a resolvable
    input schema (the single source). Detailed inputs are intentionally NOT
    fixed here — the Runtime Orchestrator generates and validates them.

    As a side effect, stamps the approval-time delegate target allowlists
    (``allowed_agent_ids`` / ``allowed_project_ids``) onto the plan from the
    current registry context. The planner never forges these lists; the
    orchestrator enforces membership per action.

    When the plan uses ``specialist_agent``, also stamps an approval-time
    fingerprint of each in-scope Agent's execution config
    (``agent_config_snapshot``). The worker compares it at execution start
    and routes drifted tasks to reapproval instead of silently running
    under a changed config.

    For v3 plans carrying ``project_resolution`` the project allowlist is
    narrowed to the single resolved project (or emptied for general tasks).
    A general task must not include ``coding_cli``. Plans without a
    resolution keep the legacy behavior of allowing every valid project.
    """
    from obsidian_ai_hub.tasks.capability_schemas import resolve_json_schema
    from obsidian_ai_hub.tasks.directional import DirectionalPlan

    enabled = {
        c["capability_key"]: c["approval_policy"] for c in context["capabilities"]
    }
    snapshot: dict[str, str] = {}
    capabilities = plan.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("Directional plan requires a non-empty capabilities list.")
    seen: set[str] = set()
    for index, entry in enumerate(capabilities):
        if not isinstance(entry, dict):
            raise ValueError(f"Plan capability {index} must be an object.")
        key = entry.get("capability_key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"Plan capability {index} needs a capability_key.")
        if key in seen:
            raise ValueError(f"Plan capability '{key}' is listed twice.")
        seen.add(key)
        if key not in enabled:
            raise ValueError(
                f"Plan capability {index} uses unknown or disabled capability '{key}'."
            )
        snapshot[key] = enabled[key]
        if resolve_json_schema(key) is None:
            raise ValueError(f"Plan capability '{key}' has no resolvable input schema.")
    agent_ids = [
        str(a.get("agent_id")) for a in context.get("agents", []) if a.get("agent_id")
    ]
    project_ids = []
    for project in context.get("projects", []):
        try:
            project_ids.append(int(project.get("project_id")))
        except (TypeError, ValueError):
            continue
    if "specialist_agent" in seen and not agent_ids:
        raise ValueError(
            "Plan uses 'specialist_agent' but no agents are registered; "
            "ask a target question instead."
        )
    if "coding_cli" in seen and not project_ids:
        raise ValueError(
            "Plan uses 'coding_cli' but no valid projects are registered; "
            "ask a target question instead."
        )
    resolution = plan.get("project_resolution")
    if not isinstance(resolution, dict):
        resolution = {}
    if resolution.get("kind") == "project":
        try:
            resolved_id = int(resolution.get("project_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError("project_resolution project_id is invalid.")
        if resolved_id not in project_ids:
            raise ValueError(
                f"project_resolution targets unregistered project '{resolved_id}'."
            )
        plan["allowed_project_ids"] = [resolved_id]
    else:
        if resolution.get("kind") == "general" and "coding_cli" in seen:
            raise ValueError(
                "A general task cannot include 'coding_cli'; "
                "resolve a project target instead."
            )
        plan["allowed_project_ids"] = project_ids
    plan["allowed_agent_ids"] = agent_ids
    if "specialist_agent" in seen:
        plan["agent_config_snapshot"] = _snapshot_agent_configs(agent_ids)
    else:
        plan["agent_config_snapshot"] = {}
    # Final consistency check against the versioned model (v2 stays
    # resolution-free; v3 requires it). agent_config_snapshot and the
    # planner "type" marker live outside the model.
    try:
        DirectionalPlan.model_validate(
            {
                key: value
                for key, value in plan.items()
                if key in DirectionalPlan.model_fields
            }
        )
    except Exception as exc:
        raise ValueError(f"Invalid directional plan: {exc}") from exc
    return snapshot


def _snapshot_agent_configs(agent_ids: list[str]) -> dict[str, Any]:
    """Fingerprint the current config of each in-scope agent.

    A missing record (deleted agent) is left out of the snapshot; the
    worker treats absence from the live registry as drift. Read errors
    propagate and fail planning like any other planner failure.
    """
    from obsidian_ai_hub.agents import store as agent_store
    from obsidian_ai_hub.tasks.directional import fingerprint_agent_config

    snapshots: dict[str, Any] = {}
    for agent_id in agent_ids:
        record = agent_store.get_agent(str(agent_id))
        if record is None:
            continue
        snapshots[str(agent_id)] = fingerprint_agent_config(record).model_dump()
    return snapshots


def _apply_target_resolution(
    task_id: str, output: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Attach a v3 target resolution to a directional planner output.

    A human-selected target wins unconditionally. An inferred confidence
    below ``TARGET_CONFIDENCE_THRESHOLD`` turns the output into a target
    question instead: the plan is NOT saved and every valid project plus
    "general" stays selectable. A forced general target rejects any plan
    that still includes ``coding_cli``.
    """
    forced = get_forced_target_resolution(task_id)
    resolution, missing_or_invalid = normalize_planner_resolution(
        output.get("project_resolution"), forced
    )
    capabilities = output.get("capabilities") or []
    capability_keys = {
        str(entry.get("capability_key"))
        for entry in capabilities
        if isinstance(entry, dict)
    }
    valid_projects = context.get("projects") or []
    if forced is None:
        need_question = False
        if missing_or_invalid:
            # Safe fallback for malformed output: only ask when a coding
            # target actually matters; otherwise save as a general task.
            need_question = "coding_cli" in capability_keys and bool(valid_projects)
        else:
            confidence = resolution.get("confidence")
            need_question = (
                isinstance(confidence, (int, float))
                and float(confidence) < TARGET_CONFIDENCE_THRESHOLD
                and bool(valid_projects)
            )
        if need_question:
            return build_target_question_output(resolution, valid_projects)
    if (
        forced is not None
        and forced.get("kind") == "general"
        and "coding_cli" in capability_keys
    ):
        raise ValueError(
            "Plan uses 'coding_cli' but the human-selected target is general; "
            "a general task cannot run coding_cli."
        )
    resolution = _refresh_resolution_display_name(resolution, valid_projects)
    output = dict(output)
    output["plan_version"] = 3
    output["project_resolution"] = resolution
    return output


def _refresh_resolution_display_name(
    resolution: dict[str, Any], projects: list[dict[str, Any]]
) -> dict[str, Any]:
    """Re-snapshot the planner's project display name from live context."""
    if resolution.get("kind") != "project":
        return resolution
    try:
        project_id = int(resolution.get("project_id"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return resolution
    name = _project_display_name(projects, project_id)
    if name:
        resolution = dict(resolution, display_name=name)
    return resolution


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
    qa_history = get_task_qa_history(task_id)
    rejection_history = get_task_rejection_history(task_id)
    forced_resolution = get_forced_target_resolution(task_id)
    provider, model = default_provider_model()
    try:
        raw = generate_llm_response(
            provider,
            model,
            build_planner_prompt(
                str(task["prompt_text"]),
                context,
                qa_history,
                rejection_history,
                forced_resolution,
            ),
            system_prompt=PLANNER_SYSTEM_PROMPT,
            session_id=f"task-plan-{task_id}",
        )
        output = parse_planner_output(raw)
        if output["type"] == "plan" and isinstance(
            output.get("capabilities"), list
        ):
            output = _apply_target_resolution(task_id, output, context)
        snapshot: Optional[dict[str, str]] = None
        if output["type"] == "plan":
            if isinstance(output.get("capabilities"), list):
                snapshot = validate_directional_plan(output, context)
            else:
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
            if isinstance(output.get("capabilities"), list):
                plan_inner: dict[str, Any] = {
                    "plan_version": output.get("plan_version", 2),
                    "purpose": output["purpose"],
                    "strategy": output.get("strategy", ""),
                    "capabilities": output["capabilities"],
                    "allowed_agent_ids": list(output.get("allowed_agent_ids") or []),
                    "allowed_project_ids": list(
                        output.get("allowed_project_ids") or []
                    ),
                    "agent_config_snapshot": dict(
                        output.get("agent_config_snapshot") or {}
                    ),
                    "constraints": output.get("constraints", ""),
                    "completion_criteria": output["completion_criteria"],
                    "max_actions": output.get("max_actions", 8),
                }
                if isinstance(output.get("project_resolution"), dict):
                    plan_inner["plan_version"] = 3
                    plan_inner["project_resolution"] = dict(
                        output["project_resolution"]
                    )
            else:
                plan_inner = {
                    "purpose": output["purpose"],
                    "steps": output["steps"],
                    "completion_criteria": output["completion_criteria"],
                }
            plan_record = task_store.create_plan(
                task_id,
                plan_inner,
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
    options = output.get("options") or []
    if options:
        question: dict[str, Any] = {
            "question_key": "target",
            "question_type": "select",
            "display_text": question_text,
            "title": "Taskの対象確認",
            "prompt": question_text,
            "choices": [
                {"value": option["value"], "label": option["label"]}
                for option in options
            ],
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
