import logging
import os
import socket
import threading
import time
import json
from pathlib import Path

import pytest
import requests


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []
    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


server_log_capture = _LogCapture()
server_log_capture.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

TEST_API_TOKEN = "test-api-token"


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


# Override root conftest's autouse fixtures so they don't change the DB or
# filesystem paths while the E2E server thread is handling requests.
@pytest.fixture(autouse=True)
def _isolate_memory_db():
    yield


@pytest.fixture(autouse=True)
def _isolate_sqlite_dbs():
    yield


@pytest.fixture(autouse=True)
def _filesystem_sandbox():
    yield


# ---------------------------------------------------------------------------
# Session-scoped: verify the frontend build exists
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def frontend_dist() -> Path:
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if not (dist / "index.html").exists():
        pytest.skip("frontend/dist/index.html not found. Run: make build-web")
    return dist


# ---------------------------------------------------------------------------
# Module-scoped seed scenario override
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def e2e_seed_scenario():
    """Override this module-scope fixture to specify which scenarios to seed.
    Can be a list containing 'memory', 'hitl', 'people', 'planner', and/or
    'summary_recovery'.
    """
    return ["memory"]


# ---------------------------------------------------------------------------
# Module-scoped: live Uvicorn server with seeded data
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def e2e_server_url(frontend_dist: Path, e2e_seed_scenario: list[str]) -> str:
    from obsidian_ai_hub.testing.seed import (
        seed_memory_demo_data,
        seed_hitl_demo_data,
        seed_people_demo_data,
        seed_summary_recovery_demo_data,
        seed_planner_demo_data,
    )
    from obsidian_ai_hub import database
    from obsidian_ai_hub.utils import config as app_config
    from obsidian_ai_hub.web.app import create_app
    import tempfile
    import uvicorn

    workspace = tempfile.TemporaryDirectory(prefix="e2e-test-")
    vault = Path(workspace.name) / "vault"
    vault.mkdir()
    db_path = Path(workspace.name) / "memory.sqlite3"

    orig_testing = os.environ.get("OBSIDIAN_AI_HUB_TESTING")
    orig_memory_path = app_config.MEMORY_SQLITE_PATH
    orig_vault_path = app_config.VAULT_PATH

    os.environ["OBSIDIAN_AI_HUB_TESTING"] = "1"
    app_config.MEMORY_SQLITE_PATH = db_path
    app_config.VAULT_PATH = vault

    uvicorn_logger = logging.getLogger("uvicorn")

    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    workspace_cleaned = False
    original_generate_summary = None

    try:
        # Explicitly run database migrations to prepare the schema
        conn = database.get_db_connection()
        conn.close()

        uvicorn_logger.setLevel(logging.INFO)
        uvicorn_logger.addHandler(server_log_capture)

        server_log_capture.records.clear()

        if "memory" in e2e_seed_scenario:
            seed_memory_demo_data()
        if "hitl" in e2e_seed_scenario:
            seed_hitl_demo_data()
        if "people" in e2e_seed_scenario:
            seed_people_demo_data()
        if "summary_recovery" in e2e_seed_scenario:
            seed_summary_recovery_demo_data()
            from obsidian_ai_hub.summary import store as summary_store
            from obsidian_ai_hub.web.routes import dashboard as dashboard_route

            original_generate_summary = dashboard_route.generate_summary

            def deterministic_summary(*_args, **kwargs):
                target_date = kwargs["target_date"]
                created = summary_store.upsert_summary({
                    "period_type": "day", "period_key": target_date,
                    "period_start": target_date, "period_end": target_date,
                    "summary": "E2E generated recovery summary", "keywords": [],
                    "topics": [], "projects": [], "people": [], "items": [],
                })
                return summary_store.get_summary_by_id(created["summary_id"])

            dashboard_route.generate_summary = deterministic_summary

        if "planner" in e2e_seed_scenario:
            seed_planner_demo_data()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        app = create_app(host="127.0.0.1", port=port, token=TEST_API_TOKEN)
        uvicorn_config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="info"
        )
        server = uvicorn.Server(config=uvicorn_config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        base_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                r = requests.get(f"{base_url}/health", timeout=2)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            if server is not None:
                server.should_exit = True
            if thread is not None:
                thread.join(timeout=5)
            workspace.cleanup()
            workspace_cleaned = True
            pytest.fail("E2E server did not start in time")

        yield base_url
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)
        if not workspace_cleaned:
            workspace.cleanup()

        uvicorn_logger.removeHandler(server_log_capture)

        if orig_testing is not None:
            os.environ["OBSIDIAN_AI_HUB_TESTING"] = orig_testing
        else:
            os.environ.pop("OBSIDIAN_AI_HUB_TESTING", None)
        app_config.MEMORY_SQLITE_PATH = orig_memory_path
        app_config.VAULT_PATH = orig_vault_path
        if original_generate_summary is not None:
            from obsidian_ai_hub.web.routes import dashboard as dashboard_route
            dashboard_route.generate_summary = original_generate_summary


# ---------------------------------------------------------------------------
# Module-scoped: Playwright browser instance
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            executable = pw.chromium.executable_path
        except Exception:
            pytest.skip("Playwright Chromium is not available")
        if not executable or not Path(executable).is_file():
            pytest.skip("Playwright Chromium binary not found")
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()


# ---------------------------------------------------------------------------
# Function-scoped: new page per test, artifact capture on failure
# ---------------------------------------------------------------------------

@pytest.fixture
def page(browser, request):
    context = browser.new_context()
    context.add_init_script(
        "localStorage.setItem('obsidian-ai-hub:api-token', %s)"
        % json.dumps(TEST_API_TOKEN)
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    console_log: list[str] = []
    page.on("console", lambda msg: console_log.append(f"[{msg.type}] {msg.text}"))

    yield page

    if hasattr(request.node, "rep_call") and request.node.rep_call.failed:
        artifacts_dir = Path("test-results") / "e2e"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        test_name = request.node.name
        try:
            page.screenshot(path=str(artifacts_dir / f"{test_name}.png"))
        except Exception:
            pass
        if console_log:
            (artifacts_dir / f"{test_name}.console.log").write_text(
                "\n".join(console_log), encoding="utf-8"
            )
        try:
            context.tracing.stop(path=str(artifacts_dir / f"{test_name}.trace.zip"))
        except Exception:
            pass
        if server_log_capture.records:
            (artifacts_dir / f"{test_name}.server.log").write_text(
                "\n".join(server_log_capture.records), encoding="utf-8"
            )
    else:
        context.tracing.stop()

    context.close()
