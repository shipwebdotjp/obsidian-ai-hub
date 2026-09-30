from __future__ import annotations

import logging

from obsidian_ai_hub.notifications.adapters.line import send_line_push_best_effort
from obsidian_ai_hub.notifications.adapters.web_push import send_web_push_best_effort
from obsidian_ai_hub.notifications.models import NotificationEvent
from obsidian_ai_hub.notifications.store import (
    get_notification_settings,
    list_active_web_push_subscriptions,
)

logger = logging.getLogger(__name__)


def publish_notification(event: NotificationEvent) -> bool:
    """Best-effort notification publisher.

    Checks notification_settings and dispatches to active Web Push / LINE adapters.
    Must be called AFTER database transaction commit.
    Never raises exceptions.
    """
    try:
        settings = get_notification_settings()
        web_push_sent = False
        line_sent = False

        if event.category == "action_required":
            should_web_push = (
                settings["web_push_enabled"] and settings["web_push_action_required"]
            )
            should_line = settings["line_enabled"] and settings["line_action_required"]
        elif event.category == "failure":
            should_web_push = (
                settings["web_push_enabled"] and settings["web_push_failure"]
            )
            should_line = settings["line_enabled"] and settings["line_failure"]
        else:
            return False

        if should_web_push:
            subs = list_active_web_push_subscriptions()
            if subs:
                web_push_sent = send_web_push_best_effort(event, subs)

        if should_line:
            line_sent = send_line_push_best_effort(event)

        return web_push_sent or line_sent
    except Exception as exc:
        logger.warning(
            "Notification publish failed: %s (%s)",
            type(exc).__name__,
            event.event_type,
        )
        return False
