# アーキテクチャ決定記録

## テスト環境隔離 (ENV=test)

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-18 |
| カテゴリ | テスト環境隔離 |
| 決定内容 | `ENV=test` 環境変数による完全隔離テストモードを導入する |

### 結論に至った経緯

既存の pytest によるテストは conftest.py の機構でデータベースアクセスを隔離しているが、CLI
コマンドを直接 `uv run python -m ...` で実行するアドホックテストが本番データや外部サービスに
アクセスするリスクがあった。本番環境変数や API キーを継承したままテスト実行されるのを防ぐ
仕組みが必要。

### 仕組みの概要

1. `ENV=test` が設定されている場合、config.py のモジュール読込時に全アプリ固有の環境変数を
   `os.environ` から削除する。
2. `.env`（本番）は読まず、`.env.test` が存在すればそれを読む（pytest 実行時は
   `OAIHUB_SKIP_DOTENV=1` によりスキップ）。
3. 全書き込み先（VAULT_PATH, MEMORY_SQLITE_PATH, AI_LOG_PATH, その他）を
   `tempfile.TemporaryDirectory` が作成する一時ワークスペース配下に設定する。
4. `ensure_external_allowed()` 関数で外部アクセス（LLM API, LINE, YouTube, Calendar,
   Reminders, Web 検索, Open Web UI）をブロック。`ALLOW_EXTERNAL_IN_TEST=1` でのみ許可。
5. `config/config.test.yml` を設定ファイルとして使用。
6. `tasks/tasks.test.yml`（空リスト）をタスク定義として使用。
