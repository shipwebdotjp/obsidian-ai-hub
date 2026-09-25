"""HITL proposals and approved coding-task creation for system maintenance."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from obsidian_ai_hub.coding import backend, store as coding_store
from obsidian_ai_hub.hitl import HitlContext, HitlResult, register_run_and_questions, update_checkpoint
from obsidian_ai_hub.runs.instance import get_instance_id, is_lock_held
from obsidian_ai_hub.system_maintenance import store
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.web.services.projects import get_project_detail

logger = logging.getLogger(__name__)

SYSTEM_MAINTENANCE_HANDLER = "system_maintenance.create_coding_tasks"
SYSTEM_MAINTENANCE_TITLE = "システムメンテナンス診断"
SYSTEM_MAINTENANCE_DISPLAY_TYPE = "システム保守"
_MAX_SESSION_TITLE_CHARS = 120


def validate_target_project() -> Tuple[int, str]:
    """Resolve the configured maintenance target project to a canonical repo."""
    project_id = config.SYSTEM_MAINTENANCE_PROJECT_ID
    if project_id is None:
        raise RuntimeError("SYSTEM_MAINTENANCE_PROJECT_ID is not configured")
    detail = get_project_detail(int(project_id))
    if detail is None:
        raise ValueError(f"Project {project_id} does not exist")
    repo_path = detail.get("project_path")
    if not repo_path:
        raise ValueError(f"Project {project_id} has no project_path")
    return int(project_id), backend.validate_git_repo(repo_path)


def _build_proposal_question(
    q_key: str,
    proposal: Mapping[str, Any],
    finding: Mapping[str, Any],
    seq: int,
) -> Dict[str, Any]:
    label = proposal.get("label") or proposal.get("fingerprint")
    display_text = f"【提案 #{seq}】{label} ({proposal.get('severity')})"
    context_json = {
        "type": "system_maintenance",
        "proposal_id": q_key,
        "fingerprint": proposal.get("fingerprint"),
        "severity": proposal.get("severity"),
        "cause": proposal.get("cause"),
        "countermeasure": proposal.get("countermeasure"),
        "coding_instruction": proposal.get("coding_instruction"),
        "occurrence_count": proposal.get("occurrence_count"),
        "run_ids": (proposal.get("run_ids") or [])[:10],
        "call_ids": (proposal.get("call_ids") or [])[:10],
        "exception_type": finding.get("exception_type"),
    }
    return {
        "question_key": q_key,
        "question_type": "select",
        "display_text": display_text,
        "choices": [
            {
                "value": "create",
                "label": "コーディングタスクを起票",
                "description": "承認した内容で対象プロジェクトにコーディングタスクを起票します。",
            },
            {
                "value": "skip",
                "label": "見送り",
                "description": "この提案は見送ります（起票しません）。",
            },
        ],
        "is_required": 1,
        "sequence": seq,
        "title": f"提案 #{seq}",
        "prompt": proposal.get("countermeasure") or proposal.get("cause"),
        "context_json": context_json,
    }


def register_maintenance_hitl_run(
    proposals: Sequence[Mapping[str, Any]],
    findings_by_fingerprint: Mapping[str, Mapping[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Optional[str]:
    if not proposals:
        return None

    current = now or datetime.now(timezone.utc)
    run_id = f"sysmaint_{int(current.timestamp())}_{uuid.uuid4().hex[:6]}"
    question_set_id = "round_1"

    enriched: List[Dict[str, Any]] = []
    for proposal in proposals:
        finding = findings_by_fingerprint.get(str(proposal["fingerprint"]), {})
        enriched.append(
            {
                **proposal,
                "label": finding.get("label") or "",
                "occurrence_count": finding.get("occurrence_count") or 0,
                "first_seen_at": finding.get("first_seen_at"),
                "last_seen_at": finding.get("last_seen_at"),
                "run_ids": list(finding.get("run_ids") or []),
                "call_ids": list(finding.get("call_ids") or []),
            }
        )

    questions_data = [
        _build_proposal_question(
            f"proposal_{index}",
            proposal,
            findings_by_fingerprint.get(str(proposal["fingerprint"]), {}),
            index,
        )
        for index, proposal in enumerate(enriched, 1)
    ]

    checkpoint = json.dumps(
        {"version": 1, "proposals": enriched, "handled": []}, ensure_ascii=False
    )
    description = (
        f"実行ログ・LLMコール履歴から検出した{len(enriched)}件の障害提案です。"
        "承認するとコーディングタスクを起票します。"
    )

    store.mark_proposed([str(p["fingerprint"]) for p in enriched], run_id)
    register_run_and_questions(
        run_id=run_id,
        handler=SYSTEM_MAINTENANCE_HANDLER,
        checkpoint=checkpoint,
        question_set_id=question_set_id,
        questions_data=questions_data,
        title=SYSTEM_MAINTENANCE_TITLE,
        description=description,
        display_type=SYSTEM_MAINTENANCE_DISPLAY_TYPE,
    )

    try:
        from obsidian_ai_hub.line_notification import notify_hitl_run

        notify_hitl_run(
            kind=SYSTEM_MAINTENANCE_DISPLAY_TYPE,
            title=SYSTEM_MAINTENANCE_TITLE,
            description=description,
            run_id=run_id,
            round_number=1,
        )
    except Exception as exc:
        logger.warning(
            "LINE system maintenance notification failed after commit for run %s: %s",
            run_id,
            type(exc).__name__,
        )

    return run_id


def _run_worker_is_alive() -> bool:
    return is_lock_held()


def _build_coding_content(proposal: Mapping[str, Any]) -> str:
    evidence: List[str] = []
    run_ids = proposal.get("run_ids") or []
    if run_ids:
        evidence.append(
            "command_runs: " + ", ".join(str(run_id) for run_id in run_ids[:10])
        )
    call_ids = proposal.get("call_ids") or []
    if call_ids:
        evidence.append(
            "llm_call_logs: " + ", ".join(str(call_id) for call_id in call_ids[:10])
        )
    if not evidence:
        evidence.append("(なし)")

    parts = [
        "システムメンテナンス診断で検出された障害の対策を実装してください。",
        "",
        "## 検出内容",
        f"- 対象: {proposal.get('label') or proposal.get('fingerprint')}",
        f"- 発生回数: {proposal.get('occurrence_count') or 0}",
        f"- 重要度: {proposal.get('severity') or 'medium'}",
        "",
        "## 原因の見立て",
        str(proposal.get("cause") or "(記載なし)"),
        "",
        "## 対策",
        str(proposal.get("countermeasure") or "(記載なし)"),
        "",
        "## 実装指示",
        str(proposal.get("coding_instruction") or "(記載なし)"),
        "",
        "## 根拠",
        *["- " + item for item in evidence],
        "",
        "変更後は関連するテストを実行し、結果を報告してください。",
    ]
    return "\n".join(parts)


def _enqueue_coding_task(proposal: Mapping[str, Any]) -> str:
    project_id, repo_path = validate_target_project()
    if not _run_worker_is_alive():
        raise RuntimeError(
            "run worker is not running; start the web service before creating a coding task"
        )

    fingerprint = str(proposal["fingerprint"])
    label = proposal.get("label") or fingerprint
    title = f"システムメンテナンス: {fingerprint} {label}"[:_MAX_SESSION_TITLE_CHARS]

    session = coding_store.find_session_by_title(project_id, title)
    if session is None:
        session = coding_store.create_session(
            project_id=project_id,
            backend="opencode",
            repo_path=repo_path,
            title=title,
            transport="acp",
        )

    idempotency_key = f"sysmaint:{fingerprint}:{proposal.get('first_seen_at') or ''}"
    try:
        _, run = coding_store.start_queued_run(
            session["session_id"],
            _build_coding_content(proposal),
            idempotency_key=idempotency_key,
            created_instance_id=get_instance_id(),
        )
        return str(run["run_id"])
    except ValueError as exc:
        if "Idempotency key conflict" not in str(exc):
            raise
        existing = coding_store.find_run_by_idempotency_key(
            session["session_id"], idempotency_key
        )
        if existing is None:
            raise
        logger.warning(
            "Reusing existing coding run %s for finding %s",
            existing.get("run_id"),
            fingerprint,
        )
        return str(existing["run_id"])


def run_approved_system_maintenance(ctx: HitlContext) -> HitlResult:
    """Create coding tasks for approved findings and record the outcome."""
    checkpoint = json.loads(ctx.checkpoint) if ctx.checkpoint else {}
    proposals = list(checkpoint.get("proposals") or [])
    handled = list(checkpoint.get("handled") or [])
    if not proposals:
        return HitlResult.complete(
            checkpoint=json.dumps({**checkpoint, "finished": True}, ensure_ascii=False)
        )

    for index, proposal in enumerate(proposals, 1):
        q_key = f"proposal_{index}"
        if q_key in handled:
            continue

        fingerprint = str(proposal.get("fingerprint") or "")
        if not fingerprint:
            return HitlResult.fail(f"Proposal {q_key} has no fingerprint")

        answer = ctx.answers_by_question_key.get(q_key)
        if answer == "create":
            try:
                coding_run_id = _enqueue_coding_task(proposal)
            except Exception as exc:
                logger.exception(
                    "Failed to enqueue coding task for finding %s", fingerprint
                )
                store.reopen_finding(fingerprint)
                return HitlResult.fail(
                    f"コーディングタスクの起票に失敗しました: "
                    f"{type(exc).__name__}: {exc}"
                )
            store.mark_coding_created(fingerprint, coding_run_id)
        elif answer == "skip":
            store.mark_dismissed(fingerprint)
        else:
            return HitlResult.fail(f"Unexpected answer '{answer}' for {q_key}")

        handled.append(q_key)
        checkpoint["handled"] = handled
        update_checkpoint(
            ctx.run_id,
            checkpoint=json.dumps(checkpoint, ensure_ascii=False),
            conn=ctx.conn,
        )

    checkpoint["handled"] = handled
    checkpoint["finished"] = True
    return HitlResult.complete(checkpoint=json.dumps(checkpoint, ensure_ascii=False))
