# Run 削除ポリシー（終端 Run のみ、soft link を解除してハード削除）

## Status

Accepted（2026-09-26）。

## Context

Run を消す手段は 2 つだけだった。Workflow aggregate の削除（[workflow-deletion.md](workflow-deletion.md)）と、
30 日経過した終端 Run の起動時 purge（`purge_terminal_runs`）である。運用検証で作った終端 Run を
残したい Workflow から掃除するには Workflow 全体を消すしかなく、Run 単位の整理ができなかった。

`workflow_runs` への外部キーはなく、参照はすべてソフトな TEXT 列である。

- `workflow_run_nodes.run_id` / `workflow_activations.run_id` / `workflow_events.run_id` — Run の一部。
- `workflow_schedule_dispatches.run_id` — 発火枠の監査行。
- `one_shot_jobs.workflow_run_id` — 発火済み one-shot の結果参照。
- `workflow_runs.source_run_id` — rerun の系譜。
- `workflow_run_nodes.child_run_id` / `hitl_run_id` — 子 Run への外向き参照。

検討した選択肢：

1. **終端 Run のハード削除 + soft link 解除** — 終端のみ許可し、参照を NULL にしてから
   Run / Node / Activation / Event を同一トランザクションで削除する。
2. **非終端 Run も削除可能** — worker が claim 済みの Run を消すと、実行中の外部処理が
   到達不能なまま副作用を続ける。採用しない。
3. **論理削除（hidden フラグ）** — すべての一覧・集計・retention に条件が増える。
   30 日 retention と役割が重複するため採用しない。

## Decision

選択肢 1 を採用する。

- `DELETE /api/v1/workflows/runs/:run_id` を追加する。
  - Run が無ければ 404。終端（`completed` / `incomplete` / `failed` / `cancelled`）以外は 409。
  - 成功応答は `{"success": true, "run_id": ..., "events": n, "nodes": n, "activations": n}`。
- 1 トランザクションで次を行う。
  1. `workflow_schedule_dispatches.run_id` を NULL（発火枠の行と状態は監査として温存）。
  2. `one_shot_jobs.workflow_run_id` を NULL（発火済み status は変更しない）。
  3. `workflow_runs.source_run_id` を NULL（rerun 系譜は失われる）。
  4. `workflow_events` → `workflow_run_nodes` → `workflow_activations` → `workflow_runs` を削除。
- 子の Agent / Coding / Research / HITL Run は削除しない。別集約の history として残る。
- スキーマ変更・マイグレーションは不要。30 日 retention はそのまま併存する。

## 操作シナリオ契約（不可逆操作: 実行履歴の削除）

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 対象確認 | Run 行（`workflow_runs`） | `run_id` | なし（読取のみ） | 本サービス | 不在は 404、非終端は 409 で削除しない | なし |
| 参照解除 | dispatch / one-shot / rerun 系譜 | `run_id` を NULL | 同一トランザクション | Jobs UI・Run 一覧 | 失敗時は全ロールバック | soft link の消失 |
| 履歴削除 | Event / Node / Activation / Run | `run_id` | ハード削除 | なし | 失敗時は全ロールバック | 実行履歴は復元不能 |
| 子 Run | 子集約の `child_run_id` | 変更なし | なし | Agent / Coding / HITL UI | — | なし |

## Consequences

- 実行履歴は復元できない。監査目的で Run を残す場合は削除しない（retention が 30 日で消す）。
- Scheduler Job の画面は「直近の Run は削除済み」を表示し、失敗と区別する。
- 発火枠・one-shot の行は残るため、スケジュールの監査と冪等性は壊れない。
- 子 Run（Agent / HITL など）の外部履歴は削除対象外であり、Run を消しても参照可能である。
