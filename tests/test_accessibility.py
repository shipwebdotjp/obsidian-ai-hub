import sys
from unittest.mock import MagicMock, patch

# Mock Quartz and AppKit before importing accessibility
sys.modules["AppKit"] = MagicMock()
sys.modules["Quartz"] = MagicMock()

from obsidian_ai_hub.utils import accessibility

def test_list_windows():
    mock_windows = [
        {
            "kCGWindowNumber": 1,
            "kCGWindowName": "Window 1",
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 100},
            "kCGWindowIsOnscreen": True,
            "kCGWindowAlpha": 1.0,
            "kCGWindowLayer": 0,
            "kCGWindowOwnerName": "App 1",
            "kCGWindowOwnerPID": 123,
        },
        {
            "kCGWindowNumber": 2,
            "kCGWindowName": "Window 2",
            "kCGWindowBounds": {"X": 50, "Y": 50, "Width": 200, "Height": 200},
            "kCGWindowIsOnscreen": True,
            "kCGWindowAlpha": 0.5,
            "kCGWindowLayer": 0,
            "kCGWindowOwnerName": "App 2",
            "kCGWindowOwnerPID": 456,
        }
    ]

    with patch("obsidian_ai_hub.utils.accessibility.CGWindowListCopyWindowInfo", return_value=mock_windows):
        results = accessibility.list_windows()

    assert len(results) == 2
    assert results[0]["window_id"] == 1
    assert results[0]["owner_name"] == "App 1"
    assert results[1]["window_id"] == 2
    assert results[1]["alpha"] == 0.5

def test_get_line_window_found():
    mock_windows = [
        {
            "kCGWindowNumber": 1,
            "kCGWindowName": "Other App",
            "kCGWindowOwnerName": "Other",
            "kCGWindowLayer": 0,
            "kCGWindowAlpha": 1.0,
        },
        {
            "kCGWindowNumber": 2,
            "kCGWindowName": "LINE",
            "kCGWindowOwnerName": "LINE",
            "kCGWindowLayer": 0,
            "kCGWindowAlpha": 1.0,
        }
    ]

    with patch("obsidian_ai_hub.utils.accessibility.CGWindowListCopyWindowInfo", return_value=mock_windows):
        win = accessibility.get_line_window()

    assert win is not None
    assert win["window_id"] == 2
    assert win["owner_name"] == "LINE"

def test_get_line_window_not_found():
    mock_windows = [
        {
            "kCGWindowNumber": 1,
            "kCGWindowName": "Chrome",
            "kCGWindowOwnerName": "Google Chrome",
            "kCGWindowLayer": 0,
            "kCGWindowAlpha": 1.0,
        }
    ]

    with patch("obsidian_ai_hub.utils.accessibility.CGWindowListCopyWindowInfo", return_value=mock_windows):
        win = accessibility.get_line_window()

    assert win is None

def test_get_line_window_invisible_ignored():
    mock_windows = [
        {
            "kCGWindowNumber": 1,
            "kCGWindowName": "",
            "kCGWindowOwnerName": "LINE",
            "kCGWindowLayer": 1, # Non-zero layer
            "kCGWindowAlpha": 1.0,
        },
        {
            "kCGWindowNumber": 2,
            "kCGWindowName": "",
            "kCGWindowOwnerName": "LINE",
            "kCGWindowLayer": 0,
            "kCGWindowAlpha": 0.0, # Zero alpha
        }
    ]

    with patch("obsidian_ai_hub.utils.accessibility.CGWindowListCopyWindowInfo", return_value=mock_windows):
        win = accessibility.get_line_window()

    assert win is None
