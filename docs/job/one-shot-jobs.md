# ワンショット実行ジョブ — 操作シナリオ契約

Scheduler Job の一種。Agent が `register_one_shot_job` tool で任意コマンドを
登録し、次回の `job_runner` 起動時または指定日時以降に一度だけ実行する。
定期 Job の YAML とは混在させず、専用 SQLite キュー（`one_shot_jobs`）に保存する。

Task Agent の Task とは別集約・別実行器である。用語は `CONTEXT.md` を参照。

## 操作シナリオ契約

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| Agent登録 | Pydantic 入力（`command` 必須、`run_at` 任意）、trusted Agent context | `job_id`（uuid4 hex） | `queued` job（`run_at_utc`、`agent_id`/`session_id`/`run_id`、`source='agent'` 付き） | runner の claim | 不正 command・不正日時は保存しない（`ValueError`） | SQLite 書込み |
| 人間の手動実行 | Bearer 認証済み recurring `job_id`、現行 YAML | one-shot `job_id`（uuid4 hex）、`source_job_id` | `queued` job（`source='manual'`、対象コピー、`run_at_utc=now`） | runner の claim | 未知 ID は 404、対象不正は 422、未完了の手動実行は 409 | SQLite 書込み（実行は runner） |
| runner claim | 到来済み（`run_at_utc <= now`）`queued` row | `job_id` | `running`（`started_at` 付き、原子 `UPDATE ... WHERE status='queued'`） | executor | claim 競合は実行しない | なし |
| 実行 | 保存済み command（`parse_command` と同一形式、shell 不使用） | `job_id` | 終了コード・セグメント別出力・終端状態 | 画面・API の詳細表示 | 非ゼロ終了は `failed`、起動例外も `failed`、クラッシュ残りは次回起動で `interrupted` | OS コマンドを一度だけ起動（at-most-once） |
| 取消・保持 | `job_id` | `job_id` | `cancelled`（`queued` のみ可）、終端行は30日保持後に削除 | 保持期限の prune | `running` 以後は取消不可（422）、自動再実行しない | なし |

## 規則

- `run_at` 省略時は登録時点の UTC を保存し、次回 runner cycle で実行する（launchd 60秒起動のため「即時」は通常1分以内）。
- タイムゾーンなし入力は JST として解釈し、オフセット付きはそのオフセットで解釈して UTC 保存する。過去日時は即時扱いとする。
- 複数セグメントは定期 runner と同じく順に実行し、最初の非ゼロ終了で停止する。各ストリーム最大20,000文字で保存し、切詰めを明示する。
- `running` のまま残った行（プロセス中断・runner 異常終了）は次回起動で `interrupted` にし、自動再実行しない。
- `source` は `agent`（Agent tool 登録）または `manual`（`/jobs` の「今すぐ実行」）。`manual` は `source_job_id` に元の定期 `job_id` を保持し、部分 UNIQUE index（v64）が同一定期ジョブの `queued`/`running` を1件に制限する。終端後は再登録できる。
- 手動実行の対象（command / workflow と inputs）は現行 YAML からサーバー側で解決してコピーする。クライアントは指定できず、元ジョブの `last_run`/`next_run` は更新されない。詳細は `docs/job/recurring-jobs.md`。
- tool ID / Capability key は `register_one_shot_job`。入力 schema は Pydantic 単一正本（`command`、`run_at`）。登録元 ID は context-aware factory から注入し、Agent 入力として偽装できない（`extra="forbid"`）。
- 新 tool は全 Agent の選択可能カタログに現れるが、既存・新規 Agent への自動付与はしない。編集画面で `tool_ids` に明示追加した Agent だけが使える。Task Agent では自動 Capability 同期で公開され、既定 `plan_required` を維持する（`TASK_CONTEXT_TOOL_IDS` 経由で Task 由来 ID を注入）。
- UI から任意の command を登録する機能は提供しない。既存の定期ジョブをその場で一度だけ実行する導線（`source='manual'`）のみ提供し、一覧・詳細・未開始取消を `queued` の間は操作できる。

## API と画面

- `GET /api/v1/scheduler-jobs/one-shot-jobs?limit=100&offset=0` — 未完了（`queued`/`running`、`run_at` 昇順）を優先し、終端履歴（`finished_at` 降順）を続けて返す。各項は `source` と `source_job_id` を含む。
- `GET /api/v1/scheduler-jobs/one-shot-jobs/{job_id}` — セグメント別 stdout/stderr を含む詳細。存在しなければ 404。
- `POST /api/v1/scheduler-jobs/one-shot-jobs/{job_id}/cancel` — `queued` のみ取消。存在しなければ 404、それ以外は 422。
- `POST /api/v1/scheduler-jobs/recurring-jobs/{job_id}/run` — 定期ジョブの手動実行（`source='manual'` の行を作成）。詳細は `docs/job/recurring-jobs.md`。
- `/jobs` の「ワンショット実行ジョブ」欄に予定時刻・状態・登録元・command・終了コードを一覧化し、詳細表示と未開始分の取消を提供する。登録元は Agent 実行なら `agent/session/run`、手動実行なら「手動（定期: <job_id>）」を表示する。いずれも Bearer 認証。

## 検証

縦断シナリオは `tests/test_one_shot_jobs.py`（隔離 SQLite＋fake executor）。結合条件：
Agent tool 登録 → 原子的 claim → 一度だけ実行 → 結果保存。未来日時、JST正規化、
過去日時の即時扱い、不正 command、非ゼロ終了、取消競合、再起動後の `interrupted`、
30日削除、claim 競合の非実行を検証する。手動実行の `source`/`source_job_id` 保存、
`find_active_manual_run`、部分 UNIQUE index による重複拒否、終端後の再登録も
`test_manual_source_fields_and_single_pending_run` で検証する。Web からの縦断は
`tests/test_scheduler_jobs_web.py` の run-now シナリオを参照。
