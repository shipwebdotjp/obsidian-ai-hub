# WorkflowをTask Agentから独立Bounded Contextとし、実行基盤のみ共有する

## Status

Superseded (2026-09-20)。
本 ADR は [Workflow Graph / Agent Node / Loop Node ADR](workflow-graph-and-agent-node.md) に置き換えられた。
下記の内容は履歴として保持するが、現在の Workflow 設計の正本ではない。

## Original Status

Accepted (2026-09-20、Phase 0 設計決定。実装未着手)

## Context

obsidian-ai-hub には既に二つのオーケストレーション層が存在する。

1. **Task Agent**(`src/obsidian_ai_hub/tasks/`): 自由文依頼を LLM Planner が Directional Plan に変換し、
   Runtime Orchestrator が動的ループで実行する
   ([docs/task-agent/specification.md](../../task-agent/specification.md))。Plan は LLM 生成物であり、
   詳細入力は Plan 時点で固定しない方針が確定している(Task Agent 仕様 §4)。
2. **Scheduler Job**(`job_runner.py`、`scheduler_jobs/`): YAML または one-shot キューに登録された
   OS コマンドを `fcntl` 単一ランナーロックと at-most-once claim で起動する。定義はコマンド列であり、
   アプリ内 Capability を呼べない。

この間に「人間が GUI で作成・編集・検証する決定的ワークフロー」の需要がある。既存 Task Agent の
Plan は LLM 生成・GUI 編集不可・入力非固定であり、Workflow の要件と真逆である。一方で
Capability / Approval Policy / HITL / worker / SSE / redaction はすでに完成済みの正本であり、
再実装する責務ではない。

問題は、第三のオーケストレーション層を追加する際に、(a) Task Agent との二重実装・三重実装への
退化、(b) CONTEXT.md が確立した「集約・実行器・状態を共有しない」分離規約
([../../../CONTEXT.md](../../../CONTEXT.md) Scheduler 項)との整合、を同時に満たす設計を確定することである。

## Decision

- **Workflow は Task Agent から独立した Bounded Context とする**。集約(Workflow 定義 / Run)、
  状態機械、SQLite テーブル(`workflow_` 接頭辞)、worker claim は独自に持ち、Task Agent の
  Task / Plan / Event と混同しない。
- **実行基盤のみを共有する**: Capability Adapter 層(`tasks/capabilities.py`、
  `tasks/capability_schemas.py`、`tasks/adapters/`)、`task_agent_capabilities` の Approval Policy、
  HITL(`tasks/hitl.py`)、redaction(`tasks/redaction.py`)、FastAPI lifespan 同居 worker
  (`runs/manager.py`)、fetch ベース SSE(`frontend/src/api/runSse.ts`)。
- **Workflow は人間が Web UI で作成・編集する決定的な実行定義である**。LLM による Plan 生成を
  持たず、GUI 編集を前提とする不変バージョンで管理する。Task Agent の LLM 生成 Directional Plan
  とは分離する。
- MVP のフロー構造は**線形ステップ、前進のみの条件分岐、上限付き反復**とする。一般 DAG、
  並列実行、任意 Python コードステップ、Web UI からの Adapter 実装、定義のインポート /
  エクスポートは MVP 対象外とする。
- **完了判定に効果契約を再利用する**: 定義内の効果的 Capability の効果集合を必須効果とし、
  予算/手順の枯渇による未達は `incomplete`(失敗ではない)とする
  ([effect-contract-completion.md](../../task-agent/adr/effect-contract-completion.md))。

### 責務境界

| 責務 | Task Agent | Scheduler Job | Workflow |
| --- | --- | --- | --- |
| 定義の生成主体 | LLM Planner (+HITL 質問) | 人間 (YAML) / Agent tool | **人間 (Web UI)** |
| 定義の形状 | 目的・Capability 範囲・制約(詳細入力は実時点) | OS コマンド発火のみ | **線形ステップ列 + 前進分岐 + 上限反復、入力を定義時に確定** |
| 実行判断 | Runtime Orchestrator の動的ループ | なし(時刻判定のみ) | なし(定義どおり決定的) |
| 集約・状態 | `task_agent_*` | `jobs/last_run.json` / `one_shot_jobs` | `workflow_*` |
| 実行器 | Task worker(`tasks/worker.py`) | `job_runner.py`(fcntl lock) | Workflow claim(同居 worker の追加ループ) |
| 外部副作用 | Capability Adapter 経由のみ | `recurring.run_command` | Capability Adapter 経由のみ |

### 共有するもの / 共有しないもの

| 区分 | 内容 |
| --- | --- |
| **共有** | Capability Adapter(検証・実行・観測)、`task_agent_capabilities`(enabled / `approval_policy` の正本)、HITL 登録・回答基盤、FastAPI lifespan worker 基盤・instance lock、Bearer 認証、redaction・30 日保持規約、fetch ベース SSE 実装 |
| **共有しない** | 集約(Task と Workflow)、状態機械の正本テーブル、Event テーブル、worker claim、Plan/定義のライフサイクル、保持期間の削除ジョブ呼び出し先 |

### 状態とライフサイクルの独立性

