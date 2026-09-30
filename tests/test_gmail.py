from __future__ import annotations

import json
import pytest

from obsidian_ai_hub.gmail.auth import GmailAuthError
from obsidian_ai_hub.gmail.client import GmailService
from obsidian_ai_hub.gmail.mime import (
    build_rfc2822_raw_message,
    derive_reply_recipients,
    derive_reply_subject,
    derive_reply_threading_headers,
    html_to_plain_text,
    parse_mime_payload,
    validate_email_address_no_injection,
    validate_header_no_injection,
)
from obsidian_ai_hub.gmail.store import (
    get_draft_request,
    mark_draft_request_created,
    mark_draft_request_creating,
    mark_draft_request_unknown,
)


def test_html_to_plain_text():
    html_content = """
    <html>
      <head><title>Test Title</title></head>
      <body>
        <style>p { color: red; }</style>
        <h1>Hello World</h1>
        <p>This is a <b>test</b> email.</p>
        <script>console.log("ignore");</script>
        <div>
          <span>Line 1</span><br/>Line 2
        </div>
      </body>
    </html>
    """
    text = html_to_plain_text(html_content)
    assert "Test Title" not in text
    assert "color: red" not in text
    assert "console.log" not in text
    assert "Hello World" in text
    assert "This is a test email." in text
    assert "Line 1" in text
    assert "Line 2" in text


def test_validate_header_no_injection():
    validate_header_no_injection("Subject", "Normal Subject")
    with pytest.raises(ValueError, match="Header injection detected"):
        validate_header_no_injection("Subject", "Bad\r\nSubject")
    with pytest.raises(ValueError, match="Header injection detected"):
        validate_header_no_injection("To", "user@example.com\nBcc: evil@example.com")


def test_parse_mime_payload_plain_text_and_truncation():
    # Build base64url encoded plain text
    import base64
    text_data = "Line 1\nLine 2\n" + ("A" * 25000)
    b64_data = base64.urlsafe_b64encode(text_data.encode("utf-8")).decode("ascii")

    payload = {
        "mimeType": "multipart/mixed",
        "body": {},
        "parts": [
            {
                "mimeType": "text/plain",
                "body": {"data": b64_data},
            },
            {
                "mimeType": "application/pdf",
                "filename": "report.pdf",
                "body": {"attachmentId": "att123", "size": 1024},
            },
        ],
    }

    body, truncated, attachments = parse_mime_payload(payload, body_cap=20000)
    assert truncated is True
    assert len(body) == 20000
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "report.pdf"
    assert attachments[0]["attachment_id"] == "att123"


def test_derive_reply_recipients():
    headers_map = {
        "from": "Alice Sender <alice@example.com>",
        "to": "Bob User <bob@example.com>",
        "cc": "Charlie CC <charlie@example.com>",
        "reply-to": "Alice Alt <alice.alt@example.com>",
    }

    # Reply to self/single
    to_str, cc_str = derive_reply_recipients(headers_map, authenticated_user_email="bob@example.com", reply_all=False)
    assert to_str == "alice.alt@example.com"
    assert cc_str == ""

    # Reply all
    to_str, cc_str = derive_reply_recipients(headers_map, authenticated_user_email="bob@example.com", reply_all=True)
    assert to_str == "alice.alt@example.com"
    assert "alice@example.com" in cc_str or "charlie@example.com" in cc_str
    assert "bob@example.com" not in to_str and "bob@example.com" not in cc_str


def test_derive_reply_subject():
    assert derive_reply_subject("Hello World") == "Re: Hello World"
    assert derive_reply_subject("Re: Hello World") == "Re: Hello World"
    assert derive_reply_subject("RE: Hello World") == "RE: Hello World"
    assert derive_reply_subject("") == "Re:"


def test_derive_reply_threading_headers():
    headers_map = {
        "message-id": "<msg123@example.com>",
        "references": "<msg100@example.com>",
    }
    in_reply_to, refs = derive_reply_threading_headers(headers_map)
    assert in_reply_to == "<msg123@example.com>"
    assert refs == "<msg100@example.com> <msg123@example.com>"

    with pytest.raises(ValueError, match="Source message does not contain a Message-ID"):
        derive_reply_threading_headers({})


def test_build_rfc2822_raw_message():
    raw_b64 = build_rfc2822_raw_message(
        to="to@example.com",
        subject="Test Subject",
        body_text="Hello body",
        cc="cc@example.com",
        in_reply_to="<parent@example.com>",
        references="<ref@example.com>",
    )
    assert isinstance(raw_b64, str)
    import base64
    decoded = base64.urlsafe_b64decode(raw_b64 + "==").decode("utf-8")
    assert "To: to@example.com" in decoded
    assert "Cc: cc@example.com" in decoded
    assert "Subject: Test Subject" in decoded
    assert "In-Reply-To: <parent@example.com>" in decoded
    assert "References: <ref@example.com>" in decoded
    assert "Hello body" in decoded


