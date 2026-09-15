"""Tests for ACP elicitation/create (form) bridged to coding.ask_user HITL."""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from obsidian_ai_hub.agents.ask_user_handler import handle_coding_ask_user
from obsidian_ai_hub.coding import acp, acp_elicitation as acp_el
from obsidian_ai_hub.coding import store as coding_store
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.dispatcher import HitlContext
from obsidian_ai_hub.hitl.service import (
    cancel_run,
    register_run_and_questions,
    submit_answer,
)

FAKE_AGENT = Path(__file__).resolve().parent.parent / "tools" / "acp_poc" / "fake_agent.py"

FORM_PARAMS = {
    "sessionId": "sess_1",
    "mode": "form",
    "message": "How should I approach this refactoring?",
    "requestedSchema": {
        "type": "object",
        "properties": {
            "strategy": {
                "type": "string",
                "enum": ["conservative", "balanced", "aggressive"],
            },
            "note": {"type": "string"},
        },
        "required": ["strategy"],
    },
}


def _parsed(params=None):
    return acp_el.parse_elicitation_create(params if params is not None else FORM_PARAMS)


# --- capability advertise ---


def test_initialize_advertises_form_only():
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    client = acp.AcpClientBackend(profile)
    seen = {}

    def fake_request(method, params, timeout=60.0):
        seen.update(params)
        return {"protocolVersion": 1, "agentCapabilities": {}}

    conn = MagicMock()
    conn.request.side_effect = fake_request
    meta = client.initialize(conn)
    assert seen["protocolVersion"] == 1
    assert seen["clientCapabilities"] == {"elicitation": {"form": {}}}
    assert "fs" not in seen["clientCapabilities"]
    assert "terminal" not in seen["clientCapabilities"]
    assert meta["protocol_version"] == 1


def test_initialize_rejects_version_mismatch():
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    client = acp.AcpClientBackend(profile)
    conn = MagicMock()
    conn.request.return_value = {"protocolVersion": 2, "agentCapabilities": {}}
    with pytest.raises(acp.AcpCapabilityMismatchError):
        client.initialize(conn)


# --- request parsing ---


def test_parse_form_valid():
    parsed = _parsed()
    assert parsed.message.startswith("How should")
    assert [p.name for p in parsed.properties] == ["strategy", "note"]
    assert parsed.properties[0].enum_values == ["conservative", "balanced", "aggressive"]
    assert parsed.properties[0].required is True
    assert parsed.properties[1].required is False


@pytest.mark.parametrize(
    "params",
    [
        {"mode": "url", "message": "m", "url": "https://example.com/x"},
        {"mode": "other", "message": "m", "requestedSchema": {"type": "object"}},
        {"mode": "form", "message": "m"},  # missing schema
        {"mode": "form", "message": "m", "requestedSchema": {"type": "object", "properties": {}}},
        {
            "mode": "form",
            "message": "m",
            "requestedSchema": {
                "type": "object",
                "properties": {"a": {"type": "object", "properties": {}}},
            },
        },
        {
            "mode": "form",
            "message": "m",
            "requestedSchema": {
                "type": "object",
                "properties": {"a": {"type": "string", "enum": []}},
            },
        },
        {"mode": "form", "message": "   ", "requestedSchema": {"type": "object", "properties": {"a": {"type": "string"}}}},
    ],
)
def test_parse_invalid_rejected(params):
    with pytest.raises(acp_el.AcpElicitationError) as exc_info:
        acp_el.parse_elicitation_create(params)
    assert exc_info.value.code == -32602


# --- question conversion ---


def test_to_questions_enum_and_free_text():
    questions_data, ask_user_args = acp_el.elicitation_to_questions(_parsed())
    by_key = {q["question_key"]: q for q in questions_data}
    assert by_key["strategy"]["question_type"] == "single_choice"
    values = [c["value"] for c in by_key["strategy"]["choices"]]
    assert {"conservative", "balanced", "aggressive"} <= set(values)
    assert "other" in values  # fixed free-input choice appended
    note_values = [c["value"] for c in by_key["note"]["choices"]]
    assert note_values == ["other"]
    assert ask_user_args["elicitation_message"].startswith("How should")


