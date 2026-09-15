# Directional PlanとRuntime Orchestratorによる動的Agentループ

## Status

Accepted

## Context

静的な全入力確定Planでは、Plannerが全ツール引数を事前に知る必要があった。
しかし Plannerは各Capabilityの入力schemaを知らず (`collect_planner_context` は
key/種別/policyのみ)、`memory_propose` への誤引数のようなPlan時検証漏れが
起きていた。手書きの `required_inputs` 複製はPydantic入力モデルとの二重定義に
なり drift する。先行ツール結果に依存する入力はそもそもPlan時に確定できない。

## Decision

- Plan承認は全体の方向性、目的、許可するCapability、主要な制約を承認する
  (Directional Plan)。個々のツール呼び出しの詳細入力は承認対象にしない。
- 承認済みPlanの実行は Runtime Orchestrator の動的ループで行う。先行ツール結果
  を Observation として受け、次の Action (capability call / finish) を構造化
  出力する。`{{steps.N.summary}}` の単純文字列置換は採用しない。
- 入力仕様の単一正本はPydanticモデル / LangChain tool の `args_schema` とし、
  `tasks/capability_schemas.py` の遅延解決層から Planner 用 compact schema と
  実行時 `model_validate()` を生成する。`required_inputs` の手書き複製はしない。
- 各ツール呼び出し直前に正本モデルで完全検証する。外部副作用のない
  validation エラーは最大2回まで自己修正を許可し、超過時は Task を failed にする。
- Approval Scope 外の Capability 要求、目的の実質的変更は実行せず、
  既存の deviation / `waiting_reapproval` フローへ戻す。承認済み Capability の
  目的に沿った詳細入力生成には再承認を要求しない。
- 委譲対象 (agent_id / project_id) は承認時点の有効集合を Plan へ記録し、
  Action ごとに範囲検証する。範囲外は実行せず再承認へ回す。登録後に増えた
  Agent / Project へ承認なしで委譲することはない。
- 無限ループ防止に `max_actions` (既定8、上限30) を必須とし、同一 Action 反復を
  検出して停止する。再開時は `capability_completed` の `action_index` で完了済み
  Action を重複実行しない。Event 保存前に既存 redaction を適用し、秘密値や
  trusted context を LLM context / Event に混入させない。
- 旧形式の静的 Plan は互換読み込み・旧実行器で扱い、DB schema 変更はしない。

## Consequences

- Planner は詳細 inputs を固定しないため、Plan 時検証は scope と schema 解決
  可能性に限定され、引数内容の正しさは実行時検証へ移る。
- 副作用 Action の完了 Event 保存前後で障害が起きると、再開時に at-least-once
  の重複実行が残る (exactly-once は現構成では不可能)。監査 Event で検出可能に
  するが、完全な防止はしない。
- 子 Agent / Coding run の自己申告なき逸脱は従来通り親で検出できない。

## Operation-scenario contract

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| Plan生成 | Capability schema (Pydantic / `args_schema` 単一正本) | `capability_key`、`agent_id`、`project_id: int` | Plan (purpose/capabilities/allowlist) + policy snapshot | 承認者、Orchestrator | 未知Capability・解決不能schema・空の委譲先集合はPlanを作らず失敗 | なし |
| 承認 | Directional Plan (方向性・Capability範囲・制約) | `plan_version: 2`、承認policy snapshot | `plan_approved` + Task状態 | worker (実行claim) | 差戻しは理由必須で再計画 | なし |
| 次Action生成 | Plan + redacted Observation履歴 | `call_capability` / `finish` (Pydantic検証) | — (LLM出力は未保存) | scope検証 | 不正JSONは最大2回まで自己修正 | なし |
| scope・入力検証 | 正本の入力モデル + 承認時allowlist | `capability_key` + target ID | `note` (検証エラー) | Orchestrator (修正) / 人間 (逸脱) | scope外は実行せず`waiting_reapproval`、修正上限超過は失敗 | なし (検証後のみ実行) |
| Capability実行 | 検証済み入力 | `action_index` | `capability_completed` (target/inputs/observation) | 次ターンのOrchestrator、再開処理 | tool失敗は即失敗 (無制限リトライなし) | Adapter経由の副作用 (例: `memory_propose` 候補作成) |
| 再開 | `capability_completed` の `action_index` | `max(action_index)+1`、重複排除 | 同上 | Orchestrator | 最大Action数到達で失敗 | 副作用〜Event保存間の障害では at-least-once の重複が残る |

縦断テスト: `tests/test_tasks_orchestrator.py::test_worker_runs_directional_plan_end_to_end`
(隔離DB + fake tool/LLM で Plan→承認→実行→完了を通す)。

## Alternatives

- 静的 Plan のまま `required_inputs` を手書き追加: 二重定義の drift と
  Plan 時入力固定の限界が残るため不採用。
- `{{steps.N.summary}}` 文字列置換: 型情報喪失・escaping・失敗時語義が不定の
  ため不採用。型付き Action / Observation 形式を採用。
- ステップごとの逐次承認: 安全だが Task の継続性を損なうため不採用
  (既存 ADR `approved-plan-as-execution-boundary.md` と同じ理由)。
