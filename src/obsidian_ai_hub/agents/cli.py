"""CLI implementation for AI Agent single-turn chat (--agent-chat)."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

from obsidian_ai_hub.agents import runtime, store
from obsidian_ai_hub.agents.service import prepare_session_turn


async def _execute_agent_chat_stream(
    agent: Dict[str, Any],
    session: Dict[str, Any],
    run: Dict[str, Any],
    history_messages: List[Dict[str, Any]],
    prompt: str,
    output_format: str,
) -> int:
    session_id = session["session_id"]
    run_id = run["run_id"]

    if output_format == "text":
        sys.stderr.write(f"[session] session_id={session_id}\n")
        sys.stderr.write(f"[run] run_id={run_id}\n")
        sys.stderr.flush()

    done_data: Optional[Dict[str, Any]] = None
    stream_error: Optional[str] = None
    printed_text_delta = False

    async for sse_chunk in runtime.generate_agent_stream(
        agent=agent,
        session=session,
        run=run,
        history_messages=history_messages,
        user_content=prompt,
    ):
        # Parse SSE chunk: "data: {...}\n\n"
        for line in sse_chunk.splitlines():
            if line.startswith("data: "):
                try:
                    payload = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                event_type = payload.get("type")

                if event_type == "text":
                    delta = payload.get("delta", "")
                    if output_format == "text" and delta:
                        sys.stdout.write(delta)
                        sys.stdout.flush()
                        printed_text_delta = True

                elif event_type == "tool_call_start":
                    if output_format == "text":
                        tool_name = payload.get("tool_name", "")
                        args = payload.get("args", {})
                        sys.stderr.write(
                            f"[tool_start] tool_name={tool_name} args={json.dumps(args, ensure_ascii=False)}\n"
                        )
                        sys.stderr.flush()

                elif event_type == "tool_call_end":
                    if output_format == "text":
                        tool_name = payload.get("tool_name", "")
                        status = payload.get("status", "")
                        hitl_id = payload.get("hitl_run_id")
                        sys.stderr.write(
                            f"[tool_end] tool_name={tool_name} status={status}\n"
                        )
                        if hitl_id:
                            sys.stderr.write(f"[hitl] run_id={hitl_id}\n")
                        sys.stderr.flush()

                elif event_type == "done":
                    done_data = payload

                elif event_type == "error":
                    stream_error = payload.get("error", "An error occurred during execution.")

    if output_format == "text" and printed_text_delta:
        sys.stdout.write("\n")
        sys.stdout.flush()

    if stream_error or not done_data:
        err_msg = stream_error or "Execution finished without done event."
        sys.stderr.write(f"[error] {err_msg}\n")
        sys.stderr.flush()
        return 1

    if output_format == "json":
        latest_session = store.get_session(session_id) or session
        output_obj = {
            "session": latest_session,
            "message": done_data.get("message", {}),
            "run": done_data.get("run", {}),
            "hitl_run_ids": done_data.get("hitl_run_ids", []),
            "tool_calls": done_data.get("tool_calls", []),
        }
        sys.stdout.write(json.dumps(output_obj, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()

    return 0


def main_agent_chat(
    agent_id: str,
    prompt: Optional[str] = None,
    resume_session: Optional[str] = None,
    output_format: str = "text",
) -> None:
    """CLI entry point for --agent-chat."""
    if prompt is None or prompt == "":
        if not sys.stdin.isatty():
            prompt = sys.stdin.read()
        else:
            prompt = ""

    clean_prompt = prompt.strip() if prompt else ""
    if not clean_prompt:
        sys.stderr.write("Error: Agent prompt is empty.\n")
        sys.stderr.flush()
        sys.exit(1)

    try:
        session, agent, run, history_messages = prepare_session_turn(
            agent_id=agent_id,
            prompt=clean_prompt,
            resume_session_id=resume_session,
        )
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.stderr.flush()
        sys.exit(1)

    exit_code = asyncio.run(
        _execute_agent_chat_stream(
            agent=agent,
            session=session,
            run=run,
            history_messages=history_messages,
            prompt=clean_prompt,
            output_format=output_format,
        )
    )

    if exit_code != 0:
        sys.exit(exit_code)
