# Revision 削除ポリシー（draft / superseded のハード削除・Run 温存）

## Status

Accepted（2026-09-21）。

## Context

Revision に削除手段がなく、失敗した下書きや試行版が蓄積する。
公開ポインタは存在せず、`published` は `status='published'` のクエリで都度導出される。
外部キーは一切なく、全参照はソフトな TEXT 列である。

検討した選択肢：

1. **ハード削除（draft / superseded のみ）** — `published` は削除不可。Run は残す。
2. **ハード削除（published 含む）** — 唯一の `published` を削除すると Run 作成不可・次の下書きが白紙化するため、「公開解除」概念の追加設計が必要。
3. **ソフト削除（`archived`）** — spec が将来構想として言及済み。status CHECK 変更のためテーブル再構築マイグレーションが必要。

## Decision

選択肢 1 を採用する。

- 削除対象は `draft` / `superseded` のみ。`published` の削除は 409 で拒否する。
- 削除は `workflow_edges` → `workflow_nodes` → `workflow_revisions` の順に同一トランザクションで行う。
- 参照する Run は削除しない。Run は作成時点のグラフ・入力スナップショットを保持するため、閲覧・rerun に影響しない。
- `DELETE` 文自体に `status IN ('draft','superseded')` の条件を付け、公開との競合では公開側が勝つ（公開された行は `rowcount == 0` となる）。
- 削除後の `version` 再利用（`MAX(version)+1`）と、Run の `revision_id` の dangling は許容する。Revision の同一性は `revision_id` が担う。

## Consequences

- スキーマ変更・マイグレーションは不要。
- published を廃棄したい場合は新 Revision を公開して superseded 化してから削除する。
- 将来 `archived` を導入する場合は本 ADR を Superseded とし、テーブル再構築マイグレーションを設計する。
