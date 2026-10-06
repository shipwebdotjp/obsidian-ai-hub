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
  decision record listed in [ai_wiki/00-Index.md](ai_wiki/00-Index.md). Do not
  keep temporary progress notes or handoffs as repository documents; rely on
  Git history.

## Project conventions

- Keep modules directly under `src/obsidian_ai_hub/` as thin CLI-facing
  wrappers; put application logic in the appropriate subpackage.
- Do not mask unexpected failures with defensive exception handling.

## Documentation

- `README.md` stays as a project overview. Do not add detailed usage,
  command references, or configuration details to it; link to the user
  guide (https://aihub.shipweb.jp) instead.
- When adding a user-facing feature or changing existing user-visible
  behavior (CLI flags, Web UI screens, configuration keys, workflows),
  update `user-guide/docs/` accordingly and remove any duplicated detail
  from `README.md`. If the guide lacks a place for required information,
  add it to the guide first, then trim the README.

## Irreversible-change quality gate

- Before designing or implementing a change that deletes data, writes or sends
  data outside the application, or changes an authorization boundary, read
  [docs/development-quality-playbook.md](docs/development-quality-playbook.md).
- Record its operation-scenario contract in the feature specification or
  implementation plan. Implement a focused, isolated end-to-end backend
  scenario for that contract before considering the change complete.
- Give `ocr review` the scenario, irreversible operation, identity/schema
  boundary, and failure/stop behavior as background. OCR supports review; it
  does not replace the scenario test or a human check of the contract.

## Test data safety

- Read [docs/testing.md](docs/testing.md) before work that can write data.
- Run database-writing tests through `uv run pytest tests/`; it redirects
  writable application paths and protects the production memory database.
- Never use the configured production database for ad-hoc checks, test setup,
  or seed data. Use a new temporary SQLite path before calling database APIs.
- Do not alter production data found during an investigation without explicit
  authorization.

## Tests

- Do not add tests that assert prompt, message, or UI wording. Wording changes
  frequently and such tests create false failures; test behavior and contracts
  instead.

## Frontend changes

- Do not add or update browser E2E tests in `tests/e2e/`, or run
  `make test-e2e` as routine validation. Existing E2E tests are not a completion
  criterion unless the user explicitly requests their use.
- Verify affected screens manually. Add focused frontend unit tests or backend
  integration tests when they usefully cover behavior; mocks are acceptable at
  the frontend boundary.

## Code review (ocr) and commit

- Never let `ocr review` stream to the terminal. Capture its full output
  from the first run, then read the file:
  ```bash
  ocr review --audience agent -b "..." > /tmp/ocr_review.txt 2>&1
  ```
- When invoking OCR through OpenCode's shell/bash tool, explicitly set
  the tool-call `timeout` to 1800000 milliseconds (30 minutes).
  This is a tool argument, not a CLI flag or shell environment variable.
  Do not rely on the tool's default timeout.
- Run OCR and read its output in separate tool calls. After OCR finishes,
  inspect the captured file and the command's exit status.
- If the shell/bash tool times out, treat that OCR run as incomplete,
  not as a successful review with no findings. Inspect the captured output
  before deciding whether to retry. Count the interrupted invocation
  toward the maximum of three OCR review runs.

## Check the operation
- Please perform operational checks using the actual database; it is acceptable if side effects occur. After modifying the code, restart the LaunchAgent services with `make restart` (job_runner + Web サーバー + hitl-worker). 初回のみ `make install-all` で LaunchAgent を登録しておくこと。
- `make serve` / `make serve-restart` はフォアグラウンドの開発用サーバーで、人間の端末専用。エージェントのシェルからはプロセスが残らないため使わない。Web サーバーだけを再起動する場合は `make restart-web`、状態確認は `make status-web` のみ使う。
- `make logs-web` / `make errorlogs-web`（および `logs` / `errorlogs`）は `tail -f` のためエージェントのシェルからは使わない。ログは次で読む（巨大行対策に `cut -c1-500` を併用可）。
  ```bash
  tail -c 4000 /tmp/obsidian_web.log
  grep -n "Uvicorn running\|ERROR\|Traceback" /tmp/obsidian_web.err | tail -5
  ```
- 起動待ちは `sleep` 固定や `/dev/tcp`（zsh 非対応）を使わず、`scripts/opcheck_wait_ready.sh <port>`（`/health` ポーリング）を使う。本番 `make restart` 直後はモデル読み込みで数分応答がないのが正常。
- エージェントのシェルは zsh である。Python 実行は必ず `uv run python` を使う。GNU 式 `ls --time-style` は使えない（`stat -f` を使う）。引用符なしの `echo ===` は書かない（zsh の `=cmd` 展開で失敗するため。区切り線は `echo "--- ..."` と引用する）。
- Before finishing, stop any foreground server you started (do not leave `make serve` or a multiplexer session running); the LaunchAgent keeps the service up across runs.
- Clean up any test data you create during operational checks before finishing, including dependent records. Use an identifying name prefix such as `__opcheck_`, report the deleted IDs/counts, and verify nothing remains. Never delete user data.
- Prefer the isolated sandbox for workflow/agent checks: `make opcheck-start` runs a second instance on
  127.0.0.1:8767 with its own DB/Vault/index under `.opcheck/` (workers enabled, real LLM credentials
  from `.env`). It backgrounds the server, saves the PID to `.opcheck/server.pid`, and waits for
  `/health` before returning. Stop it with `make opcheck-stop` (verifies the PID before signalling).
  `make opcheck-serve` is the foreground variant for human terminals. Source `.opcheck/env.sh` before running CLI commands (they read config directly, not
  over HTTP). Drive runs with `--workflow-run --execute`. See [docs/testing.md](docs/testing.md#隔離サンドボックスmake-opcheck-serve).
- http://127.0.0.1:8765
- Production DB Path: ~/.config/obsidian-ai-hub/memory.sqlite3

## Jules clean-clone & test environments

- Jules runs in a clean-clone virtual machine where neither `.env`, local databases, nor `.env.test` exist.
- Before executing tests in a clean environment, run `make jules-setup`.
- Use `ENV=test`, never `ENV=jules`, for automated tests and exploration.
- `tests/conftest.py` enforces test isolation for `uv run pytest tests/` by
  removing application secrets and preventing production `.env` loading.
