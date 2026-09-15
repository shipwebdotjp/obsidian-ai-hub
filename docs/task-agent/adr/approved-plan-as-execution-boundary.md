# 承認ポリシー付きPlanを実行境界にする

## Status

Accepted

## Context

個人用Task Agentでは、読取だけの依頼まで毎回承認すると自律性が失われる。一方、書込みや
Coding CLIのような副作用を含む依頼は、対象・能力・副作用を事前に確認できる必要がある。

## Decision

- Taskは常に内部Planを作るが、人間の承認はCapabilityの `approval_policy` に従う。
- Plan内に `plan_required` が一つでもあれば一括承認が必要で、すべて `auto` なら即時実行する。
- 承認対象はCapability、対象、入力、想定副作用、完了条件である。承認後のPlan外要求は停止し、
  同じTask IDの改訂Planを `waiting_reapproval` で再承認する。
- 差戻し理由は必須とする。実行器の逸脱検出は自己申告であり、親は技術的に完全保証しない。

## Consequences

- 低リスクの読取Taskは自律的に完了し、副作用を含むTaskだけが人間を待つ。
- Policyを緩めると承認なしの作用範囲が広がる。設定画面での変更は新規Planにのみ反映する。

## Alternatives

- 全Planを承認する: 予測可能だが、読取Taskまで手作業になり不採用。
- TaskごとにLLMが承認要否を決める: 自律的だが、挙動が予測不能で監査しづらく不採用。
- ステップごとの逐次承認: 安全だが、Taskの継続性を大きく損なうため不採用。
