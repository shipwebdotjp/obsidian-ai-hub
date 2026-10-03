from __future__ import annotations

import logging

from obsidian_ai_hub.notifications.adapters.line import send_line_push_result
from obsidian_ai_hub.notifications.adapters.web_push import send_web_push_result
from obsidian_ai_hub.notifications.models import NotificationEvent
from obsidian_ai_hub.notifications.store import (
    create_inbox_notification,
    get_notification_settings,
    list_active_web_push_subscriptions,
    mark_notification_delivery_unknown,
    update_notification_channel_delivery,
)

logger = logging.getLogger(__name__)


def publish_notification(event: NotificationEvent) -> bool:
    """Save and attempt a notification once, preserving each channel's outcome.

    The record is committed before delivery.  Each channel is then committed as
    pending, in progress, skipped, accepted, failed, or unknown independently,
    so a failure after one external call cannot make an untried channel look
    intentionally skipped.  Must be called after the caller's transaction
    commits and never raises to that caller.
    """
    if event.category not in ("action_required", "failure"):
        return False

    notification_id: str | None = None
    try:
        notification_id = create_inbox_notification(event)
        settings = get_notification_settings()
        category = event.category

        line_enabled_for_category = settings["line_enabled"] and settings[f"line_{category}"]
        if not settings["line_enabled"]:
            update_notification_channel_delivery(
                notification_id, channel="line", status="skipped", failure_reason="channel_disabled"
            )
            line_accepted = False
        elif not line_enabled_for_category:
            update_notification_channel_delivery(
                notification_id, channel="line", status="skipped", failure_reason="category_disabled"
            )
            line_accepted = False
        else:
            update_notification_channel_delivery(notification_id, channel="line", status="in_progress")
            line_result = send_line_push_result(event)
            line_status, line_reason = {
                "sent": ("accepted", None),
                "not_configured": ("skipped", "configuration_missing"),
                "failed": ("failed", "api_rejected_or_adapter_error"),
            }[line_result]
            update_notification_channel_delivery(
                notification_id, channel="line", status=line_status, failure_reason=line_reason
            )
            line_accepted = line_status == "accepted"

        web_push_enabled_for_category = (
            settings["web_push_enabled"] and settings[f"web_push_{category}"]
        )
        if not settings["web_push_enabled"]:
            update_notification_channel_delivery(
                notification_id, channel="web_push", status="skipped", failure_reason="channel_disabled"
            )
            return line_accepted
        if not web_push_enabled_for_category:
            update_notification_channel_delivery(
                notification_id, channel="web_push", status="skipped", failure_reason="category_disabled"
            )
            return line_accepted

        subscriptions = list_active_web_push_subscriptions()
        if not subscriptions:
            update_notification_channel_delivery(
                notification_id,
                channel="web_push",
                status="skipped",
                failure_reason="no_active_subscriptions",
            )
            return line_accepted

        update_notification_channel_delivery(notification_id, channel="web_push", status="in_progress")
        result = send_web_push_result(event, subscriptions)
        status, reason = {
            "sent": ("accepted", None),
            "partial_success": ("partial_accepted", "some_targets_failed"),
            "failed": ("failed", "api_rejected_or_adapter_error"),
            "disabled": ("skipped", "configuration_missing"),
            "no_subscriptions": ("skipped", "no_active_subscriptions"),
        }[result["status"]]
        update_notification_channel_delivery(
            notification_id,
            channel="web_push",
            status=status,
            failure_reason=reason,
            target_count=result["target_count"],
            success_count=result["success_count"],
            failure_count=result["failure_count"],
        )
        return line_accepted or result["success_count"] > 0
    except Exception as exc:
        if notification_id is not None:
            mark_notification_delivery_unknown(notification_id)
        logger.warning("Notification publish interrupted: %s (%s)", type(exc).__name__, event.event_type)
        return False
