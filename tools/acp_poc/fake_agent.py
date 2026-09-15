"""Canned stdio ACP agent for harness self-tests (no network, no LLM).

Speaks minimal ACP v1: initialize, session/new, session/prompt (with one
agent_message_chunk update + end_turn), session/cancel handling, and echoes a
session/request_permission call when the prompt text contains "PERMISSION".
"""

from __future__ import annotations

import json
import sys
import threading
import time


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    print("fake-agent boot (stderr)", file=sys.stderr, flush=True)
    sessions: dict[str, dict] = {}
    cancelled: set[str] = set()
    counter = 0

    def emit_permission(session_id: str) -> None:
        req_id = 9000 + counter
        send({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/request_permission",
            "params": {
                "sessionId": session_id,
                "toolCall": {"toolCallId": "call_1", "title": "Probe tool", "kind": "execute"},
                "options": [
                    {"optionId": "allow-once", "name": "Allow once", "kind": "allow_once"},
                    {"optionId": "reject-once", "name": "Reject", "kind": "reject_once"},
                ],
            },
        })

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        rid = msg.get("id")
        params = msg.get("params", {}) if isinstance(msg.get("params"), dict) else {}

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": 1,
                "agentCapabilities": {"loadSession": False},
                "agentInfo": {"name": "fake-agent", "version": "0.0.0"},
                "authMethods": [],
            }})
        elif method == "session/new":
            counter += 1
            sid = f"sess_fake_{counter}"
            sessions[sid] = params
            send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": sid}})
        elif method == "session/prompt":
            sid = params.get("sessionId", "")
            prompt = params.get("prompt", [])
            text = " ".join(
                b.get("text", "") for b in prompt
                if isinstance(b, dict) and b.get("type") == "text"
            )
            if "PERMISSION" in text:
                emit_permission(sid)

            def finish(rid=rid, sid=sid) -> None:
                time.sleep(0.3)
                if sid in cancelled:
                    send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "cancelled"}})
                    return
                send({"jsonrpc": "2.0", "method": "session/update", "params": {
                    "sessionId": sid,
                    "update": {"sessionUpdate": "agent_message_chunk",
                               "content": {"type": "text", "text": "POC-OK"}},
                }})
                send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})

            threading.Thread(target=finish, daemon=True).start()
        elif method == "session/cancel":
            sid = params.get("sessionId", "")
            cancelled.add(sid)
        elif method == "$/cancel_request":
            # Best effort: nothing to correlate without prompt id mapping; record only.
            print(f"fake-agent got $/cancel_request: {params}", file=sys.stderr, flush=True)
        elif "id" in msg:
            send({"jsonrpc": "2.0", "id": rid,
                  "error": {"code": -32601, "message": f"unknown: {method}"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
