import base64
import hashlib
import hmac
import json
import os
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.line_webhook.store import record_webhook_event, cleanup_old_events
from obsidian_ai_hub.web.app import create_app

TEST_SECRET = "test_channel_secret"
TEST_USER_ID = "U1234567890abcdef1234567890abcdef"
TEST_API_TOKEN = "test_bearer_token"


def generate_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", TEST_SECRET)
    monkeypatch.setenv("LINE_ALLOWED_USER_IDS", f" {TEST_USER_ID} ")
    monkeypatch.setenv("OBSIDIAN_AI_HUB_API_TOKEN", TEST_API_TOKEN)
    app = create_app(host="127.0.0.1", port=0, token=TEST_API_TOKEN)
    return TestClient(app)


def test_missing_config_returns_503(monkeypatch):
    monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
    monkeypatch.setenv("LINE_ALLOWED_USER_IDS", TEST_USER_ID)
    monkeypatch.setenv("OBSIDIAN_AI_HUB_API_TOKEN", TEST_API_TOKEN)
    app = create_app(host="127.0.0.1", port=0, token=TEST_API_TOKEN)
    c = TestClient(app)

    res = c.post("/api/v1/line/webhook", json={})
    assert res.status_code == 503

    monkeypatch.setenv("LINE_CHANNEL_SECRET", TEST_SECRET)
    monkeypatch.setenv("LINE_ALLOWED_USER_IDS", "  ,  ")
    res2 = c.post("/api/v1/line/webhook", json={})
    assert res2.status_code == 503


def test_missing_signature_returns_401(client):
    res = client.post("/api/v1/line/webhook", json={"events": []})
    assert res.status_code == 401
    assert res.json()["detail"] == "Missing X-Line-Signature header"


def test_invalid_signature_returns_401(client):
    body = json.dumps({"events": []}).encode("utf-8")
    res = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": "invalid_signature"},
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid X-Line-Signature"


def test_empty_events_returns_200(client):
    body = json.dumps({"events": []}).encode("utf-8")
    sig = generate_signature(TEST_SECRET, body)
    res = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig},
    )
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_valid_text_message_event(client):
    event = {
        "webhookEventId": "evt_text_001",
        "type": "message",
        "source": {"userId": TEST_USER_ID, "type": "user"},
        "message": {"id": "msg_001", "type": "text", "text": "Hello LINE!"},
    }
    body = json.dumps({"events": [event]}, ensure_ascii=False).encode("utf-8")
    sig = generate_signature(TEST_SECRET, body)

    res = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig},
    )
    assert res.status_code == 200

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM line_webhook_events WHERE dedup_key = ?",
        ("event:evt_text_001",),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["webhook_event_id"] == "evt_text_001"
    assert row["event_type"] == "message"
    assert row["status"] == "received"
    assert row["delivery_count"] == 1
    parsed_payload = json.loads(row["payload_json"])
    assert parsed_payload["message"]["text"] == "Hello LINE!"


def test_valid_postback_event(client):
    event = {
        "webhookEventId": "evt_postback_001",
        "type": "postback",
        "source": {"userId": TEST_USER_ID, "type": "user"},
        "postback": {"data": "action=buy&itemid=123"},
    }
    body = json.dumps({"events": [event]}).encode("utf-8")
    sig = generate_signature(TEST_SECRET, body)

    res = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig},
    )
    assert res.status_code == 200

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM line_webhook_events WHERE dedup_key = ?",
        ("event:evt_postback_001",),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["event_type"] == "postback"


def test_unallowed_user_not_saved(client, caplog):
    event = {
        "webhookEventId": "evt_unallowed_001",
        "type": "message",
        "source": {"userId": "U_OTHER_USER", "type": "user"},
        "message": {"id": "msg_002", "type": "text", "text": "Secret info"},
    }
    body = json.dumps({"events": [event]}).encode("utf-8")
    sig = generate_signature(TEST_SECRET, body)

    res = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig},
    )
    assert res.status_code == 200

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM line_webhook_events WHERE dedup_key = 'event:evt_unallowed_001'")
    assert cur.fetchone()[0] == 0

    assert "unauthorized_user" in caplog.text
    assert "U_OTHER_USER" not in caplog.text  # Raw userId must not be logged
    assert "Secret info" not in caplog.text  # Message body must not be logged


