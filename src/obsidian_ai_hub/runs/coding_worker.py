"""Coding run worker: queued -> running execution with event-log persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")


def _now_iso() -> str:
    return datetime.now(JST).isoformat()


async def execute_coding_run(run_id: str) -> None:
    """Execute one claimed coding run to a terminal state, persisting events."""
    from obsidian_ai_hub.agents import runtime as agents_runtime
    from obsidian_ai_hub.coding import backend, store
    from obsidian_ai_hub.coding import service as coding_service
    from obsidian_ai_hub.coding.orchestrator import CodingOrchestrator, parse_cli_request

    run = store.get_run(run_id)
    if run is None:
        logger.warning("Coding run %s not found for worker execution.", run_id)
        return
    if str(run.get("status")) == "queued":
        try:
            run = store.transition_run_status(run_id, "running")
        except ValueError:
            run = store.get_run(run_id)
            if run is None:
                return
    session = store.get_session(str(run["session_id"]))
    if session is None:
        try:
            store.transition_run_status(run_id, "failed", error_message="Session not found", finished=True)
        except ValueError:
            pass
        try:
            store.append_run_event(run_id, "error", {"message": "Session not found"})
        except Exception:
            logger.exception("Failed to append error for %s", run_id)
        return

    session_id = str(session["session_id"])
    repo_path_raw = str(session.get("repo_path") or "")
    backend_name = str(session.get("backend") or "")

    def _fail(message: str) -> None:
        try:
            cur = store.get_run(run_id)
            if cur is not None and str(cur.get("status")) in (
                "queued", "running", "cancelling",
            ):
                store.transition_run_status(run_id, "failed", error_message=message, finished=True)
        except ValueError:
            pass
        try:
            store.append_run_event(run_id, "error", {"message": message})
        except Exception:
            logger.exception("Failed to append error for %s", run_id)

    def _is_cancelling() -> bool:
        cur = store.get_run(run_id)
        return cur is not None and str(cur.get("status")) == "cancelling"

    # Validate repo.
    try:
        canonical_repo = backend.validate_git_repo(repo_path_raw)
    except ValueError as exc:
        _fail(str(exc))
        return

    # Acquire per-repo lock (non-blocking; requeue when busy).
    repo_lock = coding_service._get_repo_lock(canonical_repo)
    if not repo_lock.acquire(blocking=False):
        # Put back to queued for a later worker pass (clear worker ownership
        # so startup recovery treats it as orphaned, not owned).
        try:
            from obsidian_ai_hub.database import get_db_connection

            conn = get_db_connection()
            try:
                conn.execute(
                    "UPDATE coding_runs SET status = 'queued', worker_instance_id = NULL WHERE run_id = ? AND status = 'running';",
                    (run_id,),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.exception("Failed to requeue repo-busy run %s", run_id)
        return

    cancel_event = threading.Event()
    try:
        with coding_service._JOBS_GUARD:
            coding_service._RUNNING_JOBS[run_id] = (cancel_event, canonical_repo)

        # Record dirty-tree snapshot at start (best effort).
        try:
            is_dirty, dirty_output = backend.check_dirty_tree(canonical_repo)
            dirty_summary = dirty_output if is_dirty else None
            from obsidian_ai_hub.database import get_db_connection

            conn = get_db_connection()
            try:
                conn.execute(
                    "UPDATE coding_runs SET dirty_tree_at_start = ? WHERE run_id = ?;",
                    (dirty_summary, run_id),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.exception("Failed to record dirty tree for %s", run_id)
            is_dirty, dirty_summary = False, None

        # If cancel arrived while acquiring, stop early.
        if _is_cancelling() or cancel_event.is_set():
            try:
                store.mark_running_tool_calls_interrupted_for_run(run_id, error="User cancelled execution")
            except Exception:
                pass
            try:
                cur = store.get_run(run_id)
                if cur is not None and str(cur.get("status")) == "cancelling":
                    store.transition_run_status(
                        run_id, "cancelled", error_message="User cancelled execution", finished=True
                    )
                elif cur is not None and str(cur.get("status")) == "running":
                    store.transition_run_status(
                        run_id, "cancelled", error_message="User cancelled execution", finished=True
                    )
            except ValueError:
                pass
            try:
                store.append_run_event(run_id, "cancelled", {"message": "キャンセルされました"})
            except Exception:
                pass
            return

        effective_tool_ids = store.get_effective_session_tool_ids(session_id)
        orchestrator = CodingOrchestrator(tool_ids=effective_tool_ids)
        # Resume progress (cli_count/phase_turn) from prior HITL checkpoint when present.
        # A corrupt prior fails the run instead of silently dropping answers.
        from obsidian_ai_hub.coding.ask_user_flow import restore_coding_progress

        try:
            cli_count, phase_turn = restore_coding_progress(run.get("hitl_run_id"))
        except Exception as exc:
            _fail(f"Prior HITL checkpoint unreadable: {exc}")
            return
        final_status = "completed"
        codex_title_source: Optional[str] = None
        current_external_id = session.get("external_session_id")

        # Load user prompt from the queued user message.
        user_msg = store.get_message(str(run.get("user_message_id") or ""))
        user_prompt = str((user_msg or {}).get("content") or "")

        while True:
            if _is_cancelling() or cancel_event.is_set():
                try:
                    store.mark_running_tool_calls_interrupted_for_run(run_id, error="User cancelled execution")
                except Exception:
                    pass
                try:
                    store.transition_run_status(
                        run_id, "cancelled", error_message="User cancelled execution", finished=True
                    )
                except ValueError:
                    pass
                try:
                    store.append_run_event(run_id, "cancelled", {"message": "キャンセルされました"})
                except Exception:
                    pass
                return

            phase_turn += 1
            phase = "initial" if cli_count == 0 else "review"
            try:
                store.append_run_event(
                    run_id, "orchestrator_start", {"phase": phase, "phase_turn": phase_turn}
                )
            except Exception:
                logger.exception("Failed to append orchestrator_start for %s", run_id)

            raw_history = store.list_messages(session_id)
            history = [{"role": m["role"], "content": m["content"]} for m in raw_history]

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
                    if _is_cancelling() or cancel_event.is_set():
                        try:
                            store.mark_running_tool_calls_interrupted_for_run(
                                run_id, error="User cancelled execution"
                            )
                        except Exception:
                            pass
                        try:
                            store.transition_run_status(
                                run_id, "cancelled",
                                error_message="User cancelled execution", finished=True,
                            )
                        except ValueError:
                            pass
                        try:
                            store.append_run_event(run_id, "cancelled", {"message": "キャンセルされました"})
                        except Exception:
                            pass
                        return
                    evt_type = event.get("type")
                    if evt_type == "detected":
                        try:
                            store.append_run_event(
                                run_id, "orchestrator_tool_call_detected",
                                {
                                    "call_key": event.get("call_key"),
                                    "tool_name": event.get("tool_name"),
                                    "phase": phase,
                                    "phase_turn": phase_turn,
                                    "iteration": event.get("iteration"),
                                    "call_index": event.get("call_index"),
                                },
                            )
                        except Exception:
                            logger.exception("append detected failed %s", run_id)
                    elif evt_type == "start":
                        try:
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
                        except Exception:
                            logger.exception("create tool call failed %s", run_id)
                        try:
                            store.append_run_event(
                                run_id, "orchestrator_tool_call_start",
                                {
                                    "call_id": event.get("call_id"),
                                    "call_key": event.get("call_key"),
                                    "tool_name": event.get("tool_name"),
                                    "args": event.get("args"),
                                    "phase": phase,
                                    "phase_turn": phase_turn,
                                    "iteration": event.get("iteration"),
                                    "call_index": event.get("call_index"),
                                },
                            )
                        except Exception:
                            logger.exception("append start failed %s", run_id)
                    elif evt_type == "end":
                        try:
                            store.update_orchestrator_tool_call(
                                call_id=event["call_id"],
                                status=event["status"],
                                result=event.get("full_result", ""),
                                error=event.get("error"),
                            )
                        except Exception:
                            logger.exception("update tool call failed %s", run_id)
                        try:
                            store.append_run_event(
                                run_id, "orchestrator_tool_call_end",
                                {
                                    "call_id": event.get("call_id"),
                                    "call_key": event.get("call_key"),
                                    "tool_name": event.get("tool_name"),
                                    "status": event.get("status"),
                                    "result": event.get("result"),
                                    "error": event.get("error"),
                                    "phase": phase,
                                    "phase_turn": phase_turn,
                                    "iteration": event.get("iteration"),
                                    "call_index": event.get("call_index"),
                                },
                            )
                        except Exception:
                            logger.exception("append end failed %s", run_id)
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
                        return
                    elif evt_type == "text":
                        full_orch_response = event.get("content", "")
            except Exception as exc:
                logger.exception("Orchestrator error for %s", run_id)
                try:
                    store.mark_running_tool_calls_interrupted_for_run(
                        run_id, error=f"Orchestrator error: {exc}"
                    )
                except Exception:
                    pass
                try:
                    store.transition_run_status(
                        run_id, "failed",
                        error_message=f"Orchestrator error: {exc}", finished=True,
                    )
                except ValueError:
                    pass
                try:
                    store.append_run_event(run_id, "error", {"message": f"オーケストレーター実行エラー: {exc}"})
                except Exception:
                    pass
                return

            if _is_cancelling() or cancel_event.is_set():
                try:
                    store.transition_run_status(
                        run_id, "cancelled", error_message="User cancelled execution", finished=True
                    )
                except ValueError:
                    pass
                try:
                    store.append_run_event(run_id, "cancelled", {"message": "キャンセルされました"})
                except Exception:
                    pass
                return

            clean_orch_text, cli_prompt = parse_cli_request(full_orch_response)
            if cli_count >= coding_service.MAX_CLI_ITERATIONS:
                if cli_prompt:
                    cli_prompt = None
                    if clean_orch_text:
                        clean_orch_text = f"{clean_orch_text}\n\n{coding_service.CLI_LIMIT_REACHED_NOTICE}"
                    else:
                        clean_orch_text = coding_service.CLI_LIMIT_REACHED_NOTICE

            orch_msg = store.add_message(
                session_id, role="orchestrator", content=clean_orch_text, run_id=run_id
            )
            orch_msg_id = orch_msg["message_id"]
            try:
                store.update_run(run_id, orchestrator_message_id=orch_msg_id)
            except Exception:
                logger.exception("update orchestrator msg failed %s", run_id)
            try:
                store.associate_orchestrator_tool_calls_with_message(run_id, phase_turn, orch_msg_id)
            except Exception:
                logger.exception("associate tool calls failed %s", run_id)
            try:
                store.append_run_event(
                    run_id, "orchestrator_message",
                    {"phase": phase, "phase_turn": phase_turn, "message": orch_msg},
                )
            except Exception:
                logger.exception("append orch message failed %s", run_id)

            if _is_cancelling() or cancel_event.is_set():
                try:
                    store.transition_run_status(
                        run_id, "cancelled", error_message="User cancelled execution", finished=True
                    )
                except ValueError:
                    pass
                try:
                    store.append_run_event(run_id, "cancelled", {"message": "キャンセルされました"})
                except Exception:
                    pass
                return

            if not cli_prompt:
                break

            cli_req_msg = store.add_message(
                session_id, role="cli_request", content=cli_prompt, run_id=run_id
            )
            try:
                store.append_run_event(run_id, "cli_request", {"message": cli_req_msg})
            except Exception:
                logger.exception("append cli_request failed %s", run_id)

            cli_count += 1
            try:
                store.append_run_event(
                    run_id, "worker_start",
                    {"attempt": cli_count, "backend": backend_name, "prompt": cli_prompt},
                )
            except Exception:
                logger.exception("append worker_start failed %s", run_id)

            try:
                cli_backend = backend.get_backend(backend_name)
                db_session = store.get_session(session_id)
                db_ext = db_session.get("external_session_id") if db_session else None
                if db_ext != current_external_id and current_external_id is None and db_ext is not None:
                    current_external_id = db_ext
                elif db_ext != current_external_id and cli_count == 1:
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

                if cli_result.session_recreated or cli_result.external_session_id != ext_sess_id:
                    store.update_session_external_id(session_id, cli_result.external_session_id)
                    current_external_id = cli_result.external_session_id

                if cli_result.cancelled or _is_cancelling() or cancel_event.is_set():
                    try:
                        store.mark_running_tool_calls_interrupted_for_run(
                            run_id, error="User cancelled CLI execution"
                        )
                    except Exception:
                        pass
                    try:
                        store.transition_run_status(
                            run_id, "cancelled",
                            error_message="User cancelled CLI execution", finished=True,
                        )
                    except ValueError:
                        pass
                    try:
                        store.append_run_event(run_id, "cancelled", {"message": "CLI実行がキャンセルされました"})
                    except Exception:
                        pass
                    return

                worker_output = cli_result.output
                if backend_name == "codex" and codex_title_source is None:
                    codex_title_source = worker_output
                if cli_result.session_recreated:
                    if backend_name == "codex":
                        notice_prefix = "前の Codex セッションが見つからなかったため、新しいセッションへ切り替えて続行しました。"
                    else:
                        notice_prefix = "前の OpenCode セッションが見つからなかったため、新しいセッションへ切り替えて続行しました。"
                    worker_output = f"{notice_prefix}\n\n{worker_output}" if worker_output else notice_prefix

                worker_msg = store.add_message(
                    session_id, role="worker", content=worker_output, run_id=run_id
                )
                worker_msg_id = worker_msg["message_id"]
                diag_json_str = (
                    json.dumps(cli_result.diagnostics, ensure_ascii=False)
                    if cli_result.diagnostics
                    else None
                )
                try:
                    store.update_run(
                        run_id,
                        worker_message_id=worker_msg_id,
                        error_message=cli_result.error_message,
                        diagnostics_json=diag_json_str,
                    )
                except Exception:
                    logger.exception("update worker msg failed %s", run_id)
                try:
                    import sqlite3 as _sqlite3

                    try:
                        store.append_run_worker_message(run_id, worker_msg_id)
                    except _sqlite3.Error:
                        logger.exception("append worker linkage failed %s", run_id)
                        raise
                except Exception:
                    raise

                try:
                    git_status = backend.get_git_status(canonical_repo)
                except Exception:
                    git_status = None
                try:
                    store.append_run_event(
                        run_id, "worker_done",
                        {
                            "attempt": cli_count,
                            "message": worker_msg,
                            "exit_code": cli_result.exit_code,
                            "error": cli_result.error_message,
                            "session_recreated": cli_result.session_recreated,
                            "git_status": git_status,
                            "diagnostics": cli_result.diagnostics,
                        },
                    )
                except Exception:
                    logger.exception("append worker_done failed %s", run_id)

            except Exception as exc:
                logger.exception("CLI worker error for %s", run_id)
                try:
                    store.transition_run_status(
                        run_id, "failed", error_message=f"Worker error: {exc}", finished=True
                    )
                except ValueError:
                    pass
                try:
                    store.append_run_event(run_id, "error", {"message": f"CLIワーカー実行エラー: {exc}"})
                except Exception:
                    pass
                return

        # Title sync (best effort, must not fail run).
        session_title_updated: Optional[str] = None
        if backend_name == "codex" and codex_title_source is not None:
            try:
                cur_sess = store.get_session(session_id)
                if cur_sess and coding_service._should_update_coding_title(cur_sess.get("title")):
                    generated_title = await asyncio.to_thread(
                        agents_runtime.generate_session_title,
                        user_content=user_prompt,
                        assistant_content=codex_title_source,
                    )
                    if generated_title and generated_title != cur_sess.get("title"):
                        store.update_session_title(session_id, generated_title)
                        session_title_updated = generated_title
            except Exception as exc:
                logger.warning("Codex title generation failed for %s: %s", session_id, exc)
        elif backend_name == "opencode":
            try:
                cur_sess = store.get_session(session_id)
                if cur_sess and cur_sess.get("external_session_id"):
                    ext_id = cur_sess.get("external_session_id")
                    cur_title = cur_sess.get("title")
                    if coding_service._should_update_coding_title(cur_title):
                        fetched_title = backend.OpenCodeCliBackend.fetch_opencode_session_title(ext_id)
                        if fetched_title and fetched_title != cur_title:
                            store.update_session_title(session_id, fetched_title)
                            session_title_updated = fetched_title
            except Exception as exc:
                logger.warning("OpenCode title sync failed for %s: %s", session_id, exc)

        # Final status (respect late cancel).
        if _is_cancelling() or cancel_event.is_set():
            try:
                store.transition_run_status(
                    run_id, "cancelled", error_message="User cancelled execution", finished=True
                )
            except ValueError:
                pass
            try:
                store.append_run_event(run_id, "cancelled", {"message": "キャンセルされました"})
            except Exception:
                pass
            return

        try:
            store.transition_run_status(run_id, final_status, finished=True)
        except ValueError:
            # Already terminal (e.g. cancelled raced); keep it.
            pass
        try:
            git_status = backend.get_git_status(canonical_repo)
        except Exception:
            git_status = None
        done_payload: dict[str, Any] = {
            "run_id": run_id,
            "status": final_status,
            "git_status": git_status,
        }
        if session_title_updated:
            done_payload["session_title"] = session_title_updated
        try:
            store.append_run_event(run_id, "done", done_payload)
        except Exception:
            logger.exception("append done failed %s", run_id)
    finally:
        with coding_service._JOBS_GUARD:
            coding_service._RUNNING_JOBS.pop(run_id, None)
        try:
            repo_lock.release()
        except Exception:
            pass


async def coding_worker_loop(
    instance_id: str,
    stop_event: asyncio.Event,
    poll_interval: float = 0.5,
) -> None:
    from obsidian_ai_hub.coding import store

    while not stop_event.is_set():
        try:
            claimed = await asyncio.to_thread(store.claim_queued_run, instance_id)
        except Exception:
            logger.exception("Coding claim failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
            continue
        if claimed is None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
            continue
        try:
            await execute_coding_run(str(claimed["run_id"]))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Coding worker loop failed for %s", claimed.get("run_id"))