# --- answer conversion ---


def test_answers_to_content_enum_and_passthrough():
    content = acp_el.hitl_answers_to_content(
        _parsed(),
        {
            "strategy": {"selection": "balanced", "text": None},
            "note": {"selection": "other", "text": "careful rollout"},
        },
    )
    assert content == {"strategy": "balanced", "note": "careful rollout"}


def test_answers_to_content_missing_required():
    with pytest.raises(ValueError):
        acp_el.hitl_answers_to_content(_parsed(), {"note": {"selection": "other", "text": "x"}})


def test_answers_to_content_scalar_coercion():
    parsed = acp_el.parse_elicitation_create(
        {
            "mode": "form",
            "message": "m",
            "requestedSchema": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "ratio": {"type": "number"},
                    "flag": {"type": "boolean"},
                },
                "required": ["count", "ratio", "flag"],
            },
        }
    )
    content = acp_el.hitl_answers_to_content(
        parsed,
        {
            "count": {"selection": "other", "text": "3"},
            "ratio": {"selection": "other", "text": "0.5"},
            "flag": {"selection": "other", "text": "true"},
        },
    )
    assert content == {"count": 3, "ratio": 0.5, "flag": True}
    with pytest.raises(ValueError):
        acp_el.hitl_answers_to_content(
            parsed,
            {
                "count": {"selection": "other", "text": "many"},
                "ratio": {"selection": "other", "text": "0.5"},
                "flag": {"selection": "other", "text": "true"},
            },
        )


# --- DB-backed waiter / handler handoff ---


def _seed_coding_run(tmp_path, project_id):
    conn = get_db_connection()
    now = "2026-09-15T00:00:00+09:00"
    conn.execute(
        "INSERT INTO projects (project_id, normalized_name, display_name, domain, status, created_at, updated_at, project_path) "
        "VALUES (?, 'test_proj', 'Test Proj', 'personal', 'active', ?, ?, ?)",
        (project_id, now, now, str(tmp_path)),
    )
    conn.commit()
    conn.close()
    sess = coding_store.create_session(
        project_id=project_id,
        backend="opencode",
        repo_path=str(tmp_path),
        title="Elicit Session",
        transport="acp",
    )
    msg = coding_store.add_message(sess["session_id"], role="user", content="do work")
    run = coding_store.create_run(
        sess["session_id"], msg["message_id"], transport="acp",
    )
    return sess, run


def _seed_elicitation_hitl(run, parsed, request_id="42"):
    from obsidian_ai_hub.coding.ask_user_flow import build_coding_checkpoint

    questions_data, ask_user_args = acp_el.elicitation_to_questions(parsed)
    hitl_run_id = f"hitl_elicit_test_{request_id}_{run['run_id'][-6:]}"
    checkpoint = build_coding_checkpoint(
        session_id=run["session_id"],
        run_id=run["run_id"],
        user_prompt="do work",
        repo_path="/tmp",
        backend_name="opencode",
        ask_call={"id": f"elicitation_{request_id}", "args": ask_user_args},
        questions_data=questions_data,
        phase="initial",
        phase_turn=1,
        cli_count=1,
        tool_ids=["skills"],
        provider="test",
        model="test",
        resume_target=acp_el.RESUME_TARGET_ACP_ELICITATION,
        elicitation={"request_id": request_id, "connection_token": "tok_test"},
    )
    register_run_and_questions(
        run_id=hitl_run_id,
        handler="coding.ask_user",
        checkpoint=json.dumps(checkpoint, ensure_ascii=False),
        question_set_id="qset_1",
        questions_data=questions_data,
        title="ACP エージェントからの確認",
        description=parsed.message,
        display_type="in_conversation_question",
    )
    coding_store.update_run(run["run_id"], status="waiting_user", hitl_run_id=hitl_run_id)
    return hitl_run_id, checkpoint


