---
sidebar_position: 2
title: 用語と状態
---

# 用語と状態

## 構成要素

| 用語 | 意味 |
| --- | --- |
| **Workflow** | 恒久 ID・名前・説明を持つワークフロー本体。Revision の集合。 |
| **Workflow Revision** | 1 つのグラフ定義。`draft` / `published` / `superseded` の状態を持つ。 |
| **Node** | グラフ上の処理単位。`capability` / `agent` / `loop` / `terminal` / `loop_result` の 5 種。 |
| **Edge** | Node 間の接続。`normal` または `error`。 |
| **Workflow Run** | Revision の 1 回の実行単位。 |
| **Activation** | ある Node が、ある経路・Loop 反復で論理的に 1 回起動された単位。永続 UUID を持つ。 |
| **Capability Node** | 既存 Capability を呼び出す Node。 |
| **Agent Node** | 既存の Agent を呼び出し、出力を JSON Schema で検証する Node。 |
| **Loop Node** | 非循環の子グラフを上限付きで反復する Node。 |
| **Loop Result Node** | Loop 子グラフの終端。次の `loop.state` を返す。 |
| **Terminal Node** | グラフの終端。`success` または `failure`。 |
| **型付き参照** | `run.inputs.*` / `nodes.<node_id>.output.*` / `loop.state.*` の形で値を渡す仕組み。 |
| **Effect** | Capability が成功時に成立させる、コードで宣言された事後条件。 |

## Revision のライフサイクル

| 状態 | 意味 |
| --- | --- |
| `draft` | 編集可能。 |
| `published` | 公開済みで不変。Run はここから作成する。 |
| `superseded` | 新しい `published` が作成された旧版。参照は可能だが新規 Run には使わない。 |

- `draft` のみ編集できます。公開済み Revision を編集するには、Workflow 詳細で **新しい下書き** を作成します。
- 新しい下書きは、公開済み Revision がある場合はそのグラフ（Node / Edge / 入力 Schema・
  レイアウト・Loop 構成・型付き参照）を **複製** して開始します。複製時には新しい Node / Edge ID が
  割り当てられ、複製元の公開済み Revision は不変のまま保たれます。公開済み Revision がない場合は
  空のグラフ・既定の `inputs_schema` で開始します。
- 公開のたびに新しい `published` Revision が作られ、それ以前の `published` は `superseded` になります。
- `draft` と `superseded` の Revision は削除できます（[エディタの使い方](editor.md#revision-を削除する) を参照）。
  `published` は削除できません。削除しても Run は残り、参照したグラフは Run 側のスナップショットで閲覧・再実行できます。
- Run は作成時点の `revision_id` とグラフ・入力をスナップショットとして保持します。公開後に Capability / Agent を変更しても既存 Run には影響しません。

## グラフの構造規約

- **非循環（DAG）** — 通常の Edge は循環できません。静的検証で検証されます。
- **反復は Loop Node の中だけ** — 反復は Loop Node の非循環な子グラフで表現します。
- **Loop のネスト不可** — Loop 子グラフの中に `loop` Node は置けません。
- **OR 合流のみ** — 複数の source Node から同じ target Node へ Edge を張れます。Node は最初に到達した経路で一度だけ実行されます。並列実行 / AND join はありません。
- **entry は 1 つ** — トップレベルグラフには、入辺のない entry Node がちょうど 1 つ必要で、そこから全 Node へ到達できる必要があります。
- **Loop 子グラフ** — 1 つの `loop_result` で終わり、`entry_node_id` から全子 Node へ到達でき、全子 Node から `loop_result` へ到達できる必要があります。
- **Terminal Node に outgoing Edge は不可**。

## Edge

- `normal` — source Node の成功時に評価されます。
- `error` — source Node の失敗時に使われます。複数ある場合は最初の 1 本だけを使い、存在しなければ Run は `failed` になります。
- **条件付き Edge は排他的** — source からの outgoing Edge を `order_index` 順に評価し、最初に真になった Edge の target へ進みます。すべて偽で条件なし Edge もなければ Run は `failed` になります。

## Run の状態

| 状態 | 意味 |
| --- | --- |
| `queued` | 作成済み。worker の実行待ち。 |
| `waiting_approval` | `plan_required` Capability / Agent Node を含み、承認待ち。 |
| `running` | 実行中。 |
| `waiting_hitl` | HITL へ質問を登録済み。回答待ち。 |
| `waiting_attention` | 非冪等 Node が中断した、または取消要求後に外部処理が完了・結果不明。人間対応待ち。 |
| `cancelling` | 取消要求を受け、協調的取消処理中（画面表示は **停止要求中**）。 |
| `interrupted` | worker 停止などで中断。明示的な再開が必要。 |
| `completed` | 成功 Terminal に到達し、効果が満たされた終端状態。 |
| `incomplete` | 終端には到達したが効果未達、または Loop 上限到達。失敗ではない。 |
| `failed` | 失敗 Terminal 到達、または実行時エラー。 |
| `cancelled` | 協調取消を確認して終端。外部処理の結果が完了・不明なら `waiting_attention` に回る。 |

終端状態（`completed` / `incomplete` / `failed` / `cancelled`）からは遷移しません。
取消はロールバックではなく要求であり、実施済みの副作用は巻き戻りません。

## Node の状態

`pending` / `running` / `waiting_hitl` / `succeeded` / `skipped` / `failed` / `needs_attention` / `cancelled`。

- `skipped` は分岐の結果到達しなかった Node。
- `needs_attention` は非冪等 Node が外部操作中に中断した状態で、人間の判断を待ちます。

## 完了の判定

完了は LLM の自己申告ではなく、**効果（Effect）の成立** で決まります。

- 実際に実行された効果的な Node の `satisfied_effects` を収集します。
- 成功 Terminal に到達した時点で、必要な効果がすべて成立していれば `completed`。
- 不足していれば `incomplete`（失敗ではない）。
- Loop が `max_iterations` に達した場合も `incomplete`。
- 失敗 Terminal 到達や実行時エラーは `failed`。

## 次に読む

- [エディタの使い方](editor.md)
- [Node リファレンス](nodes.md)
