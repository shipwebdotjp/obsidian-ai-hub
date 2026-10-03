from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.notifications.models import NotificationEvent


_CHANNEL_STATUSES = {
    "line": {"pending", "in_progress", "skipped", "accepted", "failed", "unknown"},
    "web_push": {"pending", "in_progress", "skipped", "accepted", "partial_accepted", "failed", "unknown"},
}
_SAFE_DELIVERY_REASONS = {
    "channel_disabled",
    "category_disabled",
    "configuration_missing",
    "no_active_subscriptions",
    "api_rejected_or_adapter_error",
    "some_targets_failed",
    "publisher_interrupted",
}


def get_notification_settings() -> Dict[str, Any]:
    """Retrieve the single-owner notification settings row from DB."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notification_settings WHERE id = 1;")
        row = cursor.fetchone()
        if not row:
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT INTO notification_settings (
                    id, web_push_enabled, line_enabled,
                    web_push_action_required, web_push_failure,
                    line_action_required, line_failure, updated_at
                ) VALUES (1, 0, 0, 0, 0, 0, 0, ?)
                """,
                (now,),
            )
            conn.commit()
            cursor.execute("SELECT * FROM notification_settings WHERE id = 1;")
            row = cursor.fetchone()

        return {
            "web_push_enabled": bool(row["web_push_enabled"]),
            "line_enabled": bool(row["line_enabled"]),
            "web_push_action_required": bool(row["web_push_action_required"]),
            "web_push_failure": bool(row["web_push_failure"]),
            "line_action_required": bool(row["line_action_required"]),
            "line_failure": bool(row["line_failure"]),
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def update_notification_settings(
    *,
    web_push_enabled: Optional[bool] = None,
    line_enabled: Optional[bool] = None,
    web_push_action_required: Optional[bool] = None,
    web_push_failure: Optional[bool] = None,
    line_action_required: Optional[bool] = None,
    line_failure: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update notification settings in DB and return the updated settings."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM notification_settings WHERE id = 1;")
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    """
                    INSERT INTO notification_settings (
                        id, web_push_enabled, line_enabled,
                        web_push_action_required, web_push_failure,
                        line_action_required, line_failure, updated_at
                    ) VALUES (1, 0, 0, 0, 0, 0, 0, ?);
                    """,
                    (now,),
                )
                cursor.execute("SELECT * FROM notification_settings WHERE id = 1;")
                row = cursor.fetchone()

            new_wp_enabled = web_push_enabled if web_push_enabled is not None else bool(row["web_push_enabled"])
            new_line_enabled = line_enabled if line_enabled is not None else bool(row["line_enabled"])
            new_wp_ar = web_push_action_required if web_push_action_required is not None else bool(row["web_push_action_required"])
            new_wp_f = web_push_failure if web_push_failure is not None else bool(row["web_push_failure"])
            new_line_ar = line_action_required if line_action_required is not None else bool(row["line_action_required"])
            new_line_f = line_failure if line_failure is not None else bool(row["line_failure"])

            cursor.execute(
                """
                UPDATE notification_settings
                SET web_push_enabled = ?,
                    line_enabled = ?,
                    web_push_action_required = ?,
                    web_push_failure = ?,
                    line_action_required = ?,
                    line_failure = ?,
                    updated_at = ?
                WHERE id = 1;
                """,
                (
                    int(new_wp_enabled),
                    int(new_line_enabled),
                    int(new_wp_ar),
                    int(new_wp_f),
                    int(new_line_ar),
                    int(new_line_f),
                    now,
                ),
            )
            return {
                "web_push_enabled": new_wp_enabled,
                "line_enabled": new_line_enabled,
                "web_push_action_required": new_wp_ar,
                "web_push_failure": new_wp_f,
                "line_action_required": new_line_ar,
                "line_failure": new_line_f,
                "updated_at": now,
            }
    finally:
        conn.close()


