import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from starlette.concurrency import run_in_threadpool

from obsidian_ai_hub.line_webhook.store import record_webhook_event

logger = logging.getLogger(__name__)

router = APIRouter()


def parse_allowed_user_ids(env_val: str | None) -> set[str]:
    if not env_val:
        return set()
    parts = [p.strip() for p in env_val.split(",")]
    return {p for p in parts if p}


@router.post("/line/webhook")
async def line_webhook(request: Request) -> dict[str, str]:
    channel_secret = os.getenv("LINE_CHANNEL_SECRET", "")
    allowed_user_ids_raw = os.getenv("LINE_ALLOWED_USER_IDS", "")
    allowed_user_ids = parse_allowed_user_ids(allowed_user_ids_raw)

    if not channel_secret or not allowed_user_ids:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LINE Webhook configuration is missing or incomplete",
        )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 1_000_000:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="LINE webhook payload too large",
                )
        except ValueError:
            pass

    signature_header = request.headers.get("x-line-signature")
    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Line-Signature header",
        )

    raw_body = await request.body()
    expected_digest = hmac.new(
        channel_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    expected_signature = base64.b64encode(expected_digest).decode("utf-8")

    if not hmac.compare_digest(signature_header, expected_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-Line-Signature",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    body_sha256 = hashlib.sha256(raw_body).hexdigest()

    try:
        data = json.loads(raw_body.decode("utf-8"))
        if not isinstance(data, dict) or "events" not in data or not isinstance(data["events"], list):
            raise ValueError("Invalid JSON payload structure")
    except Exception as e:
        logger.warning("Malformed LINE webhook payload received: %s", e)
        dedup_key = f"body:{body_sha256}:0"
        try:
            await run_in_threadpool(
                record_webhook_event,
                dedup_key=dedup_key,
                webhook_event_id=None,
                event_type=None,
                status="malformed",
                payload_json=None,
                received_at=now_iso,
            )
        except Exception as err:
            logger.error("Failed to record malformed LINE webhook event: %s", err)
        return {"status": "ok"}

    events = data["events"]
    if not events:
        return {"status": "ok"}

    for idx, event in enumerate(events):
        if not isinstance(event, dict):
            continue

        webhook_event_id = event.get("webhookEventId")
        if webhook_event_id and isinstance(webhook_event_id, str):
            dedup_key = f"event:{webhook_event_id}"
        else:
            webhook_event_id = None
            dedup_key = f"body:{body_sha256}:{idx}"

        event_type = event.get("type")
        source = event.get("source")
        user_id = source.get("userId") if isinstance(source, dict) else None

        if not user_id or user_id not in allowed_user_ids:
            user_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest() if user_id else "unknown"
            logger.warning(
                "Rejected LINE webhook event from unallowed user_hash=%s, event_type=%s, reason=unauthorized_user",
                user_hash,
                event_type,
            )
            continue

        # Check if event is message.text or postback
        is_text_message = (
            event_type == "message"
            and isinstance(event.get("message"), dict)
            and event.get("message", {}).get("type") == "text"
        )
        is_postback = event_type == "postback"

        if is_text_message or is_postback:
            payload_json = json.dumps(event, ensure_ascii=False)
            try:
                await run_in_threadpool(
                    record_webhook_event,
                    dedup_key=dedup_key,
                    webhook_event_id=webhook_event_id,
                    event_type=event_type,
                    status="received",
                    payload_json=payload_json,
                    received_at=now_iso,
                )
            except Exception as err:
                logger.error("Failed to record LINE webhook event %s: %s", dedup_key, err)

    return {"status": "ok"}
