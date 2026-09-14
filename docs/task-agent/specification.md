# Task Agent MVP 仕様

Status: Accepted (MVP implemented, Phases 1-5 done)

関連文書: [README.md](README.md)、[CONTEXT.md](../../CONTEXT.md)、[ADR](adr/)

## 1. 目的と非目的

### 目的

- 自由文依頼を受け、Capabilityを選んだ構造化Planを作り、必要な場合だけ一括承認を受けて
  実行する単一のTaskオーケストレーターを提供する。
- CLI投入、WebUIでの質問・承認・差戻し・取消、結果・履歴の閲覧を永続的に追跡する。
- 既存のAgent run、Coding run、HITL、workerを実行基盤として再利用する。

### MVP外

- Vaultの作成・編集・削除、カレンダー/リマインダーへの直接書込み
- Task実行からの直接書込み提案（Taskは既存のカレンダー/リマインダー提案HITL登録
  ツール経由でのみ登録し、直接書込みAdapterは持たない）
- Capability Adapterの任意作成や入力仕様・説明のWeb編集
- 共通Workspaceロック、複数Task worker、Task固有の実行上限・自動リトライ・自動ロールバック
- Coding CLI/Agent内部の計画逸脱を親側で技術的に防ぐこと

既存の子runが持つ制限は変更しない。特にCodingのCLI反復上限は既存の50回を継承する。

MVP後の再検討項目は [post-mvp.md](post-mvp.md) に集約する。

## 2. 入口と画面

- CLI: `python -m obsidian_ai_hub --task-agent "依頼"`
  - 空白だけの依頼は拒否し、Taskを作らない。
  - 成功時は `task_id`、`queued`、詳細URLを即時表示して終了する。
  - URLは既存Webのhost/portから組み立てる既定値を使い、公開URL設定があればそれを優先する。
- WebUI: `/task-agent` は一覧、`/task-agent/:id` は詳細画面である。
  - `/tasks` は既存の定期タスク設定のまま維持する。
  - 詳細には状態、Plan履歴、質問、実行Event、子runへのリンク、結果、取消を表示する。
  - `waiting_approval` / `waiting_reapproval` では承認または理由必須の差戻しを行える。
- Capability設定画面では、コードで登録されたCapabilityの `enabled` と
  `approval_policy` だけを変更できる。

## 3. Capabilityと承認ポリシー

Capabilityはコード側のAdapter keyとDB側の設定を組み合わせた実行能力である。
Adapter実装、入力検証、ラベル、説明はコードの正本とし、DBは有効状態と承認ポリシーの正本とする。
入力仕様の正本は各CapabilityのPydantic入力モデル / LangChain tool の `args_schema`
であり、`tasks/capability_schemas.py` が遅延解決してPlanner用schemaと実行時検証を
生成する。必須キーの手書き複製 (`required_inputs` 等) はしない。`trusted_ctx` や
APIキー等のruntime注入値はschemaに含めず、Plannerへ公開しない。

`approval_policy` は次の二値である。

| 値 | 振る舞い |
| --- | --- |
| `auto` | Planに含まれても人間の承認を待たずに実行する。 |
| `plan_required` | Plan全体を一括承認するまで、いかなるStepも実行しない。 |

Plannerは有効Capabilityだけを選択する。Plan内に一つでも `plan_required` があれば
`waiting_approval` へ進み、すべて `auto` なら同じPlanを監査用に保存してそのまま実行する。
Plan作成後のポリシー変更は既存Planの承認要否を変えない。ただし実行開始前にCapabilityが
無効化されていたら、そのTaskは `waiting_reapproval` に停止する。

初期Capabilityは次のとおり。Agent Registryを正本として自動派生するため、
Registryに新規builtin toolを追加すればTask Capabilityとしても自動公開される
(入力スキーマは `args_schema` から自動導出)。`run_shell`、Skills、
`custom:*` プラグインは既定 `plan_required` で有効化される。

