import os

os.environ.setdefault("OAIHUB_SKIP_DOTENV", "1")

import tempfile
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from obsidian_ai_hub.utils import config as app_config

_TESTING_ENV = "OBSIDIAN_AI_HUB_TESTING"
_PRODUCTION_DB_PATH_ENV = "OBSIDIAN_AI_HUB_TEST_PRODUCTION_DB_PATH"
_test_db_bootstrap_dir: tempfile.TemporaryDirectory[str] | None = None
_original_memory_db_path: Path | None = None
_original_env: dict[str, str | None] = {}


def pytest_configure(config: pytest.Config) -> None:
    """Keep collection-time imports away from the configured production DB."""
    global _test_db_bootstrap_dir, _original_memory_db_path, _original_env

    _original_memory_db_path = Path(app_config.MEMORY_SQLITE_PATH)
    _original_env = {
        _TESTING_ENV: os.environ.get(_TESTING_ENV),
        _PRODUCTION_DB_PATH_ENV: os.environ.get(_PRODUCTION_DB_PATH_ENV),
    }
    _test_db_bootstrap_dir = tempfile.TemporaryDirectory(prefix="obsidian-ai-hub-pytest-")
    bootstrap_db = Path(_test_db_bootstrap_dir.name) / "collection.sqlite3"

    os.environ[_TESTING_ENV] = "1"
    os.environ[_PRODUCTION_DB_PATH_ENV] = str(_original_memory_db_path.expanduser().resolve())
    app_config.MEMORY_SQLITE_PATH = bootstrap_db


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore the process configuration after pytest exits."""
    global _test_db_bootstrap_dir

    if _original_memory_db_path is not None:
        app_config.MEMORY_SQLITE_PATH = _original_memory_db_path
    for name, value in _original_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if _test_db_bootstrap_dir is not None:
        _test_db_bootstrap_dir.cleanup()
        _test_db_bootstrap_dir = None

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


@pytest.fixture
def test_memory_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure a SQLite file unique to the current test."""
    db_file = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(app_config, "MEMORY_SQLITE_PATH", db_file)
    return db_file


@pytest.fixture(autouse=True)
def _isolate_memory_db(test_memory_db_path: Path):
    """Use a temporary SQLite file for every test that touches the memory DB."""
    yield
