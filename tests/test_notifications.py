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

    # Check inbox item persisted even when settings are disabled
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM notification_inbox;")
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 1
    item = dict(rows[0])
    assert item["title"] == "【要対応】タスクの承認が必要です"
    assert item["read_at"] is None
    assert item["line_status"] == "skipped"
    assert item["line_failure_reason"] == "channel_disabled"
    assert item["line_status_at"] is not None
    assert item["web_push_status"] == "skipped"
    assert item["web_push_failure_reason"] == "channel_disabled"
    assert item["web_push_status_at"] is not None


def test_inbox_persistence_and_publisher_results(tmp_path, monkeypatch):
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    # Enable line and web push settings for action_required
    update_notification_settings(
        web_push_enabled=True,
        web_push_action_required=True,
        line_enabled=True,
        line_action_required=True,
    )

    # Configure VAPID keys so Web Push isn't skipped due to VAPID missing
    monkeypatch.setattr("obsidian_ai_hub.utils.config.WEB_PUSH_VAPID_PUBLIC_KEY", "test_pub_key")
    monkeypatch.setattr("obsidian_ai_hub.utils.config.WEB_PUSH_VAPID_PRIVATE_KEY", "test_priv_key")

    # Add 2 subscriptions for Web Push testing
    upsert_web_push_subscription(
        endpoint="https://push.example.com/sub1",
        p256dh="p256dh_1",
        auth="auth_1",
    )
    upsert_web_push_subscription(
        endpoint="https://push.example.com/sub2",
        p256dh="p256dh_2",
        auth="auth_2",
    )

    # Mock line_messaging.send_line_push to return True
    monkeypatch.setattr("obsidian_ai_hub.utils.line_messaging.send_line_push", lambda token, target, text: True)
    monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_MESSAGING_TOKEN", "fake_token")
    monkeypatch.setattr("obsidian_ai_hub.utils.config.LINE_TARGET_ID", "fake_target")
    monkeypatch.setattr("obsidian_ai_hub.utils.config.OBSIDIAN_AI_HUB_WEB_URL", "http://localhost:3000")

    # Mock webpush in send_web_push_result: sub1 succeeds, sub2 fails
    def mock_webpush(subscription_info, **kwargs):
        if subscription_info["endpoint"] == "https://push.example.com/sub2":
            from pywebpush import WebPushException
            raise WebPushException("Push failed")

    monkeypatch.setattr("obsidian_ai_hub.notifications.adapters.web_push.webpush", mock_webpush)

    event = NotificationEvent(
        event_type="hitl",
        target_id="hitl_run_999",
        relative_link="/hitl",
        category="action_required",
        title="【要確認】確認事項があります",
        body="HITLの確認依頼",
    )

    sent = publish_notification(event)
    assert sent is True  # LINE succeeded and Web Push partially succeeded

    # Verify inbox contents
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM notification_inbox WHERE target_id = 'hitl_run_999';")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    item = dict(row)
    assert item["line_status"] == "accepted"
    assert item["line_status_at"] is not None
    assert item["line_failure_reason"] is None
    assert item["web_push_status"] == "partial_accepted"
    assert item["web_push_status_at"] is not None
    assert item["web_push_failure_reason"] == "some_targets_failed"
    assert item["web_push_target_count"] == 2
    assert item["web_push_success_count"] == 1
    assert item["web_push_failure_count"] == 1


def test_publisher_interruption_is_recorded_as_unknown(tmp_path, monkeypatch):
    """An exception after LINE starts cannot make either channel look skipped."""
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))
    update_notification_settings(line_enabled=True, line_action_required=True)
    monkeypatch.setattr(
        "obsidian_ai_hub.notifications.publisher.send_line_push_result",
        lambda _event: (_ for _ in ()).throw(RuntimeError("transport stopped")),
    )

    sent = publish_notification(
        NotificationEvent(
            event_type="hitl",
            target_id="hitl_interrupted",
            relative_link="/hitl",
            category="action_required",
            title="interrupted",
            body="",
        )
    )

    assert sent is False
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT line_status, line_status_at, line_failure_reason, "
            "web_push_status, web_push_status_at, web_push_failure_reason "
            "FROM notification_inbox WHERE target_id = 'hitl_interrupted'"
        ).fetchone()
    finally:
        conn.close()
    assert row["line_status"] == "unknown"
    assert row["line_failure_reason"] == "publisher_interrupted"
    assert row["line_status_at"] is not None
    assert row["web_push_status"] == "unknown"
    assert row["web_push_failure_reason"] == "publisher_interrupted"
    assert row["web_push_status_at"] is not None


