# Testing safely

Run the suite with:

```bash
uv run pytest tests/
```

Pytest switches `MEMORY_SQLITE_PATH` to a temporary SQLite file before test
collection and to a test-specific file for each test. It also sets
`OBSIDIAN_AI_HUB_TESTING=1`. While that flag is active, opening the database
path configured when pytest started is rejected before SQLite can create or
modify it.

## Database-writing tests

- Add `test_memory_db_path` to the test function arguments when it writes via
  `memory` or `obsidian_ai_hub.research.db`.
- Use that fixture path only for assertions about the database location; use
  the application APIs to seed and inspect test records.
- Keep vault, activity, and research output under pytest's `tmp_path`.
- Execute the test through pytest. Do not manually invoke a test function or
  copy its setup into `uv run python -`; doing so bypasses pytest isolation.

## One-off verification

If a manual database experiment is unavoidable, create a new temporary
directory and set `config.MEMORY_SQLITE_PATH` to a SQLite file inside it before
calling any database API. Prefer adding a focused pytest test instead. Never
use the configured production database for a test, reproduction, or seed data.

## When the safety guard fails

`Refusing to open the production memory database while tests are running`
means a test or fixture selected the database path that was configured before
pytest started. Change that code to use `test_memory_db_path` or `tmp_path`;
do not disable the guard. Production records found during an investigation are
out of scope for test cleanup and require explicit authorization to change.

## ENV=test による CLI テスト

```bash
ENV=test uv run python -m obsidian_ai_hub --merge-inbox
```

- `config/config.test.yml` を使用し、全書込み先を一時ワークスペースに隔離。
- 親プロセスから継承した API キー・トークン・パスはすべて削除。
- 本番 `.env` は読まず、`BASE_DIR/.env.test` が存在する場合のみ読み込む。
- プロセス終了後、一時データは自動削除。
- 既定では外部連携はすべてブロックされる（LLM、YouTube、LINE、Calendar、
  Open Web UI、Web 検索）。macOS の画面取得（`--screenshot`）やアクセシビリティ
  （`--scan-line-inbox`, `--log-activity`）はローカル操作として対象外。
- 外部連携が必要な場合のみ、`.env.test` に `ALLOW_EXTERNAL_IN_TEST=1` を明示。<｜end▁of▁thinking｜>
