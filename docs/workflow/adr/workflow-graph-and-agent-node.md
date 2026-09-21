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
| 定義の形状 | Directional Plan(目的・範囲・制約) | OS コマンド | **Node/Edge グラフ + Loop 子グラフ + 型付き inputs_schema** |
| 実行判断 | Runtime Orchestrator の動的ループ | 時刻判定 | **定義されたグラフと条件評価のみ** |
| 非決定要素 | Planner/Orchestrator が都度判断 | なし | **Agent Node の LLM 出力のみ** |
| 集約・状態 | `task_agent_*` | `jobs/last_run.json` / `one_shot_jobs` | `workflow_*`、`workflow_revision_*`、`workflow_run_nodes`、`workflow_activations` |
| 承認境界 | Capability Policy + 承認時点の allowed_* / 指紋 | なし | Capability Policy + 選択 Agent ID。Agent 内部設定は最新版を使用、指紋は監査のみ |

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

**対象外(将来拡張)**: 並列 Node / fork / AND join、Loop ネスト、任意の循環 Edge、任意コード Node、Agent Node ごとの prompt/model/tool 上書き、$ref/oneOf/再帰を含む JSON Schema、Workflow 独自の長期 Artifact ストア、Scheduler Job からの Workflow 起動、専用 worker、完了通知外部入口、定義のインポート/エクスポート。

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
- Scheduler Job から Workflow を起動する必要が出た時。
- `needs_attention` の人間対応が頻発し、自動化または別の停止ポリシーが必要になった時。

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
