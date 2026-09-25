# 定期実行ジョブ（Agent 登録・所有） — 操作シナリオ契約

Scheduler Job の一種。定期実行ジョブの正本は従来どおり YAML
（`jobs/jobs.local.yml`、無ければ `jobs/jobs.yml`）と `jobs/last_run.json` で
あり、DB migration や新規 HTTP API は追加しない。Agent は
`register_recurring_job` tool で新規ジョブを登録し、自身が登録してから人間に
編集されていないジョブだけを `set_recurring_job_enabled` で有効／無効にできる。

Task Agent の Task とは別集約・別実行器である。用語は `CONTEXT.md` を参照。

## 操作シナリオ契約

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| Agent 登録 | Pydantic 入力（`job_id`・`command`・`schedule`）、trusted Agent context、active YAML 全件 | `job_id`（Agent 指定・既存と重複不可） | active YAML 全件を local YAML へ保存、`agent_source` 付与、`last_run` を現在時刻へ arm | UI・runner | trusted `agent_id` 欠落・重複 ID・不正 schedule/command は無変更（`ValueError`） | YAML 書込み、将来の OS コマンド実行を永続化 |
| Agent 切替 | `job_id`・`enabled`・trusted owner | `job_id` | 対象1件だけ変更した全件 YAML、`disabled→enabled` のみ再 arm | UI・runner | 未所有（手動・他 Agent・欠落/破損 source）・存在しない ID は無変更 | なし（以後の runner cycle を止めるのみ） |
| 人間更新 | Bearer 認証済み全件 PUT と現行 raw YAML | `job_id` | 未変更 entry の未知キーと `agent_source` を保持。意味変更で source 失効 | UI・runner | revision 不一致はマージ・検証・保存の前に 409 | 無効化・削除が人間の停止手段 |
| 人間ワンクリック実行 | Bearer 認証済み `job_id`、active YAML 現行版 | recurring `job_id` → one-shot `job_id`（uuid4 hex） | `one_shot_jobs` に `source='manual'`・`source_job_id`・対象コピー・`run_at_utc=now`・`queued` を1行。YAML と `last_run` は不変 | job_runner claim、`/jobs` 一覧 | 未知 ID は 404、対象欠落・未公開 Revision は 422、未完了の手動実行は 409（部分 UNIQUE index が競合も拒否）、YAML 破損は 500 で無書込み | OS コマンド実行または Workflow Run 作成を runner が一度だけ（at-most-once） |
| Runner 実行 | YAML・state | `job_id` | 既存 `job_runner`、既存 retry 規則を維持 | — | 実行中・読込済み cycle は取消さない | shell なしで OS コマンドを起動 |

## 規則

- `schedule` は既存 YAML と同じ `{type, second?, minute?, hour?, weekday?, day?}`
  形式で、数値・cron 風文字列（`*/5`、`8-18/2`、`0,30`）・その配列を受け付ける。
  type の許可値、必須／許可キー、既定値、範囲、cron 文法の意味検証は既存
  `normalize_schedule` のみを正本とする。Pydantic は object と値の形だけを
  検証し、ネスト model による規則の二重定義はしない。`command` も既存
  `parse_command` のみで検証し、shell は実行しない。
- 登録元は trusted context から注入した `agent_id`・`session_id`・`run_id` と
  UTC の `registered_at` を `agent_source` に記録する。LLM 入力では指定できない
  （`extra="forbid"`）。trusted `agent_id` が無い登録は拒否し、source 無しの
  ジョブを作らない。
- 登録・切替は config lock 内で active YAML を**全件**読み、変更を反映した完全な
  リストを `jobs/jobs.local.yml` へ原子的に保存する。`jobs/jobs.yml` しか無い
  場合も全件を local へ写す。部分リストを `save_jobs_and_arm` に渡さない
  （既存 job 定義と `last_run` state を失わせないため）。
- arming は `save_jobs_and_arm` を再利用する。新規登録と `disabled→enabled` のみ
  現在時刻で arm し、`enabled→enabled` は再 arm しない。過去の枠を遡及実行せず、
  次の該当枠から実行する。無効化は以後の runner cycle を止めるが、設定読込済み・
  実行中の cycle は取り消さない。
- 所有判定は `agent_source.agent_id == trusted agent_id` の完全一致のみ。
  `agent_source` の欠落・型不正・不一致、手動ジョブ、存在しない ID は
  「未所有」として切替を拒否する。破損 source は runner と `/jobs` 一覧を
  止めず、人間がそのジョブを意味変更すれば source を除去する。
- 人間による意味変更は ID・command・schedule・enabled の値変更と定義する。
  同値 PUT と並び替えだけでは source を保持し、意味変更では削除する。ID 変更は
  旧ジョブの削除と source を持たない新規手動ジョブの作成として扱い、source は
  移送しない。API は PUT payload の `agent_source` を一切信用せず、所有の作成は
  Agent 登録 service だけが行う。
- tool ID は `register_recurring_job` と `set_recurring_job_enabled`。入力 schema は
  それぞれ Pydantic 単一正本。両 tool は全 Agent の選択可能カタログに現れるが
  自動付与はしない。編集画面で `tool_ids` に明示追加した Agent だけが使える。
