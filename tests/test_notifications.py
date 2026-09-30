from __future__ import annotations

import sqlite3
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.notifications.models import NotificationEvent, sanitize_notification_body
from obsidian_ai_hub.notifications.store import (
    get_notification_settings,
    update_notification_settings,
    upsert_web_push_subscription,
    deactivate_web_push_subscription_by_endpoint,
    delete_web_push_subscription,
    list_active_web_push_subscriptions,
    list_web_push_subscription_metadata,
)
from obsidian_ai_hub.notifications.publisher import publish_notification


def test_migration_v72(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA user_version;")
    version = cursor.fetchone()[0]
    assert version >= 72

    # Check notification_settings table and initial row
    cursor.execute("SELECT * FROM notification_settings WHERE id = 1;")
    settings = cursor.fetchone()
    assert settings is not None
    assert settings["web_push_enabled"] == 0
    assert settings["line_enabled"] == 0
    assert settings["web_push_action_required"] == 0
    assert settings["web_push_failure"] == 0
    assert settings["line_action_required"] == 0
    assert settings["line_failure"] == 0

    conn.close()


def test_sanitize_notification_body():
    assert sanitize_notification_body(None) == ""
    assert sanitize_notification_body("  hello\nworld  ") == "hello world"
    long_text = "a" * 100
    sanitized = sanitize_notification_body(long_text, max_length=80)
    assert len(sanitized) == 80
    assert sanitized.endswith("…")


def test_notification_settings_crud(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    # Get default settings
    settings = get_notification_settings()
    assert settings["web_push_enabled"] is False
    assert settings["line_enabled"] is False

    # Update settings
    updated = update_notification_settings(
        web_push_enabled=True,
        web_push_action_required=True,
        line_enabled=True,
        line_failure=True,
    )
    assert updated["web_push_enabled"] is True
    assert updated["web_push_action_required"] is True
    assert updated["web_push_failure"] is False
    assert updated["line_enabled"] is True
    assert updated["line_failure"] is True
    assert updated["line_action_required"] is False

    fetched = get_notification_settings()
    assert fetched == updated


def test_web_push_subscriptions_crud(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    sub = upsert_web_push_subscription(
        endpoint="https://fcm.googleapis.com/fcm/send/test_sub_123",
        p256dh="test_p256dh_key",
        auth="test_auth_key",
        user_agent="TestAgent/1.0",
    )
    assert sub["subscription_id"].startswith("wps_")
    assert sub["status"] == "active"

    # List active
    active_subs = list_active_web_push_subscriptions()
    assert len(active_subs) == 1
    assert active_subs[0]["p256dh"] == "test_p256dh_key"
    assert active_subs[0]["auth"] == "test_auth_key"

    # List metadata (masked)
    meta_subs = list_web_push_subscription_metadata()
    assert len(meta_subs) == 1
    assert meta_subs[0]["endpoint_domain"] == "fcm.googleapis.com"
    assert "p256dh" not in meta_subs[0]
    assert "auth" not in meta_subs[0]

    # Deactivate by endpoint
    ok = deactivate_web_push_subscription_by_endpoint(
        "https://fcm.googleapis.com/fcm/send/test_sub_123"
    )
    assert ok is True
    assert len(list_active_web_push_subscriptions()) == 0

    # Delete subscription
    deleted = delete_web_push_subscription(sub["subscription_id"])
    assert deleted is True


def test_publisher_disabled_settings(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    event = NotificationEvent(
        event_type="task",
        target_id="task_123",
        relative_link="/task-agent/task_123",
        category="action_required",
        title="【要対応】タスクの承認が必要です",
        body="テストタスク",
    )

    # All settings off by default
    sent = publish_notification(event)
    assert sent is False


def test_notification_api_endpoints(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    from fastapi.testclient import TestClient
    from obsidian_ai_hub.web.app import create_app

    app = create_app(host="127.0.0.1", port=0, token="test_token")
    client = TestClient(app, headers={"Authorization": "Bearer test_token"})

    # 1. GET /api/v1/notifications/settings
    res = client.get("/api/v1/notifications/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["web_push_enabled"] is False

    # 2. PUT /api/v1/notifications/settings
    res = client.put(
        "/api/v1/notifications/settings",
        json={"web_push_enabled": True, "web_push_action_required": True},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["web_push_enabled"] is True
    assert data["web_push_action_required"] is True

    # 3. GET /api/v1/notifications/vapid-public-key
    res = client.get("/api/v1/notifications/vapid-public-key")
    assert res.status_code == 200
    assert "vapid_public_key" in res.json()

    # 4. POST /api/v1/notifications/subscriptions
    res = client.post(
        "/api/v1/notifications/subscriptions",
        json={
            "endpoint": "https://push.example.com/send/sub1",
            "p256dh": "key_p256dh",
            "auth": "key_auth",
            "user_agent": "Mozilla/5.0",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["endpoint_domain"] == "push.example.com"
    assert "p256dh" not in data
    assert "auth" not in data

    # 5. GET /api/v1/notifications/subscriptions
    res = client.get("/api/v1/notifications/subscriptions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["endpoint_domain"] == "push.example.com"

    # 6. DELETE /api/v1/notifications/subscriptions
    sub_id = data[0]["subscription_id"]
    res = client.delete(f"/api/v1/notifications/subscriptions?subscription_id={sub_id}")
    assert res.status_code == 204

    res = client.get("/api/v1/notifications/subscriptions")
    assert res.status_code == 200
    assert len(res.json()) == 0


def test_notification_api_requires_bearer_token(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    from fastapi.testclient import TestClient
    from obsidian_ai_hub.web.app import create_app

    app = create_app(host="0.0.0.0", port=0, token="secret-token")
    client = TestClient(app)

    res = client.get("/api/v1/notifications/settings")
    assert res.status_code == 401

    res = client.get(
        "/api/v1/notifications/settings",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert res.status_code == 200
