# Workflow Graph / Agent Node / Loop Node

## Status

Accepted (2026-09-20、再設計 Phase 0 決定。実装未着手)

## Context

最初の Workflow ADR([workflow-independent-context-shared-foundation.md](workflow-independent-context-shared-foundation.md))では、
「人間が Web UI で作成する決定的な実行定義」として**線形 Step + 前進分岐 + 上限付き反復**を
採用した。しかし実運用で必要になる「計画 → レビュー → 改稿」の反復や、LLM 出力を後続
Capability に型付きで受け渡すフローは、線形モデルでは表現が不自然だった。

一方、既存 Task Agent は自由文依頼を LLM が動的に解釈する仕組みであり、再現性が必要な
定型フローには向かない。

したがって Workflow は次のように再定義する。

- **制御・データフローは決定的** — 人間がグラフを設計し、Run はそのグラフを走る。
- **Agent Node の出力は確率的** — Agent Node 内の LLM 出力は JSON Schema で検証し、
  型付きで後続 Node へ受け渡す。自由探索は既存 Task Agent、再現したい流れは Workflow。

## Decision

- Workflow を **Node / Edge グラフ**として再設計する。Node 種別は少なくとも
  `capability`、`agent`、`loop`、`terminal`、`loop_result` を持つ。
- **Workflow**（恒久 ID・名前・説明）と **Workflow Revision**（`draft`/`published`/`superseded`、
  グラフ・inputs_schema・版番号）を分離する。Node / Edge ID は UUID で、配列 index を
  識別子や参照パスに使わない。
- Run 開始時に Revision が宣言した **inputs_schema** に従う型付き入力フォームを表示し、
  入力値・Revision・グラフを Run へスナップショットする。
- **通常の Edge は循環不可**。反復は **Loop Node** が所有する非循環子グラフで表現する。
  Loop Node は反復状態 `loop.state`、継続条件、最大回数を持ち、ネストは v1 では禁止する。
- **Agent Node** は既存 `agents` テーブルの `agent_id` を選ぶだけ。Node ごとの
  prompt/model/tool 上書きはしない。実行時は選択 Agent の最新設定を使い、設定指紋を監査用に
  記録する。Workflow の承認境界は Capability Policy と選択 Agent ID のみ固定する。
- Node 間のデータ連携は **型付き参照**(`run.inputs.*`、`nodes.<node_id>.output.*`、
  `loop.state.*`)のみとし、文字列テンプレート展開は採用しない。
- **冪等実行境界**: Capability Adapter の実行契約に `InvocationContext` を追加し、
  `activation_id`(Node の論理的な 1 回起動単位の永続 UUID)を渡す。Retry は同じ
  `activation_id`、Loop の次反復は新しい `activation_id` を作る。各 Capability は
  冪等キーを利用可能かを宣言し、利用可能な Adapter だけが外部 API の idempotency key 等に
  変換する。
- **完了判定**: 成功終端 Node へ到達し、**実際に実行された Node** のうち効果を宣言したものが
  すべて効果を満たした場合に `completed`。効果未達なら `incomplete`。失敗終端 Node へ到達または
  実行時エラーなら `failed`。
- **非冪等 Node(Agent/Coding)が外部操作中に中断した場合**、自動再開せず Node 状態を
  `needs_attention`、Run 状態を `waiting_attention` とする。人間が子 Run 結果を確認して
  「採用して続行」「失敗扱い」「新しい Activation として再実行」のいずれかを選択する。
- Workflow 本体は長期成果物を所有しない。調査結果は Research/Vault、Agent 回答は Agent 会話、
  ノート・記憶は各専用 Capability / ドメインサービスが保持する。Workflow は Run 中の型付き
  出力、参照先 ID、redact 済み監査記録のみを 30 日保持する。

### 責務境界

