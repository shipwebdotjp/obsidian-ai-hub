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

Edge の `condition`（条件付き排他的分岐）は、Edge 一覧の **条件** から編集できます
（後述の **参照ピッカー** で `from_path` を選べます）。

## Node の設定を編集する

Node を選択すると、右パネルに対応する設定欄が表示されます。入力もスキーマ定義も
ガイド付きフォームで編集できます。

| 種別 | 設定項目 |
| --- | --- |
| `capability` | `capability_key`（選択）、`inputs`（Capability の入力スキーマから生成。要承認は選択肢に表示）、`retry.max_attempts` |
| `agent` | `agent_id`（選択）、`inputs`（構造化エディタ。キーを追加し、各値は値か参照）、`output_schema`（スキーマ作成フォーム） |
| `loop` | `state_schema`（スキーマ作成フォーム）、`input_mapping`（`state_schema` から生成。各値は値か参照）、`max_iterations`、`entry_node_id`、`continuation_condition`（条件エディタ） |
| `loop_result` | `output_mapping`（親 Loop の `state_schema` から生成。各値は値か参照） |
| `terminal` | `outcome`（`success` / `failure`） |

- `capability` の `inputs` は、選択した Capability の入力スキーマから生成されます。`enum` は選択肢、
  `boolean` はチェックボックス、`integer` / `number` は数値入力になります。自由形式の項目は JSON 欄になります。
- `agent` の `inputs` はスキーマを持たない自由形式です。キーを追加し、各値はテキスト入力か
  **参照**（型付き参照）を選べます。`task` / `context` は入力候補として表示されます。
- `agent` の `output_schema`、`loop` の `state_schema`、右パネルの `inputs_schema` は
  **スキーマ作成フォーム** で編集します（後述）。

選択中の Node は **削除** できます。**Edge 一覧** から不要な Edge を削除できます。

## スキーマを作成する

`inputs_schema` / `output_schema` / `state_schema` は **スキーマ作成フォーム** で編集します。

- **プロパティを追加** — 名前を入れて **追加**。各行で型（`string` / `integer` / `number` / `boolean` /
  `object` / `array`）、**必須**、説明、`enum`（カンマ区切り、省略可）を設定します。
- `object` 型は入れ子のプロパティ、`array` 型は `items` の型と（`object` のとき）そのプロパティを編集できます。
- **未定義のプロパティを許可する** で `additionalProperties` を切り替えます。
- 上級者向けに **JSONで編集** で生 JSON に切り替えられます。ルートは `type: "object"` が必要です。
- 許可されるのはサブセットで、`object` / `properties` / `required`、primitive、`enum`、配列などです
  （`$ref` / `oneOf` / `anyOf` / `allOf` / 再帰は未対応）。違反はフォーム下部に表示されます。

定義した `inputs_schema` は **実行入力** フォーム（および Run の再実行フォーム）に反映されます。
ネストした `object` や配列にも対応します。

## 参照ピッカー（型付き参照）

`{"$ref": "..."}` の型付き参照は、**参照** ボタンからピッカーで選べます。ピッカーは
そのスコープで使える候補を型付きで一覧します。

- `run.inputs.<field>` — `inputs_schema` の各項目（ネストも展開、配列は `[0]` の例つき）。
- `nodes.<node_id>.output.<field>` — 先行 Node の出力。Agent は `output_schema`、
  Loop は `final_state.*` / `iterations` / `exit_reason`、Loop Result は `state_schema` の項目。
  Capability の出力は型が未宣言のため `nodes.<node_id>.output` 全体のみ表示します。
- `loop.state.<field>` / `loop.input.<field>` / `loop.iteration` — Loop 子グラフ内のみ。

候補は **候補から選ぶ** で開閉でき、検索欄で絞り込めます。**コピー** でパスをコピーできます。
候補を使わず直接入力することもできます（参照形式でない場合は警告が出ます）。

## 検証

- **ローカル検証** — 編集内容に対してクライアント側でも形状チェックが走り、問題は黄色で表示されます。
- **サーバー検証** — **検証** ボタンで `POST .../validate` を呼び、結果を赤色で表示します。
- **公開** はサーバー検証に合格した場合のみ実行されます。
- 問題の行をクリックすると、該当する Node（または Edge の source Node）を選択して
  キャンバス上にスクロールします。

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
