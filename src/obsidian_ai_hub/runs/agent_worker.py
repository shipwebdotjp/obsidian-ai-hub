"""Agent run worker: queued -> running execution with event-log persistence."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from obsidian_ai_hub.runs.events import TextAggregator

logger = logging.getLogger(__name__)


def _parse_sse_payload(chunk: str) -> dict[str, Any] | None:
    for line in chunk.splitlines():
        if line.startswith("data:"):
            data = line[len("data:"):].strip()
            try:
                parsed = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return None
            if isinstance(parsed, dict):
                return parsed
    return None


async def execute_agent_run(run_id: str) -> None:
    """Execute one claimed agent run to a terminal state, persisting events."""
    from obsidian_ai_hub.agents import runtime as agent_runtime
    from obsidian_ai_hub.agents import store as agent_store

    run = await asyncio.to_thread(agent_store.get_run, run_id)
    if run is None:
        logger.warning("Agent run %s not found for worker execution.", run_id)
        return
    # Worker loop claims (queued->running) before execute, but direct calls
    # (tests, manual) may pass a queued run: promote it so complete_run's
    # running-only guard holds.
    if str(run.get("status")) == "queued":
        try:
            run = await asyncio.to_thread(
                agent_store.transition_run_status, run_id, "running"
            )
        except ValueError:
            run = await asyncio.to_thread(agent_store.get_run, run_id)
            if run is None:
                return
    session = await asyncio.to_thread(agent_store.get_session, run["session_id"])
    if session is None:
        await asyncio.to_thread(
            agent_store.transition_run_status, run_id, "failed",
            error_message="Session not found", finished=True,
        )
        try:
            await asyncio.to_thread(
                agent_store.append_run_event, run_id, "error",
                {"error": "Session not found", "run_id": run_id},
            )
        except Exception:
            logger.exception("Failed to append error event for run %s", run_id)
        return

    agent = await asyncio.to_thread(agent_store.get_agent, session["agent_id"])
    if agent is None:
        await asyncio.to_thread(
            agent_store.transition_run_status, run_id, "failed",
            error_message="Agent not found", finished=True,
        )
        try:
            await asyncio.to_thread(
                agent_store.append_run_event, run_id, "error",
                {"error": "Agent not found", "run_id": run_id},
            )
        except Exception:
            logger.exception("Failed to append error event for run %s", run_id)
        return

    history = await asyncio.to_thread(agent_store.list_messages, session["session_id"])
    user_msg = await asyncio.to_thread(agent_store.get_message, run["user_message_id"])
    user_content = str((user_msg or {}).get("content") or "")
    attachments = (user_msg or {}).get("attachments")

    aggregator = TextAggregator()
    stream = agent_runtime.generate_agent_stream(
        agent=agent,
        session=session,
        run=run,
        history_messages=history,
        user_content=user_content,
        attachments=attachments,
    )

    async def _is_cancelling() -> bool:
        current = await asyncio.to_thread(agent_store.get_run, run_id)
        return current is not None and str(current.get("status")) == "cancelling"

    try:
        async for chunk in stream:
            if await _is_cancelling():
                # Stop consuming; mark cancelled after current tool call returns.
                # aclose the generator to avoid further LLM/tool work.
                try:
                    await stream.aclose()
                except Exception:
                    pass
                flushed = aggregator.flush()
                if flushed:
                    try:
                        await asyncio.to_thread(
                            agent_store.append_run_event, run_id, "text_append",
                            {"delta": flushed},
                        )
                    except Exception:
                        logger.exception("Failed to append flushed text for %s", run_id)
                try:
                    await asyncio.to_thread(
                        agent_store.transition_run_status, run_id, "cancelled",
                        error_message="User cancelled execution", finished=True,
                    )
                except ValueError:
                    # Already terminal via runtime path; keep terminal state.
                    pass
                try:
                    await asyncio.to_thread(
                        agent_store.append_run_event, run_id, "cancelled",
                        {"run_id": run_id},
                    )
                except Exception:
                    logger.exception("Failed to append cancelled event for %s", run_id)
                return

            payload = _parse_sse_payload(chunk)
            if payload is None:
                continue
            ptype = str(payload.get("type") or "")

            if ptype == "text":
                delta = str(payload.get("delta") or "")
                aggregated = aggregator.add(delta)
                if aggregated:
                    try:
                        await asyncio.to_thread(
                            agent_store.append_run_event, run_id, "text_append",
                            {"delta": aggregated},
                        )
                    except Exception:
                        logger.exception("Failed to append text_append for %s", run_id)
            elif ptype in (
                "thinking",
                "tool_call_detected",
                "tool_call_start",
                "tool_call_end",
            ):
                try:
                    await asyncio.to_thread(
                        agent_store.append_run_event, run_id, ptype, payload
                    )
                except Exception:
                    logger.exception("Failed to append %s for %s", ptype, run_id)
            elif ptype == "user_question":
                flushed = aggregator.flush()
                if flushed:
                    try:
                        await asyncio.to_thread(
                            agent_store.append_run_event, run_id, "text_append",
                            {"delta": flushed},
                        )
                    except Exception:
                        logger.exception("Failed to flush text before user_question %s", run_id)
                # Runtime already transitioned to waiting_user.
                try:
                    await asyncio.to_thread(
                        agent_store.append_run_event, run_id, "user_question", payload
                    )
                except Exception:
                    logger.exception("Failed to append user_question for %s", run_id)
                return
            elif ptype == "done":
                flushed = aggregator.flush()
                if flushed:
                    try:
                        await asyncio.to_thread(
                            agent_store.append_run_event, run_id, "text_append",
                            {"delta": flushed},
                        )
                    except Exception:
                        logger.exception("Failed to flush text before done %s", run_id)
                # Runtime already completed run; persist terminal event.
                # Keep payload but ensure run_id present for folding.
                done_payload = dict(payload)
                done_payload.setdefault("run_id", run_id)
                try:
                    await asyncio.to_thread(
                        agent_store.append_run_event, run_id, "done", done_payload
                    )
                except Exception:
                    logger.exception("Failed to append done for %s", run_id)
                return
            elif ptype == "error":
                flushed = aggregator.flush()
                if flushed:
                    try:
                        await asyncio.to_thread(
                            agent_store.append_run_event, run_id, "text_append",
                            {"delta": flushed},
                        )
                    except Exception:
                        logger.exception("Failed to flush text before error %s", run_id)
                try:
                    await asyncio.to_thread(
                        agent_store.append_run_event, run_id, "error", payload
                    )
                except Exception:
                    logger.exception("Failed to append error for %s", run_id)
                return
            else:
                logger.debug("Ignoring unknown agent stream type %s for %s", ptype, run_id)

        # Generator ended without terminal event (e.g. cancelled close or bug).
        flushed = aggregator.flush()
        if flushed:
            try:
                await asyncio.to_thread(
                    agent_store.append_run_event, run_id, "text_append",
                    {"delta": flushed},
                )
            except Exception:
                logger.exception("Failed to flush trailing text for %s", run_id)
        current = await asyncio.to_thread(agent_store.get_run, run_id)
        if current is not None and str(current.get("status")) in ("running", "cancelling", "queued"):
            # No terminal event observed; mark failed to avoid orphaned running.
            try:
                await asyncio.to_thread(
                    agent_store.transition_run_status, run_id, "failed",
                    error_message="Agent worker ended without terminal event", finished=True,
                )
            except ValueError:
                pass
            try:
                await asyncio.to_thread(
                    agent_store.append_run_event, run_id, "error",
                    {"error": "Agent worker ended without terminal event", "run_id": run_id},
                )
            except Exception:
                logger.exception("Failed to append trailing error for %s", run_id)
    except asyncio.CancelledError:
        # Worker shutdown: leave run for shutdown recovery (interrupted).
        raise
    except Exception as exc:
        logger.exception("Agent worker failed for run %s", run_id)
        try:
            flushed = aggregator.flush()
            if flushed:
                await asyncio.to_thread(
                    agent_store.append_run_event, run_id, "text_append",
                    {"delta": flushed},
                )
        except Exception:
            pass
        try:
            current = await asyncio.to_thread(agent_store.get_run, run_id)
            if current is not None and str(current.get("status")) in (
                "queued", "running", "cancelling",
            ):
                await asyncio.to_thread(
                    agent_store.transition_run_status, run_id, "failed",
                    error_message=str(exc), finished=True,
                )
        except Exception:
            logger.exception("Failed to mark agent run %s failed", run_id)
        try:
            await asyncio.to_thread(
                agent_store.append_run_event, run_id, "error",
                {"error": str(exc), "run_id": run_id},
            )
        except Exception:
            logger.exception("Failed to append error event for %s", run_id)


async def agent_worker_loop(
    instance_id: str,
    stop_event: asyncio.Event,
    poll_interval: float = 0.5,
) -> None:
    from obsidian_ai_hub.agents import store as agent_store

    while not stop_event.is_set():
        try:
            claimed = await asyncio.to_thread(agent_store.claim_queued_run, instance_id)
        except Exception:
            logger.exception("Agent claim failed")
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
            await execute_agent_run(str(claimed["run_id"]))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Agent worker loop execution failed for %s", claimed.get("run_id"))
