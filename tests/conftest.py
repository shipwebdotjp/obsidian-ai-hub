import sys
from unittest.mock import MagicMock

# If we are not on macOS, mock all macOS-specific dependencies globally for test collection and execution
if sys.platform != "darwin":
    mock_modules = [
        "objc",
        "AppKit",
        "Foundation",
        "EventKit",
        "Quartz",
        "Vision",
        "Cocoa",
        "ApplicationServices",
        "atomacos",
    ]
    for name in mock_modules:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
