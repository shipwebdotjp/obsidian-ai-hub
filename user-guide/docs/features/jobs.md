---
sidebar_position: 7
title: ジョブ管理
---

# ジョブ管理

**ジョブ管理** 画面（`/jobs`）では、定期実行ジョブとワンショット実行ジョブを扱います。
画面上部に **設定ファイル** のパスが表示されます。

## 定期実行ジョブ

ジョブは `jobs/jobs.local.yml` に定義します（無い場合は `jobs/jobs.yml` にフォールバック）。
Web UI の **ジョブ新規追加** / **編集** / **削除** からも管理できます。

`jobs/jobs.local.sample.yml` をコピーして `jobs/jobs.local.yml` を作るのが出発点です。

### ジョブの形

```yaml
- id: example
  enabled: true
  schedule:
    type: hourly
    minute: 0
  command: echo "hello"
```

### スケジュール

`schedule.type` は `minutely` / `hourly` / `daily` / `weekly` / `monthly` に対応します。

| type | フィールド（既定） |
| --- | --- |
| `minutely` | `second`（0） |
| `hourly` | `second`（0）、`minute`（0） |
| `daily` | `second`、`minute`、`hour`（0） |
| `weekly` | `second`、`minute`、`hour`、`weekday`（`*`、月=0） |
| `monthly` | `second`、`minute`、`hour`、`day`（1） |

フィールドの書き方: 単一の数値、リスト、カンマ区切り文字列、範囲（`8-18`）、ステップ（`*/15`、`8-18/2`）、`*`。

### コマンド実行の規則

コマンドはシェルを介さず、`&&` で区切って `shlex` でトークン化して実行されます。

- `cd /path && ...` のようにディレクトリ移動をつなげられます。
- パイプ・リダイレクト・環境変数展開などのシェル演算子は解釈されません。

Web UI のジョブ編集では **標準モード（プリセット）** と **詳細モード（任意コマンド）** を選べます。
詳細モードでは、バックエンドの構文解析プレビュー（`cd:` / `args:`）が表示され、解釈違いを防げます。
コメントは構造化保存では保持されません。

### 実行の仕組み

- job runner は `jobs/last_run.json` に最終実行時刻を保存し、一致する枠を 1 回だけ実行します。
- LaunchAgent は 60 秒ごとに起動するため、「即時」の実行も通常は ~1 分以内です。
- 追加・再有効化・スケジュールやコマンドの変更時は、保存時刻で **arming** され、過去の枠を遡って実行しません。
- コマンドが失敗した場合、`last_run` は更新されず、後続のサイクルで再試行されます。
- 設定の保存は一時ファイル + `os.replace` で原子的に行われます。同時編集の競合は `409 Conflict` になります。

## ワンショット実行ジョブ

ワンショットジョブは Agent の `register_one_shot_job` ツールで登録され、専用の SQLite キューに保存されます。
**Web UI からの手動登録はありません。** 次の runner サイクルが各ジョブを一度だけ実行します（at-most-once、中断後の自動再試行なし）。

タブの **ワンショット実行ジョブ** では、予定時刻・状態・登録元・コマンド・終了コードを確認し、
`queued` のものだけ **取消** できます。終端履歴は 30 日保持されます。

## Agent 所有の定期実行ジョブ

Agent が `register_recurring_job` ツールで登録した定期ジョブは、`agent_source`（agent / session / run ID と UTC 登録時刻）で所有元を記録します。

- 所有 Agent だけが `set_recurring_job_enabled` で有効 / 無効を切り替えられます。
- 人間が `/jobs` で ID・コマンド・スケジュール・enabled を変更すると、所有権（`agent_source`）が削除され、人間管理へ移ります。
- Task Agent は登録はできますが、有効 / 無効の切り替えツールは付与されません（停止・変更は人間が `/jobs` で行います）。

## 旧 `tasks/` からの移行

`tasks/` ファイルが残っていると runner は起動を拒否します。次の一度きりのコマンドで移行します。

```bash
uv run -m obsidian_ai_hub.job_runner --migrate-tasks-to-jobs
```

`tasks/tasks.local.yml`（または `tasks.yml`）を `jobs/jobs.local.yml` へ移し、`last_run.json` の状態をコピーし、旧ファイルを削除します。
Web UI は `/tasks` から `/jobs`、API は `/api/v1/task-config` から `/api/v1/scheduler-jobs` へ移動済みで、旧 URL は 404 を返します。

## 参考ジョブ

- **Inbox をほぼリアルタイムに処理** — `merge_inbox` を `type: minutely`、`second: 0` で登録します。
- **日曜夜の週次レビュー下書き** — `review_draft_sunday_evening` の例をプロジェクトパスに合わせて有効化します。週次ノートに空の `result::` 行が必要です。

## 実行状態を確認する

- **実行ログ → ジョブ状態**（`/execution-logs/job-states`）で、定期・高頻度ジョブの最終確認、空振り回数、成功 / スキップ / 失敗を確認できます。
- job runner のログは `make logs` / `make errorlogs` で確認できます。

## 次に読む

- [リファレンス: ジョブのスケジュール](../reference/job-schedules.md)
- [運用](../operations.md)
