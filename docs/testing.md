# Testing safely

Run the suite with:

```bash
uv run pytest tests/
```

Pytest switches `MEMORY_SQLITE_PATH` to a temporary SQLite file before test
collection and to a test-specific file for each test. An autouse fixture also
redirects all writable application paths (Vault, inbox, daily notes, people,
activity, logs, task state, search index, etc.) under that test's temporary
directory. It also sets `OBSIDIAN_AI_HUB_TESTING=1`. While that flag is active,
opening the database path configured when pytest started is rejected before
SQLite can create or modify it.

## Database-writing tests

Every test is automatically given an isolated `MEMORY_SQLITE_PATH`,
`HEALTHCARE_SQLITE_PATH` and a Vault workspace under `tmp_path`. Request
`test_memory_db_path` / `test_healthcare_db_path` only when the test needs the
path for an assertion, explicit setup explanation, or fixture composition — it
is not required for isolation. Healthcare uses a separate DB
(`healthcare.sqlite3` v1, `health_imports`/`health_records`/`health_ecg` etc.)
and the same `OBSIDIAN_AI_HUB_TESTING=1` guard as memory.

Use the application APIs to seed and inspect test records.
- Keep vault, activity, research and healthcare export output under pytest's `tmp_path`.
- Execute the test through pytest. Do not manually invoke a test function or
  copy its setup into `uv run python -`; doing so bypasses pytest isolation.

## One-off verification

If a manual database experiment is unavoidable, create a new temporary
directory and set `config.MEMORY_SQLITE_PATH` (or `HEALTHCARE_SQLITE_PATH` for
healthcare) to a SQLite file inside it before calling any database API. Prefer
adding a focused pytest test instead. Never use the configured production
database for a test, reproduction, or seed data. For healthcare manual checks,
use `ENV=test` with an explicit `--healthcare-export-dir` pointing at a
temporary copy of `export.xml` (see `docs/healthcare-import/plan.md`).

## ブラウザ E2E の扱い

個人開発ではブラウザ E2E を追加・更新しない。既存の `tests/e2e/` は維持しても、
通常の検証・完了条件には含めない。フロントエンド変更後は影響した画面を手動で
確認する。

- 状態遷移、API契約、データ整合性には、必要に応じて単体テストまたは結合テストを
  追加する。フロントエンド境界でのモックを許容する。
- `make test-e2e` はユーザーが明示的に依頼した場合だけ実行する。

### 既存 E2E の保守

既存の E2E テストを明示的に実行・変更する必要が生じた場合だけ、初期データは生 SQL
ではなく `src/obsidian_ai_hub/testing/seed.py` のアプリケーション API で構築する。

各テストモジュールは `e2e_seed_scenario` フィクスチャをオーバーライドすることで、テスト実行前に必要なシナリオのみ（`memory`、`hitl`など）をシードできます。

```python
import pytest

@pytest.fixture(scope="module")
def e2e_seed_scenario() -> list[str]:
    return ["hitl"]
```

これにより、既存シナリオの安全な実行を保てる。

---

## When the safety guard fails

`Refusing to open the production memory database while tests are running`
(and `Refusing to open the production healthcare database while tests are running`)
means a test or fixture selected the database path that was configured before
pytest started. Change that code to use `test_memory_db_path` /
`test_healthcare_db_path` or `tmp_path`; do not disable the guard. Production
records found during an investigation are out of scope for test cleanup and
require explicit authorization to change. `HEALTHCARE_SQLITE_PATH` must never
equal `MEMORY_SQLITE_PATH` (separate DB, enforced in `healthcare/store.py`).

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
  （`--scan-line-inbox`, `--log-activity`）はローカル操作として対象外.
- 外部連携が必要な場合のみ、`.env.test` に `ALLOW_EXTERNAL_IN_TEST=1` を明示。

## Jules環境（クリーンクローンVM）におけるテストとセットアップ

Jules VMなどのクリーンな一時環境において、動作検証を実行するためのガイドラインです。

### 1. クリーン環境 of セットアップ

Jules VMが立ち上がった直後、および最初の動作確認を行う前に必ず以下のセットアップを実行します。
これにより、フロントエンドビルド依存関係（`npm ci`）、Python依存関係（`uv sync`）、およびPlaywrightのChromiumブラウザが準備されます。

```bash
make jules-setup
```

Jules VMの **Initial Setup** には、以下を設定して環境をスナップショット化します：

```bash
make jules-setup && ENV=test uv run pytest tests/
```

※このセットアップは、本番の `.env` や `.env.test`、ローカル上のVaultディレクトリやダウンロード済みAIモデルなどの存在を前提とせずに完結するよう設計されています。

### 2. 環境変数設定とサーバー起動のルール

- **`ENV=jules` は使用しないでください（非推奨・無効化されました）**。
- Jules VM環境においても、すべてのテストとアドホック検証は標準の `ENV=test` 隔離環境を使用します。
- 探索用サーバーなどの起動は、親プロセスの環境変数を継承せず、内部で強制的に `ENV=test` にセットされて実行されます。これにより誤って本番用データ（Vault等）や `.env` の本番設定に触れるリスクが完全に排除されます。

### 3. 通常検証

- 内部ロジックや一般機能の単体テスト検証：
  ```bash
  ENV=test uv run pytest tests/
  ```
- ブラウザ E2E は通常実行しない。ユーザーが明示的に依頼した場合のみ、
  `ENV=test make test-e2e` を実行する。
