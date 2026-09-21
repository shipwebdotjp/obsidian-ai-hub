---
sidebar_position: 1
title: CLI の基本
---

# CLI の基本

CLI は 1 回限りの処理を実行する入口です。実行結果は実行ログ（`/execution-logs/logs`）にも記録されます。

## 呼び出し方

```bash
uv run -m obsidian_ai_hub --merge-inbox
```

引数なしで実行するとヘルプが表示されます。

```bash
uv run -m obsidian_ai_hub
```

## テストモードで安全に試す

データを書き込む操作を試すときは `ENV=test` を付けます。
本番の設定・秘密情報・データベースを使わず、一時ディレクトリへ隔離されます。

```bash
ENV=test uv run python -m obsidian_ai_hub --merge-inbox
```

テストモードの主な特性:

- 設定は `config/config.test.yml` を使用する。
- 本番の `.env` を読み込まず、アプリの秘密情報環境変数を取り除く。
- 書き込み先（メモリ DB、ヘルスケア DB、Vault インデックス、`last_run.json` など）を一時ワークスペースへリダイレクトする。
- ジョブは `jobs/jobs.test.yml` のみを読む。
- LLM や外部サービスへの接続は既定でブロックされる（`.env.test` の `ALLOW_EXTERNAL_IN_TEST=1` で許可可能）。

## コマンドのカテゴリ

代表的なコマンドだけを挙げます。全一覧は [CLI リファレンス](../reference/cli.md) を参照してください。

| カテゴリ | 例 |
| --- | --- |
| デイリーノート | `--merge-inbox`、`--make-target`、`--write-today-schedule` |
| サマリ | `--summerize-day`、`--summerize-week`、`--summerize-month`、`--review-draft` |
| 予定・提案 | `--notify-today-schedule`、`--generate-planner-proposals` |
| バックアップ・同期 | `--backup`、`--sync-vault`、`--sync-knowledge`、`--sync-people`、`--rebuild-vault` |
| リサーチ | `--research-agent`、`--add-research-theme`、`--suggest-research-theme` |
| メモリ | `--memory-extract`、`--memory-review`、`--memory-compile`、`--render-copilot-profile` |
| ヘルスケア | `--import-apple-health` |
| キャプチャ・活動 | `--screenshot`、`--scan-line-inbox`、`--log-activity` |
| Vault 検索 | `--vault-search` |
| クリーンアップ | `--cleanup-line-webhooks`、`--cleanup-execution-logs` |
| エージェント | `--agent-chat`、`--coding`、`--task-agent` |
| 承認待ち | `--hitl-dispatch`、`--hitl-worker` |
| サーバー | `--serve` |

:::note[スペルについて]
サマリ系のフラグは `--summerize-*`（`summerize`）という綴りで定義されています。
`--summarize-*` ではない点に注意してください。
:::

## 次のページ

- [Inbox とデイリーノート](inbox-and-daily-note.md)
- [サマリ](summaries.md)
- [予定・目標・バックアップ](schedule-target-backup.md)