| key / 種別 | 既定 | 備考 |
| --- | --- | --- |
| 読取・検索系の既存Registry tool | `auto` | web、Vault、Calendar、Reminders、Memory、People、Projectの読取・検索のみ。 |
| `calendar_create_proposal` / `reminder_create_proposal` | `auto` | 既存提案HITLの登録のみ（直接書込みなし）。人間の承認はHITL側で行うため、auto時のPlan確認は不要。 |
| `memory_propose` | `plan_required` | Memory candidateの作成。 |
| `specialist_agent` | `plan_required` | 登録済みAI Agentを指定して一回限りの子runを作る。 |
| `coding_cli` | `plan_required` | 登録済みProjectのGit rootで新規Coding session/runを作る。 |
| `research_agent` | `plan_required` | 既存リサーチ基盤のjobを作成・実行し、レポートをVaultへ公開する(target不要)。 |
| `run_shell`、Skills、その他新規Registry tool | `plan_required` | Registryの正本から自動派生。 |

Task Capabilityにしないtool(コード固定の除外セット): `ask_user`
(会話内専用)、`agent_delegate`(`specialist_agent` と重複し親Agent run文脈が前提)。
`calendar_create_proposal` / `reminder_create_proposal` はTask Capabilityとし、
既存ツール経由で提案HITL登録のみ行う（直接書込みはしない）。

`research_agent` の操作シナリオ契約 (Vault公開は不可逆操作):

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 入力検証 | `ResearchAgentInputs` (単一正本、theme必須) | `capability_key` / `research_agent` | 検証失敗はStep失敗 | ResearchAdapter | 未知キー・theme欠損は実行せず失敗 | なし |
| テーマ/job解決 | `theme`(NFKC正規化キー) | `theme_id` / `job_id` | research_themes / research_jobs | research db / WebUI | 同内容のapprovedテーマは再利用、candidateはjob成功後に承認化 | research DB作成 |
| 実行 | job (既存パイプライン) | `job_id` | research_jobs (succeeded/failed) | Adapterの待受ループ・WebUI | 失敗時はjob失敗でStep失敗 | なし |
| Vault公開 | succeededなjobのmarkdown | `output_path` / `is_published` | research_jobs (output_path, is_published) | Vault購読者 | 公開失敗はjobをfailedへ。未公開のまま(再実行可能) | Vaultへmarkdown新規作成 |
| タスク取消 | — | `child_run_id=job_id` | child_run_started Event | 再開ロジック | research jobに協調的キャンセルはなし。job終端まで待ってから取消を伝播 | job継続(公開され得る) |

一回性: 再実行 (rerun等) は既存 `save_research_to_vault` の冪等性
(`is_published=1` で既存ファイルがあれば skip) に依存し、Vault上の同一
ファイル名は `<title>_<job_id>.md` で固有化する。Task再開時の重複実行は
jobごとに最大1回の公開に収まる (at-least-once、Event履歴で検出可能)。


`specialist_agent` は実行開始時のAgent設定指紋とPlan承認時の指紋を照合する。
承認後にAgentのsystem prompt・有効tool・provider/model・委譲先が変わった場合、
または対象Agentが削除された場合は実行せず `waiting_reapproval` に停止し、
改訂Plan（同一内容の次版）と差分メモを残して人間の再承認を求める。
スナップショットを持たない旧Planと `specialist_agent` を含まないPlanは従来通り実行する。
実行開始後の設定変更（長時間ループ中の変更）の検出と、承認時点設定での子run固定は
将来課題とし、子run自体は従来通り実行時の設定で動作する。

## 4. Planと実行境界

Plan承認は全体的な方向性、目的、許可するCapability、主要な制約を承認する
(Directional Plan)。個々のツール呼び出しの詳細入力は承認対象ではなく、
承認済みPlanの目的・Capability範囲内の詳細入力生成には再承認を要求しない。

Directional Planは少なくとも目的、実行方針、承認されたCapabilityの集合
(Capabilityごとの大まかな意図付き)、制約、完了条件、最大Action数を持つ。
詳細inputsはPlan時点で固定しない。`{{steps.N.summary}}` の単純文字列置換は
採用しない。旧形式の静的Plan (順序付きStep・確定対象・入力を持つ) は互換
読み込みし、旧実行器で実行する。DB schema変更はしない。

