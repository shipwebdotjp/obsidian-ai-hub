# AGENTS.md

## Project knowledge

- Before work that relies on prior product or architecture decisions, read
  [ai_wiki/00-Index.md](ai_wiki/00-Index.md).
- Create or update a decision record (ADR) only for decisions with a high
  cost of revisiting them; importance alone is not a criterion. An ADR is a
  candidate when it satisfies at least two of the following:
  - **Difficulty of change:** changing it later would require data migration,
    broad modifications, or materially affect users.
  - **Cross-cutting impact:** it affects multiple modules, agents, or teams.
  - **Alternatives:** realistic options were compared.
  - **Need to re-explain:** code alone would not convey why the choice was
    made.
  - **External constraints:** security, personal data, cost, contracts, or
    API constraints apply.
  - **Likely recurring disagreement:** the same discussion is likely to recur.
- For an ADR candidate, record the context and rationale in the relevant
  decision record listed in [ai_wiki/00-Index.md](ai_wiki/00-Index.md). Use
  [ai_wiki/20-Worklog.md](ai_wiki/20-Worklog.md) only for temporary progress
  notes and handoffs.

## Project conventions

- Keep modules directly under `src/obsidian_ai_hub/` as thin CLI-facing
  wrappers; put application logic in the appropriate subpackage.
- Do not mask unexpected failures with defensive exception handling.

## Test data safety

- Read [docs/testing.md](docs/testing.md) before work that can write data.
- Run database-writing tests through `uv run pytest tests/`; it redirects
  writable application paths and protects the production memory database.
- Never use the configured production database for ad-hoc checks, test setup,
  or seed data. Use a new temporary SQLite path before calling database APIs.
- Do not alter production data found during an investigation without explicit
  authorization.

## Frontend changes

- Do not add or update browser E2E tests in `tests/e2e/`, or run
  `make test-e2e` as routine validation. Existing E2E tests are not a completion
  criterion unless the user explicitly requests their use.
- Verify affected screens manually. Add focused frontend unit tests or backend
  integration tests when they usefully cover behavior; mocks are acceptable at
  the frontend boundary.

## Code review (ocr)

- Never let `ocr review` stream to the terminal. Capture its full output from
  the first run, then read the file:
  ```bash
  ocr review --audience agent -b "..." > /tmp/ocr_review.txt 2>&1
  ```

## Jules clean-clone & test environments

- Jules runs in a clean-clone virtual machine where neither `.env`, local databases, nor `.env.test` exist.
- Before executing tests in a clean environment, run `make jules-setup`.
- Use `ENV=test`, never `ENV=jules`, for automated tests and exploration.
- `tests/conftest.py` enforces test isolation for `uv run pytest tests/` by
  removing application secrets and preventing production `.env` loading.