def _hitl_context(hitl_run_id, checkpoint, raw_answers):
    conn = get_db_connection()
    return HitlContext(
        run_id=hitl_run_id,
        checkpoint=json.dumps(checkpoint, ensure_ascii=False),
        answers_by_question_key={},
        conn=conn,
        raw_answers_by_question_key=raw_answers,
    )


def test_handler_live_waiter_skips_requeue(tmp_path):
    _, run = _seed_coding_run(tmp_path, 991)
    hitl_run_id, checkpoint = _seed_elicitation_hitl(run, _parsed())
    acp_el.create_wait(
        hitl_run_id=hitl_run_id,
        coding_run_id=run["run_id"],
        elicitation_request_id="42",
        connection_token="tok_test",
    )
    ctx = _hitl_context(
        hitl_run_id, checkpoint, {"strategy": {"value": "balanced", "comment": None}}
    )
    result = handle_coding_ask_user(ctx)
    assert result.status == "completed"
    assert coding_store.get_run(run["run_id"])["status"] == "waiting_user"
    assert acp_el.get_wait(hitl_run_id)["status"] == acp_el.WAIT_STATUS_CONSUMED


def test_handler_stale_waiter_falls_back_to_requeue(tmp_path):
    _, run = _seed_coding_run(tmp_path, 992)
    hitl_run_id, checkpoint = _seed_elicitation_hitl(run, _parsed())
    # No wait row: stale (e.g. restart wiped the waiter thread).
    ctx = _hitl_context(
        hitl_run_id, checkpoint, {"strategy": {"value": "balanced", "comment": None}}
    )
    result = handle_coding_ask_user(ctx)
    assert result.status == "completed"
    assert coding_store.get_run(run["run_id"])["status"] == "queued"


def test_handler_token_mismatch_falls_back_to_requeue(tmp_path):
    _, run = _seed_coding_run(tmp_path, 996)
    hitl_run_id, checkpoint = _seed_elicitation_hitl(run, _parsed())
    acp_el.create_wait(
        hitl_run_id=hitl_run_id,
        coding_run_id=run["run_id"],
        elicitation_request_id="42",
        connection_token="tok_other",  # different turn/connection
    )
    ctx = _hitl_context(
        hitl_run_id, checkpoint, {"strategy": {"value": "balanced", "comment": None}}
    )
    result = handle_coding_ask_user(ctx)
    assert result.status == "completed"
    assert coding_store.get_run(run["run_id"])["status"] == "queued"


def test_handler_expired_heartbeat_falls_back_to_requeue(tmp_path):
    from obsidian_ai_hub.database import get_db_connection as _conn

    _, run = _seed_coding_run(tmp_path, 997)
    hitl_run_id, checkpoint = _seed_elicitation_hitl(run, _parsed())
    acp_el.create_wait(
        hitl_run_id=hitl_run_id,
        coding_run_id=run["run_id"],
        elicitation_request_id="42",
        connection_token="tok_test",
    )
    conn = _conn()
    try:
        conn.execute(
            "UPDATE acp_elicitation_waits SET heartbeat_at = ? WHERE hitl_run_id = ?",
            ("2000-01-01T00:00:00+00:00", hitl_run_id),
        )
        conn.commit()
    finally:
        conn.close()
    ctx = _hitl_context(
        hitl_run_id, checkpoint, {"strategy": {"value": "balanced", "comment": None}}
    )
    result = handle_coding_ask_user(ctx)
    assert result.status == "completed"
    assert coding_store.get_run(run["run_id"])["status"] == "queued"
    assert acp_el.get_wait(hitl_run_id)["status"] == acp_el.WAIT_STATUS_STALE


