import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from obsidian_ai_hub.utils import config

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


@pytest.fixture(autouse=True)
def _isolate_memory_db(tmp_path: Path):
    """Use a temporary SQLite file for every test that touches the memory DB."""
    db_file = tmp_path / "memory.sqlite3"
    # Patch BEFORE get_db_connection() is called (research.db._get_db -> memory.get_db_connection)
    original = config.MEMORY_SQLITE_PATH
    config.MEMORY_SQLITE_PATH = db_file
    yield
    config.MEMORY_SQLITE_PATH = original
