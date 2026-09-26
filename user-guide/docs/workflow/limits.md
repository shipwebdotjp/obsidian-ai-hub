---
sidebar_position: 8
title: 制約とトラブルシューティング
---

# 制約とトラブルシューティング

## 実行上限・制約

| 項目 | 制限 |
| --- | --- |
| Revision あたりの Node 数 | 最大 **30** |
| Revision あたりの Edge 数 | 最大 **60** |
| Loop の `max_iterations` | **1〜50** |
| Loop のネスト | 不可 |
| 通常 Edge の循環 | 不可 |
| 並列 Node / fork / AND join | 不可（OR 合流のみ） |
| 任意コード Node | 不可 |
| Agent Node ごとの prompt / model / tool 上書き | 不可 |
| Workflow 全体のタイムアウト | なし（各 Capability / 子 Run のタイムアウトに従う） |
| 定義 package の形式 | JSON / YAML の v1 のみ（zip・一括 import / export は不可） |
| 定義 package のサイズ | 最大 1 MiB |
| Workflow ごとの同時実行数制御 | 不可（発火ごとに Run を作成） |
| 承認待ち Run の自動失効・抑止 | 不可（人間が取消・無効化） |

### ユーザーテンプレートと import / export の制約

- Template は**公開済み Revision からのみ**作成・内容更新できます。draft は対象外です。
- Template 利用（instantiate）と import は、常に**新しい Workflow の下書き**を作ります。
  実行・公開・Scheduler 登録は自動では行いません。
- import は現在の環境の Capability / Agent で再検証されます。未知の Capability / Agent があると
  下書きと検証エラーが作られ、そのままでは公開できません。
- package の形式違反（未知 version・不正 YAML・サイズ超過・重複 ID・不正参照）は拒否され、
  DB には何も作られません。
- package には実行履歴・Scheduler 設定・秘密値は含まれません。秘密値を定義に書かないでください。
- Template の削除は Template 行だけを消し、そこから作成済みの Workflow・Run・Scheduler Job は
  変更しません。

### JSON Schema のサブセット

許可: `object` / `properties` / `required`、primitive（string / integer / number / boolean）、`enum`、配列、
および `additionalProperties` / `description` / `title` / `default` / `minimum` / `maximum` /
`minLength` / `maxLength` / `minItems` / `maxItems` / `pattern` など一部の制約。

未対応: `$ref` / `oneOf` / `anyOf` / `allOf` / `not` / `const` / `if`-`then`-`else` / 再帰など。

## 検証エラー

公開時の検証で検出される代表例:

- **未知の Capability** — `Capability '<key>' は無効です`。Capability が `enabled` か確認します。
- **存在しない Agent** — `Agent '<id>' が存在しません`。
- **循環 Edge** — `cycle: ...グラフに循環 Edge があります`。
- **Loop ネスト** — `loop_nested: ... Loop Node のネストは未対応です`。
- **loop_result の数** — 子グラフに `loop_result` がちょうど 1 つ必要です。
- **entry の数** — トップレベルに entry Node（入辺なし）がちょうど 1 つ必要です。
- **到達不能 Node** — entry から、または `loop_result` へ到達できない子 Node がある。
- **参照スコープ** — `reference_scope: ... 参照先 Node は同一スコープにありません` など。
- **branch の継続条件未指定** — Loop の `continuation_condition` は必須です。

エディタではローカル検証（黄色）とサーバー検証（赤色）が別々に表示されます。
**公開** はサーバー検証に合格した場合だけ実行できます。

## よくあるつまずき

### 「実行」で Run が作成できない

Run は `published` Revision からのみ作成できます。`draft` のまま **実行** すると
`Only a published revision can start a run.` で失敗します。先に **公開** してください。

### 公開済み Revision を編集できない

`published` / `superseded` は不変です。Workflow 詳細で **新しい下書き** を作成し、
そこを編集してください。新しい下書きは公開済み Revision のグラフを複製して始まります
（公開済み Revision がない場合のみ空のグラフで始まります）。

### 承認しても実行されない／進まない

- Web サーバー（worker）が停止していないか確認します。停止中は `queued` のまま進みません。
- Capability や Agent が実行時に無効化されていると `interrupted` で停止します。再開に進みません。

### `incomplete` になった

失敗ではありません。次のいずれかです。

- 実行した効果的 Node の Effect が不足している。
- Loop が `max_iterations` に達した。

内容を確認し、必要なら再実行してください。

### `waiting_attention` になった

Agent / Coding などの非冪等 Node が外部操作中に中断した状態です。
Run 詳細で **採用して続行** / **再実行** / **失敗として処理** のいずれかを選びます。
重複副作用の可能性を確認してから **再実行** してください。

### Edge の条件（condition）の編集

Edge の `condition`（条件付き排他的分岐）は、Edge 一覧の **条件** から編集できます。
Loop の `continuation_condition` も同様の条件エディタで編集します。
詳しくは [エディタ](editor.md) と [データフロー](data-flow.md) を参照してください。

## 運用上の注意

- Workflow worker は Web サーバーの lifespan に同居します。**サーバー停止中は新規実行が進みません。**
- 終端 Run とその Node・Activation・Event は 30 日後に削除されます。
- 自動ロールバックは行いません。実施済みの副作用は人間が確認・処置します。
- Run 入力に秘密値を入れないでください。Scheduler Job の固定入力も平文で保存されるため同様です。
- Scheduler Job からの発火は `job_runner` が Run を作成し、実行は Workflow worker が担います。承認待ち Run は発火ごとに作られ、自動では失効しません。
- **承認なしで実行する** を有効にした Workflow は、Scheduler 発火でも承認なしで実行されます。無人の外部副作用が起きうるため、対象 Workflow と Agent の権限を確認してから有効にしてください。

## 次に読む

- [Run・承認・復旧](runs.md)
- [ワークフロー概要](index.md)