- Workflow Run は Task 状態機械(Task Agent specification.md §5)に含まれない。`running` が Task のそれと
  同値でも、許可遷移・keeper・claim は Workflow store 内で閉じる。
- Workflow 定義の draft → published → archived は Task Plan の `pending / approved / superseded`
  とは別ライフサイクルである。互換読み込みはしない(Task が旧静的 Plan を互換するのとは対照的に、
  Workflow には旧形式が存在しない)。

## Alternatives

- **Task Agent に「保存済み Plan GUI 編集」を追加する**: Directional Plan は詳細入力を固定しない
  設計(Task Agent 仕様 §4)であり、GUI 編集可能な静的定義と要件が矛盾する。`{{steps.N.summary}}` 型の文字列
  置換は既に否決済み。LLM 生成と人間編集を同一集約に混ぜると検証責任が曖昧になるため不採用。
- **Task Agent の Capability `run_shell` 定義だけを組み合わせて Workflow を作る**: Scheduler との
  差別化が消え、GUI 編集・バージョニング・検証の必要性を解決しない。不採用。
- **Workflow → Task Agent 投入の変換層(Workflow を LLM Plan に渡す)**: 決定的手順を LLM の
  再解釈に晒し、実行内容が非決定的になる。GUI 承認の意味も失う。不採用。
- **独立ワーカープロセス(launchd)を新規に立てる**: post-mvp の専用 worker 課題を先倒しにする
  変更で、二重実行制御の新規設計を MVP に持ち込む。同居 worker ループ追加で十分なため不採用
  (将来、実測上のボトルネックが出た段階で再検討)。
- **一般 DAG + 並列実行**: 個人用途での実需要が未確認で、状態機械・実行上限・UI の複雑さが
  大幅に増える。MVP では不採用。

## MVP範囲と対象外

**範囲**: 定義 CRUD・不変バージョン・静的検証(API + Web UI)、線形実行、構造化出力参照、
前進条件分岐、上限付き反復、効果契約による完了/`incomplete` 判定、承認(HITL)/取消/明示再開、
実行履歴・SSE 進捗・Run 詳細 UI、redact+30 日保持。

**対象外(将来拡張)**: 一般 DAG、並列ステップ、ループバック(Phase 1 は前進のみ)、任意コード
ステップ、Adapter の Web 実装・編集、定義のインポート/エクスポート、Scheduler Job からの
Workflow 起動(Phase 5)、完了通知の外部入口、専用 worker、複数同時 Run。

## Consequences

**利点**

- 承認・副作用・観測の安全性規約が既存正本(Plan 承認境界、効果契約)から逸脱しない。
- Scheduler との CONTEXT.md 分離規約に倣うことで、三重実装化を避け、用語が混濁しない。
- GUI で決定的手順をプロンプトなしに直感操作でき、LLM の再解釈が入らないため挙動が予測可能。

**不利益・コスト**

- 新規テーブル群・状態機械・UI で、既に Task Agent と似通った機構が一部重複する(Event 型、
  claim、再開の重複排除)。これらは「正本の独立性」を保つ受け入れられる重複とする。
- Capability の有効化・承認ポリシーは共有正本を参照するため、Workflow は Task Agent 側の
  policy 変更の影響を直接受ける(実行直前検証で吸収するが、実行中の変更は保証しない)。

**リスク**

- GUI 定義が Capability の schema 変更・無効化で静的には保存済みのまま壊れ得る。
  動的検証+`interrupted`停止で対処する(Workflow 仕様 §7)。
- 前進分岐のみでは「戻る」手順を表現できず、利用者が定義を複製して体裁を合わせる必要がある。

## 将来見直す条件

- Scheduler Job から Workflow を起動する利用が実需要になった時(Phase 5、`job_runner` が唯一の
  実行入口である規約は維持)。
- 後方 goto・一般ループの実需要的な要望が出た時。その際は反復検知・終了条件の追加設計(ADR)を要する。
- 単一 serial worker がボトルネックになった時(post-mvp「専用常駐 worker」「複数 worker」の再検討)。
- Capability policy の Workflow 承認専用の差別化(例: Workflow 単位で緩和)が要望された時。

## 関連文書

- [../../../CONTEXT.md](../../../CONTEXT.md) — Bounded Context と Scheduler 分離規約
- [../task-agent/specification.md](../../task-agent/specification.md) — Capability / Plan / 状態機械の正本
- [../task-agent/adr/approved-plan-as-execution-boundary.md](../../task-agent/adr/approved-plan-as-execution-boundary.md) — 承認ポリシーの再利用根拠
- [../task-agent/adr/effect-contract-completion.md](../../task-agent/adr/effect-contract-completion.md) — 効果契約
- [../task-agent/adr/no-automatic-rollback-recovery-via-trace-and-hitl.md](../../task-agent/adr/no-automatic-rollback-recovery-via-trace-and-hitl.md) — 自動ロールバックなし
- [../task-agent/adr/sqlite-as-task-state-source-of-truth.md](../../task-agent/adr/sqlite-as-task-state-source-of-truth.md) — SQLite 正本
- [../development-quality-playbook.md](../../development-quality-playbook.md) — 不可逆操作の品質ゲート
- [../task-agent/post-mvp.md](../../task-agent/post-mvp.md) — 専用 worker・実行上限など未解決課題の帰着先
