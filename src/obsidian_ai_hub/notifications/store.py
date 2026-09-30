from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from obsidian_ai_hub.database import get_db_connection


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
