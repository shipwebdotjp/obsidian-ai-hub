---
sidebar_position: 1
title: CLI リファレンス
---

# CLI リファレンス

すべてのコマンドは次の形で実行します。

```bash
uv run -m obsidian_ai_hub <flag> [options]
# または
python -m obsidian_ai_hub <flag> [options]
```

引数なしで実行するとヘルプが表示されます。

## サーバー

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--serve` | — | Web UI（FastAPI + React）を起動する。 |
| `--serve-host` | 文字列 | 待ち受けアドレス。既定 `OBSIDIAN_AI_HUB_HOST` → `127.0.0.1`。 |
| `--serve-port` | 整数 | 待ち受けポート。既定 `OBSIDIAN_AI_HUB_PORT` → `8765`。 |
| `--debug` | — | 開発用。`--serve` 併用で自動リロード + 詳細ログ。 |

## デイリーノート

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--merge-inbox` | — | Inbox をデイリーノートへ取り込む。 |
| `--make-target` | — | 今日の目標を生成して書き込む。 |
| `--write-today-schedule` | — | カレンダー / リマインダーの予定を今日のノートへ書き出す。 |

## サマリ・レビュー

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--summerize-day` | — | 日次サマリを生成する。 |
| `--day-date` | `YYYY-MM-DD` | `--summerize-day` の対象日。 |
| `--summerize-week` | — | 週次サマリを生成する。 |
| `--week-date` | `YYYY-MM-DD` | `--summerize-week` の対象週の任意の日。 |
| `--summerize-month` | — | 月次サマリを生成する（既定は前月）。 |
| `--month` | `YYYY-MM` | `--summerize-month` の対象月。 |
| `--review-draft` | — | 週次ノートへレビュー下書きを保存し LINE 通知する。 |
| `--review-week-date` | `YYYY-MM-DD` | `--review-draft` の対象週。 |

## 予定・通知

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--notify-today-schedule` | — | 今日の予定を LINE へ通知する。 |
| `--generate-planner-proposals` | — | AI プランナー提案を生成して保存・通知する。 |

## バックアップ・同期

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--backup` | — | 指定フォルダを rsync でバックアップする。 |
| `--sync-vault` | — | Vault を md-hybrid-search インデックスへ同期する。 |
| `--rebuild-vault` | — | Vault インデックスを完全に再構築する。 |
| `--sync-knowledge` | — | Vault を Open WebUI のナレッジベースへ同期する。 |
| `--sync-people` | — | 人物候補・重複を正規レコードへ統合する。 |

## リサーチ

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--research-agent` | — | テーマを即時リサーチして保存する。`--theme` が必須。 |
| `--add-research-theme` | — | リサーチ候補テーマに追加する。 |
| `--suggest-research-theme` | — | Task Agent にテーマ提案を投入する。 |
| `--theme` | 文字列 | `--research-agent` / `--add-research-theme` のテーマ。 |
| `--direction` | 文字列 | `--add-research-theme` の調査方向（任意）。 |
| `--context` | 文字列 | `--research-agent` の補足文脈。 |
| `--output-style` | `short` / `medium` / `long` | `--research-agent` の出力長。 |
| `--research-mode` | `auto` / `internal` / `web` / `deep` / `project` | 調査モード（既定 auto）。`project` は `--project-id` が必要。 |
| `--project-id` | 整数 | `--coding` の新規セッション、または `--research-agent --research-mode project` の対象プロジェクト。 |

`--research-agent` / `--add-research-theme` / `--suggest-research-theme` は相互に排他的です。

## メモリ

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--memory-extract` | — | 週次ノートから長期メモリ候補を抽出する。 |
| `--week` | `YYYY-MM-DD` | `--memory-extract` の対象週。 |
| `--memory-interview` | — | インタビュー質問を生成して HITL に登録する。 |
| `--memory-interview-week` | `YYYY-MM-DD` | `--memory-interview` の対象週。 |
| `--memory-review` | — | 候補をレビューする。`--id` と `--approve` / `--reject` / `--edit` のいずれかが必須。 |
| `--id` | 文字列 | 対象メモリ ID。 |
| `--approve` / `--reject` | — | 承認 / 却下。 |
| `--edit` | — | 編集して承認する。`--content` が必要。 |
| `--content` | 文字列 | `--edit` の新しい本文。 |
| `--memory-delete` | — | メモリを完全削除する。`--id` が必要。`--yes` で確認を省略。 |
| `--yes` | — | 削除の確認プロンプトを省略する。 |
| `--memory-compile` | — | コンパイルされるメモリ文脈を確認する。`--for` が必要。 |
| `--for` | 文字列 | `--memory-compile` の用途（例 `make-target`）。 |
| `--render-copilot-profile` | — | Copilot プロファイル（7 ファイル）を生成・上書きする。 |
| `--memory-maintain` | — | 承認済みメモリのメンテナンスを手動実行する。 |

## ヘルスケア

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--import-apple-health` | — | Apple Health エクスポートを取り込む。 |
| `--healthcare-export-dir` | パス | エクスポートディレクトリ。 |
| `--healthcare-batch-size` | 整数 | コミットのバッチサイズ。 |
| `--healthcare-dry-run` | — | 書き込まずに件数だけ数える。 |

`--healthcare-*` は `--import-apple-health` と併用します。

## キャプチャ・活動・検索

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--screenshot` | — | macOS の画面をキャプチャして Inbox へ保存する。 |
| `--display` | 整数 | `--screenshot` のディスプレイ番号（既定 1）。 |
| `--scan-line-inbox` | — | 最前面の LINE から未読候補を抽出する。 |
| `--log-activity` | — | 活動ログを記録する。 |
| `--vault-search` | — | Vault を検索する。`--query` が必須。 |
| `--query` | 文字列 | 検索クエリ。 |
| `--k` | 整数 | 結果件数（既定 10）。 |
| `--search-mode` | `similarity` / `keyword` / `hybrid` | 検索モード（既定 hybrid）。 |
| `--json` | — | JSON で出力する（`--vault-search` / `--coding`）。 |

## クリーンアップ

| フラグ | 説明 |
| --- | --- |
| `--cleanup-line-webhooks` | 30 日より古い LINE webhook を削除する。 |
| `--cleanup-execution-logs` | 30 日より古い実行ログを削除する。 |

## エージェント・コーディング

| フラグ | 引数 | 説明 |
| --- | --- | --- |
| `--agent-chat` | — | 既存 AI エージェントへ 1 ターンのメッセージを送る。`--agent-id` が必須。 |
| `--agent-id` | 文字列 | 対象エージェント ID。 |
| `--agent-prompt` | 文字列 | メッセージ本文。省略時は stdin を使用。 |
| `--resume-session` | 文字列 | 再開するセッション ID。 |
| `--agent-output` | `text` / `json` | `--agent-chat` の出力形式。 |
| `--coding` | — | コーディングを単発実行する。 |
| `prompt` | 位置引数 | コーディングのプロンプト。 |
| `--task-agent` | 文字列 | 自由文の依頼を Task Agent に投入する。 |

## 承認待ち（HITL）

| フラグ | 説明 |
| --- | --- |
| `--hitl-dispatch` | HITL を 1 回スキャンして処理する（手動復旧用）。 |
| `--hitl-worker` | 常駐 HITL ワーカーを起動する。 |

## テストモード

```bash
ENV=test uv run python -m obsidian_ai_hub --merge-inbox
```

## 次に読む

- [ジョブのスケジュール](job-schedules.md)
- [Web UI マップ](web-ui-map.md)