def test_unsupported_event_type_not_saved(client):
    event = {
        "webhookEventId": "evt_follow_001",
        "type": "follow",
        "source": {"userId": TEST_USER_ID, "type": "user"},
    }
    body = json.dumps({"events": [event]}).encode("utf-8")
    sig = generate_signature(TEST_SECRET, body)

    res = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig},
    )
    assert res.status_code == 200

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM line_webhook_events WHERE dedup_key = 'event:evt_follow_001'")
    assert cur.fetchone()[0] == 0


def test_malformed_payload_saves_minimal_metadata(client):
    raw_invalid_json = b"{ invalid json string"
    sig = generate_signature(TEST_SECRET, raw_invalid_json)

    res = client.post(
        "/api/v1/line/webhook",
        content=raw_invalid_json,
        headers={"X-Line-Signature": sig},
    )
    assert res.status_code == 200

    body_hash = hashlib.sha256(raw_invalid_json).hexdigest()
    dedup_key = f"body:{body_hash}:0"

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM line_webhook_events WHERE dedup_key = ?", (dedup_key,))
    row = cur.fetchone()
    assert row is not None
    assert row["status"] == "malformed"
    assert row["payload_json"] is None


def test_deduplication_updates_delivery_count(client):
    event = {
        "webhookEventId": "evt_dup_001",
        "type": "message",
        "source": {"userId": TEST_USER_ID, "type": "user"},
        "message": {"id": "msg_003", "type": "text", "text": "Dup test"},
    }
    body = json.dumps({"events": [event]}).encode("utf-8")
    sig = generate_signature(TEST_SECRET, body)

    res1 = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig},
    )
    assert res1.status_code == 200

    res2 = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig},
    )
    assert res2.status_code == 200

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT delivery_count FROM line_webhook_events WHERE dedup_key = 'event:evt_dup_001'")
    assert cur.fetchone()[0] == 2


def test_deduplication_fallback_body_hash_without_webhook_event_id(client):
    event = {
        "type": "message",
        "source": {"userId": TEST_USER_ID, "type": "user"},
        "message": {"id": "msg_no_id", "type": "text", "text": "Fallback dedup test"},
    }
    body = json.dumps({"events": [event]}).encode("utf-8")
    sig = generate_signature(TEST_SECRET, body)

    res1 = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig},
    )
    assert res1.status_code == 200

    body_hash = hashlib.sha256(body).hexdigest()
    dedup_key = f"body:{body_hash}:0"

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT delivery_count FROM line_webhook_events WHERE dedup_key = ?", (dedup_key,))
    assert cur.fetchone()[0] == 1

    res2 = client.post(
        "/api/v1/line/webhook",
        content=body,
        headers={"X-Line-Signature": sig},
    )
    assert res2.status_code == 200

    cur.execute("SELECT delivery_count FROM line_webhook_events WHERE dedup_key = ?", (dedup_key,))
    assert cur.fetchone()[0] == 2


def test_cleanup_old_events():
    conn = get_db_connection()
    now_dt = datetime.now(timezone.utc)
    old_iso = (now_dt - timedelta(days=31)).isoformat()
    recent_iso = (now_dt - timedelta(days=5)).isoformat()

    record_webhook_event(
        dedup_key="key_old",
        webhook_event_id="old_evt",
        event_type="message",
        status="received",
        payload_json="{}",
        received_at=old_iso,
        conn=conn,
    )
    record_webhook_event(
        dedup_key="key_recent",
        webhook_event_id="recent_evt",
        event_type="message",
        status="received",
        payload_json="{}",
        received_at=recent_iso,
        conn=conn,
    )

    deleted = cleanup_old_events(days=30, conn=conn, now_dt=now_dt)
    assert deleted == 1

    cur = conn.cursor()
    cur.execute("SELECT dedup_key FROM line_webhook_events")
    remaining_keys = [r[0] for r in cur.fetchall()]
    assert "key_old" not in remaining_keys
    assert "key_recent" in remaining_keys