def test_handler_consumed_row_never_requeues(tmp_path):
    _, run = _seed_coding_run(tmp_path, 998)
    hitl_run_id, checkpoint = _seed_elicitation_hitl(run, _parsed())
    acp_el.create_wait(
        hitl_run_id=hitl_run_id,
        coding_run_id=run["run_id"],
        elicitation_request_id="42",
        connection_token="tok_test",
    )
    assert acp_el.consume_wait_if_live(hitl_run_id, "42", "tok_test") is True
    # Second consume loses: exactly-once ownership.
    assert acp_el.consume_wait_if_live(hitl_run_id, "42", "tok_test") is False
    ctx = _hitl_context(
        hitl_run_id, checkpoint, {"strategy": {"value": "balanced", "comment": None}}
    )
    result = handle_coding_ask_user(ctx)
    assert result.status == "completed"
    assert coding_store.get_run(run["run_id"])["status"] == "waiting_user"


def test_waiter_returns_answers(tmp_path):
    _, run = _seed_coding_run(tmp_path, 993)
    parsed = _parsed()
    hitl_run_id, _ = _seed_elicitation_hitl(run, parsed)
    acp_el.create_wait(
        hitl_run_id=hitl_run_id,
        coding_run_id=run["run_id"],
        elicitation_request_id="42",
        connection_token="tok_test",
    )
    submit_answer(hitl_run_id, "qset_1", "strategy", {"value": "balanced"})
    submit_answer(hitl_run_id, "qset_1", "note", {"value": "other", "comment": "go slow"})
    formatted = acp_el.wait_for_hitl_answers(
        hitl_run_id=hitl_run_id,
        active_question_set_id="qset_1",
        parsed=parsed,
        cancel_event=threading.Event(),
        deadline_monotonic=time.monotonic() + 30,
        coding_run_id=run["run_id"],
        poll_interval_s=0.01,
    )
    assert formatted["strategy"] == {"selection": "balanced", "text": None}
    assert formatted["note"] == {"selection": "other", "text": "go slow"}
    content = acp_el.hitl_answers_to_content(parsed, formatted)
    assert content == {"strategy": "balanced", "note": "go slow"}


def test_waiter_cancelled_hitl(tmp_path):
    _, run = _seed_coding_run(tmp_path, 994)
    hitl_run_id, _ = _seed_elicitation_hitl(run, _parsed())
    acp_el.create_wait(
        hitl_run_id=hitl_run_id,
        coding_run_id=run["run_id"],
        elicitation_request_id="42",
        connection_token="tok_test",
    )
    cancel_run(hitl_run_id)
    with pytest.raises(acp_el.AcpElicitationCancelled):
        acp_el.wait_for_hitl_answers(
            hitl_run_id=hitl_run_id,
            active_question_set_id="qset_1",
            parsed=_parsed(),
            cancel_event=threading.Event(),
            deadline_monotonic=time.monotonic() + 30,
            coding_run_id=run["run_id"],
            poll_interval_s=0.01,
        )


def test_waiter_deadline(tmp_path):
    _, run = _seed_coding_run(tmp_path, 995)
    hitl_run_id, _ = _seed_elicitation_hitl(run, _parsed())
    acp_el.create_wait(
        hitl_run_id=hitl_run_id,
        coding_run_id=run["run_id"],
        elicitation_request_id="42",
        connection_token="tok_test",
    )
    with pytest.raises(acp_el.AcpElicitationCancelled):
        acp_el.wait_for_hitl_answers(
            hitl_run_id=hitl_run_id,
            active_question_set_id="qset_1",
            parsed=_parsed(),
            cancel_event=threading.Event(),
            deadline_monotonic=time.monotonic() - 1,
            coding_run_id=run["run_id"],
            poll_interval_s=0.01,
        )
    assert acp_el.get_wait(hitl_run_id)["status"] == acp_el.WAIT_STATUS_STALE


# --- execute_turn protocol dispatch (mocked) ---


def _mocked_turn(client_requests):
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    client = acp.AcpClientBackend(profile)
    reqs = list(client_requests)
    state = {"responded": [], "errors": []}

    class FakeConn:
        def pop_client_requests(self):
            out, reqs[:] = reqs[:], []
            return out

        def pop_notifications(self):
            return []

        def respond(self, rid, result):
            state["responded"].append((rid, result))

        def respond_error(self, rid, code, message):
            state["errors"].append((rid, code, message))

    return client, FakeConn(), state


