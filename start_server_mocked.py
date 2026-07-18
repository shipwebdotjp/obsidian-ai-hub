import sys
from unittest.mock import MagicMock

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

import uvicorn
from obsidian_ai_hub.web.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
