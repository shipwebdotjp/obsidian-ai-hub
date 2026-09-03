import logging
import re

logger = logging.getLogger(__name__)

# Keys targeted for key-value masking (case-insensitive)
TARGET_KEYS_PATTERN = r"(?:password|passphrase|token|access_token|auth_token|credential|client_?secret|private_?key|api[_\- ]key|secret[_\- ]key|authorization)"

# Regex 1: PEM Private Key Blocks
PEM_PRIVATE_KEY_REGEX = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)

# Regex 2: Key-value assignments (dotenv, JSON, YAML, general : or = assignments)
# unquoted_val allows one extra horizontal-space-separated token to capture `Bearer <token>` style values
KEY_VALUE_REGEX = re.compile(
    rf'(?i)(?P<key>(?:"{TARGET_KEYS_PATTERN}"|\'{TARGET_KEYS_PATTERN}\'|{TARGET_KEYS_PATTERN}))'
    rf'(?P<delim>\s*[:=]\s*)'
    rf'(?:'
    rf'(?P<quote>["\'])(?P<quoted_val>[\s\S]*?)(?P=quote)'
    rf'|'
    rf'(?P<unquoted_val>[^\s,\r\n#}}]+(?:[ \t]+[^\s,\r\n#}}]+)?)'
    rf')',
    re.DOTALL,
)

# Regex 3: Authorization schemes (Bearer, Basic, etc.)
AUTH_HEADER_REGEX = re.compile(
    r"(?i)\b((?:Bearer|Basic|Digest|Token)\s+)(\S+)",
)

# Backward compatibility alias
BEARER_REGEX = AUTH_HEADER_REGEX

# Regex 4: Explicit token patterns (OpenAI, GitHub, Slack, AWS)
# OpenAI: sk-proj-... or sk-...
OPENAI_TOKEN_REGEX = re.compile(r"\bsk-[a-zA-Z0-9_\-]{20,}\b")

# GitHub: ghp_... or github_pat_...
GITHUB_TOKEN_REGEX = re.compile(
    r"\b(?:ghp_[a-zA-Z0-9]{36,}|github_pat_[a-zA-Z0-9_]{22,})\b"
)

# Slack: xoxb-..., xoxp-..., xoxa-..., xoxr-..., xoxs-...
SLACK_TOKEN_REGEX = re.compile(r"\bxox[baprs]-[a-zA-Z0-9\-]{10,}\b")

# AWS Access Key ID: AKIA...
AWS_KEY_REGEX = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def sanitize_clipboard_text(raw_text: str | None) -> str:
    """
    Sanitizes raw clipboard text by replacing sensitive patterns with [REDACTED].
    Truncates text exceeding 4,000 characters (after masking) and appends \\n[TRUNCATED].
    Returns "(なし)" if the input is empty or results in an empty string.
    """
    if not raw_text or not raw_text.strip():
        return "(なし)"

    text = raw_text

    # 1. Mask PEM Private Key blocks
    text = PEM_PRIVATE_KEY_REGEX.sub("[REDACTED]", text)

    # 2. Mask Authorization / Bearer / Basic tokens
    text = AUTH_HEADER_REGEX.sub(r"\1[REDACTED]", text)

    # 3. Mask explicit tokens (OpenAI, GitHub, Slack, AWS)
    text = OPENAI_TOKEN_REGEX.sub("[REDACTED]", text)
    text = GITHUB_TOKEN_REGEX.sub("[REDACTED]", text)
    text = SLACK_TOKEN_REGEX.sub("[REDACTED]", text)
    text = AWS_KEY_REGEX.sub("[REDACTED]", text)

    # 4. Mask Key-Value pairs
    def _kv_replacer(match: re.Match) -> str:
        key = match.group("key")
        delim = match.group("delim")
        quote = match.group("quote")

        if quote:
            return f"{key}{delim}{quote}[REDACTED]{quote}"
        else:
            val = match.group("unquoted_val") or ""
            # Preserve scheme for authorization headers (e.g. `Authorization: Bearer <token>` -> `Authorization: Bearer [REDACTED]`)
            raw_key = key.strip('"\'')
            if raw_key.lower() == "authorization":
                m = re.match(r"(?i)^(Bearer|Basic|Digest|Token)[ \t]+(\S+.*)", val)
                if m:
                    return f"{key}{delim}{m.group(1)} [REDACTED]"
            return f"{key}{delim}[REDACTED]"

    text = KEY_VALUE_REGEX.sub(_kv_replacer, text)

    # Check non-empty
    if not text.strip():
        return "(なし)"

    # Truncation: limit to first 4,000 characters, append \n[TRUNCATED] if exceeded
    if len(text) > 4000:
        text = text[:4000] + "\n[TRUNCATED]"

    return text


def get_sanitized_clipboard_text() -> str:
    """
    Retrieves plain text from NSPasteboard, masks sensitive values,
    truncates to 4,000 chars if necessary, and returns sanitized text.
    Returns "(なし)" on empty clipboard, non-text, or errors.
    """
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        raw_text = pb.stringForType_(NSPasteboardTypeString)
        if not raw_text or not isinstance(raw_text, str):
            return "(なし)"
        return sanitize_clipboard_text(raw_text)
    except Exception as e:
        logger.warning(f"Failed to retrieve clipboard text from NSPasteboard: {e}")
        return "(なし)"
