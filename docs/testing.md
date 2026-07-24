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

Every test is automatically given an isolated `MEMORY_SQLITE_PATH` and a
Vault workspace under `tmp_path`. Request `test_memory_db_path` only when the
test needs the path for an assertion, explicit setup explanation, or fixture
composition — it is not required for isolation.

Use the application APIs to seed and inspect test records.
- Keep vault, activity, and research output under pytest's `tmp_path`.
- Execute the test through pytest. Do not manually invoke a test function or
  copy its setup into `uv run python -`; doing so bypasses pytest isolation.

## One-off verification

If a manual database experiment is unavoidable, create a new temporary
directory and set `config.MEMORY_SQLITE_PATH` to a SQLite file inside it before
calling any database API. Prefer adding a focused pytest test instead. Never
use the configured production database for a test, reproduction, or seed data.

## E2E の対象範囲とシナリオ設計

E2E は、ブラウザを通した主要なユーザーフローが壊れて操作不能になる重大な
回帰を防ぐためだけに使う。テストの追加・更新は、回帰によって主要な操作が完了
できない、ユーザーデータを失う・壊す、または認可境界を越える場合に限る。

- 追加対象は、画面の起動・遷移不能、主要なデータ変更操作の失敗、破壊的操作の
  安全性、認可・権限に関わる一連の操作など、利用者に重大な影響を与える導線。
- E2E は、操作とその結果を検証する。追加したコンポーネントや文言そのものの
  存在を検証するためには使わない。
- 静的なプリセット・選択肢、単一のUI要素、ラベルなどの文言、ステータス表示、
  スタイル、並び順だけの追加・変更にはE2Eを追加しない。コードレビューと必要な
  目視確認で十分である。
- ドメインロジックがある場合は、E2Eではなく単体テストまたは結合テストで検証する。

### E2E シナリオ分割とシード設計

E2E テストスイート（`tests/e2e/`）は、不透明な生 SQL による初期化ではなく、クリーンなアプリケーション API で構築したシナリオ（`src/obsidian_ai_hub/testing/seed.py`）を使用します。

各テストモジュールは `e2e_seed_scenario` フィクスチャをオーバーライドすることで、テスト実行前に必要なシナリオのみ（`memory`、`hitl`など）をシードできます。

```python
import pytest

@pytest.fixture(scope="module")
def e2e_seed_scenario() -> list[str]:
    return ["hitl"]
```

これにより、不要なデータのコンフリクトを回避し、E2E 実行時間を最適化しつつ安全性を担保します。

---

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
  （`--scan-line-inbox`, `--log-activity`）はローカル操作として対象外.
- 外部連携が必要な場合のみ、`.env.test` に `ALLOW_EXTERNAL_IN_TEST=1` を明示。

## Jules環境（クリーンクローンVM）におけるテストとセットアップ

Jules VMなどのクリーンな一時環境において、動作検証やE2Eテストを実行するためのガイドラインです。

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

### 3. 通常検証とE2Eテストの実行方法

- 内部ロジックや一般機能の単体テスト検証：
  ```bash
  ENV=test uv run pytest tests/
  ```
- フロントエンド変更時、およびブラウザE2Eの検証：
  ```bash
  ENV=test make test-e2e
  ```
  このコマンドは自動的に `frontend/dist` をリビルドし、一時的なSQLite、一時的なテスト用Vault、シードデータ、自動起動したloopbackサーバーを使用してテストを実行します。
