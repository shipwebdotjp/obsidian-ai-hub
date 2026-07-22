# E2E Test Foundation TODO

## Phase 1: Safety and Shared Data

- [ ] Extend the root pytest autouse fixture in `tests/conftest.py` so every
      writable configured path is under `tmp_path`, not only
      `MEMORY_SQLITE_PATH`.
- [ ] Redirect at least Vault, Inbox, Daily, People, Activity, Research output,
      AI log, task state, knowledge-sync state, and Vault index paths.
- [ ] Update `docs/testing.md` to state that pytest database isolation is
      automatic and that `test_memory_db_path` is needed only when the path
      itself is relevant to a test.
- [ ] Add `src/obsidian_ai_hub/testing/` with a test-mode guard.
- [ ] Add `factories.py` with a stable `make_memory()` builder based on the
      complete Memory Review record used in existing tests.
- [ ] Add `seed.py` with a public-API-based `seed_memory_demo_data()` function.
- [ ] Verify that all new factory and seed code fails outside test mode.

## Phase 2: Exploration Server

- [ ] Add `obsidian_ai_hub.testing.e2e_server` as a dedicated module that sets
      `ENV=test` before importing application configuration.
- [ ] Build a fresh temporary test workspace, seed the Memory demo data, and
      serve the existing FastAPI app from loopback only.
- [ ] Print the test URL and workspace path at startup.
- [ ] Ensure Ctrl-C stops Uvicorn and cleans up the temporary workspace.
- [ ] Do not add a test-data HTTP endpoint or modify normal web API routes.
- [ ] Add `make build-web`, using `npm ci && npm run build`.
- [ ] Add `make e2e-serve`, using the compiled SPA and the exploration server.
- [ ] Correct the existing Makefile/README/AGENTS command mismatch while adding
      these targets.

## Phase 3: Automated Browser Smoke Test

- [ ] Add pytest configuration in `pyproject.toml` with `testpaths = ["tests"]`
      and an `e2e` marker.
- [ ] Add `tests/e2e/conftest.py` with a Uvicorn lifecycle fixture that uses
      pytest's temporary paths and the shared Memory seed function.
- [ ] Make the fixture wait for `/health` before Playwright opens the page.
- [ ] Add `tests/e2e/test_memory_smoke.py` for the first Memory Review journey.
- [ ] Add accessible labels or narrowly scoped `data-testid` attributes only
      where reliable user-facing locators are unavailable.
- [ ] Add `make test-e2e` to build the SPA and execute `pytest -m e2e`.
- [ ] Confirm that `make test-e2e` leaves no database, Vault content, log, or
      index data outside temporary test directories.

## Phase 4: Failure Diagnostics and CI

- [ ] Save Playwright traces and screenshots for failed E2E tests.
- [ ] Capture browser console errors and Uvicorn logs with the test artifacts.
- [ ] Add `test-results/e2e/` to `.gitignore`.
- [ ] Add a dedicated browser E2E GitHub Actions job.
- [ ] In that job, run `npm ci`, `npm run build`, Playwright Chromium install,
      and the E2E command from a clean checkout.
- [ ] Upload `test-results/e2e/` as an artifact only on failure.

## Phase 5: Agent Operating Contract

- [ ] Add a concise `docs/e2e-test/usage.md` explaining exploration-server and
      single-command usage for AI agents.
- [ ] Add a frontend verification requirement to `AGENTS.md`: interactively
      verify changed browser behavior when appropriate, then run
      `make test-e2e`.
- [ ] Document how agents inspect trace, screenshot, console, and server-log
      artifacts after a failure.
- [ ] Record this E2E architecture decision in `ai_wiki/10-Decisions.md` once
      the implementation is accepted.

## Later Domain Coverage

- [ ] Add research theme/job factories and a research-page journey when that UI
      needs browser regression coverage.
- [ ] Add summary factories and summary-dashboard coverage.
- [ ] Add people and project factories with relationship data only when their
      UI journeys need it.
- [ ] Add execution-log and vault-search seed data when browser coverage is
      introduced for those pages.
- [ ] Keep each added scenario small, deterministic, and tied to an explicit
      user journey.
