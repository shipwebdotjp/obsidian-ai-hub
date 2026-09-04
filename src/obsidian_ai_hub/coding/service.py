"""Service layer orchestrating coding workspace sessions and runs."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from datetime import datetime
from typing import AsyncGenerator, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from obsidian_ai_hub.agents import runtime as agents_runtime
from obsidian_ai_hub.coding import backend, store
from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator, parse_cli_request

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")

MAX_CLI_ITERATIONS = 50
CLI_LIMIT_REACHED_NOTICE = (
    "追加のCLI実行が必要と判断されましたが、このメッセージ内での自動実行上限（50回）に達したため実行していません。"
    "続行する場合は、作業を継続するよう指示してください。"
)

DEFAULT_CODING_SESSION_TITLE = "新しいコーディングセッション"


def _should_update_coding_title(current_title: Optional[str]) -> bool:
    """Return True only if title is auto-generated / unset and safe to overwrite.

    Overwrite only when title equals the default placeholder or is empty.
    This prevents destroying user-supplied titles.
    """
    if not current_title:
        return True
    stripped = current_title.strip()
    return stripped == "" or stripped == DEFAULT_CODING_SESSION_TITLE


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
        run = store.create_run(
            session_id=session_id,
            user_message_id=user_msg_id,
            dirty_tree_at_start=dirty_summary,
        )
        run_id = run["run_id"]
        store.update_message_run_id(user_msg_id, run_id)

        with _JOBS_GUARD:
            _RUNNING_JOBS[run_id] = (cancel_event, canonical_repo)

        yield f"data: {json.dumps({'event': 'start', 'run_id': run_id, 'is_dirty': is_dirty, 'dirty_summary': dirty_summary}, ensure_ascii=False)}\n\n"

        effective_tool_ids = store.get_effective_session_tool_ids(session_id)
        orchestrator = CodingOrchestrator(tool_ids=effective_tool_ids)
        # Resume progress (cli_count/phase_turn) from prior HITL checkpoint when present.
        from obsidian_ai_hub.coding.ask_user_flow import restore_coding_progress

        cli_count, phase_turn = restore_coding_progress(run.get("hitl_run_id"))
        final_status = "completed"
        codex_title_source: Optional[str] = None
        # Track in-memory external session id for this turn (P0-1: carry recreated id to next iteration)
        current_external_id = session.get("external_session_id") if session else None

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

            full_orch_response = ""
            try:
                async for event in orchestrator.generate_response_events(
                    history=history,
                    repo_path=canonical_repo,
                    backend_name=backend_name,
                    phase=phase,
                    phase_turn=phase_turn,
                    hitl_run_id=run.get("hitl_run_id"),
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

            clean_orch_text, cli_prompt = parse_cli_request(full_orch_response)

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
            yield f"data: {json.dumps({'event': 'worker_start', 'attempt': cli_count, 'backend': backend_name, 'prompt': cli_prompt}, ensure_ascii=False)}\n\n"

            # Execute worker CLI in thread pool
            try:
                cli_backend = backend.get_backend(backend_name)
                # P0-1: Keep in-memory recreated ID as priority within the same turn.
                # The turn's conversation continuity (recreated ses_...) outranks concurrent
                # external DB updates. Only adopt DB value when this turn has not yet
                # established one (first iteration with pre-existing session) or explicitly
                # on the first iteration to pick up updates made before the turn started.
                # Re-fetch from DB only if in-memory is stale (e.g., concurrent update outside turn)
                db_session = store.get_session(session_id)
                db_ext = db_session.get("external_session_id") if db_session else None
                if (
                    db_ext != current_external_id
                    and current_external_id is None
                    and db_ext is not None
                ):
                    # Adopt DB value if this turn hasn't yet set one (first iteration with pre-existing session)
                    current_external_id = db_ext
                elif db_ext != current_external_id and cli_count == 1:
                    # Prefer DB on first iteration (cli_count is 1 after increment) to pick up external updates prior to turn
                    current_external_id = db_ext
                ext_sess_id = current_external_id

                loop = asyncio.get_running_loop()
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
                    # Update in-memory id so next <cli_request> in same turn uses recreated id (P0-1)
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
                if backend_name == "codex" and codex_title_source is None:
                    # Use the first Codex response, matching AI Agents' initial-turn
                    # title generation semantics rather than querying Codex for a title.
                    codex_title_source = worker_output
                if cli_result.session_recreated:
                    if backend_name == "codex":
                        notice_prefix = "前の Codex セッションが見つからなかったため、新しいセッションへ切り替えて続行しました。"
                    else:
                        notice_prefix = "前の OpenCode セッションが見つからなかったため、新しいセッションへ切り替えて続行しました。"

                    if worker_output:
                        worker_output = f"{notice_prefix}\n\n{worker_output}"
                    else:
                        worker_output = notice_prefix

                # Save worker output message (P1-2: link to run via run_id)
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
                # P1-2: v30以降は coding_messages.run_id が唯一の正のため junction 二重書き込みは不要。
                # add_message(..., run_id=...) で既に紐付け済み。migration前（列不存在）時のみ
                # junction で追跡する。判定は store._has_run_id_column に委譲するが、
                # 冗長呼び出し自体は store側で早期returnする。DBエラーは握りつぶさず伝播させ、
                # 外側の except Exception で run を failed に遷移させる。
                try:
                    store.append_run_worker_message(run_id, worker_msg_id)
                except sqlite3.Error as exc:  # pragma: no cover - DB整合性エラーは明確にログし伝播
                    logger.error(
                        "Failed to persist worker message linkage for run %s message %s: %s",
                        run_id,
                        worker_msg_id,
                        exc,
                    )
                    raise

                # Compute up-to-date git status after CLI execution
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
                logger.exception("Error during CLI worker execution")
                store.update_run(
                    run_id,
                    status="failed",
                    error_message=f"Worker error: {str(exc)}",
                    finished_at=datetime.now(JST).isoformat(),
                )
                yield f"data: {json.dumps({'event': 'error', 'message': f'CLIワーカー実行エラー: {str(exc)}'}, ensure_ascii=False)}\n\n"
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
