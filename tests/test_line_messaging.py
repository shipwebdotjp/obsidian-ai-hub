import pytest
import requests
from unittest.mock import patch, MagicMock

from obsidian_ai_hub.utils.line_messaging import (
    send_line_push,
    send_line_push_messages,
)


@pytest.fixture
def mock_post():
    with patch("obsidian_ai_hub.utils.line_messaging.requests.post") as m:
        yield m


@pytest.fixture
def mock_ensure_external():
    with patch("obsidian_ai_hub.utils.line_messaging.config.ensure_external_allowed") as m:
        yield m


class TestSendLinePushMessages:
    def test_sends_correct_payload(self, mock_post, mock_ensure_external):
        mock_post.return_value = MagicMock(status_code=200)
        ok = send_line_push_messages("token123", "user456", ["msg1", "msg2"])
        assert ok is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"] == {
            "to": "user456",
            "messages": [
                {"type": "text", "text": "msg1"},
                {"type": "text", "text": "msg2"},
            ],
        }
        assert kwargs["headers"]["Authorization"] == "Bearer token123"

    def test_single_message(self, mock_post, mock_ensure_external):
        mock_post.return_value = MagicMock(status_code=200)
        ok = send_line_push_messages("t", "u", ["only"])
        assert ok is True
        _, kwargs = mock_post.call_args
        assert len(kwargs["json"]["messages"]) == 1

    def test_five_messages_ok(self, mock_post, mock_ensure_external):
        mock_post.return_value = MagicMock(status_code=200)
        ok = send_line_push_messages("t", "u", ["a", "b", "c", "d", "e"])
        assert ok is True

    def test_zero_messages_raises(self, mock_post, mock_ensure_external):
        with pytest.raises(ValueError, match="1-5"):
            send_line_push_messages("t", "u", [])

    def test_six_messages_raises(self, mock_post, mock_ensure_external):
        with pytest.raises(ValueError, match="1-5"):
            send_line_push_messages("t", "u", ["a"] * 6)

    def test_api_4xx_returns_false(self, mock_post, mock_ensure_external):
        mock_post.return_value = MagicMock(status_code=400)
        ok = send_line_push_messages("t", "u", ["msg"])
        assert ok is False

    def test_api_2xx_other_returns_true(self, mock_post, mock_ensure_external):
        mock_post.return_value = MagicMock(status_code=299)
        ok = send_line_push_messages("t", "u", ["msg"])
        assert ok is True

    def test_request_exception_returns_false(self, mock_post, mock_ensure_external):
        mock_post.side_effect = requests.RequestException("connection error")
        ok = send_line_push_messages("t", "u", ["msg"])
        assert ok is False

    def test_ensure_external_called(self, mock_post, mock_ensure_external):
        mock_post.return_value = MagicMock(status_code=200)
        send_line_push_messages("t", "u", ["msg"])
        mock_ensure_external.assert_called_once_with("LINE Messaging API")


class TestSendLinePush:
    def test_sends_single_message(self, mock_post, mock_ensure_external):
        mock_post.return_value = MagicMock(status_code=200)
        ok = send_line_push("t", "u", "hello")
        assert ok is True
        _, kwargs = mock_post.call_args
        assert kwargs["json"] == {
            "to": "u",
            "messages": [{"type": "text", "text": "hello"}],
        }