| 責務 | Task Agent | Scheduler Job | Workflow (再設計後) |
| --- | --- | --- | --- |
| 定義の生成主体 | LLM Planner | 人間 / Agent tool (YAML) | **人間 (Web UI グラフエディタ)** |
| 定義の形状 | Directional Plan(目的・範囲・制約) | OS コマンド / **公開 Workflow の起動対象 + 固定入力** | **Node/Edge グラフ + Loop 子グラフ + 型付き inputs_schema** |
| 実行判断 | Runtime Orchestrator の動的ループ | 時刻判定 | **定義されたグラフと条件評価のみ** |
| 非決定要素 | Planner/Orchestrator が都度判断 | なし | **Agent Node の LLM 出力のみ** |
| 集約・状態 | `task_agent_*` | `jobs/last_run.json` / `one_shot_jobs` / `workflow_schedule_dispatches`（発火枠） | `workflow_*`、`workflow_revision_*`、`workflow_run_nodes`、`workflow_activations` |
| 承認境界 | Capability Policy + 承認時点の allowed_* / 指紋 | **Workflow 発火時は Workflow の承認境界を継承**（発火ごとに `waiting_approval` Run を作る） | Capability Policy + 選択 Agent ID。Agent 内部設定は最新版を使用、指紋は監査のみ |

### 共有するもの / 共有しないもの

| 区分 | 内容 |
| --- | --- |
| **共有** | Capability Adapter 層(`tasks/capabilities.py`、schema、adapters)、`task_agent_capabilities` の有効/Policy 正本、HITL 登録・回答基盤、FastAPI lifespan worker / instance lock、Bearer 認証、redaction・30 日保持規約、fetch ベース SSE、Agent 設定(`agents` テーブル) |
| **共有しない** | Workflow 集約・Revision ライフサイクル・グラフ構造・Run 状態機械・Node 状態・Event テーブル・Activation 管理・Capability への InvocationContext 付加層 |

## Alternatives

- **線形 Step モデルを維持する**: 計画→レビュー→改稿の反復を前進分岐 + 同一 Step 反復で無理に表現すると、Reviewer 出力を Planner 入力に戻す構造が曖昧になり、データフローも追いにくい。不採用。
- **一般 DAG + 自由な循環 Edge を許可する**: 無限ループ・停止不能 Run のリスクが高く、個人用途での運用負荷が大きい。反復は Loop Node に閉じることで、終了条件・上限・状態が局所化される。不採用。
- **Agent Node ごとに prompt/model を上書き可能にする**: Agent 設定の正本を `agents` テーブルに保つため、Node ごとの上書きは v1 では導入しない。必要なら将来、Node レベルの override 承認を含む ADR で検討。
- **Agent 設定を承認時点で固定する**: 既存 Task Agent と同じ安全性だが、Workflow は「利用者が選んだ流れを再現する」用途であり、Agent 改善を即活かす方が価値が高い。Agent 内部設定の変更は Workflow 承認範囲外の技術的権限とみなし、指紋監査で運用カバーする。不採用。
- **activation_id を inputs JSON に注入する**: 既存 Pydantic schema が未知フィールドを拒否し得るため、実行契約を拡張して InvocationContext として渡す方を採用。不採用。

## MVP範囲と対象外

**範囲**: Workflow / Revision / Node / Edge / Loop 子グラフの保存・検証、Capability Node、Agent Node(JSON Schema サブセット、Agent 選択)、Loop Node(非ネスト)、terminal/loop_result Node、型付き inputs_schema、型付き参照、条件付き排他的分岐、OR 合流、承認(`waiting_approval`)、HITL wait(`waiting_hitl`)、`needs_attention`/`waiting_attention`、中断・明示再開・キャンセル、効果契約による動的完了判定、Event 監査、redaction・30 日保持、バックエンド API、後続フェーズで GUI / SSE を実装。

**対象外(将来拡張)**: 並列 Node / fork / AND join、Loop ネスト、任意の循環 Edge、任意コード Node、Agent Node ごとの prompt/model/tool 上書き、$ref/oneOf/再帰を含む JSON Schema、Workflow 独自の長期 Artifact ストア、専用 worker、完了通知外部入口、定義のインポート/エクスポート。

## Consequences

**利点**

