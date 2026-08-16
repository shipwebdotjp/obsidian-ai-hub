# E2E Test Foundation TODO

## Phase 1: Safety and Shared Data

- [x] Extend the root pytest autouse fixture in `tests/conftest.py` so every
      writable configured path is under `tmp_path`, not only
      `MEMORY_SQLITE_PATH`.
- [x] Redirect at least Vault, Inbox, Daily, People, Activity, Research output,
      AI log, task state, knowledge-sync state, and Vault index paths.
- [x] Update `docs/testing.md` to state that pytest database isolation is
      automatic and that `test_memory_db_path` is needed only when the path
      itself is relevant to a test.
- [x] Add `src/obsidian_ai_hub/testing/` with a test-mode guard.
- [x] Add `factories.py` with a stable `make_memory()` builder based on the
      complete Memory Review record used in existing tests.
- [x] Add `seed.py` with a public-API-based `seed_memory_demo_data()` function.
- [x] Verify that all new factory and seed code fails outside test mode.

## Phase 2: Exploration Server

- [x] Add `obsidian_ai_hub.testing.e2e_server` as a dedicated module that sets
      `ENV=test` before importing application configuration.
- [x] Build a fresh temporary test workspace, seed the Memory demo data, and
      serve the existing FastAPI app from loopback only.
- [x] Print the test URL and workspace path at startup.
- [x] Ensure Ctrl-C stops Uvicorn and cleans up the temporary workspace.
- [x] Do not add a test-data HTTP endpoint or modify normal web API routes.
- [x] Add `make build-web`, using `npm ci && npm run build`.
- [x] Add `make e2e-serve`, using the compiled SPA and the exploration server.
- [x] Correct the existing Makefile/README/AGENTS command mismatch while adding
      these targets.

## Phase 3: Automated Browser Smoke Test

- [x] Add pytest configuration in `pyproject.toml` with `testpaths = ["tests"]`
      and an `e2e` marker.
- [x] Add `tests/e2e/conftest.py` with a Uvicorn lifecycle fixture that uses
      pytest's temporary paths and the shared Memory seed function.
- [x] Make the fixture wait for `/health` before Playwright opens the page.
- [x] Add `tests/e2e/test_memory_smoke.py` for the first Memory Review journey.
- [x] Add accessible labels or narrowly scoped `data-testid` attributes only
      where reliable user-facing locators are unavailable.
- [x] Add `make test-e2e` to build the SPA and execute `pytest -m e2e`.
- [x] Confirm that `make test-e2e` leaves no database, Vault content, log, or
      index data outside temporary test directories.

## Phase 4: Failure Diagnostics and CI

- [x] Save Playwright traces and screenshots for failed E2E tests.
- [x] Capture browser console errors and Uvicorn logs with the test artifacts.
- [x] Add `test-results/e2e/` to `.gitignore`.
- [x] Add a dedicated browser E2E GitHub Actions job.
- [x] In that job, run `npm ci`, `npm run build`, Playwright Chromium install,
      and the E2E command from a clean checkout.
- [x] Upload `test-results/e2e/` as an artifact only on failure.

## Phase 5: Agent Operating Contract

- [x] Add a concise `docs/e2e-test/usage.md` explaining exploration-server and
      single-command usage for AI agents.
- [x] Add a frontend verification requirement to `AGENTS.md`: interactively
      verify changed browser behavior when appropriate, then run
      `make test-e2e`.
- [x] Document how agents inspect trace, screenshot, console, and server-log
      artifacts after a failure.
- [x] Record this E2E architecture decision in `ai_wiki/10-Decisions-Testing.md` once
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

## Phase 7–9: Test Reduction & CI Alignment

- [x] Restructure E2E tests: split the 5 tests into 3 files of distinct scenarios (Memory, HITL Answer, HITL Cancel).
- [x] Refactor E2E conftest.py's live server fixture to accept seed scenarios parameterized via module-scoped overrides.
- [x] Relocate raw SQL database seeding for HITL into clean application-scoped functions under `src/obsidian_ai_hub/testing/seed.py`.
- [x] Create dedicated `frontend-e2e.yml` GitHub Actions workflow.
- [x] Document updated testing guidelines, post-reduction state, and usages in ADR and `docs/`.
