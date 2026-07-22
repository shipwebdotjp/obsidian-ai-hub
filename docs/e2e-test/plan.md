# E2E Test Foundation Plan

## Goal

Enable an AI agent to verify frontend changes against a real browser without
accessing production data or external services. The foundation has two modes
that share the same factories, seed data, and safety rules:

| Mode | Purpose | Primary user |
| --- | --- | --- |
| Exploration server | Freely inspect and operate a seeded UI while developing or investigating a change. | AI agent and developer |
| Single-command E2E suite | Run representative browser journeys deterministically to prevent regressions. | AI agent and CI |

The exploration server validates that a particular new interaction works. The
E2E suite retains the important interactions discovered during exploration as
repeatable regression tests.

## Existing Foundation

- Pytest already assigns a unique temporary `MEMORY_SQLITE_PATH` to every test
  in `tests/conftest.py` and refuses to open the initially configured
  production database while pytest is running.
- `ENV=test` creates an isolated temporary workspace, removes application
  credentials, and blocks external integrations by default. See
  `src/obsidian_ai_hub/utils/config.py` and `docs/testing.md`.
- Python Playwright is already a development dependency, Chromium is installed
  in CI, and a legacy HTML browser test exists.
- The React SPA is served by FastAPI from `frontend/dist`. A clean CI checkout
  must build the frontend before it can exercise this route.

## Decisions

### Use Python Playwright

Continue using Python Playwright with pytest. Do not introduce a second
Playwright stack through Node `@playwright/test`; Python Playwright is already
installed and used by the repository.

### Do not commit a test database

Each run creates a disposable SQLite database. A checked-in `test.db` risks
stale schemas, state leakage, and accidental reuse outside test mode.

### Use one source of demo data

Factories and seed functions must be shared by exploration and automated E2E
tests. Normal seed data goes through application persistence APIs rather than
raw SQL so it has the same representation as production records. Raw SQL stays
limited to migration, constraint, and relationship-edge-case tests.

### Keep test setup out of HTTP APIs

Do not add an endpoint that creates test data. The exploration launcher seeds
the database before serving the app. This keeps test-only mutation capability
out of the web API.

### Serve the production-like build

E2E uses the compiled `frontend/dist` served by FastAPI, not Vite's development
server. This validates static asset delivery, SPA fallback, React startup, and
same-origin API requests in one flow.

### Separate direct exploration from deterministic execution

The exploration launcher owns one `ENV=test` process, creates and seeds its
workspace before starting Uvicorn, and remains available until interrupted.
Restarting it resets all mutated data.

The pytest suite starts Uvicorn inside its test fixture, with pytest's temporary
paths and test database. Both modes call the same factory and seed functions,
but the suite does not depend on a manually running exploration server.

`ENV=test` cannot be used by one process to seed data and another independent
process to serve it: each process receives a separate temporary workspace.

## Planned Layout

```text
src/obsidian_ai_hub/testing/
  factories.py       # Stable dict builders: make_memory(), ...
  seed.py            # seed_demo_data() and domain-specific seed functions
  e2e_server.py      # Sets ENV=test, seeds data, and launches Uvicorn

tests/
  conftest.py         # Per-test database and full filesystem sandbox
  e2e/
    conftest.py       # Live Uvicorn, browser, and artifact fixtures
    test_memory_smoke.py

docs/e2e-test/
  plan.md
  TODO.md
```

The `obsidian_ai_hub.testing` package is test support code. Its entry points
must fail unless test mode is active, and must not be imported by normal
application startup.

## Data Contract

Factories use explicit, stable values. They must not generate timestamps or IDs
from the current time unless a test explicitly needs to cover such behavior.

The initial `demo` dataset covers the Memory Review UI:

- Candidate memories for review and approval actions.
- An approved memory and a rejected memory for status filtering.
- A memory with evidence for the detail panel.
- Distinct content, topic, kind, tag, and fixed date values for search and
  filter assertions.

Expand `demo` data only when an E2E test needs another domain. Planned future
domains are research themes/jobs, summaries, people, projects, execution logs,
and vault-search Markdown files. Avoid a large fixture that no test uses.

## Planned Commands

These commands describe the target interface; they do not exist yet.

```bash
# Build the SPA deterministically.
make build-web

# Start an isolated, seeded server for Playwright CLI exploration.
make e2e-serve

# Build the SPA and execute browser E2E tests from scratch.
make test-e2e
```

`make e2e-serve` will report its loopback URL and its temporary workspace path.
The default URL should be a documented fixed loopback address such as
`http://127.0.0.1:8766`. It uses `ENV=test`, blocks external services, and
destroys the workspace after the server stops.

An AI agent can then use Playwright CLI against the displayed URL. The server
must not be bound to a non-loopback address and must not require an API token.

`make test-e2e` will perform the equivalent of:

```bash
cd frontend && npm ci && npm run build
uv run pytest -m e2e
```

The final Make target may implement this without exposing the underlying shell
steps, but it must be deterministic and safe to run repeatedly.

## First Browser Journey

The first E2E case is intentionally narrow and covers the Memory Review page:

1. Start from the seeded test database and open `/` in Chromium.
2. Confirm that React redirects to `/memories` and displays the `メモリ` heading.
3. Confirm a seeded candidate appears in the list.
4. Open the candidate and confirm its seeded detail content.
5. Approve the candidate through the UI.
6. Confirm it leaves the candidate list.
7. Switch to approved status and confirm the same memory appears there.
8. Open `/memories` directly to verify FastAPI's SPA fallback.

Use role/name locators for headings, links, and buttons. Add an accessible name
or a narrow `data-testid` only where a repeated row or control cannot otherwise
be located reliably. Do not couple tests to Tailwind classes or DOM hierarchy.

## Test Runtime and Artifacts

The live-server pytest fixture must:

- Verify that `frontend/dist` exists before starting the browser.
- Seed the database before Uvicorn begins serving requests.
- Bind only to loopback and wait for `/health` before opening Chromium.
- Always stop Uvicorn and Chromium, including after assertion failures.
- Capture browser trace, screenshot, console errors, and server logs on test
  failure.

Artifacts are written below `test-results/e2e/`, ignored by Git, and uploaded
by CI only when the E2E job fails.

## CI and Agent Workflow

The existing fast Python test job remains independent of browser build work.
Add a browser E2E job that installs Python dependencies, runs `npm ci`, builds
the frontend, installs Chromium, and runs `make test-e2e` or its underlying
pytest command.

For every frontend behavior change, the expected agent workflow is:

1. Start `make e2e-serve` when interactive verification is needed.
2. Use Playwright to exercise the changed user journey and inspect browser
   console/network failures when relevant.
3. Add or update a deterministic E2E case if the journey is important to retain.
4. Run `make test-e2e` before considering the frontend change complete.

Authentication against a remote, token-protected host is outside the first
browser smoke scope. Loopback browser flows need no token, and existing API
tests already cover the remote bearer-token rules.