- 計画→レビュー→改稿の反復や、Agent 出力を Capability 入力に受け渡す定型フローを自然に表現できる。
- Agent Node の出力を JSON Schema で検証することで、確率的な出力を Workflow の決定的制御フローに安全に組み込める。
- Loop Node が反復を局所化するため、無限ループ・状態管理が制御しやすい。
- Capability Adapter に InvocationContext を渡す設計は、既存 Task Agent にも将来同じ形で適用可能。

**不利益・コスト**

- 線形 Step モデルよりもグラフ保存・検証・実行エンジンが複雑になる。
- Agent 設定を最新版で使うため、承認時点と実行時点で Agent の権限・振る舞いが変わりうる。運用上の信頼は監査ログに依存する。
- Capability Adapter への `InvocationContext` 対応は、既存 Adapter 群の段階的な更新を要する。

**リスク**

- Agent Node の出力 JSON Schema が緩い場合、後続 Node への型安全性が損なわれる。UI は schema サブセットを強制する。
- `loop.state` の型付き参照が複雑化すると、静的検証が困難になる。v1 では state_schema を object/properties に限定する。
- 非冪等 Node の `needs_attention` は人間の対応待ちを生む。運用頻度が高い場合、再開自動化の議論が発生する。

## 将来見直す条件

- Loop ネストや並列 Node の実需要が発生した時。
- Agent Node ごとの prompt/model/tool 上書きが必要になった時。
- `needs_attention` の人間対応が頻発し、自動化または別の停止ポリシーが必要になった時。
- 承認待ち Run の蓄積が運用負荷になり、抑止・期限・自動失効のいずれかが必要になった時。
- Workflow ごとの同時実行数制御や動的な日時入力テンプレートの実需要が発生した時。

## Amendment (Capability ブリッジ Task の隔離)

Status: Accepted (2026-09-21)。

- Task Adapter の実行契約は `task_id` を要求し、子 Run 連携 (`set_active_child`)・取消監視・
  Event 記録に Task 行を使う。Workflow の Capability Node はこれに合わせ、実行中だけ
  **短命のブリッジ Task** を作る。作成と `queued` 離脱は単一トランザクションにして
  Task worker に claim させず、終端化して 30 日保持に委ねる。
- ブリッジ Task は Task Agent の集約ではないため、`task_agent_tasks.origin = 'workflow'` を
  付与し、Task Agent の一覧 API・画面・件数から除外する。Task 詳細 URL の直接参照は監査用に残す。
- 将来 Adapter を InvocationContext ネイティブ化して Task 行を不要にできれば、ブリッジ Task
  自体を廃止する（本 ADR の「共有しない: Capability への InvocationContext 付加層」の完成）。
  それまでの隔離手段がこの origin である。

## Amendment (取消・不確実結果の追跡)

Status: Accepted (2026-09-22)。

取消は**ロールバックではなく要求**である。外部処理を強制停止したり巻き戻したりせず、
「どこまで進み、どの結果が確定しているか」を正本として残す。自動retryと
`backoff_seconds` は本 amendment では変更しない（残余リスクは後述）。

### 取消時の正本

取消に関わる状態は次の 4 つを正本とする。UI・API・エンジンはこの組み合わせだけを読む。

- **Workflow Run 状態**（`running` → `cancelling` → `cancelled` / `waiting_attention`）:
  取消要求と終端判断の唯一の正本。
- **Activation**（`activation_id`）: Node の論理的な 1 回起動。取消後も取消前の実行を
  同定する基準。
- **ブリッジ Task**（`workflow_run_nodes.bridge_task_id`）: Capability Adapter が外部
  呼び出しに使う短命 Task。取消伝播の到達点であり、外部操作の開始前に保存する。
- **子 Run 参照**（`child_kind` / `child_run_id` / `hitl_run_id`）: Adapter が実際に
  起動した外部処理。結果確度（`cancel_outcome`）と効果（`effects_json`）を伴う。

### 取消の状態遷移

- 実行中（`running`）の Run への取消は `cancelling` と取消 Event を原子的に記録し、
  保存済みのブリッジ Task を `cancelling` にする。エンジンは各 Node の開始前と完了直後に
  取消を確認し、取消後に次 Node・次 Loop 反復を起動しない。
