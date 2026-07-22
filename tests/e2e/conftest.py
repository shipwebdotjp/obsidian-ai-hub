import os
import socket
import threading
import time
from pathlib import Path

import pytest
import requests


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
# Module-scoped: live Uvicorn server with seeded data
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def e2e_server_url(frontend_dist: Path) -> str:
    from obsidian_ai_hub.testing.seed import seed_memory_demo_data
    from obsidian_ai_hub.utils import config as app_config
    from obsidian_ai_hub.web.app import create_app
    import tempfile
    import uvicorn

    workspace = tempfile.TemporaryDirectory(prefix="e2e-test-")
    vault = Path(workspace.name) / "vault"
    vault.mkdir()
    db_path = Path(workspace.name) / "memory.sqlite3"

    os.environ["OBSIDIAN_AI_HUB_TESTING"] = "1"
    app_config.MEMORY_SQLITE_PATH = db_path
    app_config.VAULT_PATH = vault

    seed_memory_demo_data()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    app = create_app(host="127.0.0.1", port=port, token="")
    uvicorn_config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error"
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
        server.should_exit = True
        thread.join(timeout=5)
        workspace.cleanup()
        pytest.fail("E2E server did not start in time")

    yield base_url

    server.should_exit = True
    thread.join(timeout=10)
    workspace.cleanup()


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

    context.close()
