from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from pywebpush import WebPushException, webpush

from obsidian_ai_hub.notifications.models import NotificationEvent
from obsidian_ai_hub.notifications.store import (
    deactivate_web_push_subscription_by_endpoint,
)
from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


def send_web_push_result(
    event: NotificationEvent,
    subscriptions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Send Web Push delivery to subscriptions and return detailed outcome structure.

    Returns dict with keys: status, target_count, success_count, failure_count.
    Handles 404/410 by deactivating subscriptions.
    Never raises exceptions, and logs warnings without sensitive info.
    """
    vapid_private_key = config.WEB_PUSH_VAPID_PRIVATE_KEY
    vapid_public_key = config.WEB_PUSH_VAPID_PUBLIC_KEY
    vapid_claims = {"sub": config.WEB_PUSH_VAPID_SUBJECT or "mailto:admin@example.com"}

    if not vapid_private_key or not vapid_public_key:
        logger.warning("Web Push skipped: VAPID public/private key is not configured")
        return {
            "status": "disabled",
            "target_count": 0,
            "success_count": 0,
            "failure_count": 0,
        }

    target_count = len(subscriptions)
    if target_count == 0:
        return {
            "status": "no_subscriptions",
            "target_count": 0,
            "success_count": 0,
            "failure_count": 0,
        }

    payload = json.dumps(
        {
            "title": event.title,
            "body": event.body,
            "relative_link": event.relative_link,
            "event_type": event.event_type,
            "category": event.category,
        },
        ensure_ascii=False,
    )

    success_count = 0
    failure_count = 0
    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"],
            },
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims,
                ttl=86400,
                timeout=10,
            )
            success_count += 1
        except WebPushException as exc:
            failure_count += 1
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None) if response is not None else None
            if status_code in (404, 410):
                deactivate_web_push_subscription_by_endpoint(sub["endpoint"])
                logger.info(
                    "Web Push endpoint returned %s; marked subscription as inactive",
                    status_code,
                )
            else:
                logger.warning("Web Push delivery failed: status_code=%s", status_code)
        except Exception as exc:
            failure_count += 1
            logger.warning("Web Push delivery failed: %s", type(exc).__name__)

    if success_count == target_count:
        status = "sent"
    elif success_count > 0:
        status = "partial_success"
    else:
        status = "failed"

    return {
        "status": status,
        "target_count": target_count,
        "success_count": success_count,
        "failure_count": failure_count,
    }


def send_web_push_best_effort(
    event: NotificationEvent,
    subscriptions: List[Dict[str, Any]],
) -> bool:
    """Best-effort Web Push delivery to active subscriptions (backwards-compatible wrapper)."""
    res = send_web_push_result(event, subscriptions)
    return res["success_count"] > 0
