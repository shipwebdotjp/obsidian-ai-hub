"""Canned stdio ACP agent for harness self-tests (no network, no LLM).

Speaks minimal ACP v1: initialize, session/new, session/prompt (with one
agent_message_chunk update + end_turn), session/cancel handling, echoes a
session/request_permission call when the prompt text contains "PERMISSION",
and emits an elicitation/create (form) call when the prompt text contains
"ELICITATION", embedding the client's reply action/content in its output.
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

    pending_elicit: dict[int, dict] = {}
    elicit_counter = 0

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

    def emit_elicitation(session_id: str) -> "threading.Event":
        nonlocal elicit_counter
        elicit_counter += 1
        req_id = 9100 + elicit_counter
        done = threading.Event()
        pending_elicit[req_id] = {"event": done}
        send({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "elicitation/create",
            "params": {
                "sessionId": session_id,
                "mode": "form",
                "message": "How should I approach this refactoring?",
                "requestedSchema": {
                    "type": "object",
                    "properties": {
                        "strategy": {
                            "type": "string",
                            "enum": ["conservative", "balanced", "aggressive"],
                        },
                    },
                    "required": ["strategy"],
                },
            },
        })
        return done

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Replies to our own elicitation/create calls: record, never answer.
        if "id" in msg and ("result" in msg or "error" in msg):
            entry = pending_elicit.get(msg["id"])
            if entry is not None:
                entry["result"] = msg.get("result")
                entry["error"] = msg.get("error")
                entry["event"].set()
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
        elif method == "session/set_model":
            # Emulate a compliant agent: accept the model pin (real OpenCode
            # returns {} on success).
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "session/prompt":
            sid = params.get("sessionId", "")
            prompt = params.get("prompt", [])
            if isinstance(prompt, str):
                text = prompt
            else:
                text = " ".join(
                    b.get("text", "") for b in prompt
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            if "PERMISSION" in text:
                emit_permission(sid)
            elicit_done = emit_elicitation(sid) if "ELICITATION" in text else None

            def finish(rid=rid, sid=sid, elicit_done=elicit_done) -> None:
                elicit_note = ""
                if elicit_done is not None:
                    if elicit_done.wait(timeout=20.0):
                        entry = next(
                            (e for e in pending_elicit.values() if e["event"] is elicit_done),
                            {},
                        )
                        if entry.get("error") is not None:
                            elicit_note = f" ELICIT-ERR {json.dumps(entry['error'], ensure_ascii=False)}"
                        else:
                            res = entry.get("result") or {}
                            elicit_note = (
                                " ELICIT-OK action=" + str(res.get("action"))
                                + " content=" + json.dumps(res.get("content"), ensure_ascii=False)
                            )
                    else:
                        elicit_note = " ELICIT-MISSING"
                    time.sleep(0.1)
                else:
                    time.sleep(0.3)
                if sid in cancelled:
                    send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "cancelled"}})
                    return
                send({"jsonrpc": "2.0", "method": "session/update", "params": {
                    "sessionId": sid,
                    "update": {"sessionUpdate": "agent_message_chunk",
                               "content": {"type": "text", "text": "POC-OK" + elicit_note}},
                }})
                # Let the client drain the update before the turn result lands.
                time.sleep(0.3)
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