def test_execute_turn_elicitation_accept_mocked():
    client, conn, state = _mocked_turn(
        [
            {
                "id": 7,
                "method": "elicitation/create",
                "params": FORM_PARAMS,
            }
        ]
    )
    record = client._handle_elicitation_request(
        {
            "id": 7,
            "method": "elicitation/create",
            "params": FORM_PARAMS,
        },
        conn,
        on_elicitation_create=lambda parsed, ctx: {
            "action": "accept",
            "content": {"strategy": "balanced"},
        },
        cancel_event=threading.Event(),
        deadline_monotonic=time.monotonic() + 30,
        connection_token="tok_1",
    )
    assert record["action"] == "accept"
    assert state["responded"] == [
        (7, {"action": "accept", "content": {"strategy": "balanced"}})
    ]


def test_execute_turn_url_mode_rejected():
    client, conn, state = _mocked_turn([])
    record = client._handle_elicitation_request(
        {
            "id": 8,
            "method": "elicitation/create",
            "params": {"mode": "url", "message": "m", "url": "https://example.com"},
        },
        conn,
        on_elicitation_create=lambda parsed, ctx: {"action": "accept"},
        cancel_event=threading.Event(),
        deadline_monotonic=time.monotonic() + 30,
        connection_token="tok_1",
    )
    assert record["action"] == "error"
    assert state["errors"] == [(8, -32602, record["error"])]
    assert state["responded"] == []


def test_execute_turn_accept_requires_content():
    client, conn, state = _mocked_turn([])
    with pytest.raises(acp.AcpError):
        client._handle_elicitation_request(
            {"id": 10, "method": "elicitation/create", "params": FORM_PARAMS},
            conn,
            on_elicitation_create=lambda parsed, ctx: {"action": "accept"},
            cancel_event=threading.Event(),
            deadline_monotonic=time.monotonic() + 30,
            connection_token="tok_1",
        )
    assert state["responded"] == []
    assert state["errors"][0][:2] == (10, -32603)


def test_execute_turn_idless_rejected():
    client, conn, state = _mocked_turn([])
    with pytest.raises(acp.AcpError):
        client._handle_elicitation_request(
            {"method": "elicitation/create", "params": FORM_PARAMS},
            conn,
            on_elicitation_create=lambda parsed, ctx: {"action": "accept", "content": {}},
            cancel_event=threading.Event(),
            deadline_monotonic=time.monotonic() + 30,
            connection_token="tok_1",
        )
    # No orphan HITL state may be created without a replyable request id.
    assert state["responded"] == [] and state["errors"] == []


def test_execute_turn_no_handler_cancels():
    client, conn, state = _mocked_turn([])
    record = client._handle_elicitation_request(
        {"id": 9, "method": "elicitation/create", "params": FORM_PARAMS},
        conn,
        on_elicitation_create=None,
        cancel_event=threading.Event(),
        deadline_monotonic=time.monotonic() + 30,
        connection_token="tok_1",
    )
    assert record["action"] == "cancel"
    assert state["responded"] == [(9, {"action": "cancel"})]


# --- execute_turn against a real subprocess (fake_agent) ---


def _git_init(path):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


def _real_profile():
    return acp.AcpLaunchProfile(
        profile_id="test_fake",
        backend_name="opencode",
        executable=sys.executable,
        argv=[sys.executable, str(FAKE_AGENT)],
    )


def test_execute_turn_elicitation_real_subprocess_accept(tmp_path):
    _git_init(tmp_path)
    client = acp.AcpClientBackend(_real_profile())
    res = client.execute_turn(
        repo_path=str(tmp_path),
        prompt="please ELICITATION now",
        timeout=60.0,
        on_elicitation_create=lambda parsed, ctx: {
            "action": "accept",
            "content": {"strategy": "balanced"},
        },
    )
    assert res.stop_reason == "end_turn"
    assert "ELICIT-OK action=accept" in res.output
    assert '"balanced"' in res.output
    assert res.diagnostics["elicitations"][0]["action"] == "accept"


