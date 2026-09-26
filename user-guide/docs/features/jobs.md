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

実行対象は `command` または `workflow` のどちらか一方です（同時指定はできません）。

```yaml
- id: example
  enabled: true
  schedule:
    type: hourly
    minute: 0
  command: echo "hello"
```

公開 Workflow を起動する場合は、`command` の代わりに `workflow` を指定します。

```yaml
- id: nightly_research
  enabled: true
  schedule:
    type: daily
    hour: 7
    minute: 0
  workflow:
    workflow_id: wf_xxxxxxxx
    inputs:
      topic: "今日のテーマ"
```

- 対象は**発火時点の最新 published Revision**です。登録時の Revision には固定されません。
- `inputs` は発火時に最新公開版の `inputs_schema` で検証されます。不適合なら Run は作られず、その枠は失敗として消費されます。
- 入力は平文で設定に保存されます。**秘密値を入力に含めないでください。**
- Web UI の **ジョブ新規追加 / 編集** では「コマンド」と「公開 Workflow」を切り替えられます。公開 Workflow は published Revision を持つものだけが選択肢に出ます。

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
- 追加・再有効化・スケジュールや対象（command / workflow と入力）の変更時は、保存時刻で **arming** され、過去の枠を遡って実行しません。
- コマンドが失敗した場合、`last_run` は更新されず、後続のサイクルで再試行されます。
- Workflow の発火枠は、成功・失敗にかかわらず 1 回だけ処理されます。失敗（公開版不在・入力不整合）しても当該枠は再試行せず、次回枠で最新公開版を評価し直します。
- 発火枠の処理は `workflow_schedule_dispatches` に記録され、runner が再起動しても同じ枠で Run が二重に作られることはありません。
- 承認が必要な Workflow は、**発火のたびに** `waiting_approval` の Run を作ります。未承認の Run が残っていても次の発火は抑止されません。承認・取消は Run 詳細で行います。
- 設定の保存は一時ファイル + `os.replace` で原子的に行われます。同時編集の競合は `409 Conflict` になります。

### 今すぐ一度だけ実行する

定期ジョブの行にある **今すぐ実行** を押すと、そのジョブをスケジュールとは別に一度だけ実行します。

- 実行対象は保存されている現行の command / Workflow と入力のコピーです。押した後にジョブを編集・削除しても、登録済みの実行内容は変わりません。
- 無効化中（有効チェックが外れた状態）のジョブでも実行できます。
- **次回予定枠は変更されません**。手動実行後も通常どおり次のスケジュール枠で実行されます。
- 登録は「ワンショット実行ジョブ」として保存され、通常は数秒以内、runner が別の実行中の場合は最大約 1 分後に開始します。進捗と結果は **ワンショット実行ジョブ** タブで確認できます。
- 同じジョブの手動実行が未開始・実行中の間は、ボタンが **実行中** になり登録できません。完了・失敗・取消のあとに再実行できます。
- Workflow の場合、承認が必要なものは Run が `waiting_approval` で作成されます。承認するまで実行されません。
- 登録元の列には「手動（定期: `<ジョブID>`）」と表示されます。

## ワンショット実行ジョブ

ワンショットジョブは Agent の `register_one_shot_job`（コマンド）または `register_one_shot_workflow_job`（公開 Workflow）ツールで登録され、専用の SQLite キューに保存されます。
次の runner サイクルが各ジョブを一度だけ処理します（at-most-once、中断後の自動再試行なし）。

タブの **ワンショット実行ジョブ** では、予定時刻・状態・登録元・対象・Run を確認し、
`queued` のものだけ **取消** できます。終端履歴は 30 日保持されます。

- **Workflow を予約** から、公開 Workflow と固定入力・実行予定日時を指定して手動登録できます。
- Workflow 対象の成功時は状態が `dispatched` になります。これは Run の作成成功を表し、Workflow 本体の完了・失敗は Run 詳細で確認します。dispatch 後の取消は Run 詳細から行います。
- 公開版不在・入力不整合の場合は状態 `failed` と理由が残ります。

## Workflow の発火と承認

- 対象 Workflow は発火のたびに最新の published Revision を使います。すでに `waiting_approval` の Run は作成時のスナップショットを維持します。
- 承認が必要な Workflow（`plan_required` Capability または Agent Node を含む）は、承認するまで Capability を実行しません。
- Web サーバー（Workflow worker）が停止していると、作成済みの Run は `queued` のまま進みません。

## Agent 所有の定期実行ジョブ

Agent が `register_recurring_job` ツールで登録した定期ジョブは、`agent_source`（agent / session / run ID と UTC 登録時刻）で所有元を記録します。

- 所有 Agent だけが `set_recurring_job_enabled` で有効 / 無効を切り替えられます。
- 人間が `/jobs` で ID・対象（コマンド / Workflow と入力）・スケジュール・enabled を変更すると、所有権（`agent_source`）が削除され、人間管理へ移ります。
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
