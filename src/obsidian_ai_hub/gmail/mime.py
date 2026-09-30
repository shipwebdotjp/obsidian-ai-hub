from __future__ import annotations

import base64
import html
import re
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from typing import Any


class HTMLToTextParser(HTMLParser):
    """Simple standard-library HTML parser that extracts text while skipping non-content tags."""

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._ignore_stack: list[str] = []
        self._ignore_tags = {"script", "style", "head", "title"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._ignore_tags:
            self._ignore_stack.append(tag_lower)
        elif tag_lower in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if self._ignore_stack and self._ignore_stack[-1] == tag_lower:
            self._ignore_stack.pop()
        elif tag_lower in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignore_stack:
            self._pieces.append(data)

    def get_text(self) -> str:
        raw_text = "".join(self._pieces)
        unescaped = html.unescape(raw_text)
        # Normalize line breaks and multiple spaces
        lines = [line.strip() for line in unescaped.splitlines()]
        normalized = "\n".join(line for line in lines if line)
        return normalized


def html_to_plain_text(html_content: str) -> str:
    parser = HTMLToTextParser()
    parser.feed(html_content)
    return parser.get_text()


def validate_header_no_injection(header_name: str, value: str) -> None:
    if "\r" in value or "\n" in value:
        raise ValueError(
            f"Header injection detected in {header_name}: newlines are not allowed in email headers."
        )


def validate_email_address_no_injection(address: str) -> None:
    validate_header_no_injection("email address", address)


def parse_mime_payload(payload: dict[str, Any], body_cap: int = 20000) -> tuple[str, bool, list[dict[str, Any]]]:
    """Recursively parse a Gmail message payload (MIME tree).

    Prefers text/plain. Falls back to text/html -> html_to_plain_text.
    Exposes attachments as metadata list only.
    Caps text body at body_cap characters and sets truncated flag.
    """
    plain_text_parts: list[str] = []
    html_text_parts: list[str] = []
    attachments: list[dict[str, Any]] = []

    def _walk(part: dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        filename = part.get("filename", "")
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        size = body.get("size", 0)

        # Attachment check
        if filename or attachment_id:
            attachments.append({
                "attachment_id": attachment_id or "",
                "filename": filename or "unnamed",
                "mime_type": mime_type,
                "size": size,
            })

        # Body parsing
        data_b64 = body.get("data")
        if data_b64:
            try:
                # Gmail API uses base64url encoding
                decoded_bytes = base64.urlsafe_b64decode(data_b64 + "==")
                decoded_text = decoded_bytes.decode("utf-8", errors="replace")
                if mime_type == "text/plain":
                    plain_text_parts.append(decoded_text)
                elif mime_type == "text/html":
                    html_text_parts.append(decoded_text)
            except Exception:
                pass

        parts = part.get("parts", [])
        for subpart in parts:
            _walk(subpart)

    _walk(payload)

    if plain_text_parts:
        raw_body = "\n".join(plain_text_parts)
    elif html_text_parts:
        raw_body = "\n".join(html_to_plain_text(h) for h in html_text_parts)
    else:
        raw_body = ""

    truncated = len(raw_body) > body_cap
    final_body = raw_body[:body_cap] if truncated else raw_body

    return final_body, truncated, attachments


def extract_headers_dict(headers_list: list[dict[str, str]]) -> dict[str, str]:
    """Extract message headers into a case-insensitive dictionary map preserving raw values."""
    res: dict[str, str] = {}
    for h in headers_list:
        name = h.get("name", "")
        value = h.get("value", "")
        if name:
            res[name.lower()] = value
    return res


def normalize_addresses(raw_header_value: str) -> list[str]:
    """Extract clean email addresses from a header value (e.g. 'John Doe <john@example.com>')."""
    if not raw_header_value:
        return []
    parsed = getaddresses([raw_header_value])
    addrs: list[str] = []
    for realname, email_addr in parsed:
        email_clean = email_addr.strip().lower()
        if email_clean and email_clean not in addrs:
            addrs.append(email_clean)
    return addrs


def derive_reply_recipients(
    source_headers_map: dict[str, str],
    authenticated_user_email: str,
    reply_all: bool = False,
) -> tuple[str, str]:
    """Derive 'to' and 'cc' recipient address lists for a reply or reply-all.

    Excludes the authenticated mailbox and deduplicates.
    Returns (to_header_str, cc_header_str).
    """
    auth_email_clean = authenticated_user_email.strip().lower()

    # Determine primary reply-to address
    reply_to_header = source_headers_map.get("reply-to", "")
    from_header = source_headers_map.get("from", "")

    primary_candidates = normalize_addresses(reply_to_header) or normalize_addresses(from_header)
    primary_to = [addr for addr in primary_candidates if addr != auth_email_clean]

    if not primary_to:
        # Fallback if the user is replying to a self-sent email
        primary_to = primary_candidates

    to_addrs = primary_to[:1]  # Take primary recipient
    cc_addrs: list[str] = []

    if reply_all:
        # Collect from original From, To, Cc
        all_original = (
            normalize_addresses(source_headers_map.get("from", ""))
            + normalize_addresses(source_headers_map.get("to", ""))
            + normalize_addresses(source_headers_map.get("cc", ""))
        )
        for addr in all_original:
            if addr != auth_email_clean and addr not in to_addrs and addr not in cc_addrs:
                cc_addrs.append(addr)

    to_str = ", ".join(to_addrs)
    cc_str = ", ".join(cc_addrs)
    return to_str, cc_str


def derive_reply_subject(source_subject: str) -> str:
    """Ensure subject starts with 'Re:' without duplicating prefixes like 'Re: Re:'."""
    subject_clean = source_subject.strip()
    if not subject_clean:
        return "Re:"
    if re.match(r"^re:\s*", subject_clean, flags=re.IGNORECASE):
        return subject_clean
    return f"Re: {subject_clean}"


def derive_reply_threading_headers(source_headers_map: dict[str, str]) -> tuple[str, str]:
    """Derive In-Reply-To and References headers for reply threading.

    Raises ValueError if source Message-ID is missing.
    """
    source_msg_id = source_headers_map.get("message-id", "").strip()
    if not source_msg_id:
        raise ValueError("Source message does not contain a Message-ID header required for threading.")

    in_reply_to = source_msg_id
    existing_references = source_headers_map.get("references", "").strip()
    if existing_references:
        references = f"{existing_references} {source_msg_id}"
    else:
        references = source_msg_id

    return in_reply_to, references


def build_rfc2822_raw_message(
    to: str,
    subject: str,
    body_text: str,
    cc: str | None = None,
    bcc: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """Build a text-only RFC 2822 email message using EmailMessage and return base64url encoded string.

    Validates headers to prevent injection before constructing message.
    """
    validate_header_no_injection("To", to)
    validate_header_no_injection("Subject", subject)

    if cc:
        validate_header_no_injection("Cc", cc)
    if bcc:
        validate_header_no_injection("Bcc", bcc)
    if in_reply_to:
        validate_header_no_injection("In-Reply-To", in_reply_to)
    if references:
        validate_header_no_injection("References", references)

    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    msg.set_content(body_text)

    # Convert to RFC 2822 bytes
    raw_bytes = msg.as_bytes()
    # base64url encode
    encoded = base64.urlsafe_b64encode(raw_bytes).decode("ascii")
    return encoded