承認済みDirectional Planの実行はRuntime Orchestratorの動的ループで行う:
次のAction (Capability呼び出し / finish) を構造化出力し、承認範囲・入力
schemaを検証してから実行し、ActionとObservationをEventへ保存する。
各ツール呼び出し直前に入力モデルで完全検証し、外部副作用のないvalidation
エラーは最大2回まで自己修正させる。`max_actions` (既定8、上限30) と同一
Action反復検出で無限ループを防ぐ。再開時は完了済みActionを重複実行しない
(`capability_completed` の `action_index` 基準。副作用完了〜Event保存間の
障害では at-least-once の重複が残り得る)。

未承認Capabilityの追加、目的の実質的変更は自動実行せず、改訂Planを同じ
Task IDの次版として保存して `waiting_reapproval` にする (旧形式の自己申告
フローと同様)。`coding_cli` ではProject、正規化済みGit root、backendを実行
時に解決し、対象IDの検証は共通のPydanticモデルで行う。`specialist_agent` /
`coding_cli` の委譲対象は、承認時点で有効だったAgent / Project IDの集合
(`allowed_agent_ids` / `allowed_project_ids`) としてPlanへ記録し、Actionごとに
範囲内か検証する。範囲外の対象は実行せず `waiting_reapproval` に回す。

### 操作シナリオ契約

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| Plan生成 | Capability schema (`args_schema`単一正本) | `capability_key` / `agent_id` / `project_id`(数値正規化) | Plan (方向性・Capability範囲・対象allowlist) | 承認者、Orchestrator | 未知Capability・解決不能schema・対象不在はPlan化せず失敗/質問 | なし |
| 承認 | 承認範囲 (目的・Capability・制約・対象allowlist) | plan_version・承認snapshot | plan_approved / ready | worker | 差戻しは理由必須でqueuedへ | なし |
| Action生成 | Plan・依頼・履歴Observation | RuntimeAction (構造化JSON) | 保存しない (LLM出力は使い捨て) | Orchestrator検証 | 不正出力は最大2回修正させて失敗 | なし |
| Action検証 | 正本のPydanticモデル | capability_key・target・inputs | note (検証エラー) | Orchestrator (修正) / 人間 (再承認) | 範囲外は実行せずdeviation、修正尽きは失敗 (対象範囲外は再承認) | なし (実行しない) |
| Action実行 | 検証済み入力 | action_index | capability_completed (target・inputs・observation) | 次ターンOrchestrator・再開時resume | tool失敗は失敗、取消は伝播 | memory_propose等の副作用 (at-least-once注意) |
| 再開 | capability_completedのaction_index | action_index (max+1、重複排除) | 既存Event | Orchestrator | 上限到達・同一反復は停止 | 完了Event未保存の副作用は再実行され得る |
| 完了 | 完了条件・finish要約 | result_summary | completed | 閲覧者 | — | — |

保証範囲: 完了済みActionの非重複実行は `action_index` 基準のbest-effortであり、
exactly-onceではない。副作用の実行から完了Event保存の間に障害が起きると、
再開時に重複実行され得る (at-least-once)。Event履歴で検出可能にするが、
自動的な防止・取消はしない。

### 操作シナリオ契約

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| Plan生成 | Capability schema (`args_schema`単一正本) | `capability_key` / `agent_id` / `project_id`(数値正規化) | Plan (方向性・Capability範囲・対象allowlist) | 承認者、Orchestrator | 未知Capability・解決不能schema・対象不在はPlan化せず失敗/質問 | なし |
| 承認 | 承認範囲 (目的・Capability・制約・対象allowlist) | plan_version・承認snapshot | plan_approved / ready | worker | 差戻しは理由必須でqueuedへ | なし |
| Action生成 | Plan・依頼・履歴Observation | RuntimeAction (構造化JSON) | 保存しない (LLM出力は使い捨て) | Orchestrator検証 | 不正出力は最大2回修正させて失敗 | なし |
| Action検証 | 正本のPydanticモデル | capability_key・target・inputs | note (検証エラー) | Orchestrator (修正) / 人間 (再承認) | 範囲外は実行せずdeviation、修正尽きは失敗 (対象範囲外は再承認) | なし (実行しない) |
| Action実行 | 検証済み入力 | action_index | capability_completed (target・inputs・observation) | 次ターンOrchestrator・再開時resume | tool失敗は失敗、取消は伝播 | memory_propose等の副作用 (at-least-onceに注意) |
| 再開 | capability_completedのaction_index | action_index (max+1、重複排除) | 既存Event | Orchestrator | 上限到達・同一反復は停止 | 完了Event未保存の副作用は再実行され得る |
| 完了 | 完了条件・finish要約 | result_summary | completed | 閲覧者 | — | — |

