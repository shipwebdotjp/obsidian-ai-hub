from __future__ import annotations

import hashlib
import json
from typing import Any

from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from obsidian_ai_hub.gmail.auth import GmailAuthError, load_credentials
from obsidian_ai_hub.gmail.mime import (
    build_rfc2822_raw_message,
    derive_reply_recipients,
    derive_reply_subject,
    derive_reply_threading_headers,
    extract_headers_dict,
    parse_mime_payload,
    validate_email_address_no_injection,
    validate_header_no_injection,
)
from obsidian_ai_hub.gmail.store import (
    delete_draft_request,
    mark_draft_request_created,
    mark_draft_request_creating,
    mark_draft_request_unknown,
)


class GmailService:
    def __init__(self, service: Resource | None = None) -> None:
        self._service = service

    def _get_service(self) -> Resource:
        if self._service is not None:
            return self._service
        creds = load_credentials()
        return build("gmail", "v1", credentials=creds)

    def search_messages(
        self,
        query: str = "",
        label_ids: list[str] | None = None,
        page_token: str | None = None,
        include_spam_trash: bool = False,
        max_results: int = 10,
    ) -> dict[str, Any]:
        max_results = max(1, min(20, max_results))
        srv = self._get_service()

        kwargs: dict[str, Any] = {
            "userId": "me",
            "maxResults": max_results,
            "includeSpamTrash": include_spam_trash,
        }
        if query:
            kwargs["q"] = query
        if label_ids:
            kwargs["labelIds"] = label_ids
        if page_token:
            kwargs["pageToken"] = page_token

        res = srv.users().messages().list(**kwargs).execute()
        raw_messages = res.get("messages", [])
        result_size_estimate = res.get("resultSizeEstimate", len(raw_messages))
        next_page_token = res.get("nextPageToken")

        messages_summary: list[dict[str, Any]] = []
        for raw_msg in raw_messages:
            msg_id = raw_msg["id"]
            # Get metadata headers for listing
            msg_data = (
                srv.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_id,
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
            )
            headers_list = msg_data.get("payload", {}).get("headers", [])
            headers_map = extract_headers_dict(headers_list)

            messages_summary.append({
                "message_id": msg_id,
                "thread_id": msg_data.get("threadId", ""),
                "from": headers_map.get("from", ""),
                "to": headers_map.get("to", ""),
                "subject": headers_map.get("subject", ""),
                "date": headers_map.get("date", ""),
                "snippet": msg_data.get("snippet", ""),
                "label_ids": msg_data.get("labelIds", []),
            })

        return {
            "messages": messages_summary,
            "next_page_token": next_page_token,
            "result_size_estimate": result_size_estimate,
        }

    def read_message(self, message_id: str) -> dict[str, Any]:
        srv = self._get_service()
        msg_data = srv.users().messages().get(userId="me", id=message_id, format="full").execute()

        payload = msg_data.get("payload", {})
        headers_list = payload.get("headers", [])
        headers_map = extract_headers_dict(headers_list)

        normalized_headers = {
            "from": headers_map.get("from", ""),
            "to": headers_map.get("to", ""),
            "cc": headers_map.get("cc", ""),
            "bcc": headers_map.get("bcc", ""),
            "subject": headers_map.get("subject", ""),
            "date": headers_map.get("date", ""),
            "message_id": headers_map.get("message-id", ""),
            "in_reply_to": headers_map.get("in-reply-to", ""),
            "references": headers_map.get("references", ""),
        }

        body_text, truncated, attachments = parse_mime_payload(payload, body_cap=20000)

        return {
            "message_id": msg_data.get("id", message_id),
            "thread_id": msg_data.get("threadId", ""),
            "label_ids": msg_data.get("labelIds", []),
            "snippet": msg_data.get("snippet", ""),
            "headers": normalized_headers,
            "body_text": body_text,
            "truncated": truncated,
            "attachments": attachments,
        }

    def get_authenticated_user_email(self) -> str:
        srv = self._get_service()
        profile = srv.users().getProfile(userId="me").execute()
        return profile.get("emailAddress", "")

    def create_draft(
        self,
        mode: str,
        body_text: str,
        request_key: str,
        to: str | None = None,
        cc: str | None = None,
        bcc: str | None = None,
        subject: str | None = None,
        reply_to_message_id: str | None = None,
        reply_all: bool = False,
    ) -> dict[str, Any]:
        # Validate input & mode
        if mode not in ("new", "reply"):
            raise ValueError("mode must be 'new' or 'reply'")

        canonical_input = {
            "mode": mode,
            "to": to or "",
            "cc": cc or "",
            "bcc": bcc or "",
            "subject": subject or "",
            "reply_to_message_id": reply_to_message_id or "",
            "reply_all": reply_all,
            "body_text": body_text,
        }
        input_json = json.dumps(canonical_input, sort_keys=True)
        input_sha256 = hashlib.sha256(input_json.encode("utf-8")).hexdigest()

        # Idempotency check before doing any API call
        existing = mark_draft_request_creating(request_key, input_sha256)
        if existing and existing.get("status") == "created":
            return {
                "request_key": request_key,
                "gmail_draft_id": existing["gmail_draft_id"],
                "gmail_message_id": existing["gmail_message_id"],
                "gmail_thread_id": existing["gmail_thread_id"],
                "status": "created",
                "reused_receipt": True,
                "receipt_persisted": True,
            }

        thread_id: str | None = None
        in_reply_to: str | None = None
        references: str | None = None

        # Pre-dispatch setup & validation
        try:
            srv = self._get_service()
            if mode == "new":
                if not to or not to.strip():
                    raise ValueError("'to' email address is required for mode='new'")
                if subject is None:
                    subject = ""
                final_to = to.strip()
                final_cc = cc.strip() if cc else None
                final_bcc = bcc.strip() if bcc else None
                final_subject = subject.strip()
            else:  # mode == "reply"
                if not reply_to_message_id or not reply_to_message_id.strip():
                    raise ValueError("'reply_to_message_id' is required for mode='reply'")

                # Fetch source message to derive recipients and subject/thread
                source_msg = srv.users().messages().get(
                    userId="me", id=reply_to_message_id, format="full"
                ).execute()
                thread_id = source_msg.get("threadId")
                source_payload = source_msg.get("payload", {})
                source_headers_list = source_payload.get("headers", [])
                source_headers_map = extract_headers_dict(source_headers_list)

                auth_user_email = self.get_authenticated_user_email()
                derived_to, derived_cc = derive_reply_recipients(
                    source_headers_map, auth_user_email, reply_all=reply_all
                )

                if not derived_to:
                    raise ValueError("Could not derive valid 'to' recipient from source message.")

                final_to = derived_to
                final_cc = derived_cc if derived_cc else (cc.strip() if cc else None)
                final_bcc = bcc.strip() if bcc else None

                derived_subject = derive_reply_subject(source_headers_map.get("subject", ""))
                final_subject = subject.strip() if (subject and subject.strip()) else derived_subject

                in_reply_to, references = derive_reply_threading_headers(source_headers_map)

            # Build raw base64url email message
            raw_message = build_rfc2822_raw_message(
                to=final_to,
                subject=final_subject,
                body_text=body_text,
                cc=final_cc,
                bcc=final_bcc,
                in_reply_to=in_reply_to,
                references=references,
            )

            draft_body: dict[str, Any] = {
                "message": {
                    "raw": raw_message,
                }
            }
            if thread_id:
                draft_body["message"]["threadId"] = thread_id
        except Exception as pre_exc:
            delete_draft_request(request_key)
            raise pre_exc

        # Dispatch API call where outcome could become uncertain on transport/server failure
        try:
            res = srv.users().drafts().create(userId="me", body=draft_body).execute()
        except Exception as dispatch_exc:
            mark_draft_request_unknown(request_key)
            raise dispatch_exc

        draft_id = res.get("id", "")
        msg_res = res.get("message", {})
        created_msg_id = msg_res.get("id", "")
        created_thread_id = msg_res.get("threadId", thread_id or "")

        receipt_persisted = True
        try:
            mark_draft_request_created(
                request_key=request_key,
                gmail_draft_id=draft_id,
                gmail_message_id=created_msg_id,
                gmail_thread_id=created_thread_id,
            )
        except Exception as store_exc:
            import logging
            logging.getLogger(__name__).exception("Failed to mark draft request created in DB for %s", request_key)
            receipt_persisted = False

        return {
            "request_key": request_key,
            "gmail_draft_id": draft_id,
            "gmail_message_id": created_msg_id,
            "gmail_thread_id": created_thread_id,
            "status": "created",
            "reused_receipt": False,
            "receipt_persisted": receipt_persisted,
        }