def test_isolated_backend_scenario_contract(tmp_path, monkeypatch):
    """Contract: Event saved -> delivery attempted -> result recorded -> verified via Web API."""
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    from fastapi.testclient import TestClient
    from obsidian_ai_hub.web.app import create_app

    app = create_app(host="127.0.0.1", port=0, token="test_token")
    client = TestClient(app, headers={"Authorization": "Bearer test_token"})

    # 1. Initially no notifications
    res = client.get("/api/v1/notifications")
    assert res.status_code == 200
    assert res.json()["total"] == 0

    res = client.get("/api/v1/notifications/unread-count")
    assert res.status_code == 200
    assert res.json()["unread_count"] == 0

    # 2. Publish an action_required event
    event1 = NotificationEvent(
        event_type="workflow",
        target_id="wf_run_001",
        relative_link="/workflows/runs/wf_run_001",
        category="action_required",
        title="【要対応】ワークフロー実行入力待ち",
        body="ワークフロー入力待ちです",
    )
    publish_notification(event1)

    # 3. Publish a failure event
    event2 = NotificationEvent(
        event_type="task",
        target_id="task_002",
        relative_link="/task-agent/task_002",
        category="failure",
        title="【失敗】タスク実行エラー",
        body="タスクが失敗しました",
    )
    publish_notification(event2)

    # 4. Check unread count
    res = client.get("/api/v1/notifications/unread-count")
    assert res.json()["unread_count"] == 2

    # 5. Check list with filtering and pagination
    res = client.get("/api/v1/notifications?status=unread")
    assert res.json()["total"] == 2
    items = res.json()["items"]
    assert items[0]["title"] == "【失敗】タスク実行エラー"
    assert items[1]["title"] == "【要対応】ワークフロー実行入力待ち"

    # Category filter
    res = client.get("/api/v1/notifications?category=failure")
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["target_id"] == "task_002"

    # 6. Detail retrieval and mark read
    ntf_id = items[0]["notification_id"]
    res = client.get(f"/api/v1/notifications/{ntf_id}")
    assert res.status_code == 200
    assert res.json()["read_at"] is None

    res = client.post(f"/api/v1/notifications/{ntf_id}/read")
    assert res.status_code == 200
    assert res.json()["read_at"] is not None

    # Unread count decreased
    res = client.get("/api/v1/notifications/unread-count")
    assert res.json()["unread_count"] == 1

    # Filter status=unread now returns 1 item
    res = client.get("/api/v1/notifications?status=unread")
    assert res.json()["total"] == 1


def test_mark_all_notifications_read_contract(tmp_path, monkeypatch):
    """Contract: read-all marks only unread rows, preserves read timestamps, is idempotent."""
    test_db = tmp_path / "test_memory.sqlite3"
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(test_db))

    from fastapi.testclient import TestClient
    from obsidian_ai_hub.web.app import create_app
    from obsidian_ai_hub.notifications.store import (
        create_inbox_notification,
        get_inbox_notification,
    )

    app = create_app(host="127.0.0.1", port=0, token="test_token")
    client = TestClient(app, headers={"Authorization": "Bearer test_token"})

    def make_notification(title: str, target_id: str) -> str:
        return create_inbox_notification(
            NotificationEvent(
                event_type="workflow",
                target_id=target_id,
                relative_link=f"/workflows/runs/{target_id}",
                category="action_required",
                title=title,
                body="body",
            )
        )

    first_id = make_notification("first", "run_1")
    second_id = make_notification("second", "run_2")

    # Mark the first as read individually so its timestamp must survive read-all.
    res = client.post(f"/api/v1/notifications/{first_id}/read")
    assert res.status_code == 200
    original_read_at = res.json()["read_at"]
    assert original_read_at is not None

    # read-all updates only the remaining unread notification.
    res = client.post("/api/v1/notifications/read-all")
    assert res.status_code == 200
    assert res.json()["updated_count"] == 1

    assert get_inbox_notification(first_id)["read_at"] == original_read_at
    assert get_inbox_notification(second_id)["read_at"] is not None

    res = client.get("/api/v1/notifications/unread-count")
    assert res.json()["unread_count"] == 0

    # Re-running is a successful no-op.
    res = client.post("/api/v1/notifications/read-all")
    assert res.status_code == 200
    assert res.json()["updated_count"] == 0


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