保証範囲: 完了済みActionの非重複実行は `action_index` 基準のbest-effortであり、
exactly-onceではない。副作用の実行から完了Event保存の間に障害が起きると、
再開時に重複実行され得る (at-least-once)。Event履歴で検出可能にするが、
自動的な防止・取消はしない。`specialist_agent` /
`coding_cli` の委譲対象は、承認時点で有効だったAgent / Project IDの集合
(`allowed_agent_ids` / `allowed_project_ids`) としてPlanへ記録し、Actionごとに
範囲内か検証する。範囲外の対象は実行せず `waiting_reapproval` に回す。

- Plannerは対象を一意に解決できなければ、既存HITLの質問を登録し `waiting_user` にする。
- 実行器は保存済みPlanのStepだけを順に実行し、実行時にCapabilityを再選択しない。
- Adapterが追加のCapability、対象、または副作用が必要だと自己申告した場合、実行を止め、
  改訂Planを同じTask IDの次版として保存して `waiting_reapproval` にする。
- Coding CLI/Agentがこの自己申告をせずに逸脱することは親側で防止・検出できない。Adapterは
  「Plan外が必要なら実行せず構造化結果を返す」ことを子runへの指示に含める。
- 差戻しは理由必須であり、同じTask IDを再キューして新しいPlan版を作る。

Planの承認・差戻しはTask APIで直接処理する。対象解決の質問だけは既存HITLに保存し、
回答後にTaskを再キューする。カレンダー/リマインダー提案HITLは、承認済みPlanの範囲内で
既存ツール経由でのみ登録し、直接書込みはしない。`auto` のみのPlanはPlan確認を経ずに
実行し、ツール側のHITL承認を人間の承認とする。`plan_required` を含むPlanの承認フローは
従来どおり維持する。

## 5. 状態モデル

| 状態 | 意味 |
| --- | --- |
| `queued` | 受付済み、または質問回答・差戻し後の再計画待ち。 |
| `planning` | workerがPlanまたは質問を生成中。 |
| `waiting_user` | 対象などの質問への回答待ち。 |
| `waiting_approval` | `plan_required` Planの初回承認待ち。 |
| `ready` | 承認済みで実行workerのclaim待ち。 |
| `running` | Step実行中または子run完了待ち。 |
| `waiting_reapproval` | 逸脱自己申告後の改訂Plan承認待ち。 |
| `cancelling` | 子runの協調的取消待ち。 |
| `interrupted` | worker停止により中断。 |
| `completed` / `failed` / `cancelled` | 終端状態。 |

許可遷移は次のとおり。

| From | To |
| --- | --- |
| `queued` | `planning`, `cancelled` |
| `planning` | `waiting_user`, `waiting_approval`, `running`, `failed`, `cancelled`, `interrupted` |
| `waiting_user` | `queued`, `cancelled` |
| `waiting_approval` | `ready`, `queued`, `cancelled` |
| `ready` | `running`, `cancelled`, `interrupted` |
| `running` | `completed`, `failed`, `waiting_reapproval`, `cancelling`, `interrupted` |
| `waiting_reapproval` | `ready`, `queued`, `cancelled` |
| `cancelling` | `cancelled`, `failed`, `interrupted` |
| `interrupted` | `queued`, `cancelled` |

終端状態からの遷移は禁止する。`ready` は承認済みの実行待ちを明示するため残す。
`waiting_lock` は存在しない。Task workerは一度に一つのTaskだけを進め、Coding Stepの
リポジトリ排他は既存Coding基盤に委ねる。

## 6. worker・取消・復旧

- Task workerはFastAPIの `runs.manager` lifespanでAgent/Coding workerと同居する。Webサーバーが
  止まっている間、Taskはキューに残る。
