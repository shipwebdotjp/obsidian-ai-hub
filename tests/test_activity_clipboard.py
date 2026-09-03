import pytest
from obsidian_ai_hub.activity.clipboard import sanitize_clipboard_text, get_sanitized_clipboard_text


def test_sanitize_clipboard_empty():
    assert sanitize_clipboard_text(None) == "(なし)"
    assert sanitize_clipboard_text("") == "(なし)"
    assert sanitize_clipboard_text("   \n ") == "(なし)"


def test_sanitize_clipboard_normal_text():
    text = "Hello world! This is a simple test text."
    assert sanitize_clipboard_text(text) == text


def test_sanitize_clipboard_key_value_dotenv():
    raw = "API_KEY=" + "sk-" + "1234567890abcdef1234567890\nPASSWORD=mysecretpassword123\nNORMAL_VAR=hello"
    expected = "API_KEY=[REDACTED]\nPASSWORD=[REDACTED]\nNORMAL_VAR=hello"
    assert sanitize_clipboard_text(raw) == expected


def test_sanitize_clipboard_key_value_json():
    raw = '{\n  "api_key": "secret_value_123",\n  "secret_key": "topsecret",\n  "name": "john"\n}'
    expected = '{\n  "api_key": "[REDACTED]",\n  "secret_key": "[REDACTED]",\n  "name": "john"\n}'
    assert sanitize_clipboard_text(raw) == expected


def test_sanitize_clipboard_key_value_yaml():
    raw = "api-key: my_api_key_value\npassphrase: 'super secret passphrase'\nuser: admin"
    expected = "api-key: [REDACTED]\npassphrase: '[REDACTED]'\nuser: admin"
    assert sanitize_clipboard_text(raw) == expected


def test_sanitize_clipboard_key_value_spaces_in_keys():
    raw = 'API key: "my key"\nsecret key = my_secret_val'
    expected = 'API key: "[REDACTED]"\nsecret key = [REDACTED]'
    assert sanitize_clipboard_text(raw) == expected


def test_sanitize_clipboard_explicit_tokens():
    raw = (
        "OpenAI key: " + "sk-" + "proj-1234567890abcdef1234567890123456\n"
        "GitHub token: " + "ghp_" + "1234567890abcdef1234567890abcdef123456\n"
        "GitHub Pat: " + "github_pat_" + "11AAAAAAA01234567890_abcdefghijklmnopqrstuvwxyz01234567890\n"
        "Slack token: " + "xoxb-" + "1234567890-123456789012-abcdefghijklmnopqrstuvwx\n"
        "AWS key: " + "AKIA" + "IOSFODNN7EXAMPLE"
    )
    expected = (
        "OpenAI key: [REDACTED]\n"
        "GitHub token: [REDACTED]\n"
        "GitHub Pat: [REDACTED]\n"
        "Slack token: [REDACTED]\n"
        "AWS key: [REDACTED]"
    )
    assert sanitize_clipboard_text(raw) == expected


def test_sanitize_clipboard_bearer_token():
    raw = "Authorization: Bearer my.secret.jwt.token.here\nBearer xyz123456789"
    expected = "Authorization: Bearer [REDACTED]\nBearer [REDACTED]"
    assert sanitize_clipboard_text(raw) == expected


def test_sanitize_clipboard_pem_key():
    raw = (
        "Header text\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA0\n"
        "-----END RSA PRIVATE KEY-----\n"
        "Footer text"
    )
    expected = "Header text\n[REDACTED]\nFooter text"
    assert sanitize_clipboard_text(raw) == expected


def test_sanitize_clipboard_truncation():
    raw = "A" * 5000
    sanitized = sanitize_clipboard_text(raw)
    assert len(sanitized.split("\n[TRUNCATED]")[0]) == 4000
    assert sanitized.endswith("\n[TRUNCATED]")


def test_get_sanitized_clipboard_text_mocked():
    import sys
    import types
    from unittest.mock import patch

    dummy = types.ModuleType("AppKit")

    class DummyPB:
        def stringForType_(self, tp):
            return "api_key = secret123"

        @classmethod
        def generalPasteboard(cls):
            return DummyPB()

    dummy.NSPasteboard = DummyPB
    dummy.NSPasteboardTypeString = "public.utf8-plain-text"
    with patch.dict(sys.modules, {"AppKit": dummy}):
        assert get_sanitized_clipboard_text() == "api_key = [REDACTED]"


def test_get_sanitized_clipboard_text_exception():
    import sys
    import types
    from unittest.mock import patch

    dummy = types.ModuleType("AppKit")

    class DummyPB:
        @classmethod
        def generalPasteboard(cls):
            raise RuntimeError("Pasteboard error")

    dummy.NSPasteboard = DummyPB
    dummy.NSPasteboardTypeString = "public.utf8-plain-text"
    with patch.dict(sys.modules, {"AppKit": dummy}):
        assert get_sanitized_clipboard_text() == "(なし)"