- Task Agent へは `register_recurring_job` のみ Capability として自動同期し、既定
  `plan_required` とする（`TASK_CONTEXT_TOOL_IDS` 経由で `task-agent:<task_id>` を
  登録元に注入）。`set_recurring_job_enabled` は `EXCLUDED_TOOL_IDS` により Task
  Capability から除外し、Task 由来 Job の停止・変更・削除は人間が `/jobs` で行う。
- 通常 Agent の tool 呼出しには登録ごとの人間承認ゲートを置かない。Agent 編集
  画面での明示付与が唯一の直接実行ゲートである。
- 人間ワンクリック実行は `job_id` だけを受け取り、実行対象（command / workflow と
  inputs）は現行 YAML からサーバー側で解決する。クライアント供給の target は一切
  信用しない。`enabled=false` のジョブも実行でき、実行しても `last_run` /
  `next_run` は更新しない（次回スケジュール枠は維持される）。
- 投入後に元ジョブを編集・削除しても、予約済みの手動実行は登録時にコピーした
  対象で実行される。取消は `/jobs` のワンショット一覧から `queued` の間だけ可能。
- 重複防止は同一 `source_job_id` の `queued`/`running` を部分 UNIQUE index
  （`one_shot_jobs`、v64）で1件に制限し、API は 409 を返す。SQLite の制約違反も
  同じ 409 に写像するため、Web と runner、同時リクエスト間の競合でも二重登録しない。
  終端後は再実行できる。Workflow は dispatch 後 `dispatched`（終端）になるため、
  Run 実行中にあらためて実行を登録できる。
- 登録成功後、Web サーバーは `job_runner` プロセスを best-effort で1サイクル分
  起動する。起動失敗や runner lock 競合時もキュー行は残り、最大60秒後の次サイクルが
  実行する。spawn した runner は別プロセスなので Web サーバー再起動では中断しない。

## API と画面

- `GET /api/v1/scheduler-jobs/recurring-jobs` — 各ジョブを schedule・command・
  `next_run`・`agent_source`（欠落/破損は `null`）付きで返す。
- `PUT /api/v1/scheduler-jobs/recurring-jobs` — revision 照合 → raw YAML との
  semantic merge → validate → `save_jobs_and_arm`。revision 不一致は 409 で
  何も書かない。
- `POST /api/v1/scheduler-jobs/recurring-jobs/{job_id}/run` — 手動実行を
  ワンショットキューへ登録し、201 で one-shot サマリを返す。未知 ID は 404、
  対象欠落・未公開 Revision・入力不整合は 422、未完了の手動実行は 409、YAML
  破損は 500。成功時は runner 起動を試みる（失敗しても 201）。
- `/jobs` の定期ジョブ一覧に登録元 Agent ID を表示する。フォーム・トグル・削除を
  含む更新で `agent_source` を payload に含めて往復し、意味変更時のみ失効させる。
- `/jobs` の定期ジョブ各行に「今すぐ実行」を置き、対象を確認ダイアログで示す。
  実行中（`queued`/`running`）の間はボタンを無効化し、結果はワンショット一覧で
  確認させる。手動実行の登録元は「手動（定期: <job_id>）」と表示する。
- 既知のトレードオフ: 構造化保存（UI 保存・Agent 登録・切替）では
  `jobs.local.yml` の人間コメントは保持されない。

## 検証

縦断シナリオは `tests/test_recurring_agent_jobs.py`（隔離 YAML/state＋fake
runner）と `tests/test_scheduler_jobs_web.py`。結合条件：Agent tool 登録 →
`agent_source` 付き全件保存 → 次回枠で一度だけ実行 → 所有 Agent の無効化。
加えて、DEFAULT→LOCAL の全件 shadow 保存、state と未知キーの保持、重複 ID、
不正 schedule/command、context 欠落、source 偽装、壊れた source、所有者不一致、
再有効化時の arm、同値 PUT での source 保持、意味変更での失効、client 供給
source の拒否、古い revision の 409 無書込み、Task Capability からの
`set_recurring_job_enabled` 除外を検証する。

人間ワンクリック実行は `tests/test_scheduler_jobs_web.py` の
`test_run_recurring_job_now_command_scenario` /
`test_run_recurring_job_now_workflow_scenario` /
`test_run_recurring_job_now_ignores_client_target_payload` が縦断する。
無効ジョブの 201、client 供給 target の無視、409 重複、422（対象欠落・未公開
Revision）、404、500（YAML 破損・無書込み）、`last_run` 不変、runner による
一度だけの実行・dispatch を検証する。DB 制約は `tests/test_one_shot_jobs.py` の
`test_manual_source_fields_and_single_pending_run` と
`tests/test_jobs_migration.py` の v64 テスト。実装後は `uv run pytest tests/` と
frontend test/build を実行し、実 DB 接続の `/jobs` で無害な登録・無効化・
ワンクリック実行・人間編集後の所有失効を手動確認する。
