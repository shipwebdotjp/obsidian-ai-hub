---
sidebar_position: 3
title: エディタの使い方
---

# エディタの使い方

## Workflow を作成する

**ワークフロー** 一覧（`/workflows`）で名前と説明を入力し、**新規作成** を押すと、
空の `draft` Revision のエディタ（`/workflows/revisions/:revisionId/edit`）へ移動します。

または **テンプレートから作成** のボタンから、定義済みのグラフで開始できます
（[テンプレート](templates.md) を参照）。

## エディタの画面構成

上部ヘッダーに `workflow_id / v<version> (<status>)` が表示され、未保存の変更があると **未保存** が付きます。

| ボタン | 動作 |
| --- | --- |
| **保存** | `draft` Revision を保存する。公開済み / 旧版では保存されない。 |
| **検証** | 未保存があれば保存してからサーバー静的検証を実行する。 |
| **公開** | 保存後に検証し、合格すれば `published` にする。 |
| **実行** | 保存後、右側の **実行入力** を使って Run を作成する。 |
| **削除** | `draft` / 旧版 Revision を削除する。公開済み Revision には表示されない。 |

公開済み / 旧版の Revision では「このリビジョンは編集できません（実行のみ）」と表示されます。

:::warning[実行には公開が必要です]
Run は `published` Revision からしか作成できません。`draft` のまま **実行** すると
「Only a published revision can start a run.」で失敗します。先に **公開** してください。
:::

キャンバス上で Node をドラッグして位置を調整できます。

## Node を追加する

右パネルの **Node 追加** で種別を選び、**追加** を押します。

1. **種別** — `capability` / `agent` / `loop` / `terminal` / `loop_result`。
2. `capability` のときは **capability を選択** — 有効な Capability のみ表示され、`plan_required` のものには `(要承認)` が付きます。
3. `agent` のときは **Agent を選択** — 既存の Agent 一覧から選びます。
4. **親** — トップレベルに置くか、既存の Loop Node の子グラフに置くかを選びます（`loop_result` は子グラフ内でのみ有効）。

追加した Node は選択状態になり、右パネルで設定を編集できます。Node ID は UUID、`label` はテンプレート由来のものだけが設定されます。

## Edge を追加する

**Edge 追加** で source と target を選び、種別（`normal` / `error`）を決めて **Edge 追加** を押します。

- target には **同じスコープ**（トップレベル同士、または同じ Loop の子）にある Node だけが表示されます。
- 同じ source からの Edge は追加順に `order_index` が割り当てられます。

:::note[条件分岐の編集について]
現行のエディタの Edge 追加 UI は source / target / 種別（`normal` / `error`）のみを設定します。
Edge の `condition`（条件付き排他的分岐）はグラフモデルおよび検証・実行エンジンには存在しますが、
キャンバス UI からの編集コントロールは用意されていません。条件を使うグラフは API 経由で作成・更新します。
:::

## Node の設定を編集する

Node を選択すると、右パネルに対応する設定欄が表示されます。JSON 欄は直接編集でき、
不正な JSON を入力すると「JSON が不正です」と表示されます。

| 種別 | 設定項目 |
| --- | --- |
| `capability` | `capability_key`（選択）、`inputs`（JSON） |
| `agent` | `agent_id`（選択）、`inputs`（JSON）、`output_schema`（JSON） |
| `loop` | `state_schema`、`input_mapping`、`max_iterations`、`entry_node_id`、`continuation_condition` |
| `loop_result` | `output_mapping`（JSON） |
| `terminal` | `outcome`（`success` / `failure`） |

選択中の Node は **削除** できます。**Edge 一覧** から不要な Edge を削除できます。

## 入力スキーマ（inputs_schema）

右パネルの **入力 Schema** に、Run 開始時に入力する値の JSON Schema を定義します。
許可されるのはサブセットで、`object` / `properties` / `required`、primitive、`enum`、配列などです
（`$ref` / `oneOf` / `anyOf` / `allOf` / 再帰は未対応）。

## 検証

- **ローカル検証** — 編集内容に対してクライアント側でも形状チェックが走り、問題は黄色で表示されます。
- **サーバー検証** — **検証** ボタンで `POST .../validate` を呼び、結果を赤色で表示します。
- **公開** はサーバー検証に合格した場合のみ実行されます。

検証で検出される代表的なエラーは [制約とトラブルシューティング](limits.md#検証エラー) を参照してください。

## Run を開始する

1. グラフを **保存** し、**公開** します。
2. 右パネルの **実行入力** に値を入れます（`inputs_schema` からフォームが生成されます）。
3. **実行** を押します。

`plan_required` の Capability か Agent Node を含む場合、Run は `waiting_approval` で作成され、
Run 詳細で承認するまで実行されません（[Run・承認・復旧](runs.md) を参照）。

## Revision を追加する

Workflow 詳細（`/workflows/:workflowId`）で **新しい下書き** を押すと、
次のバージョンの `draft` Revision が作成されます。公開済み Revision は編集できないため、
変更は新しい下書きで行います。

- 公開済み Revision がある場合、その **Node / Edge / 入力 Schema などのグラフ内容が
  複製** され、新しい ID が割り当てられた `draft` として作成されます。キャンバスの
  配置（`ui_position`）や Loop の子グラフ構成・型付き参照も引き継がれます。
- 公開済み Revision がない場合（作成直後の最初の下書きを除く）は、空のグラフ・
  既定の `inputs_schema` で開始します。
- 複製元の公開済み Revision は変更されません。下書き側を編集しても複製元には影響しません。

## Revision を削除する

`draft` と旧版（`superseded`）の Revision は、エディタの **削除** ボタンか Workflow 詳細の一覧から削除できます。
公開済み（`published`）の Revision は削除できません。

- 削除は確認後に実行され、取り消せません。グラフ（Node / Edge）ごと削除されます。
- 削除した Revision を参照する Run は残ります。Run はグラフをスナップショットとして保持しているため、
  閲覧や再実行（rerun）に影響しません。

## 次に読む

- [Node リファレンス](nodes.md)
- [データの受け渡し](data-flow.md)
- [Run・承認・復旧](runs.md)
