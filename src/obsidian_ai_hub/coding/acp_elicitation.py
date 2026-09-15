"""ACP elicitation/create (form) bridge to the existing coding.ask_user HITL.

Operation-scenario contract (see docs/acp/permission-hitl-contract.md):

| Stage | Input & source of truth | Machine-readable identifiers | Persistence | Next reader | On stop/failure | Irreversible op |
| --- | --- | --- | --- | --- | --- | --- |
| Receive | elicitation/create params | ACP request id + sessionId + connection_token (per turn uuid) | acp_elicitation_waits row (waiting) + HITL run/checkpoint | waiter thread / HITL handler | mode != form -> -32602; invalid schema -> -32602 | none (reply stays on same connection) |
| Register | normalized message + requestedSchema | hitl_run_id, question_key = schema property name, choice value = stable id | hitl_runs/hitl_questions + coding_runs waiting_user | Web UI answerer | unconvertible -> fail turn without creating HITL | none |
| Wait | HITL answers/cancel/expiry | hitl_run_id | wait-row heartbeat | waiter | cancel/expiry/disconnect/restart -> cancel reply; stale heartbeat -> stale row | accept/cancel reply on same connection (lets Agent continue) |
| Respond | formatted answers -> content | elicitation request id | coding run event (elicitation_response) | ACP Agent | validation failure -> cancel reply + failed turn | Agent workspace ops after accept (already-delegated scope) |
| Resume branch | checkpoint.resume_target | hitl_run_id | wait row consumed/stale | HITL handler | live waiter -> no requeue; stale -> fallback requeue | none |

Cross-process note: the HITL answer handler (``handle_coding_ask_user``) may run
in a separate ``--hitl-worker`` process from the ACP turn waiter thread, so
liveness is mediated by the ``acp_elicitation_waits`` row (heartbeat), never by
in-process state. A restart wipes heartbeats, which degrades to the
``<needs_user_input>`` fallback path instead of answering a dead connection.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from obsidian_ai_hub.coding.acp import AcpError
from obsidian_ai_hub.database import get_db_connection

logger = logging.getLogger(__name__)

# ELICITATION_FORM_CAPABILITY is re-exported from coding.acp (single source of
# truth, advertised at initialize). Form only: elicitation/url, fs and terminal
# stay non-advertised (see permission-hitl-contract.md D3).

RESUME_TARGET_ACP_ELICITATION = "acp_elicitation"

WAIT_STATUS_WAITING = "waiting"
WAIT_STATUS_CONSUMED = "consumed"
WAIT_STATUS_STALE = "stale"

WAIT_HEARTBEAT_TIMEOUT_S = 30.0
WAIT_POLL_INTERVAL_S = 0.5

_PRIMITIVE_TYPES = ("string", "number", "integer", "boolean")


class AcpElicitationError(AcpError):
    """Invalid elicitation/create request from the Agent (JSON-RPC error code attached)."""

    def __init__(self, message: str, code: int = -32602):
        super().__init__(message)
        self.code = code


class AcpElicitationDeclined(AcpError):
    """The user explicitly declined the elicitation (respond decline)."""


class AcpElicitationCancelled(AcpError):
    """The elicitation was dismissed without choosing (respond cancel)."""


@dataclass
class ElicitationProperty:
    name: str
    json_type: str
    enum_values: Optional[List[Any]] = None
    title: Optional[str] = None
    description: Optional[str] = None
    required: bool = False


@dataclass
class ParsedElicitation:
    session_id: Optional[str]
    tool_call_id: Optional[str]
    message: str
    properties: List[ElicitationProperty] = field(default_factory=list)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_elicitation_create(params: Any) -> ParsedElicitation:
    """Validate elicitation/create params for form mode.

    Raises AcpElicitationError (code -32602) for unadvertised modes and for
    schemas outside the flat primitive/enum form subset.
    """
    if not isinstance(params, dict):
        raise AcpElicitationError("elicitation/create params must be an object.")
    mode = params.get("mode")
    if mode != "form":
        raise AcpElicitationError(
            f"elicitation mode '{mode}' is not advertised (form only)."
        )
    message = params.get("message")
    if not isinstance(message, str) or not message.strip():
        raise AcpElicitationError("elicitation/create requires a non-empty message.")
    schema = params.get("requestedSchema")
    if not isinstance(schema, dict):
        raise AcpElicitationError("elicitation/create requires a requestedSchema object.")
    if schema.get("type") != "object":
        raise AcpElicitationError("elicitation requestedSchema must be a flat object schema.")
    raw_props = schema.get("properties")
    if not isinstance(raw_props, dict) or not raw_props:
        raise AcpElicitationError("elicitation requestedSchema needs non-empty properties.")
    required = schema.get("required") or []
    if not isinstance(required, list):
        raise AcpElicitationError("elicitation requestedSchema.required must be a list.")
    required_set = {str(r) for r in required}

    properties: List[ElicitationProperty] = []
    seen: set[str] = set()
    for name, prop in raw_props.items():
        prop_name = str(name or "").strip()
        if not prop_name:
            raise AcpElicitationError("elicitation schema property names must be non-empty.")
        if prop_name in seen:
            raise AcpElicitationError(
                f"Duplicate elicitation schema property '{prop_name}'."
            )
        seen.add(prop_name)
        if not isinstance(prop, dict):
            raise AcpElicitationError(
                f"elicitation property '{prop_name}' must be an object."
            )
        json_type = prop.get("type")
        if json_type not in _PRIMITIVE_TYPES:
            raise AcpElicitationError(
                f"elicitation property '{prop_name}' has unsupported type '{json_type}'. "
                "Only flat primitive/enum form schemas are supported."
            )
        enum_values = prop.get("enum")
        if enum_values is not None:
            if not isinstance(enum_values, list) or not enum_values:
                raise AcpElicitationError(
                    f"elicitation property '{prop_name}' enum must be a non-empty list."
                )
            for v in enum_values:
                if isinstance(v, (dict, list)):
                    raise AcpElicitationError(
                        f"elicitation property '{prop_name}' enum must be flat values."
                    )
        properties.append(
            ElicitationProperty(
                name=prop_name,
                json_type=json_type,
                enum_values=list(enum_values) if enum_values is not None else None,
                title=prop.get("title") if isinstance(prop.get("title"), str) else None,
                description=prop.get("description")
                if isinstance(prop.get("description"), str)
                else None,
                required=prop_name in required_set,
            )
        )

    session_id = params.get("sessionId")
    tool_call_id = params.get("toolCallId")
    return ParsedElicitation(
        session_id=str(session_id) if session_id is not None else None,
        tool_call_id=str(tool_call_id) if tool_call_id is not None else None,
        message=message.strip(),
        properties=properties,
    )


def elicitation_to_questions(
    parsed: ParsedElicitation,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Map a parsed form elicitation to ask_user-style questions_data + args.

    Reuses the existing question shape (question_type single_choice with
    normalized choices) so the established Web UI and answer validation apply
    unchanged. Enum properties become choices; free-form properties expose the
    fixed free-input ("other") choice only.
    """
    from obsidian_ai_hub.agents.ask_user import build_questions_data

    ask_items: List[Dict[str, Any]] = []
    for prop in parsed.properties:
        if prop.enum_values is not None:
            raw_choices = [
                {
                    "value": str(v),
                    "label": str(v),
                    "description": None,
                }
                for v in prop.enum_values
            ]
        else:
            raw_choices = []
        question_text = prop.title or prop.description or f"{parsed.message} [{prop.name}]"
        ask_items.append(
            {
                "question_id": prop.name,
                "question": question_text,
                "choices": raw_choices,
            }
        )
    questions_data = build_questions_data(ask_items)
    ask_user_args = {"questions": ask_items, "elicitation_message": parsed.message}
    return questions_data, ask_user_args


