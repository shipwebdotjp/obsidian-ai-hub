from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from obsidian_ai_hub.notifications import store
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.web.routes.deps import require_bearer_token

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_bearer_token)],
)


class NotificationSettingsResponse(BaseModel):
    web_push_enabled: bool
    line_enabled: bool
    web_push_action_required: bool
    web_push_failure: bool
    line_action_required: bool
    line_failure: bool
    updated_at: str


class NotificationSettingsUpdateRequest(BaseModel):
    web_push_enabled: Optional[bool] = None
    line_enabled: Optional[bool] = None
    web_push_action_required: Optional[bool] = None
    web_push_failure: Optional[bool] = None
    line_action_required: Optional[bool] = None
    line_failure: Optional[bool] = None


class VapidPublicKeyResponse(BaseModel):
    vapid_public_key: str


class WebPushSubscriptionRegisterRequest(BaseModel):
    endpoint: str = Field(..., min_length=1)
    p256dh: str = Field(..., min_length=1)
    auth: str = Field(..., min_length=1)
    user_agent: Optional[str] = None


class WebPushSubscriptionMetadataResponse(BaseModel):
    subscription_id: str
    endpoint_domain: str
    user_agent: Optional[str] = None
    status: str
    created_at: str
    updated_at: str


class NotificationInboxItemResponse(BaseModel):
    notification_id: str
    event_type: str
    target_id: str
    category: str
    title: str
    body: str
    relative_link: str
    created_at: str
    read_at: Optional[str] = None
    web_push_status: str
    web_push_status_at: Optional[str] = None
    web_push_failure_reason: Optional[str] = None
    web_push_target_count: int
    web_push_success_count: int
    web_push_failure_count: int
    line_status: str
    line_status_at: Optional[str] = None
    line_failure_reason: Optional[str] = None


class NotificationInboxListResponse(BaseModel):
    items: List[NotificationInboxItemResponse]
    total: int
    page: int
    limit: int


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class NotificationMarkAllReadResponse(BaseModel):
    updated_count: int


@router.get("/settings", response_model=NotificationSettingsResponse)
def get_notification_settings():
    return store.get_notification_settings()


@router.put("/settings", response_model=NotificationSettingsResponse)
def update_notification_settings(req: NotificationSettingsUpdateRequest):
    return store.update_notification_settings(
        web_push_enabled=req.web_push_enabled,
        line_enabled=req.line_enabled,
        web_push_action_required=req.web_push_action_required,
        web_push_failure=req.web_push_failure,
        line_action_required=req.line_action_required,
        line_failure=req.line_failure,
    )


@router.get("/vapid-public-key", response_model=VapidPublicKeyResponse)
def get_vapid_public_key():
    return {"vapid_public_key": config.WEB_PUSH_VAPID_PUBLIC_KEY}


@router.get("/subscriptions", response_model=List[WebPushSubscriptionMetadataResponse])
def list_subscriptions():
    return store.list_web_push_subscription_metadata()


@router.post("/subscriptions", response_model=WebPushSubscriptionMetadataResponse)
def register_subscription(req: WebPushSubscriptionRegisterRequest):
    stored = store.upsert_web_push_subscription(
        endpoint=req.endpoint,
        p256dh=req.p256dh,
        auth=req.auth,
        user_agent=req.user_agent,
    )
    meta_list = store.list_web_push_subscription_metadata()
    for m in meta_list:
        if m["subscription_id"] == stored["subscription_id"]:
            return m
    domain = urlparse(req.endpoint).netloc or "push-service"
    return {
        "subscription_id": stored["subscription_id"],
        "endpoint_domain": domain,
        "user_agent": req.user_agent,
        "status": "active",
        "created_at": stored["created_at"],
        "updated_at": stored["updated_at"],
    }


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def unregister_subscription(
    subscription_id: Optional[str] = Query(None),
    endpoint: Optional[str] = Query(None),
):
    if subscription_id:
        store.delete_web_push_subscription(subscription_id)
    elif endpoint:
        store.deactivate_web_push_subscription_by_endpoint(endpoint)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="subscription_id or endpoint is required",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=NotificationInboxListResponse)
def list_inbox_notifications(
    status: str = Query("all", pattern="^(unread|read|all)$"),
    category: str = Query("all", pattern="^(action_required|failure|all)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    return store.list_inbox_notifications(
        status=status,
        category=category,
        page=page,
        limit=limit,
    )


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
def get_unread_notification_count():
    count = store.get_unread_notification_count()
    return {"unread_count": count}


@router.post("/read-all", response_model=NotificationMarkAllReadResponse)
def mark_all_notifications_as_read():
    updated_count = store.mark_all_notifications_as_read()
    return {"updated_count": updated_count}


@router.get("/{notification_id}", response_model=NotificationInboxItemResponse)
def get_inbox_notification(notification_id: str):
    item = store.get_inbox_notification(notification_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return item


@router.post("/{notification_id}/read", response_model=NotificationInboxItemResponse)
def mark_notification_as_read(notification_id: str):
    item = store.mark_notification_as_read(notification_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return item