def test_draft_request_store_idempotency():
    req_key = "test_req_key_123"
    input_hash = "hash123456"

    # 1. First mark creating
    res = mark_draft_request_creating(req_key, input_hash)
    assert res is None
    record = get_draft_request(req_key)
    assert record["status"] == "creating"

    # 2. Duplicate while creating throws RuntimeError
    with pytest.raises(RuntimeError, match="Automatic retry blocked"):
        mark_draft_request_creating(req_key, input_hash)

    # 3. Mark created
    mark_draft_request_created(req_key, "draft_1", "msg_1", "thread_1")
    record = get_draft_request(req_key)
    assert record["status"] == "created"
    assert record["gmail_draft_id"] == "draft_1"

    # 4. Repeated call when created returns existing record
    res = mark_draft_request_creating(req_key, input_hash)
    assert res is not None
    assert res["status"] == "created"
    assert res["gmail_draft_id"] == "draft_1"

    # 5. Unknown status
    req_key_2 = "test_req_key_456"
    mark_draft_request_creating(req_key_2, input_hash)
    mark_draft_request_unknown(req_key_2)
    record = get_draft_request(req_key_2)
    assert record["status"] == "unknown"

    with pytest.raises(RuntimeError, match="Automatic retry blocked"):
        mark_draft_request_creating(req_key_2, input_hash)


def test_gmail_create_draft_no_trusted_ctx():
    from obsidian_ai_hub.agents.registry import _make_gmail_create_draft_tool

    tool = _make_gmail_create_draft_tool(None)
    res_str = tool.invoke({"mode": "new", "to": "test@example.com", "body_text": "hello"})
    res = json.loads(res_str)
    assert "error" in res
    assert "信頼された実行コンテキスト" in res["error"]


def test_fake_gmail_service_create_draft(monkeypatch):
    class FakeGmailResource:
        def __init__(self):
            self.created_drafts = []

        def users(self):
            return self

        def messages(self):
            return self

        def drafts(self):
            return self

        def getProfile(self, userId):
            return self

        def get(self, userId, id, format):
            return self

        def execute(self):
            return {
                "emailAddress": "me@example.com",
                "threadId": "thread_source_123",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Sender <sender@example.com>"},
                        {"name": "Subject", "value": "Source Subject"},
                        {"name": "Message-ID", "value": "<source_msg_id@example.com>"},
                    ]
                },
            }

        def create(self, userId, body):
            self.created_drafts.append(body)
            return self

        def execute_create(self):
            return {
                "id": "draft_fake_789",
                "message": {
                    "id": "msg_fake_789",
                    "threadId": "thread_source_123",
                },
            }

    fake_res = FakeGmailResource()

    # Monkeypatch build in client.py
    class MockService(GmailService):
        def _get_service(self):
            return fake_res

        def get_authenticated_user_email(self):
            return "me@example.com"

    service = MockService()

    # Direct override srv.users().drafts().create().execute()
    def fake_drafts_create(*args, **kwargs):
        body = kwargs.get("body") or (args[1] if len(args) > 1 else {})
        fake_res.created_drafts.append(body)
        class Exec:
            def execute(self):
                return {
                    "id": "draft_fake_789",
                    "message": {
                        "id": "msg_fake_789",
                        "threadId": body.get("message", {}).get("threadId", "thread_new_123"),
                    },
                }
        return Exec()

    def fake_messages_get(*args, **kwargs):
        class ExecGet:
            def execute(self):
                return {
                    "threadId": "thread_source_123",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Sender <sender@example.com>"},
                            {"name": "Subject", "value": "Source Subject"},
                            {"name": "Message-ID", "value": "<source_msg_id@example.com>"},
                        ]
                    },
                }
        return ExecGet()

    fake_res.drafts = lambda: type("Drafts", (), {"create": fake_drafts_create})()
    fake_res.messages = lambda: type("Messages", (), {"get": fake_messages_get})()

    req_key = "req_fake_reply_1"
    res = service.create_draft(
        mode="reply",
        body_text="Thanks for your email!",
        request_key=req_key,
        reply_to_message_id="msg_source_123",
    )

    assert res["status"] == "created"
    assert res["gmail_draft_id"] == "draft_fake_789"
    assert res["reused_receipt"] is False
    assert len(fake_res.created_drafts) == 1

    # Second call with same request key reuses receipt without creating new draft
    res2 = service.create_draft(
        mode="reply",
        body_text="Thanks for your email!",
        request_key=req_key,
        reply_to_message_id="msg_source_123",
    )
    assert res2["reused_receipt"] is True
    assert len(fake_res.created_drafts) == 1
