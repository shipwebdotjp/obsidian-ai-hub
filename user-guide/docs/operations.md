---
sidebar_position: 1
title: 運用
---

# 運用

## サーバーの起動と停止

```bash
make serve            # 起動（uv run -m obsidian_ai_hub --serve）
make serve-restart    # 8765 のプロセスを終了して再起動
make serve-debug      # 自動リロード + 詳細ログ
```

LaunchAgent として登録している場合:

```bash
make start / make stop / make restart
make reload           # plist 再読み込み（設定変更時）
make status
make logs / make errorlogs
```

## 常駐ワーカー

次のワーカーは Web サーバーの FastAPI lifespan に同居します。

- **Task worker** — Task の計画・実行。
- **Workflow worker** — ワークフロー Run の実行。
- **Agent / Coding worker** — 各実行の処理。

:::warning[サーバー停止中は処理が進みません]
Web サーバー停止中は新しい計画・実行が進まず、Task や Run はキューに残ります。
停止時に `running` だったものは `interrupted` になり、自動再実行されません。
再開後、Task は **再計画**、Run は **再開** で明示的に戻してください。
:::

HITL は別の常駐ワーカーで動かします。

```bash
make restart-hitl-worker
make logs-hitl-worker / make errorlogs-hitl-worker
```

## ジョブ実行

- job runner は LaunchAgent から 60 秒ごとに起動します。
- 手動で 1 サイクル実行するには `uv run -m obsidian_ai_hub.job_runner` を使います。
- 終了時や再起動後は、未実行のワンショットジョブが `interrupted` として扱われ、自動再試行されません。

## データの保存先

| データ | 既定の場所 |
| --- | --- |
| メモリ / Task / ワークフロー / 実行ログ | `~/.config/obsidian-ai-hub/memory.sqlite3` |
| ヘルスケア | `~/.config/obsidian-ai-hub/healthcare.sqlite3` |
| ジョブの最終実行時刻 | `jobs/last_run.json` |
| Vault 検索インデックス | `vault_index.sqlite_path` / `chroma_path` の設定値 |

## 保持期間

- 終端 Task・Plan・Event — 終端化から 30 日後に削除。
- 終端 Workflow Run・Node・Activation・Event — 30 日後に削除。
- ワンショットジョブの終端履歴 — 30 日後に削除。
- LINE webhook / 実行ログ — `--cleanup-line-webhooks` / `--cleanup-execution-logs` で 30 日より古いものを削除。

非終端のものは削除されません。

## 実行ログを見る

- **実行ログ → ログ**（`/execution-logs/logs`）— 過去 30 日の CLI 実行ログと LLM コール履歴（閲覧専用）。
- **実行ログ → ジョブ状態**（`/execution-logs/job-states`）— 定期・高頻度ジョブの最終確認・空振り・成功/スキップ/失敗。

## ネットワークとセキュリティ

- API はすべて Bearer トークン認証を要求します。ループバックでも免除されません。
- 外部公開する場合は `--serve-host` で待ち受け、TLS をリバースプロキシ等で終端してください。
- 実行ログや HITL には機密情報が含まれうるため、公開範囲に注意してください。

## テスト環境

`ENV=test` で本番データを触らずにコマンドを試せます。
テストを実行する場合は `uv run pytest tests/` を使います。
`tests/conftest.py` が本番の `.env` を読み込まず、書き込み先を一時領域へ隔離します。

## 次に読む

- [トラブルシューティング](troubleshooting.md)
- [ジョブ管理](features/jobs.md)
