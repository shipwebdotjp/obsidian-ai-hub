# ワンショット実行ジョブの導入プラン

## Summary

- Task Agent の `Task` と区別し、`task_runner` が扱う新概念を**ワンショット実行ジョブ**と呼ぶ。
- Agent が `register_one_shot_job` tool で任意コマンドを登録し、次回の `task_runner` 起動時または指定日時以降に一度だけ実行できるようにする。
- 定期タスク YAML には混在させず、専用 SQLite キューへ保存する。終了後は30日間、登録元・予定・終了コード・出力を保持する。

## 実装変更

- SQLite migration v48 で `one_shot_jobs` を追加する。`job_id`、command、JST/UTC正規化済み予定時刻、`queued/running/succeeded/failed/cancelled/interrupted`、登録元 Agent/session/run、開始・終了時刻、終了コード、セグメント別出力、エラー要約を保存し、期限・完了時刻の索引を持たせる。
- `one_shot_jobs` サブパッケージに、入力モデル、登録・取得・取消・期限切れ削除、原子的 claim、コマンド実行を分離する。`task_runner.py` は既存 runner lock 内で、放置された `running` を `interrupted` にし、期限到来済みジョブを claim して実行する入口に留める。
- command は既存の `parse_command` と同じ argv / `cd … && …` 形式のみ許可し、shell は使わない。複数セグメントは現行 runner と同じく順に実行し、いずれかの非ゼロ終了または起動例外で `failed` にする。
- 実行直前に `running` を永続化する。プロセス中断・runner 異常終了時は次回起動で `interrupted` にし、自動再実行しない（at-most-once）。`queued` のみ取消可能とする。
- `run_at` は任意の日時入力とし、省略時は登録時点で期限到来済みとして次回 runner cycle に実行する。タイムゾーンなしは JST、オフセット付き日時はそのオフセットで解釈して UTC 保存し、過去日時も即時扱いとする。
- tool ID / Capability key は `register_one_shot_job` とする。Pydantic の単一入力 schema は `command` と任意の `run_at`。Registry の context-aware factory から登録元 ID を注入し、Agent が入力として偽装できないようにする。
- 新 tool は全 Agent の選択可能カタログへ現れるが、既存・新規 Agent への自動付与はしない。編集画面で `tool_ids` に明示追加した Agent だけが使える。Task Agent 側では既存の自動 Capability 同期で公開され、既定 `plan_required` を維持する。

## Web API と画面

- Bearer 認証付きで以下を追加する。
  - `GET /api/v1/task-config/one-shot-jobs?limit=100&offset=0`：未完了を優先し、終端履歴を続けて返す一覧。
  - `GET /api/v1/task-config/one-shot-jobs/{job_id}`：セグメント別 stdout/stderr を含む詳細。
  - `POST /api/v1/task-config/one-shot-jobs/{job_id}/cancel`：`queued` のみ取消。
- `/tasks` に「定期タスク」と「ワンショット実行ジョブ」を分けて表示する。後者は予定時刻・状態・登録元・command・終了コードを一覧化し、詳細表示と未開始分の取消を提供する。UI からの手動登録は追加しない。
- stdout/stderr は各ストリーム最大20,000文字を保存し、切詰めを明示する。定期タスクの YAML、アーム処理、既存の実行挙動は変更しない。

## 操作シナリオ契約

| 段階 | 正本・ID | 永続化 | 停止時 | 副作用 |
| --- | --- | --- | --- | --- |
| Agent登録 | Pydantic入力、trusted Agent context、`job_id` | `queued` job | 不正commandは保存しない | SQLite書込み |
| runner claim | 到来済み `queued` row | `running` | claim競合は実行しない | なし |
| 実行 | 保存済みcommand | 終了コード・出力・終端状態 | 非ゼロは`failed`、クラッシュ残りは`interrupted` | OSコマンドを一度起動 |
| 取消・保持 | `job_id` | `cancelled`、終端30日保持 | `running`以後は取消不可 | なし |

## 検証と文書化

- 隔離 SQLite と fake command executor の結合テストで、Agent tool 登録 → 原子的 claim → 一度だけ実行 → 結果保存を通す。未来日時、JST正規化、過去日時の即時扱い、不正command、非ゼロ終了、取消競合、runner 再起動後の `interrupted`、30日削除を検証する。
- Registry catalog / Agent明示付与、Task Agent Capability 自動導出・`plan_required` 既定、API認証・一覧・詳細・取消、画面の一覧更新と取消操作をテストする。ブラウザ E2E は追加しない。
- `CONTEXT.md` に用語と境界を追加し、`docs/job/one-shot-jobs.md` に上記契約を残す。SQLiteキュー・at-most-once・Agent権限の判断は `ai_wiki/10-Decisions-Architecture.md`、Capability公開規則は既存 Task Agent ADR に記録する。
- `uv run pytest tests/` を実行し、OCR には副作用、`job_id`、入力schema、at-most-once と中断時停止規則を渡して出力を `/tmp/ocr_review.txt` に保存して確認する。
- 実装後は既存サーバーを停止して `make serve` で再起動し、実 DB 上で `printf` のみを実行するワンショット実行ジョブを登録・実行して、`/tasks` の成功履歴と出力を手動確認する。

## Assumptions

- launchd の既存60秒起動を維持するため、「即時」は直接起動ではなく次回 `task_runner` cycle（通常1分以内）を意味する。
- command に未知の秘密値を埋め込まないのは運用者責任とし、既存の任意コマンド権限と同じ範囲を Agent に明示付与する。
- Agent がいつ自律的に登録するかは各 Agent の system prompt が決め、本変更で全 Agent に自動実行を強制しない。
