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
    _test_db_bootstrap_dir = tempfile.TemporaryDirectory(
        prefix="obsidian-ai-hub-pytest-"
    )
    bootstrap_db = Path(_test_db_bootstrap_dir.name) / "collection.sqlite3"

    os.environ[_TESTING_ENV] = "1"
    os.environ[_PRODUCTION_DB_PATH_ENV] = str(
        _original_memory_db_path.expanduser().resolve()
    )
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


@pytest.fixture(autouse=True)
def _patch_register_run_and_questions(monkeypatch):
    import obsidian_ai_hub.hitl.service as hitl_service
    import obsidian_ai_hub.hitl as hitl_module
    from obsidian_ai_hub.hitl.store import get_run

    orig_register = hitl_service.register_run_and_questions
    hitl_service._orig_register_run_and_questions = orig_register

    def wrapped_register(
        run_id,
        handler,
        checkpoint,
        question_set_id,
        questions_data,
        conn=None,
        title=None,
        description=None,
        display_type=None,
    ):
        import sqlite3
        import logging
        run_exists = False
        try:
            run_exists = get_run(run_id, conn) is not None
        except sqlite3.Error as e:
            logging.getLogger(__name__).warning("sqlite3.Error in wrapped_register run_exists check: %s", e)

        if not run_exists:
            if title is None:
                title = "Test Run Title"
            if display_type is None:
                display_type = "テスト"

        return orig_register(
            run_id=run_id,
            handler=handler,
            checkpoint=checkpoint,
            question_set_id=question_set_id,
            questions_data=questions_data,
            conn=conn,
            title=title,
            description=description,
            display_type=display_type,
        )

    monkeypatch.setattr(hitl_service, "register_run_and_questions", wrapped_register)
    monkeypatch.setattr(hitl_module, "register_run_and_questions", wrapped_register)


@pytest.fixture(autouse=True)
def _filesystem_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all writable application paths under tmp_path."""
    vault = tmp_path / "vault"

    monkeypatch.setattr(app_config, "VAULT_PATH", vault)
    monkeypatch.setattr(app_config, "INBOX_PATH", vault / app_config.INBOX_DIR_NAME)
    monkeypatch.setattr(app_config, "DAILY_PATH", vault / app_config.DAILY_DIR_NAME)
    monkeypatch.setattr(app_config, "PEOPLE_PATH", vault / app_config.PEOPLE_DIR_NAME)
    monkeypatch.setattr(app_config, "DASHBOARD_PATH", vault / app_config.DASHBOARD_DIR_NAME)
    monkeypatch.setattr(app_config, "ACTIVITY_PATH", vault / "activity")
    monkeypatch.setattr(app_config, "RESEARCH_OUTPUT_DIR", vault / app_config.RESEARCH_DIR_NAME)
    monkeypatch.setattr(app_config, "KNOWLEDGE_SYNC_FOLDER", vault / app_config.KNOWLEDGE_DIR_NAME)
    monkeypatch.setattr(app_config, "WEBCLIP_PATH", vault / app_config.WEBCLIP_DIR_NAME)
    monkeypatch.setattr(app_config, "SCREENSHOT_PATH", vault / "screenshots")
    monkeypatch.setattr(app_config, "TEMPLATE_PATH", vault / app_config.DAILY_DIR_NAME / app_config.TEMPLATE_DIR_NAME / app_config.DAILY_TEMPLATE_FILENAME)
    monkeypatch.setattr(app_config, "WEEKLY_TEMPLATE_PATH", vault / app_config.DAILY_DIR_NAME / app_config.TEMPLATE_DIR_NAME / app_config.WEEKLY_TEMPLATE_FILENAME)
    monkeypatch.setattr(app_config, "MONTHLY_TEMPLATE_PATH", vault / app_config.DAILY_DIR_NAME / app_config.TEMPLATE_DIR_NAME / app_config.MONTHLY_TEMPLATE_FILENAME)
    monkeypatch.setattr(app_config, "RESEARCH_CANDIDATE_THEME_LIST_PATH", (vault / app_config.RESEARCH_DIR_NAME) / app_config.RESEARCH_CANDIDATE_THEME_LIST_FILENAME)

    monkeypatch.setattr(app_config, "AI_LOG_PATH", tmp_path / "ai-log")
    monkeypatch.setattr(app_config, "TASK_RUN_STATE_PATH", tmp_path / "last_run.json")
    monkeypatch.setattr(app_config, "KNOWLEDGE_SYNC_STATE_PATH", tmp_path / "knowledge_sync_state.json")
    monkeypatch.setattr(app_config, "VAULT_INDEX_SQLITE_PATH", tmp_path / "vault-index" / "search.sqlite")
    monkeypatch.setattr(app_config, "VAULT_INDEX_CHROMA_PATH", tmp_path / "vault-index" / "chroma")
    monkeypatch.setattr(app_config, "LOCAL_MODEL_DIR", tmp_path / "local-models")