- 子 Run の**協調取消が確認できた**場合のみ Node / Run を `cancelled` にする。
- 外部処理が**完了した、または結果が不明**な場合は、結果・効果・子 Run 参照を保存して
  Node を `needs_attention`、Run を `waiting_attention` にする。`cancelling` から
  `waiting_attention` への遷移を許可する（`cancelled` と混同しないための明示的な経路）。
- HITL は他の子 Run と同様に**保留**であり、要求した取消は子の状態を保証しない。
  `hitl_wait` 置換も「常に適用される取消」ではなく要求である。`waiting_hitl` の取消は
  関連 HITL Run も取消し、遅延した回答が Run を再キューしないようにする。
- `adopt`（採用）は、保存済みの成功出力・効果証跡がある**取消起因**の Node のみ許可する。
  証跡がなければ 409 で停止し、利用者は失敗扱い・中断・新 Activation での再実行を選ぶ。

### 残余リスク（本 amendment の対象外）

- 自動ロールバック、外部サービスの強制停止、exactly-once 保証は提供しない。
- 自動 retry と `backoff_seconds` の挙動は変更しない。Capability retry の冪等性は
  後続の InvocationContext 導入で扱う。したがって「取消要求後に retry で副作用が重複し
  うる」リスクは残る。Run が `cancelling` の間はエンジンが次 Node を起動しないため、
  取消時の新規重複は主に in-flight な単一 Node の retry に限られる。

## Amendment (Scheduler Job からの公開 Workflow 起動)

Status: Accepted (2026-09-22)。前提の「取消・不確実結果の追跡」amendment 完了後に着手する。

Scheduler Job の実行対象に「公開 Workflow」を第一級として加える。ここでいう公開 Workflow は
**発火時点の最新 published Revision** を指し、登録時に固定した Revision ではない。

### 決定

- **Scheduler の唯一の実行入口は `job_runner` のまま**。定期 Job は YAML、one-shot は
  `one_shot_jobs` に置き、`job_runner` が発火時に Workflow Run を 1 件作成する。Workflow 本体の
  実行は既存の lifespan 同居 Workflow worker が担う。Workflow 対象は OS コマンドを経由しない。
- **発火枠の冪等性は `workflow_schedule_dispatches`（定期）と `one_shot_jobs` の原子的 claim
  （one-shot）で保証する。** dispatch 行と Run 行は同一 SQLite transaction で commit し、
  commit 後に `last_run` を進める。これにより runner 再起動や `last_run` 保存失敗でも
  Run を二重作成しない。
- **最新公開版追従**: 発火のたびに最新 published Revision を解決し、その `inputs_schema` で
  固定入力を検証して Run の graph/input snapshot を作る。すでに `waiting_approval` の Run は
  自分の snapshot を維持し、新 Revision の影響を受けない。
- **承認待ちの蓄積を受容する**: 承認が必要な Workflow は発火ごとに必ず `waiting_approval` の
  Run を作る。未完了 Run があっても新規発火を抑止しない。蓄積は運用作（`/jobs` の表示、
  人間による取消・無効化）で扱い、抑止・期限・自動失効は本 amendment の対象外とする。
- **失敗も枠を消費する**: published 不在・入力 schema 不一致は Run を作らず、dispatch に
  失敗理由を残して当該枠を消費する。定期 Job は次回枠で最新公開版を再評価し、過去枠を
  全件 backfill しない。one-shot は `failed` として理由とともに残す。
- **one-shot は `dispatched` を終端とする**: Workflow dispatch 成功時の one-shot 状態は
  `dispatched` とし、Workflow 本体の完了・失敗とは区別する。dispatch 後の取消は Workflow Run
  側で行い、`queued` の one-shot のみ従来どおり取消可能とする。
- **command Job の意味は変更しない**: retry/backoff を含め既存の command 実行契約は不変。
  上記の「失敗も枠を消費する」は Workflow 対象のみに適用する。
- **所有規則を Workflow 対象にも適用する**: Agent 所有 Recurring Job は現行の `agent_source` と
  所有失効規則をそのまま適用し、人間が対象・入力・schedule・有効状態を変更すると所有を外す。

