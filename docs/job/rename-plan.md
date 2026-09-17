# Scheduler Task から Job への完全移行計画

## 目的と完了条件

Task Agent の **Task**（自由文依頼、Plan、Event を持つ集約）と、Scheduler の
**Job**（指定時刻にコマンドを起動する定義）を完全に分離する。定期実行と
ワンショット実行は、ともに Scheduler Job とする。

完了時には scheduler 領域の実行コード、設定、状態DB、Web API、画面、CLI/launchd、
テスト、利用者向け文書で `task` / `Task` を使わない。Task Agent の `Task` 関連名だけは
変更しない。

## Phase 1 — ドメインと永続化の切替

- `CONTEXT.md` に `Scheduler Job`、`Recurring Job`、`One-shot Job` を追加し、Task Agent Task と別集約・別実行器であることを明記する。
- `task_runner.py` を `job_runner.py` に置き換え、scheduler のアプリケーションロジックを `scheduler_jobs` サブパッケージへ集約する。旧モジュールは削除し、import alias は提供しない。
- `tasks/` を `jobs/` へ、`tasks.yml` / `tasks.local.yml` / `tasks.local.sample.yml` を `jobs.yml` / `jobs.local.yml` / `jobs.local.sample.yml` へ移す。状態ファイル、config定数、lock file も `job` 名へ移す。
- DB migration で `task_state` を `job_state` へ再作成して既存行をコピーし、旧表を削除する。Scheduler Job の既存実行状態を保持するが、旧表・旧SQL・旧APIモデルは残さない。
- migration 実行前に既存 YAML を `jobs/` へ移動する明示的な one-shot migration command を提供する。成功後に旧 `tasks/` は削除し、以後 runner は `jobs/` のみ読む。移行失敗・既に新ファイルが存在する場合は停止し、両方を読んで合成しない。

受入条件: 新しい runner は移行済み `jobs/jobs.local.yml` を唯一の利用者設定として読み、`job_state` を唯一のScheduler状態として更新する。

## Phase 2 — 公開インターフェースとUIの切替

- Web route を `/jobs`、APIを `/api/v1/scheduler-jobs` に改める。定期設定のリソース名は `recurring-jobs`、ワンショットのリソース名は `one-shot-jobs` とする。
- request / response の `tasks`、`TaskConfig*`、`TaskItem` を `jobs`、`SchedulerJobConfig*`、`RecurringJob` へ置換する。旧 `/task-config`、旧schema、旧クライアント関数は削除する。
- フロントエンドは `TaskPage` を `JobPage` に改め、`/jobs` に定期実行ジョブとワンショット実行ジョブを表示する。ワンショットは予定・状態・登録元・結果詳細・未開始取消を扱う。
- Agent tool / Task Agent Capability は `register_one_shot_job` を用いる。Agent 編集画面の tool 選択、PlannerのCapability表示、監査表示を Job 用語にする。
- 旧 `/tasks`、`/api/v1/task-config` を呼ぶ外部クライアント・ブックマークは動作しない。README とリリースノートに、移行コマンドと新URLを明記する。

受入条件: Scheduler利用者が使うURL、JSONキー、TypeScript型、画面、Agent toolに scheduler 意味の `Task` 名が残らない。

## Phase 3 — 運用入口と履歴の切替

- `batch/scheduler.sh`、LaunchAgent plist、ログラッパー、Makefile、運用手順を `job_runner` と `jobs/` のパスに更新する。旧 entry point は削除する。
- `job_state` 一覧API・実行ログ画面を Job 表記へ変更し、既存の状態集計・実行ログを新IDで参照できるようにする。
- 既存 `command_runs` は一般実行ログとして名称を維持するが、scheduler 起因の表示・引数・説明は `job_id` を使用する。過去ログの列や本文は書き換えない。
- 旧 `tasks/` と旧状態ファイルが残っている場合、runner は無視せず起動を失敗させ、明確な移行手順を表示する。意図せず旧設定だけで運用を続けないようにする。

受入条件: launchd から新 runner が起動し、定期Job・ワンショットJobとも新しい設定・状態・画面で確認できる。

## 検証・文書化

- YAML移行 command の成功、旧/新ファイル併存時停止、移行後の定期Job実行、`job_state` への集計、ワンショットJobの一度だけ実行・取消・中断後停止を隔離環境で結合テストする。
- 新APIのBearer認証、旧 route の404、旧Python import の失敗、新UI route、Agent tool / Capability catalog、launchd実行コマンドをテストする。ブラウザE2Eは追加しない。
- `ai_wiki/10-Decisions-Architecture.md` に、完全改称・設定移行・旧入口をfail-closedとする判断をADRとして記録する。`docs/job/` に移行手順とワンショットJobの操作シナリオ契約を残す。
- `uv run pytest tests/` とOCRレビューを実行する。実装後は既存サーバーを停止して `make serve` で再起動し、実DBで安全な `printf` Job を登録・実行して `/jobs` と `job_state` を確認する。

## 非目標

- `task_agent_*` SQLiteテーブル、Task Agent API / CLI / UI、Task Agent の状態名・履歴の改称。
- 過去の `command_runs`、Task Agent Event、監査ログ本文の書換え。
- 旧Scheduler URL・ファイル名・Python import の互換レイヤー、リダイレクト、fallback読込。
