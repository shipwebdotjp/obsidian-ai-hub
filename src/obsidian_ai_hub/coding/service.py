"""Service layer orchestrating coding workspace sessions and runs."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import AsyncGenerator, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from obsidian_ai_hub.agents import runtime as agents_runtime
from obsidian_ai_hub.coding import acp as acp_module, backend, store
from obsidian_ai_hub.coding.orchestrator import (
    PROTOCOL_CORRECTION_INSTRUCTION,
    CodingOrchestrator,
    parse_and_normalize_worker_output,
    parse_coordinator_response,
    parse_cli_request,
)

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")

MAX_CLI_ITERATIONS = 50
CLI_LIMIT_REACHED_NOTICE = (
    "追加のCLI実行が必要と判断されましたが、このメッセージ内での自動実行上限（50回）に達したため実行していません。"
    "続行する場合は、作業を継続するよう指示してください。"
)

DEFAULT_CODING_SESSION_TITLE = "新しいコーディングセッション"

# Legacy Task-generated session titles ("Task <task_id> step <n>") carry no
# work description. Mirrored from tasks.adapters.child_runs (single source of
# the pattern); kept local to avoid a coding -> tasks import cycle.
_TASK_GENERATED_TITLE_PATTERN = re.compile(r"^Task \S+ step \d+$")


def _should_update_coding_title(current_title: Optional[str]) -> bool:
    """Return True only if title is auto-generated / unset and safe to overwrite.

    Overwrite only when title equals the default placeholder, is empty, or
    is a legacy Task-generated ``Task <id> step <n>`` title carrying no work
    description. Content-derived and user-supplied titles are preserved.
    The legacy pattern is mirrored from
    ``tasks.adapters.child_runs.is_task_generated_session_title`` to avoid
    a coding -> tasks import cycle.
    """
    if not current_title:
        return True
    stripped = current_title.strip()
    if stripped == "" or stripped == DEFAULT_CODING_SESSION_TITLE:
        return True
    return bool(_TASK_GENERATED_TITLE_PATTERN.match(stripped))


# Lock per normalized repo_path to prevent concurrent execution on the same Git repo
_REPO_LOCKS: Dict[str, threading.Lock] = {}
_REPO_LOCKS_GUARD = threading.Lock()

# Map run_id -> (cancel_event, repo_path)
_RUNNING_JOBS: Dict[str, Tuple[threading.Event, str]] = {}
_JOBS_GUARD = threading.Lock()


def _get_repo_lock(repo_path: str) -> threading.Lock:
    with _REPO_LOCKS_GUARD:
        if repo_path not in _REPO_LOCKS:
            _REPO_LOCKS[repo_path] = threading.Lock()
        return _REPO_LOCKS[repo_path]


def is_repo_busy(repo_path: str) -> bool:
    lock = _get_repo_lock(repo_path)
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
        return False
    return True


def cancel_active_run(run_id: str) -> bool:
    """Trigger cancellation for an active run."""
    with _JOBS_GUARD:
        if run_id in _RUNNING_JOBS:
            cancel_event, _ = _RUNNING_JOBS[run_id]
            cancel_event.set()
            logger.info("Signalled cancellation for coding run %s", run_id)
            return True
    return False


async def run_coding_turn_stream(
    session_id: str,
    user_prompt: str,
) -> AsyncGenerator[str, None]:
    """Execute a coding turn (user prompt -> orchestrator -> optional worker CLI) and yield SSE formatted strings."""
    session = store.get_session(session_id)
    if not session:
        yield f"data: {json.dumps({'event': 'error', 'message': 'Session not found'})}\n\n"
        return

    # Block submission if active run in waiting_user status exists
    latest_run = store.get_latest_run_for_session(session_id)
    if latest_run and latest_run.get("status") == "waiting_user":
        yield f"data: {json.dumps({'event': 'error', 'message': 'Session is waiting for user input on an active question'})}\n\n"
        return

    repo_path = session["repo_path"]
    backend_name = session["backend"]
    session_transport = session.get("transport") or "direct_cli"

    # Validate git repo path
    try:
        canonical_repo = backend.validate_git_repo(repo_path)
    except ValueError as exc:
        yield f"data: {json.dumps({'event': 'error', 'message': str(exc)})}\n\n"
        return

    # Check repository lock
    repo_lock = _get_repo_lock(canonical_repo)
    if not repo_lock.acquire(blocking=False):
        yield f"data: {json.dumps({'event': 'error', 'message': '同一リポジトリで別のコーディング実行が進行中です'})}\n\n"
        return

    cancel_event = threading.Event()

    try:
        # Check uncommitted changes
        is_dirty, dirty_output = backend.check_dirty_tree(canonical_repo)
        dirty_summary = dirty_output if is_dirty else None

        # Add user message
        user_msg = store.add_message(session_id, role="user", content=user_prompt)
        user_msg_id = user_msg["message_id"]

        # Create run
        acp_sess_id = session.get("acp_session_id")
        acp_prof_id = session.get("acp_profile_id")
        run = store.create_run(
            session_id=session_id,
            user_message_id=user_msg_id,
            dirty_tree_at_start=dirty_summary,
            transport=session_transport,
            acp_session_id=acp_sess_id,
            acp_profile_id=acp_prof_id,
        )
        run_id = run["run_id"]
        store.update_message_run_id(user_msg_id, run_id)

        with _JOBS_GUARD:
            _RUNNING_JOBS[run_id] = (cancel_event, canonical_repo)

        yield f"data: {json.dumps({'event': 'start', 'run_id': run_id, 'is_dirty': is_dirty, 'dirty_summary': dirty_summary}, ensure_ascii=False)}\n\n"

        effective_tool_ids = store.get_effective_session_tool_ids(session_id)
        # Single-shot CLI path owns no slash invocation: store.create_run()
        # never persists slash_invocation_json. Slash skills are handled by
        # the queued path (start_queued_run + coding_worker).
        selected_skill_name: Optional[str] = None
        frozen_skill_index = None

        orchestrator = CodingOrchestrator(tool_ids=effective_tool_ids)
        # Resume progress (cli_count/phase_turn) from prior HITL checkpoint when present.
        from obsidian_ai_hub.coding.ask_user_flow import restore_coding_progress

        cli_count, phase_turn = restore_coding_progress(run.get("hitl_run_id"))
        final_status = "completed"
        codex_title_source: Optional[str] = None
        # Track in-memory external session id for this turn (P0-1: carry recreated id to next iteration)
        current_external_id = session.get("external_session_id") if session else None
        # Exclusive-control protocol: one self-correction per turn, then fail.
        protocol_retried = False
        ephemeral_correction: list = []

        while True:
            if cancel_event.is_set():
                store.mark_running_tool_calls_interrupted_for_run(run_id, error="User cancelled execution")
                store.update_run(
                    run_id,
                    status="cancelled",
                    error_message="User cancelled execution",
                    finished_at=datetime.now(JST).isoformat(),
                )
                yield f"data: {json.dumps({'event': 'cancelled', 'message': 'キャンセルされました'}, ensure_ascii=False)}\n\n"
                return

            phase_turn += 1
            phase = "initial" if cli_count == 0 else "review"
            yield f"data: {json.dumps({'event': 'orchestrator_start', 'phase': phase, 'phase_turn': phase_turn}, ensure_ascii=False)}\n\n"

            # Fetch up-to-date message history for orchestrator context
            raw_history = store.list_messages(session_id)
            history = []
            for m in raw_history:
                msg_dict = {"role": m["role"], "content": m["content"]}
                history.append(msg_dict)
            # Ephemeral protocol self-correction context (not persisted).
            history.extend(ephemeral_correction)

            full_orch_response = ""
            try:
                async for event in orchestrator.generate_response_events(
                    history=history,
                    repo_path=canonical_repo,
                    backend_name=backend_name,
                    phase=phase,
                    phase_turn=phase_turn,
                    hitl_run_id=run.get("hitl_run_id"),
                    selected_skill_name=selected_skill_name,
                    frozen_skill_index=frozen_skill_index,
                    session_id=session_id,
                    current_run_id=run_id,
                ):
                    if cancel_event.is_set():
                        store.mark_running_tool_calls_interrupted_for_run(run_id, error="User cancelled execution")
                        store.update_run(
                            run_id,
                            status="cancelled",
                            error_message="User cancelled execution",
                            finished_at=datetime.now(JST).isoformat(),
                        )
                        yield f"data: {json.dumps({'event': 'cancelled', 'message': 'キャンセルされました'}, ensure_ascii=False)}\n\n"
                        return

                    evt_type = event.get("type")
                    if evt_type == "detected":
                        yield f"data: {json.dumps({'event': 'orchestrator_tool_call_detected', 'call_key': event['call_key'], 'tool_name': event['tool_name'], 'phase': phase, 'phase_turn': phase_turn, 'iteration': event['iteration'], 'call_index': event['call_index']}, ensure_ascii=False)}\n\n"
                    elif evt_type == "start":
                        store.create_orchestrator_tool_call(
                            call_id=event["call_id"],
                            run_id=run_id,
                            phase=phase,
                            phase_turn=phase_turn,
                            iteration=event["iteration"],
                            call_index=event["call_index"],
                            call_key=event["call_key"],
                            tool_name=event["tool_name"],
                            args=event["args"],
                            provider_call_id=event.get("provider_call_id"),
                            status="running",
                        )
                        yield f"data: {json.dumps({'event': 'orchestrator_tool_call_start', 'call_id': event['call_id'], 'call_key': event['call_key'], 'tool_name': event['tool_name'], 'args': event['args'], 'phase': phase, 'phase_turn': phase_turn, 'iteration': event['iteration'], 'call_index': event['call_index']}, ensure_ascii=False)}\n\n"
                    elif evt_type == "end":
                        store.update_orchestrator_tool_call(
                            call_id=event["call_id"],
                            status=event["status"],
                            result=event.get("full_result", ""),
                            error=event.get("error"),
                        )
                        yield f"data: {json.dumps({'event': 'orchestrator_tool_call_end', 'call_id': event['call_id'], 'call_key': event['call_key'], 'tool_name': event['tool_name'], 'status': event['status'], 'result': event['result'], 'error': event.get('error'), 'phase': phase, 'phase_turn': phase_turn, 'iteration': event['iteration'], 'call_index': event['call_index']}, ensure_ascii=False)}\n\n"
                    elif evt_type == "user_question":
                        ask_call = event.get("ask_call", {})
                        questions_data = event.get("questions", [])
                        hitl_run_id = f"hitl_ask_{uuid.uuid4().hex[:12]}"
                        question_set_id = "qset_1"

                        from obsidian_ai_hub.coding.ask_user_flow import (
                            build_coding_checkpoint,
                            load_prior_history_sync,
                        )

                        prior_history, _ = await asyncio.to_thread(
                            load_prior_history_sync, run.get("hitl_run_id")
                        )
                        checkpoint_data = build_coding_checkpoint(
                            session_id=session_id,
                            run_id=run_id,
                            user_prompt=user_prompt,
                            repo_path=canonical_repo,
                            backend_name=backend_name,
                            ask_call=ask_call,
                            questions_data=questions_data,
                            phase=phase,
                            phase_turn=phase_turn,
                            cli_count=cli_count,
                            tool_ids=effective_tool_ids,
                            provider=orchestrator.provider,
                            model=orchestrator.model,
                            prior_history=prior_history,
                        )

                        from obsidian_ai_hub.hitl.service import register_run_and_questions

                        register_run_and_questions(
                            run_id=hitl_run_id,
                            handler="coding.ask_user",
                            checkpoint=json.dumps(checkpoint_data, ensure_ascii=False),
                            question_set_id=question_set_id,
                            questions_data=questions_data,
                            title="会話内の要件確認",
                            description="Coding Orchestrator からの確認質問",
                            display_type="in_conversation_question",
                        )

                        store.update_run(
                            run_id,
                            status="waiting_user",
                            hitl_run_id=hitl_run_id,
                        )

                        user_question_payload = {
                            "hitl_run_id": hitl_run_id,
                            "question_set_id": question_set_id,
                            "questions": questions_data,
                        }
                        store.append_run_event(run_id, "user_question", user_question_payload)

                        yield f"data: {json.dumps({'event': 'user_question', **user_question_payload}, ensure_ascii=False)}\n\n"
                        return
                    elif evt_type == "text":
                        full_orch_response = event.get("content", "")
            except Exception as exc:
                logger.exception("Error during orchestrator execution")
                store.mark_running_tool_calls_interrupted_for_run(
                    run_id, error=f"Orchestrator error: {str(exc)}"
                )
                store.update_run(
                    run_id,
                    status="failed",
                    error_message=f"Orchestrator error: {str(exc)}",
                    finished_at=datetime.now(JST).isoformat(),
                )
                yield f"data: {json.dumps({'event': 'error', 'message': f'オーケストレーター実行エラー: {str(exc)}'}, ensure_ascii=False)}\n\n"
                return

            if cancel_event.is_set():
                store.update_run(
                    run_id,
                    status="cancelled",
                    error_message="User cancelled execution",
                    finished_at=datetime.now(JST).isoformat(),
                )
                yield f"data: {json.dumps({'event': 'cancelled', 'message': 'キャンセルされました'}, ensure_ascii=False)}\n\n"
                return

            parsed = parse_coordinator_response(full_orch_response)
            if parsed.kind == "invalid":
                if not protocol_retried:
                    protocol_retried = True
                    ephemeral_correction.append(
                        {"role": "orchestrator", "content": full_orch_response}
                    )
                    ephemeral_correction.append(
                        {
                            "role": "user",
                            "content": (
                                f"プロトコル違反（{parsed.violation}: {parsed.detail}）。"
                                f"{PROTOCOL_CORRECTION_INSTRUCTION}"
                            ),
                        }
                    )
                    continue
                store.mark_running_tool_calls_interrupted_for_run(
                    run_id,
                    error=f"Coordinator protocol violation: {parsed.violation}",
                )
                store.update_run(
                    run_id,
                    status="failed",
                    error_message=(
                        f"Coordinator protocol violation: {parsed.violation} "
                        f"({parsed.detail})"
                    ),
                    finished_at=datetime.now(JST).isoformat(),
                )
                yield f"data: {json.dumps({'event': 'error', 'message': f'オーケストレーター応答が制御契約に違反しました（{parsed.violation}）。実行を中断しました。'}, ensure_ascii=False)}\n\n"
                return
            # A successful parse consumes the pending correction budget.
            protocol_retried = False
            ephemeral_correction = []

            if parsed.kind == "continue":
                clean_orch_text = parsed.clean_text
                cli_prompt = parsed.cli_prompt
            else:
                clean_orch_text = parsed.final_report or ""
                cli_prompt = None

            # Check maximum autonomous CLI limit ceiling
            if cli_count >= MAX_CLI_ITERATIONS:
                if cli_prompt:
                    cli_prompt = None
                    if clean_orch_text:
                        clean_orch_text = (
                            f"{clean_orch_text}\n\n{CLI_LIMIT_REACHED_NOTICE}"
                        )
                    else:
                        clean_orch_text = CLI_LIMIT_REACHED_NOTICE

            # Save orchestrator message
            orch_msg = store.add_message(
                session_id, role="orchestrator", content=clean_orch_text, run_id=run_id
            )
            orch_msg_id = orch_msg["message_id"]
            store.update_run(run_id, orchestrator_message_id=orch_msg_id)
            store.associate_orchestrator_tool_calls_with_message(
                run_id, phase_turn, orch_msg_id
            )

            yield f"data: {json.dumps({'event': 'orchestrator_message', 'phase': phase, 'message': orch_msg}, ensure_ascii=False)}\n\n"

            if cancel_event.is_set():
                store.update_run(
                    run_id,
                    status="cancelled",
                    error_message="User cancelled execution",
                    finished_at=datetime.now(JST).isoformat(),
                )
                yield f"data: {json.dumps({'event': 'cancelled', 'message': 'キャンセルされました'}, ensure_ascii=False)}\n\n"
                return

            if not cli_prompt:
                break

            # Save cli_request message for history & UI dedicated card
            cli_req_msg = store.add_message(
                session_id, role="cli_request", content=cli_prompt, run_id=run_id
            )
            yield f"data: {json.dumps({'event': 'cli_request', 'message': cli_req_msg}, ensure_ascii=False)}\n\n"

            cli_count += 1
            yield f"data: {json.dumps({'event': 'worker_start', 'attempt': cli_count, 'backend': backend_name, 'transport': session_transport, 'prompt': cli_prompt}, ensure_ascii=False)}\n\n"

            # Execute worker in thread pool via selected transport
            try:
                loop = asyncio.get_running_loop()

                if session_transport == "acp":
                    acp_profile = acp_module.AcpLaunchProfile.get_profile(backend_name)
                    acp_client = acp_module.AcpClientBackend(acp_profile)
                    db_session = store.get_session(session_id)
                    db_acp_id = db_session.get("acp_session_id") if db_session else None
                    if (
                        db_acp_id != current_external_id
                        and current_external_id is None
                        and db_acp_id is not None
                    ):
                        current_external_id = db_acp_id
                    elif db_acp_id != current_external_id and cli_count == 1:
                        current_external_id = db_acp_id
                    act_acp_id = current_external_id

                    def _update_handler(params: Dict[str, Any]):
                        # Optional: emit supplementary ACP live update events
                        pass

                    acp_res: acp_module.AcpExecutionResult = await loop.run_in_executor(
                        None,
                        lambda s=act_acp_id: acp_client.execute_turn(
                            repo_path=canonical_repo,
                            prompt=cli_prompt,
                            acp_session_id=s,
                            cancel_event=cancel_event,
                            on_update_callback=_update_handler,
                        ),
                    )

                    if acp_res.session_recreated or acp_res.acp_session_id != act_acp_id:
                        store.update_session_acp_id(
                            session_id, acp_res.acp_session_id, acp_profile.profile_id
                        )
                        current_external_id = acp_res.acp_session_id

                    if acp_res.cancelled:
                        store.mark_running_tool_calls_interrupted_for_run(run_id, error="User cancelled ACP execution")
                        store.update_run(
                            run_id,
                            status="cancelled",
                            error_message="User cancelled ACP execution",
                            finished_at=datetime.now(JST).isoformat(),
                        )
                        yield f"data: {json.dumps({'event': 'cancelled', 'message': 'ACP実行がキャンセルされました'}, ensure_ascii=False)}\n\n"
                        return

                    worker_output = acp_res.output
                    if acp_res.session_recreated:
                        notice_prefix = f"前の {backend_name.capitalize()} ACP セッションが見つからなかったため、新しいセッションへ切り替えて続行しました。"
                        worker_output = f"{notice_prefix}\n\n{worker_output}" if worker_output else notice_prefix

                    worker_output, _worker_blocker = parse_and_normalize_worker_output(worker_output)
                    if backend_name == "codex" and codex_title_source is None:
                        codex_title_source = worker_output

                    worker_msg = store.add_message(
                        session_id, role="worker", content=worker_output, run_id=run_id
                    )
                    worker_msg_id = worker_msg["message_id"]

                    diag_json_str = (
                        json.dumps(acp_res.diagnostics, ensure_ascii=False)
                        if acp_res.diagnostics
                        else None
                    )

                    store.update_run(
                        run_id,
                        worker_message_id=worker_msg_id,
                        error_message=acp_res.error_message,
                        diagnostics_json=diag_json_str,
                    )
                    store.append_run_worker_message(run_id, worker_msg_id)

                    git_status = backend.get_git_status(canonical_repo)
                    worker_done_data = {
                        "event": "worker_done",
                        "attempt": cli_count,
                        "message": worker_msg,
                        "exit_code": acp_res.exit_code,
                        "error": acp_res.error_message,
                        "session_recreated": acp_res.session_recreated,
                        "git_status": git_status,
                        "diagnostics": acp_res.diagnostics,
                        "stop_reason": acp_res.stop_reason,
                    }
                    yield f"data: {json.dumps(worker_done_data, ensure_ascii=False)}\n\n"

                else:
                    cli_backend = backend.get_backend(backend_name)
                    db_session = store.get_session(session_id)
                    db_ext = db_session.get("external_session_id") if db_session else None
                    if (
                        db_ext != current_external_id
                        and current_external_id is None
                        and db_ext is not None
                    ):
                        current_external_id = db_ext
                    elif db_ext != current_external_id and cli_count == 1:
                        current_external_id = db_ext
                    ext_sess_id = current_external_id

                    cli_result: backend.CodingBackendResult = await loop.run_in_executor(
                        None,
                        lambda s=ext_sess_id: cli_backend.execute(
                            repo_path=canonical_repo,
                            prompt=cli_prompt,
                            external_session_id=s,
                            cancel_event=cancel_event,
                        ),
                    )

                    if (
                        cli_result.session_recreated
                        or cli_result.external_session_id != ext_sess_id
                    ):
                        store.update_session_external_id(
                            session_id, cli_result.external_session_id
                        )
                        current_external_id = cli_result.external_session_id

                    if cli_result.cancelled:
                        store.mark_running_tool_calls_interrupted_for_run(run_id, error="User cancelled CLI execution")
                        store.update_run(
                            run_id,
                            status="cancelled",
                            error_message="User cancelled CLI execution",
                            finished_at=datetime.now(JST).isoformat(),
                        )
                        yield f"data: {json.dumps({'event': 'cancelled', 'message': 'CLI実行がキャンセルされました'}, ensure_ascii=False)}\n\n"
                        return

                    worker_output = cli_result.output
                    if cli_result.session_recreated:
                        if backend_name == "codex":
                            notice_prefix = "前の Codex セッションが見つからなかったため、新しいセッションへ切り替えて続行しました。"
                        else:
                            notice_prefix = "前の OpenCode セッションが見つからなかったため、新しいセッションへ切り替えて続行しました。"

                        if worker_output:
                            worker_output = f"{notice_prefix}\n\n{worker_output}"
                        else:
                            worker_output = notice_prefix

                    worker_output, _worker_blocker = parse_and_normalize_worker_output(
                        worker_output
                    )
                    if backend_name == "codex" and codex_title_source is None:
                        codex_title_source = worker_output

                    worker_msg = store.add_message(
                        session_id, role="worker", content=worker_output, run_id=run_id
                    )
                    worker_msg_id = worker_msg["message_id"]

                    diag_json_str = (
                        json.dumps(cli_result.diagnostics, ensure_ascii=False)
                        if cli_result.diagnostics
                        else None
                    )

                    store.update_run(
                        run_id,
                        worker_message_id=worker_msg_id,
                        error_message=cli_result.error_message,
                        diagnostics_json=diag_json_str,
                    )
                    store.append_run_worker_message(run_id, worker_msg_id)

                    git_status = backend.get_git_status(canonical_repo)

                    worker_done_data = {
                        "event": "worker_done",
                        "attempt": cli_count,
                        "message": worker_msg,
                        "exit_code": cli_result.exit_code,
                        "error": cli_result.error_message,
                        "session_recreated": cli_result.session_recreated,
                        "git_status": git_status,
                        "diagnostics": cli_result.diagnostics,
                    }
                    yield f"data: {json.dumps(worker_done_data, ensure_ascii=False)}\n\n"

            except Exception as exc:
                logger.exception("Error during worker execution")
                store.update_run(
                    run_id,
                    status="failed",
                    error_message=f"Worker error: {str(exc)}",
                    finished_at=datetime.now(JST).isoformat(),
                )
                yield f"data: {json.dumps({'event': 'error', 'message': f'ワーカー実行エラー: {str(exc)}'}, ensure_ascii=False)}\n\n"
                return

        # Generate a Codex title through the app's standard AI Agents title LLM.
        # Codex CLI does not provide a title retrieval API, so never query it for one.
        session_title_updated: Optional[str] = None
        if backend_name == "codex" and codex_title_source is not None:
            try:
                cur_sess = store.get_session(session_id)
                if cur_sess and _should_update_coding_title(cur_sess.get("title")):
                    generated_title = await asyncio.to_thread(
                        agents_runtime.generate_session_title,
                        user_content=user_prompt,
                        assistant_content=codex_title_source,
                    )
                    if generated_title and generated_title != cur_sess.get("title"):
                        store.update_session_title(session_id, generated_title)
                        session_title_updated = generated_title
                        logger.info(
                            "Updated coding session %s title with AI Agents title generator",
                            session_id,
                        )
            except Exception as exc:
                # A title is auxiliary metadata and must not fail the Codex run.
                logger.warning(
                    "Failed to generate Codex title for session %s: %s", session_id, exc
                )

        # Attempt OpenCode external session title sync (safe post-turn hook)
        elif backend_name == "opencode":
            try:
                cur_sess = store.get_session(session_id)
                if cur_sess and cur_sess.get("external_session_id"):
                    ext_id = cur_sess.get("external_session_id")
                    cur_title = cur_sess.get("title")
                    if _should_update_coding_title(cur_title):
                        fetched_title = (
                            backend.OpenCodeCliBackend.fetch_opencode_session_title(
                                ext_id
                            )
                        )
                        if fetched_title and fetched_title != cur_title:
                            store.update_session_title(session_id, fetched_title)
                            session_title_updated = fetched_title
                            logger.info(
                                "Updated coding session %s title from OpenCode export: %s",
                                session_id,
                                fetched_title,
                            )
            except Exception as exc:
                logger.warning(
                    "Failed to sync OpenCode title for session %s: %s", session_id, exc
                )

        # Update final run status
        now_iso = datetime.now(JST).isoformat()
        store.update_run(
            run_id,
            status=final_status,
            finished_at=now_iso,
        )

        git_status = backend.get_git_status(canonical_repo)
        done_data = {
            "event": "done",
            "run_id": run_id,
            "status": final_status,
            "git_status": git_status,
        }
        if session_title_updated:
            done_data["session_title"] = session_title_updated
        yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

    finally:
        with _JOBS_GUARD:
            if "run_id" in locals():
                _RUNNING_JOBS.pop(run_id, None)
        repo_lock.release()
