"""Service layer orchestrating coding workspace sessions and runs."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from typing import AsyncGenerator, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from obsidian_ai_hub.coding import backend, store
from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator, parse_cli_request

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")

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

        with _JOBS_GUARD:
            _RUNNING_JOBS[run_id] = (cancel_event, canonical_repo)

        yield f"data: {json.dumps({'event': 'start', 'run_id': run_id, 'is_dirty': is_dirty, 'dirty_summary': dirty_summary}, ensure_ascii=False)}\n\n"

        # Fetch history
        raw_history = store.list_messages(session_id)
        # Exclude the newly added user message from history argument
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in raw_history
            if m["message_id"] != user_msg_id
        ]

        # Call orchestrator
        orchestrator = CodingOrchestrator()
        full_orch_response = ""

        try:
            async for token in orchestrator.stream_response(
                history=history,
                new_user_message=user_prompt,
                repo_path=canonical_repo,
                backend_name=backend_name,
            ):
                if cancel_event.is_set():
                    break
                full_orch_response += token
                yield f"data: {json.dumps({'event': 'orchestrator_chunk', 'text': token}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("Error during orchestrator streaming")
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
                error_message="User cancelled during orchestrator phase",
                finished_at=datetime.now(JST).isoformat(),
            )
            yield f"data: {json.dumps({'event': 'cancelled', 'message': 'キャンセルされました'}, ensure_ascii=False)}\n\n"
            return

        clean_orch_text, cli_prompt = parse_cli_request(full_orch_response)

        # Save orchestrator message
        orch_msg = store.add_message(session_id, role="orchestrator", content=clean_orch_text)
        orch_msg_id = orch_msg["message_id"]
        store.update_run(run_id, orchestrator_message_id=orch_msg_id)

        worker_msg_id = None
        final_status = "completed"
        if cli_prompt and not cancel_event.is_set():
            yield f"data: {json.dumps({'event': 'worker_start', 'backend': backend_name, 'prompt': cli_prompt}, ensure_ascii=False)}\n\n"

            # Execute worker CLI in thread pool to not block event loop
            try:
                cli_backend = backend.get_backend(backend_name)
                ext_sess_id = session.get("external_session_id")

                loop = asyncio.get_running_loop()
                cli_result: backend.CodingBackendResult = await loop.run_in_executor(
                    None,
                    lambda: cli_backend.execute(
                        repo_path=canonical_repo,
                        prompt=cli_prompt,
                        external_session_id=ext_sess_id,
                        cancel_event=cancel_event,
                    ),
                )

                if cli_result.session_recreated or cli_result.external_session_id != ext_sess_id:
                    store.update_session_external_id(
                        session_id, cli_result.external_session_id
                    )

                if cli_result.cancelled:
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

                # Save worker output message
                worker_msg = store.add_message(
                    session_id, role="worker", content=worker_output
                )
                worker_msg_id = worker_msg["message_id"]

                if cli_result.exit_code != 0:
                    final_status = "failed"

                store.update_run(
                    run_id,
                    worker_message_id=worker_msg_id,
                    error_message=cli_result.error_message,
                )

                worker_done_data = {
                    'event': 'worker_done',
                    'output': worker_output,
                    'exit_code': cli_result.exit_code,
                    'error': cli_result.error_message,
                    'session_recreated': cli_result.session_recreated,
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

        # Update final run status
        now_iso = datetime.now(JST).isoformat()
        store.update_run(
            run_id,
            status=final_status,
            finished_at=now_iso,
        )

        yield f"data: {json.dumps({'event': 'done', 'run_id': run_id, 'status': final_status}, ensure_ascii=False)}\n\n"

    finally:
        with _JOBS_GUARD:
            if 'run_id' in locals():
                _RUNNING_JOBS.pop(run_id, None)
        repo_lock.release()
