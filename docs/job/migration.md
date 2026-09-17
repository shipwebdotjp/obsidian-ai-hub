# Scheduler Task → Job 移行手順

`task_runner` / `tasks/` / `task_state` / `/api/v1/task-config` / `/tasks` を、
`job_runner` / `jobs/` / `job_state` / `/api/v1/scheduler-jobs` / `/jobs` へ
完全移行する手順。互換レイヤー、リダイレクト、fallback 読込は提供しない。

## 前提

- Task Agent の Task（`task_agent_*` テーブル、Task Agent API/CLI/UI）は改称対象外。
- 過去の `command_runs`、Task Agent Event、監査ログ本文は書き換えない。

## 手順

1. コードを新版に更新する（`scheduler_jobs` 集約、`job_runner` 入口、
   DB migration v48 まで適用）。
2. YAML を移行する（明示的な one-shot migration command、一度だけ実行）。
   ```bash
   python -m obsidian_ai_hub.job_runner --migrate-tasks-to-jobs
   ```
   - `tasks/tasks.local.yml`（なければ `tasks/tasks.yml`）を検証後に
     `jobs/jobs.local.yml` へ複写する。
   - `tasks/last_run.json` と `tasks/knowledge_sync_state.json` があれば
     `jobs/` へ複写する（なければ作らない）。
   - 成功後に旧ファイルを削除する。`jobs/jobs.local.yml` が既に存在する場合や
     旧 YAML がない場合・内容が不正な場合は停止し、両ディレクトリを合成しない。
3. DB を移行する。初回のサーバー／runner 起動時に migration v48 が走り、
   `task_state` を `job_state`（`task_id` → `job_id`）へ再作成して既存行を
   複写し、旧表を削除する。同時に `one_shot_jobs` を作成する。
4. 運用入口を切り替える。
   - `batch/scheduler.sh` と LaunchAgent plist は `job_runner` を指す。
     既存 plist の再インストール（`make enable` 相当の再登録）を行う。
   - ブックマークと外部クライアントを新 URL（`/jobs`、
     `/api/v1/scheduler-jobs/...`）へ更新する。旧 URL は 404 を返す。

## fail-closed 動作

- 旧 `tasks/` ファイル（`tasks.local.yml`、`tasks.yml`、`tasks.test.yml`、
  `last_run.json`）が残っている場合、runner と定期 Job API は起動・読込せず、
  移行コマンドの実行を促すエラーで停止する。旧設定だけを見て運用を
  続けることはない。
- テスト環境（`ENV=test`）ではこのガードを適用しない（sandbox が書込み先を
  リダイレクトするため）。fail-closed 自体は `tests/test_jobs_migration.py`
  で検証する。

## 確認

- `jobs/jobs.local.yml` を唯一の利用者設定として runner が読み、
  `job_state` を唯一の Scheduler 状態として更新すること。
- launchd から新 runner が起動し、定期 Job・ワンショット Job とも新しい
  設定・状態・画面（`/jobs`）で確認できること。