### 操作シナリオ契約（不可逆操作: Workflow Capability の副作用）

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| Job 登録 | `workflow_id`、現行 published Revision、固定入力 | `job_id` / `workflow_id` | YAML または `one_shot_jobs` | `job_runner` | Revision 不在・入力不適合は登録拒否 | なし |
| 時刻発火 | source_kind + scheduler_job_id + scheduled_for | dispatch 行 | `workflow_schedule_dispatches` | `job_runner` | 同一枠の再実行は既存結果を返す | なし |
| Run 作成 | 発火時の最新 published Revision と検証済み入力 | `run_id` / `revision_id` | Run の graph/input snapshot | Workflow worker | 不整合・公開版不在は Run なしで dispatch 失敗 | なし |
| 承認 | Run snapshot の capability policy | `run_id` | `waiting_approval` Run | 人間 / approve API | 承認前に Capability を実行しない | なし |
| 実行 | 承認済み snapshot + InvocationContext | `activation_id` | `workflow_run_nodes` / `workflow_events` | 次 Edge | validation 失敗は実行しない | Capability 副作用 |
| one-shot 完了 | one-shot Job ID と Workflow Run ID | `job_id` / `run_id` | `dispatched` | 人間 / Run 詳細 | 以後の取消・復旧は Run 側で追跡 | なし |

運用は `docs/development-quality-playbook.md` に従い、隔離 backend + fake Capability の縦断
結合テストで「承認前に副作用 0 回」「二重 Run なし」を反証可能にする。

## Amendment (User Template と Workflow Definition Package)

Status: Accepted (2026-09-23)。

公開済み Revision を再利用可能な User Template として保存し、公開 Revision と User Template の
両方を JSON / YAML でバックアップ・共有できるようにする。

### 決定

- **Template は元 Workflow への参照ではなく、公開 Revision の独立した定義スナップショットとする。**
  `workflow_user_templates` は `template_id`、名前・説明、作成元 Workflow / Revision の監査用 ID、
  定義スナップショット、作成・更新日時を持つ。作成元への外部キーは持たず、元 Workflow の削除後も
  Template は利用できる。Template 内の版履歴は持たない。
- **Template は公開済み Revision からのみ作成・内容更新できる。** 更新は同じ `template_id` の定義を
  新しい公開 Revision のスナップショットへ置換し、過去に Template から作成した Workflow には
  影響しない。
- **import は常に新しい Workflow の draft を作り、既存 Workflow / Revision / Run を変更しない。**
  既存 draft の置換 import は行わない。
- **Workflow Definition Package v1 は `format` / `version` / `name` / `description` /
  `inputs_schema` / `nodes` / `edges` のみを含む。** Workflow / Revision / Template ID、status、
  Run、Event、Scheduler 設定は含めない。Node / Edge ID は package 内のグラフ接続・参照解決に
  だけ使い、import / instantiate 時にすべて新規 ID へ採番し、`$ref`、Loop の `entry_node_id`、
  親 Loop、Edge 条件も一貫して書き換える。Revision 複製とコード定義 Template の ID 再採番は
  共通 helper に統合する。
- **import 境界では安全な YAML parse、package version、許可キー、型、ファイルサイズ、
  Node / Edge 上限、ID 一意性、graph-local 参照整合を検証する。** 違反は 422 で停止し、
  DB に何も作成しない。
- **graph の意味検証は import / instantiate 後に現行の `validate_graph` で行う。** 作成した draft と
  validation_errors を返し、未知 Capability / Agent などは公開不可のままエディタで修正できる。
- **import・Template 作成・Template 利用では実行・公開・Scheduler 登録を自動で行わない。**
- **既存のコード定義 Template API（`/workflows/templates`, `/workflows/from-template`）は変更せず、
  ユーザー Template API と明確に分離する。**

### 操作シナリオ契約（不可逆操作: import / instantiate の DB 書込み、export の外部送信）

| 段階 | 正本・ID | 永続化 | 停止・削除時 |
| --- | --- | --- | --- |
| Template 保存 | published `revision_id` | `template_id` と定義 snapshot | draft / 不在 Revision は拒否 |
| import | package v1 の graph-local ID | 新規 `workflow_id` / draft Revision | 形式・上限違反は DB 書込みなし |
| 再検証 | 現行 Capability / Agent | draft と検証結果 | エラー時も公開・実行しない |
| Template 削除 | `template_id` | Template 行のみ削除 | 作成済み Workflow / Run は不変 |

