# AGENTS.md

## Project knowledge

- Before work that relies on prior product or architecture decisions, read
  [ai_wiki/00-Index.md](ai_wiki/00-Index.md).
- Record durable implementation decisions, including their context and
  rationale, in [ai_wiki/10-Decisions.md](ai_wiki/10-Decisions.md). Use
  [ai_wiki/20-Worklog.md](ai_wiki/20-Worklog.md) only for temporary progress
  notes and handoffs.

## Project conventions

- Keep modules directly under `src/obsidian_ai_hub/` as thin CLI-facing
  wrappers; put application logic in the appropriate subpackage.
- Do not mask unexpected failures with defensive exception handling.

## Test data safety

- Read [docs/testing.md](docs/testing.md) before work that can write data.
- Run database-writing tests through `uv run pytest tests/`. Pytest redirects
  writable application paths and protects the production memory database.
- Never use the configured production database for ad-hoc checks, test setup,
  or seed data. Use a new temporary SQLite path before calling database APIs.
- Do not alter production data found during an investigation without explicit
  authorization.

## Frontend changes

- When changing the frontend, verify the affected path against the seeded E2E
  server and add coverage for important user flows in `tests/e2e/`.
- Complete frontend work by running `make test-e2e`. Its diagnostic artifacts
  are written to `test-results/e2e/` on failure.
