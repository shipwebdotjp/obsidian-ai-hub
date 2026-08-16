# E2E Test Usage and Guidelines

This document provides instructions for developers and AI agents on how to use, explore, and run the structured E2E (End-to-End) browser tests in the repository.

---

## 2. Goals and Philosophy

We adhere to the strict philosophy of **limiting browser E2E tests only to critical, high-impact user flows**.

- **E2E Tests (`make test-e2e`)**: Cover the major, critical user journeys—such as ensuring standard Memory approval cascades and that Human-in-the-Loop (HITL) answers/cancellations successfully persist. They serve to prevent critical, high-impact regression failures (e.g. data loss, unauthorized access, broken main navigation loops).
- **Vitest Unit/Integration Tests**: Cover specific UI states, filter operations, dynamic form errors, debounce interactions, accessibility labels, and style details.

For details on the split and post-reduction state, please read the decision log: [フロントエンドテストの Vitest 化と E2E テストの役割縮小 (Phase 3〜5、および 7〜9)](../../ai_wiki/10-Decisions-Testing.md#フロントエンドテストの-vitest-化と-e2e-テストの役割縮小-phase-3〜5および-7〜9).

---

## 3. Developing and Exploring with the Exploration Server

While developing frontend changes or investigating bugs, you can spin up an isolated, pre-seeded exploration server.

```bash
# 1. Build the production-ready frontend bundle
make build-web

# 2. Run the isolated loopback-bound exploration server
make e2e-serve
```

This starts a server bound to a loopback address (typically `http://127.0.0.1:8765` or another port logged in the output) in `ENV=test` mode. It:
- Completely isolates the filesystem and creates a temporary SQLite database.
- Pre-seeds demo data for Memory and HITL.
- Destroys all workspace data on exit (Ctrl-C).

---

## 4. Running the E2E Test Suite

Before submitting any frontend change, you MUST run the E2E test suite to verify no regressions occurred in the core user journeys.

```bash
# Build the SPA and run all Playwright E2E tests
make test-e2e
```

Behind the scenes, this executes `pytest -m e2e` with pytest temporary sandboxes and live Uvicorn servers.

---

## 5. Scenario-Based Test Architecture

The E2E tests are organized cleanly in scenario files under `tests/e2e/`:

1. `test_memory_scenario.py`: Covers the Memory approval main flow: page load with `/` → `/memories` redirect, direct URL access to `/memories`, candidate approval cascading, the approved entry showing up under the approved filter, and SPA fallback for arbitrary paths.
2. `test_hitl_answer_scenario.py`: Covers the Human-In-The-Loop flow for answering active interaction questions.
3. `test_hitl_cancel_scenario.py`: Covers the Human-In-The-Loop flow for cancelling outstanding execution runs.

### How E2E Scenario Seeding Works

To prevent database clutter and ensure isolation, we do not share a single monolithic database state. Instead, each module overrides the `e2e_seed_scenario` fixture to request specific pre-seed data from the central seeding API (`src/obsidian_ai_hub/testing/seed.py`).

For example, a test file can override the seed scenario like so:

```python
import pytest

@pytest.fixture(scope="module")
def e2e_seed_scenario() -> list[str]:
    return ["hitl"]
```

This instructs the E2E test server to seed the database with HITL scenarios before spinning up.

---

## 6. Failure Diagnostics and Logs

If an E2E test fails, the framework automatically dumps full failure diagnostics under `test-results/e2e/`:
- **`*.png`**: A screenshot of the viewport at the moment of failure.
- **`*.console.log`**: Standard output and error console logs from the browser.
- **`*.server.log`**: Uvicorn/FastAPI backend framework server logs.
- **`*.trace.zip`**: Playwright browser execution trace.

Open Playwright Trace Viewer to inspect the failure:
```bash
uv run playwright show-trace test-results/e2e/some_test_name.trace.zip
```