運用は `docs/development-quality-playbook.md` に従い、export → import → delete の縦断結合テストで
「境界違反時に DB 書込み 0 件」「全 ID 再採番」「Template 削除が生成済み Workflow に影響しない」を
反証可能にする。

## Amendment (Workflow 単位の承認スキップ)

Status: Accepted (2026-09-23)。

Agent Node を含む Workflow は起動のたびに `waiting_approval` となり、定型的に繰り返す
自分の Workflow では承認操作が運用負荷になる。Workflow 単位で承認ゲートを外せるようにする。

### 決定

- **設定は Workflow に持つ（`workflows.skip_approval`、既定 0）。** Revision や Run ではなく
  Workflow 本体に置く。理由は、同一 Workflow の全 Revision / Run に一貫して適用したいこと、
  変更に新 Revision を要さないこと、Workflow Definition Package v1 の形式を変えずに済むこと。
  承認判定は Run 作成時に一度だけ行い、スナップショット済みの既存 Run は後から影響を受けない。
- **スキップは Agent Node と `plan_required` Capability の両方に適用する。** 片方だけを残しても
  「起動のたびに承認待ち」は解消せず、中途半端な境界は説明コストに見合わない。
- **`skip_approval` が有効な Workflow の Run は `queued` で作成する。** worker がそのまま
  claim し、人間の承認なしで Node を実行しうる。
- **監査として `run_approval_skipped` Event を Run に残す。** 本来 `waiting_approval` に
  なるノード集合をスキップした事実を Run 詳細で追えるようにする。手動実行・rerun・
  Scheduler 発火の全経路で記録する。
- **承認 UI の文言は維持する。** Agent は実行時点の最新設定で動くという前提は変わらず、
  スキップは「現在および将来の Agent 権限での無承認実行」を利用者が明示的に選ぶ行為である。
- **既定は無効のまま。** 既存 Workflow と新規 Workflow は従来どおり承認を要求する。

### 操作シナリオ契約（不可逆操作: 承認なしの Capability 副作用）

| 段階 | 入力と正本 | 識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 設定 | Workflow の `skip_approval` | `workflow_id` | `workflows.skip_approval` | Run 作成 | 既定 OFF | なし |
| Run 作成 | published Revision + フラグ | `run_id` | Run + `run_approval_skipped` Event | worker | 未公開 / 入力 schema 不一致は拒否 | なし |
| 実行 | 承認スキップ Run の snapshot | `activation_id` | `workflow_run_nodes` / `workflow_events` | 次 Edge | Capability validation 失敗は実行しない | Capability 副作用（承認前） |

運用は `docs/development-quality-playbook.md` に従い、隔離 DB と fake Capability の縦断結合テストで
「フラグ OFF なら承認前に副作用 0 回」「フラグ ON なら承認なしで副作用が 1 回だけ」を反証可能にする。

### 残余リスク

- スキップした Workflow は、実行時点の最新 Agent 設定（将来の権限変更を含む）で無承認に動く。
- Scheduler 発火では無人の外部副作用が定期的に発生しうる。利用者が Workflow 単位で明示的に
  有効化することを前提に受容する。承認待ち Run の抑止・自動失効はひき続き対象外とする。

## Amendment (会話型 Agent と単発 LLM Node の責務分離)

Status: Accepted (2026-09-25)。

Agent Node は会話・ツール・HITL を伴う子 Run で、会話を `agent_sessions` / `agent_messages` /
`agent_runs` に保存する。定型の構造化抽出・分類・言い換えのように「会話を残す必要がなく、
型付き JSON だけが欲しい」用途では、Agent Node の会話保存を設定で止めるのではなく、別種別の
`llm` Node を追加して責務を分離する。

### 決定