def test_execute_turn_elicitation_real_subprocess_cancel(tmp_path):
    _git_init(tmp_path)
    client = acp.AcpClientBackend(_real_profile())

    def _cancel(parsed, ctx):
        raise acp_el.AcpElicitationCancelled("user dismissed")

    res = client.execute_turn(
        repo_path=str(tmp_path),
        prompt="please ELICITATION now",
        timeout=60.0,
        on_elicitation_create=_cancel,
    )
    assert res.stop_reason == "end_turn"
    assert "ELICIT-OK action=cancel" in res.output


def _make_handler(run, cancel_event, deadline_s=30):
    import time as _time
    return acp_el.make_elicitation_handler(
        run_id=run["run_id"],
        session_id=run["session_id"],
        user_prompt="do work",
        repo_path="/tmp",
        backend_name="opencode",
        phase="initial",
        phase_turn=1,
        cli_count=1,
        tool_ids=["skills"],
        provider="test",
        model="test",
        prior_hitl_run_id=None,
        cancel_event=cancel_event,
    )


def test_make_handler_registers_hitl_and_accepts(tmp_path):
    import threading, time
    _, run = _seed_coding_run(tmp_path, 981)
    cancel_event = threading.Event()
    handler = _make_handler(run, cancel_event)
    parsed = _parsed()
    wait_ctx = {"request_id": 77, "connection_token": "tok_h",
                "deadline_monotonic": time.monotonic() + 30}
    result_box = {}
    def _run():
        result_box["res"] = handler(parsed, wait_ctx)
    th = threading.Thread(target=_run)
    th.start()
    # Wait for HITL registration, then answer via HITL service.
    deadline = time.monotonic() + 10
    hitl_run_id = None
    while time.monotonic() < deadline:
        r = coding_store.get_run(run["run_id"])
        if r.get("hitl_run_id"):
            hitl_run_id = r["hitl_run_id"]
            break
        time.sleep(0.05)
    assert hitl_run_id is not None
    submit_answer(hitl_run_id, "qset_1", "strategy", {"value": "balanced"})
    submit_answer(hitl_run_id, "qset_1", "note", {"value": "other", "comment": "go slow"})
    th.join(timeout=15)
    assert not th.is_alive()
    assert result_box["res"] == {"action": "accept",
                                 "content": {"strategy": "balanced", "note": "go slow"}}


def test_make_handler_cancel_event_aborts(tmp_path):
    import threading, time
    _, run = _seed_coding_run(tmp_path, 982)
    cancel_event = threading.Event()
    cancel_event.set()
    handler = _make_handler(run, cancel_event)
    with __import__("pytest").raises(acp_el.AcpElicitationCancelled):
        handler(_parsed(), {"request_id": 78, "connection_token": "tok_h",
                            "deadline_monotonic": time.monotonic() + 30})


def test_waiter_coding_run_cancel_aborts(tmp_path):
    import threading, time
    _, run = _seed_coding_run(tmp_path, 983)
    parsed = _parsed()
    hitl_run_id, _ = _seed_elicitation_hitl(run, parsed)
    acp_el.create_wait(hitl_run_id=hitl_run_id, coding_run_id=run["run_id"],
                       elicitation_request_id="42", connection_token="tok_test")
    coding_store.update_run(run["run_id"], status="cancelled")
    with __import__("pytest").raises(acp_el.AcpElicitationCancelled):
        acp_el.wait_for_hitl_answers(
            hitl_run_id=hitl_run_id, active_question_set_id="qset_1", parsed=parsed,
            cancel_event=threading.Event(),
            deadline_monotonic=time.monotonic() + 30,
            coding_run_id=run["run_id"], poll_interval_s=0.01)