def _format_raw_answers(raw_answers: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize raw {question_key: {value, comment} | scalar} answers.

    Mirrors agents.ask_user_handler._format_answers semantics (selection/text
    payloads, "other" carries free text) so both resume paths interpret answers
    identically.
    """
    formatted: Dict[str, Any] = {}
    for q_key, ans in (raw_answers or {}).items():
        if isinstance(ans, dict):
            val = ans.get("value")
            comment = ans.get("comment")
        else:
            val = ans
            comment = None
        if val == "other":
            formatted[q_key] = {"selection": "other", "text": comment or None}
        else:
            formatted[q_key] = {"selection": val, "text": None}
    return formatted


def _coerce_value(prop: ElicitationProperty, raw: Any) -> Any:
    """Coerce a single answer value to the schema property type."""
    if prop.json_type == "string":
        if not isinstance(raw, str):
            raise ValueError(
                f"Elicitation answer for '{prop.name}' must be a string."
            )
        return raw
    if prop.json_type == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in ("true", "1", "yes", "はい"):
                return True
            if lowered in ("false", "0", "no", "いいえ"):
                return False
        raise ValueError(
            f"Elicitation answer for '{prop.name}' must be a boolean."
        )
    if prop.json_type == "integer":
        if isinstance(raw, bool):
            raise ValueError(
                f"Elicitation answer for '{prop.name}' must be an integer."
            )
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            try:
                return int(raw.strip())
            except (TypeError, ValueError):
                pass
        raise ValueError(
            f"Elicitation answer for '{prop.name}' must be an integer."
        )
    if prop.json_type == "number":
        if isinstance(raw, bool):
            raise ValueError(
                f"Elicitation answer for '{prop.name}' must be a number."
            )
        if isinstance(raw, (int, float)):
            return raw
        if isinstance(raw, str):
            try:
                return float(raw.strip())
            except (TypeError, ValueError):
                pass
        raise ValueError(
            f"Elicitation answer for '{prop.name}' must be a number."
        )
    raise ValueError(f"Unsupported elicitation property type '{prop.json_type}'.")


def hitl_answers_to_content(
    parsed: ParsedElicitation, formatted_answers: Dict[str, Any]
) -> Dict[str, Any]:
    """Convert formatted HITL answers to elicitation/create accept content.

    Selection values map back to the original enum member types; "other"
    free-text answers pass through for enum properties (the Agent re-validates
    per spec) and coerce for scalar properties. Missing required answers and
    failed scalar coercions raise ValueError so the turn fails loudly instead
    of sending a schemaless reply.
    """
    content: Dict[str, Any] = {}
    for prop in parsed.properties:
        ans = (formatted_answers or {}).get(prop.name)
        if not isinstance(ans, dict):
            if prop.required:
                raise ValueError(f"Elicitation answer for '{prop.name}' is missing.")
            continue
        selection = ans.get("selection")
        text = ans.get("text")
        if selection == "other":
            if text is None or (isinstance(text, str) and not text.strip()):
                if prop.required:
                    raise ValueError(
                        f"Elicitation answer for '{prop.name}' is missing."
                    )
                continue
            value: Any = text
        elif selection is None:
            if prop.required:
                raise ValueError(f"Elicitation answer for '{prop.name}' is missing.")
            continue
        elif prop.enum_values is not None:
            matched: Any = None
            found = False
            for candidate in prop.enum_values:
                if str(candidate) == str(selection):
                    matched = candidate
                    found = True
                    break
            value = matched if found else selection
        else:
            value = selection
        content[prop.name] = _coerce_value(prop, value)
    missing = [p.name for p in parsed.properties if p.required and p.name not in content]
    if missing:
        raise ValueError(f"Elicitation answers missing for: {', '.join(missing)}.")
    return content


def make_elicitation_handler(
    *,
    run_id: str,
    session_id: str,
    user_prompt: str,
    repo_path: str,
    backend_name: str,
    phase: str,
    phase_turn: int,
    cli_count: int,
    tool_ids: List[str],
    provider: str,
    model: str,
    prior_hitl_run_id: Optional[str],
    cancel_event: Any,
) -> Any:
    """Build the on_elicitation_create callback for an ACP worker turn.

    Shared by the SSE streaming flow (coding/service.py) and the resident
    worker (runs/coding_worker.py): registers the elicitation as a
    coding.ask_user HITL run, waits for the answer on the same connection,
    and returns the accept payload. Raises AcpElicitationCancelled when the
    wait aborts so the caller replies cancel.
    """
    import uuid as _uuid

    def _handle(parsed: ParsedElicitation, wait_ctx: Dict[str, Any]) -> Dict[str, Any]:
        from obsidian_ai_hub.coding import store as coding_store
        from obsidian_ai_hub.coding.ask_user_flow import (
            build_coding_checkpoint,
            load_prior_history_sync,
        )
        from obsidian_ai_hub.hitl.service import register_run_and_questions

        questions_data, ask_user_args = elicitation_to_questions(parsed)
        elicitation_request_id = str(wait_ctx.get("request_id"))
        ask_call = {
            "id": f"elicitation_{elicitation_request_id}",
            "args": ask_user_args,
        }
        prior_history, _ = load_prior_history_sync(prior_hitl_run_id)
        hitl_run_id = f"hitl_elicit_{_uuid.uuid4().hex[:12]}"
        question_set_id = "qset_1"
        checkpoint_data = build_coding_checkpoint(
            session_id=session_id,
            run_id=run_id,
            user_prompt=user_prompt,
            repo_path=repo_path,
            backend_name=backend_name,
            ask_call=ask_call,
            questions_data=questions_data,
            phase=phase,
            phase_turn=phase_turn,
            cli_count=cli_count,
            tool_ids=list(tool_ids),
            provider=provider,
            model=model,
            prior_history=prior_history,
            resume_target=RESUME_TARGET_ACP_ELICITATION,
            elicitation={
                "request_id": elicitation_request_id,
                "session_id": parsed.session_id,
                "tool_call_id": parsed.tool_call_id,
                "connection_token": str(wait_ctx.get("connection_token")),
            },
        )
        register_run_and_questions(
            run_id=hitl_run_id,
            handler="coding.ask_user",
            checkpoint=json.dumps(checkpoint_data, ensure_ascii=False),
            question_set_id=question_set_id,
            questions_data=questions_data,
            title="ACP エージェントからの確認",
            description=parsed.message,
            display_type="in_conversation_question",
        )
        coding_store.update_run(run_id, status="waiting_user", hitl_run_id=hitl_run_id)
        coding_store.append_run_event(
            run_id,
            "user_question",
            {
                "hitl_run_id": hitl_run_id,
                "question_set_id": question_set_id,
                "questions": questions_data,
                "elicitation": True,
            },
        )
        create_wait(
            hitl_run_id=hitl_run_id,
            coding_run_id=run_id,
            elicitation_request_id=elicitation_request_id,
            connection_token=str(wait_ctx.get("connection_token")),
        )
        try:
            formatted = wait_for_hitl_answers(
                hitl_run_id=hitl_run_id,
                active_question_set_id=question_set_id,
                parsed=parsed,
                cancel_event=cancel_event,
                deadline_monotonic=float(wait_ctx.get("deadline_monotonic")),
                coding_run_id=run_id,
            )
            # Answer validation failures raise ValueError here and fail the
            # turn loudly instead of sending a schemaless reply. The run is
            # marked failed so it cannot strand in waiting_user.
            try:
                content = hitl_answers_to_content(parsed, formatted)
            except Exception as exc:
                mark_wait_if_waiting(hitl_run_id, WAIT_STATUS_STALE)
                cur = coding_store.get_run(run_id)
                if cur is not None and str(cur.get("status")) == "waiting_user":
                    coding_store.update_run(
                        run_id,
                        status="failed",
                        error_message=f"elicitation validation failed: {exc}",
                    )
                raise
        except Exception:
            # Leave no live waiter behind on teardown paths; the consumed row
            # is kept so the handler skips requeue.
            mark_wait_if_waiting(hitl_run_id, WAIT_STATUS_STALE)
            cur = coding_store.get_run(run_id)
            if cur is not None and str(cur.get("status")) == "waiting_user":
                coding_store.update_run(run_id, status="running")
            raise
        cur = coding_store.get_run(run_id)
        if cur is not None and str(cur.get("status")) == "waiting_user":
            coding_store.update_run(run_id, status="running")
        coding_store.append_run_event(
            run_id,
            "elicitation_response",
            {
                "hitl_run_id": hitl_run_id,
                "action": "accept",
                "properties": [p.name for p in parsed.properties],
            },
        )
        return {"action": "accept", "content": content}

    return _handle


# --- Wait-row persistence (cross-process waiter liveness) ---


def create_wait(
    *,
    hitl_run_id: str,
    coding_run_id: str,
    elicitation_request_id: str,
    connection_token: str,
) -> None:
    now = _utc_now_iso()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO acp_elicitation_waits "
            "(hitl_run_id, coding_run_id, elicitation_request_id, connection_token, "
            "status, heartbeat_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'waiting', ?, ?, ?)",
            (
                hitl_run_id,
                coding_run_id,
                elicitation_request_id,
                connection_token,
                now,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def touch_wait(hitl_run_id: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE acp_elicitation_waits SET heartbeat_at = ?, updated_at = ? "
            "WHERE hitl_run_id = ? AND status = 'waiting'",
            (_utc_now_iso(), _utc_now_iso(), hitl_run_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_wait(hitl_run_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM acp_elicitation_waits WHERE hitl_run_id = ?",
            (hitl_run_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def consume_wait_if_live(
    hitl_run_id: str,
    elicitation_request_id: str,
    connection_token: Optional[str] = None,
    max_age_s: float = WAIT_HEARTBEAT_TIMEOUT_S,
) -> bool:
    """Atomically consume a live wait row (single statement, rowcount-checked).

    Consumes only when the row is still waiting, the request id (and, when
    given, the connection token) matches, and the heartbeat is fresh. Returns
    True only when this caller won ownership, closing the waiter/handler race:
    exactly one side delivers or falls back, never both, never neither.
    Heartbeats are UTC ISO strings written by _utc_now_iso, so lexicographic
    comparison against the cutoff is chronological.
    """
    cutoff = (
        datetime.now(timezone.utc).timestamp() - max_age_s
    )
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    sql = (
        "UPDATE acp_elicitation_waits SET status = ?, updated_at = ? "
        "WHERE hitl_run_id = ? AND elicitation_request_id = ? "
        "AND status = 'waiting' AND heartbeat_at >= ?"
    )
    params: List[Any] = [WAIT_STATUS_CONSUMED, _utc_now_iso(), hitl_run_id, str(elicitation_request_id), cutoff_iso]
    if connection_token is not None:
        sql += " AND connection_token = ?"
        params.append(str(connection_token))
    conn = get_db_connection()
    try:
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def mark_wait_if_waiting(hitl_run_id: str, status: str) -> None:
    """Mark the wait row only when it is still waiting (teardown safety)."""
    if status not in (WAIT_STATUS_CONSUMED, WAIT_STATUS_STALE):
        raise ValueError(f"Invalid elicitation wait status: '{status}'.")
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE acp_elicitation_waits SET status = ?, updated_at = ? "
            "WHERE hitl_run_id = ? AND status = 'waiting'",
            (status, _utc_now_iso(), hitl_run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _heartbeat_age_s(row: Dict[str, Any]) -> float:
    try:
        beat = datetime.fromisoformat(str(row.get("heartbeat_at") or ""))
        if beat.tzinfo is None:
            beat = beat.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - beat).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def is_wait_live(
    hitl_run_id: str,
    elicitation_request_id: str,
    connection_token: Optional[str] = None,
    max_age_s: float = WAIT_HEARTBEAT_TIMEOUT_S,
) -> bool:
    """True when a live waiter owns this elicitation.

    Requires: row still waiting, same elicitation request id, same connection
    token (when given), and a fresh heartbeat. Read-only check; ownership
    transfer must use consume_wait_if_live.
    """
    row = get_wait(hitl_run_id)
    if row is None:
        return False
    if row.get("status") != WAIT_STATUS_WAITING:
        return False
    if str(row.get("elicitation_request_id") or "") != str(elicitation_request_id):
        return False
    if connection_token is not None and str(row.get("connection_token") or "") != str(
        connection_token
    ):
        return False
    return _heartbeat_age_s(row) <= max_age_s


def wait_for_hitl_answers(
    *,
    hitl_run_id: str,
    active_question_set_id: str,
    parsed: ParsedElicitation,
    cancel_event: Any,
    deadline_monotonic: float,
    coding_run_id: str,
    poll_interval_s: float = WAIT_POLL_INTERVAL_S,
) -> Dict[str, Any]:
    """Block until the HITL run is answered, cancelled, or the wait aborts.

    Returns formatted answers ({question_key: {selection, text}}). Raises
    AcpElicitationCancelled on user cancel, coding-run cancel, expiry-driven
    HITL cancel, or deadline expiry. Raises AcpError on inconsistent DB state
    so the turn fails loudly instead of replying with made-up content.
    """
    from obsidian_ai_hub.coding import store as coding_store
    from obsidian_ai_hub.hitl import store as hitl_store

    while True:
        touch_wait(hitl_run_id)

        if cancel_event is not None and cancel_event.is_set():
            mark_wait_if_waiting(hitl_run_id, WAIT_STATUS_STALE)
            raise AcpElicitationCancelled("Coding run cancelled while waiting.")

        coding_run = coding_store.get_run(coding_run_id)
        if coding_run is None:
            mark_wait_if_waiting(hitl_run_id, WAIT_STATUS_STALE)
            raise AcpElicitationCancelled("Coding run disappeared while waiting.")
        if str(coding_run.get("status")) in ("cancelling", "cancelled", "failed", "interrupted"):
            mark_wait_if_waiting(hitl_run_id, WAIT_STATUS_STALE)
            raise AcpElicitationCancelled(
                f"Coding run is {coding_run.get('status')} while waiting."
            )

        hitl_run = hitl_store.get_run(hitl_run_id)
        if hitl_run is None:
            mark_wait_if_waiting(hitl_run_id, WAIT_STATUS_STALE)
            raise AcpError(f"HITL run {hitl_run_id} disappeared while waiting.")
        hitl_status = str(hitl_run.get("status") or "")
        if hitl_status in ("cancelled", "failed"):
            mark_wait_if_waiting(hitl_run_id, WAIT_STATUS_STALE)
            raise AcpElicitationCancelled(f"HITL run is {hitl_status}.")

        if hitl_status in ("ready_to_resume", "completed"):
            questions = hitl_store.get_questions_by_set(hitl_run_id, active_question_set_id)
            raw: Dict[str, Any] = {}
            for q in questions:
                answer = q.get("answer")
                if answer is None:
                    continue
                raw[str(q.get("question_key"))] = answer
            formatted = _format_raw_answers(raw)
            missing = [
                p.name
                for p in parsed.properties
                if p.required and p.name not in formatted
            ]
            if missing:
                raise AcpError(
                    f"HITL run {hitl_run_id} is {hitl_status} but answers "
                    f"are missing for: {', '.join(missing)}."
                )
            # Conditional consume: a concurrent handler may already own the
            # row; answers come from the questions table either way.
            mark_wait_if_waiting(hitl_run_id, WAIT_STATUS_CONSUMED)
            return formatted

        if time.monotonic() >= deadline_monotonic:
            mark_wait_if_waiting(hitl_run_id, WAIT_STATUS_STALE)
            raise AcpElicitationCancelled("Timed out waiting for elicitation answers.")

        time.sleep(poll_interval_s)