- **`llm` Node は Workflow 専用の単発 LLM 呼び出し**とし、`provider` / `model` /
  `system_prompt` / `max_tokens` / 任意の `reasoning_effort` / `inputs` / 必須の
  `output_schema` のみを設定とする。未知キー（`retry` を含む）は保存・公開時に拒否する。
- **会話・ツールを持たない。** ツールを bind せず、`agent_sessions` / `agent_messages` /
  `agent_runs` を作成しない。OpenAI は `store=False`、OpenCode Go は Activation 由来の一意な
  識別子を使い、呼び出し間で会話コンテキストを共有しない。
- **出力は Agent Node と同じ JSON Schema サブセット**で検証し、`nodes.<id>.output.*` として
  後続 Node へ型付きで渡す。
- **承認境界を広げない。** `llm` は Capability / Agent の権限を持たず、`requires_approval` の
  対象外とする。既存の承認規則は変更しない。
- **既存 LLM ログ機構を再利用する。** request / response / token usage / failure は
  `llm_call_logs` に記録し、`run_id` は CLI 専用外部キーのため NULL の独立行とする。
- **自動再送しない。** 1 Activation あたり外部送信は高々 1 回。JSON 不正・schema 不一致・
  provider エラーは Node を失敗させ、error Edge がなければ Run を失敗させる。取消が送信前に
  届けば送信せず、送信中の取消は API を中断できないため終了後に監査を残し、後続 Node を起動せず
  Run を `cancelled` にする。
- **DB migration は不要。** Node 種別の追加のみで、既存の Agent Node・スターターテンプレートの
  会話保存動作は変更しない。

### 操作シナリオ契約（不可逆操作: 外部 LLM への送信）

| 段階 | 入力・識別子 | 外部送信と停止規則 |
| --- | --- | --- |
| 公開 | 検証済み Revision の `llm` config | 不正設定なら送信なし |
| Node 開始 | Run snapshot、`activation_id`、解決済み `inputs` | 実行中 Node を保存してから 1 回だけ送信 |
| LLM 応答 | `llm_call_logs.call_id`、JSON output | schema 不一致なら後続へ渡さず Node 失敗 |
| 取消・失敗 | Run 状態、Node 状態、LLM log | 後続操作なし。再送は新しい Run 実行だけ |

### 残余リスク

- 外部 LLM への送信は取り消せない。取消は結果を受け取っても後続 Node を起動しないことで、
  副作用の連鎖を止めるに留まる。
- `inputs` に秘密値を入れると provider に送信される。Revision に固定保存しない運用規約は
  Agent / Capability と同様。

## 関連文書

- [workflow-independent-context-shared-foundation.md](workflow-independent-context-shared-foundation.md) — 撤回された初期 ADR
- [../specification.md](../specification.md) — 本 ADR に基づく詳細仕様
- [../../../CONTEXT.md](../../../CONTEXT.md) — Bounded Context と Scheduler 分離規約
- [../task-agent/specification.md](../../task-agent/specification.md) — Task Agent 契約
- [../task-agent/adr/approved-plan-as-execution-boundary.md](../../task-agent/adr/approved-plan-as-execution-boundary.md) — Approval Policy
- [../task-agent/adr/effect-contract-completion.md](../../task-agent/adr/effect-contract-completion.md) — 効果契約
- [../task-agent/adr/no-automatic-rollback-recovery-via-trace-and-hitl.md](../../task-agent/adr/no-automatic-rollback-recovery-via-trace-and-hitl.md) — 自動ロールバックなし
- [../../development-quality-playbook.md](../../development-quality-playbook.md) — 不可逆操作の品質ゲート
- [../../testing.md](../../testing.md) — テスト規約
- [../../../src/obsidian_ai_hub/tasks/capabilities.py](../../../src/obsidian_ai_hub/tasks/capabilities.py) — Capability 定義
- [../../../src/obsidian_ai_hub/runs/manager.py](../../../src/obsidian_ai_hub/runs/manager.py) — lifespan 同居 worker
- [../../../src/obsidian_ai_hub/database.py](../../../src/obsidian_ai_hub/database.py) — マイグレーション
- [../../frontend/src/api/runSse.ts](../../../frontend/src/api/runSse.ts) — fetch ベース SSE