- workerはPlan生成または承認済みPlanのStep実行を行う。子Agent/Coding runは既存workerへ
  登録し、Task workerはその終端結果を監視して次Stepへ進む。
- 取消は、実行前なら即時 `cancelled`、実行中なら `cancelling` とし、実行中の子runへ既存の
  取消要求を伝播してから `cancelled` にする。実施済み変更は戻さない。
- 起動・停止時は、そのinstanceが所有する `planning`、`running`、`cancelling` だけを
  `interrupted` にする。承認待ちと質問待ちは維持する。`interrupted` は明示的な再計画でのみ
  `queued` へ戻り、自動再実行しない。
- Task固有の一律上限と自動リトライは持たない。失敗時は実施済みStep、未実施Step、子run結果、
  エラーをEventと結果要約に残す。

## 7. 永続化・監査・保持

SQLiteの新規テーブル名は既存 `task_state` と区別するため `task_agent_` 接頭辞を使う。

```text
task_agent_tasks
  task_id, prompt_text, status, current_plan_id, worker_instance_id
  active_child_kind, active_child_run_id, result_summary, error_summary
  created_at, updated_at, started_at, finished_at

task_agent_plans
  plan_id, task_id, version, plan_json, approval_policy_snapshot
  status, rejection_reason, created_at, decided_at

task_agent_events
  event_id, task_id, seq, event_type, payload_json, created_at

task_agent_capabilities
  capability_key, adapter_kind, enabled, approval_policy, updated_at
```

`task_agent_events` は追記のみであり、子run ID、HITL run ID、成果物への参照、状態遷移、
Capability入力/結果の要約を保持する。独立したArtifact、Delegation、HITL link、Workspace lock
テーブルはMVPでは作らない。

Task、Plan、Eventは終端化から30日後にまとめて削除する。非終端Taskは削除しない。
依頼本文・Plan・Event・Adapter要約は、既知の設定済み秘密値をredactしてから保存する。
未知の秘密値を自由文に含めないことは利用者の運用責任である。LLMの非公開思考過程や全出力の
無条件保存はしない。

## 8. API契約

- `GET /api/v1/task-agent/tasks` — Task一覧。
- `GET /api/v1/task-agent/tasks/{task_id}` — Task、Plan履歴、Event、関連子run/HITL参照。
- `POST /api/v1/task-agent/tasks/{task_id}/approve` — `waiting_approval` または
  `waiting_reapproval` の現行Planを承認し `ready` にする。
- `POST /api/v1/task-agent/tasks/{task_id}/reject` — 必須の `reason` を受け取り、現行Planを
  却下して `queued` にする。
- `POST /api/v1/task-agent/tasks/{task_id}/cancel` — 取消を要求する。
- `POST /api/v1/task-agent/tasks/{task_id}/replan` — `interrupted` Taskを明示的に `queued` に戻す。
- `GET /api/v1/task-agent/capabilities`、`PUT /api/v1/task-agent/capabilities/{capability_key}` —
  Capabilityの一覧と `enabled` / `approval_policy` の更新。

すべて既存Bearer認証に従う。CLIは内部の受付サービスを呼び、HTTP APIを経由しない。

## 9. 受入基準

1. CLI投入がTask ID、`queued`、詳細URLを即時返す。
2. `auto` のみのPlanは承認なしで実行される。
3. `plan_required` を含むPlanは承認前に子run・副作用を起こさない。
4. 未解決対象は既存HITLの質問となり、回答後に再計画される。
5. 差戻し理由は必須で、同じTask IDにPlan版が増える。
6. 無効化Capabilityは実行前に `waiting_reapproval` で止まる。
7. 取消・サーバー停止は子runに伝播し、Taskを自動再実行しない。
8. Coding/Agent Stepの子runと結果がTask Eventから辿れる。
9. Task Capabilityにないtool(`ask_user`、`agent_delegate`)をTaskが選べない。提案HITL登録は `calendar_create_proposal` / `reminder_create_proposal` の既存ツール経由でのみ行う。
10. Task履歴が30日で削除され、既知秘密値と非公開思考過程を保存しない。
