import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

# We need to mock dependencies that might fail during import or execution
with patch("obsidian_ai_hub.utils.accessibility.CGWindowListCopyWindowInfo", return_value=[]), \
     patch("AppKit.NSWorkspace.sharedWorkspace", return_value=MagicMock()):
    from obsidian_ai_hub import scan_line_inbox

@pytest.fixture
def mock_scan_deps():
    with patch("obsidian_ai_hub.scan_line_inbox.accessibility") as mock_acc, \
         patch("obsidian_ai_hub.scan_line_inbox.take_screenshot") as mock_ts, \
         patch("obsidian_ai_hub.scan_line_inbox.llm_client") as mock_llm, \
         patch("obsidian_ai_hub.scan_line_inbox.config") as mock_cfg:

        mock_cfg.LINE_INBOX_SCAN_PROVIDER = "openai"
        mock_cfg.LINE_INBOX_SCAN_MODEL = "gpt-4-vision"

        yield {
            "acc": mock_acc,
            "ts": mock_ts,
            "llm": mock_llm,
            "cfg": mock_cfg
        }

def test_scan_line_inbox_success(mock_scan_deps):
    deps = mock_scan_deps
    deps["acc"].get_line_window.return_value = {
        "window_id": 123,
        "window_title": "LINE"
    }
    deps["ts"].main.return_value = "/tmp/screenshot.png"

    expected_data = {
        "candidates": [
            {
                "chat_name": "Test User",
                "unread_count": 5,
                "preview_text": "Hello",
                "confidence": 0.9
            }
        ]
    }
    deps["llm"].generate_llm_response.return_value = json.dumps(expected_data)

    result = scan_line_inbox.scan_line_inbox()

    assert result["window_id"] == 123
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["chat_name"] == "Test User"
    assert "error" not in result

def test_scan_line_inbox_no_window(mock_scan_deps):
    deps = mock_scan_deps
    deps["acc"].get_line_window.return_value = None

    result = scan_line_inbox.scan_line_inbox()

    assert result["window_id"] is None
    assert result["candidates"] == []
    assert "error" in result

def test_scan_line_inbox_local_provider_error(mock_scan_deps):
    deps = mock_scan_deps
    deps["cfg"].LINE_INBOX_SCAN_PROVIDER = "local"

    with pytest.raises(RuntimeError, match="does not support multimodal"):
        scan_line_inbox.scan_line_inbox()

def test_parse_json_with_markdown(mock_scan_deps):
    response = "```json\n{\"candidates\": []}\n```"
    data = scan_line_inbox.parse_json_response(response)
    assert data == {"candidates": []}

def test_parse_json_raw(mock_scan_deps):
    response = "{\"candidates\": []}"
    data = scan_line_inbox.parse_json_response(response)
    assert data == {"candidates": []}

def test_parse_json_with_extra_text(mock_scan_deps):
    response = "Here is the result: {\"candidates\": []} Hope it helps!"
    data = scan_line_inbox.parse_json_response(response)
    assert data == {"candidates": []}

def test_parse_json_invalid(mock_scan_deps):
    response = "Not a JSON at all"
    with pytest.raises(ValueError, match="Invalid JSON response"):
        scan_line_inbox.parse_json_response(response)
