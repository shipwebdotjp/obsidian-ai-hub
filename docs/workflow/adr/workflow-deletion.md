# Workflow 削除ポリシー（非終端 Run・Scheduler 参照を拒否、aggregate をハード削除）

## Status

Accepted（2026-09-22）。

## Context

Workflow 本体に改名・説明更新と削除の手段がなく、不要な Workflow を整理できない。
外部キーは一切なく、全参照はソフトな TEXT 列である（[workflow-revision-deletion.md](workflow-revision-deletion.md) と同じ前提）。
Run は `workflow_id` で Workflow に紐づくが、Run 一覧 API は Workflow 詳細からしか辿れず、
グローバルな Run 一覧は存在しない。

Revision 削除は「draft / superseded のみ削除、published は 409、Run は温存」とした。
Workflow 本体の削除はこれと異なり、published Revision を含む定義全体を対象にする必要がある
（不要な Workflow を残さないことが目的のため）。

検討した選択肢：

1. **aggregate 全体のハード削除** — 非終端 Run があれば 409、Scheduler Job 参照があれば 409。
   定義（Workflow / Revision / Node / Edge）と実行履歴（Run / Node / Activation / Event / dispatch）を
   同一トランザクションで削除する。
2. **定義のみ削除し Run は温存** — Revision 削除の前例に合わせる。ただし Workflow 詳細への導線が消え、
   `workflow_id` が dangling な Run だけが残る。非終端 Run は到達不能になる。
3. **Run が 1 件でもあれば削除拒否** — 最も保守的だが、不要 Workflow の整理用途で削除できない
   ケースが増える。

## Decision

選択肢 1 を採用する。

- 削除前に次を検証し、該当すれば 409 で拒否する。
  - 非終端 Run（`workflow_runs.status` が終端状態以外）が 1 件以上ある。進行中 Run の孤立を防ぐ。
  - Scheduler Job が対象 Workflow を参照している。
    - 定期 YAML ジョブ（`workflow.workflow_id`）は発火のたびに published Revision を解決するため、
      参照があれば先に変更・削除を求める。
    - one-shot の非終端ジョブ（`one_shot_jobs.target_kind='workflow'` かつ status が終端以外）。
      終端の one-shot は再発火しないため参照とみなさない。
- 検証後に 1 つのトランザクションで `workflow_events` → `workflow_run_nodes` → `workflow_activations`
  → `workflow_runs` → `workflow_edges` → `workflow_nodes` → `workflow_revisions`
  → `workflow_schedule_dispatches` → `workflows` の順に削除する。
- published Revision も定義の一部として削除する。Workflow が消えるため公開ポインタの概念も消える。
- 改名・説明更新は `PATCH /api/v1/workflows/:id` の部分更新とし、空名は 422 で拒否する。

## Consequences

- スキーマ変更・マイグレーションは不要。
- 実行履歴は復元できない。監査目的で Run を残したい場合は本 ADR を Superseded とし、
  Run 温存方式（選択肢 2）を再検討する。
- Scheduler Job を残したまま Workflow が消えることはない。Job 側の解除が先操作になる。
- 非終端 Run を持つ Workflow は、その Run を終端（完了・失敗・取消）させるまで削除できない。