def upsert_web_push_subscription(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert a browser push subscription by endpoint."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        new_sub_id = f"wps_{uuid.uuid4().hex[:12]}"
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO web_push_subscriptions (
                subscription_id, endpoint, p256dh, auth, user_agent, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                p256dh = excluded.p256dh,
                auth = excluded.auth,
                user_agent = excluded.user_agent,
                status = 'active',
                updated_at = excluded.updated_at;
            """,
            (new_sub_id, endpoint, p256dh, auth, user_agent, now, now),
        )
        conn.commit()

        cursor.execute(
            "SELECT subscription_id, user_agent, status, created_at, updated_at FROM web_push_subscriptions WHERE endpoint = ?;",
            (endpoint,),
        )
        row = cursor.fetchone()
        return {
            "subscription_id": row["subscription_id"],
            "user_agent": row["user_agent"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def deactivate_web_push_subscription_by_endpoint(endpoint: str) -> bool:
    """Deactivate a subscription by endpoint (e.g. after 410/404 response)."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE web_push_subscriptions
            SET status = 'inactive', updated_at = ?
            WHERE endpoint = ? AND status = 'active';
            """,
            (now, endpoint),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_web_push_subscription(subscription_id: str) -> bool:
    """Unregister/delete a subscription by subscription_id."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM web_push_subscriptions WHERE subscription_id = ?;",
            (subscription_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_active_web_push_subscriptions() -> List[Dict[str, Any]]:
    """List active subscriptions with secret keys/endpoints for sending Web Push."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT subscription_id, endpoint, p256dh, auth, user_agent, created_at, updated_at
            FROM web_push_subscriptions
            WHERE status = 'active';
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def list_web_push_subscription_metadata() -> List[Dict[str, Any]]:
    """List active subscriptions metadata for user API response (omitting secrets/endpoints)."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT subscription_id, endpoint, user_agent, status, created_at, updated_at
            FROM web_push_subscriptions
            WHERE status = 'active'
            ORDER BY created_at DESC;
            """
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            parsed = urlparse(row["endpoint"])
            domain = parsed.netloc or "push-service"
            result.append(
                {
                    "subscription_id": row["subscription_id"],
                    "endpoint_domain": domain,
                    "user_agent": row["user_agent"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return result
    finally:
        conn.close()


def create_inbox_notification(event: NotificationEvent) -> str:
    """Create an inbox event with neither external channel attempted yet."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        notification_id = f"ntf_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO notification_inbox (
                notification_id, event_type, target_id, category, title, body,
                relative_link, created_at, read_at, web_push_status, web_push_status_at,
                web_push_target_count, web_push_success_count, web_push_failure_count,
                line_status, line_status_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'pending', ?, 0, 0, 0, 'pending', ?);
            """,
            (
                notification_id, event.event_type, event.target_id, event.category,
                event.title, event.body, event.relative_link, now, now, now,
            ),
        )
        conn.commit()
        return notification_id
    finally:
        conn.close()


def update_notification_channel_delivery(
    notification_id: str,
    *,
    channel: str,
    status: str,
    failure_reason: Optional[str] = None,
    target_count: Optional[int] = None,
    success_count: Optional[int] = None,
    failure_count: Optional[int] = None,
) -> None:
    """Persist one channel transition before moving to the next side effect.

    ``failure_reason`` is an operator-safe reason code, never an exception
    message or a remote response body.
    """
    if channel not in _CHANNEL_STATUSES:
        raise ValueError(f"Unsupported notification channel: {channel}")
    if status not in _CHANNEL_STATUSES[channel]:
        raise ValueError(f"Unsupported {channel} delivery status: {status}")
    if failure_reason is not None and failure_reason not in _SAFE_DELIVERY_REASONS:
        raise ValueError("Unsupported notification delivery failure reason")

    now = datetime.now(timezone.utc).isoformat()
    fields = [f"{channel}_status = ?", f"{channel}_status_at = ?", f"{channel}_failure_reason = ?"]
    params: List[Any] = [status, now, failure_reason]
    if channel == "web_push":
        for column, value in (
            ("web_push_target_count", target_count),
            ("web_push_success_count", success_count),
            ("web_push_failure_count", failure_count),
        ):
            if value is not None:
                fields.append(f"{column} = ?")
                params.append(value)

    conn = get_db_connection()
    try:
        conn.execute(
            f"UPDATE notification_inbox SET {', '.join(fields)} WHERE notification_id = ?;",
            [*params, notification_id],
        )
        conn.commit()
    finally:
        conn.close()


def mark_notification_delivery_unknown(notification_id: str) -> None:
    """Mark channels left unresolved when the publisher exits unexpectedly."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        for channel in ("line", "web_push"):
            conn.execute(
                f"""
                UPDATE notification_inbox
                SET {channel}_status = 'unknown', {channel}_status_at = ?,
                    {channel}_failure_reason = 'publisher_interrupted'
                WHERE notification_id = ? AND {channel}_status IN ('pending', 'in_progress');
                """,
                (now, notification_id),
            )
        conn.commit()
    finally:
        conn.close()


def list_inbox_notifications(
    *,
    status: str = "all",
    category: str = "all",
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """Retrieve paginated list of inbox notifications with optional status/category filter."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        where_clauses = []
        params: List[Any] = []

        if status == "unread":
            where_clauses.append("read_at IS NULL")
        elif status == "read":
            where_clauses.append("read_at IS NOT NULL")

        if category in ("action_required", "failure"):
            where_clauses.append("category = ?")
            params.append(category)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        count_sql = f"SELECT COUNT(*) FROM notification_inbox {where_sql};"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        offset = max(0, (page - 1) * limit)
        data_sql = f"""
            SELECT notification_id, event_type, target_id, category, title, body,
                   relative_link, created_at, read_at, web_push_status, web_push_status_at,
                   web_push_failure_reason, web_push_target_count, web_push_success_count,
                   web_push_failure_count, line_status, line_status_at, line_failure_reason
            FROM notification_inbox
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?;
        """
        cursor.execute(data_sql, params + [limit, offset])
        rows = [dict(row) for row in cursor.fetchall()]

        return {
            "items": rows,
            "total": total,
            "page": page,
            "limit": limit,
        }
    finally:
        conn.close()


def get_inbox_notification(notification_id: str) -> Optional[Dict[str, Any]]:
    """Get single notification details from inbox."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT notification_id, event_type, target_id, category, title, body,
                   relative_link, created_at, read_at, web_push_status, web_push_status_at,
                   web_push_failure_reason, web_push_target_count, web_push_success_count,
                   web_push_failure_count, line_status, line_status_at, line_failure_reason
            FROM notification_inbox
            WHERE notification_id = ?;
            """,
            (notification_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_unread_notification_count() -> int:
    """Get total count of unread notifications."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM notification_inbox WHERE read_at IS NULL;")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def mark_notification_as_read(notification_id: str) -> Optional[Dict[str, Any]]:
    """Mark notification as read and return updated notification dict."""
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE notification_inbox
            SET read_at = ?
            WHERE notification_id = ? AND read_at IS NULL;
            """,
            (now, notification_id),
        )
        conn.commit()
        return get_inbox_notification(notification_id)
    finally:
        conn.close()
