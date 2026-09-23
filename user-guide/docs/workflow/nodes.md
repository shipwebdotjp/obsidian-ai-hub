---
sidebar_position: 4
title: Node リファレンス
---

# Node リファレンス

Node は `config_json` に種別ごとの設定を持ちます。エディタでは、Capability 入力・
Loop の入出力マッピング・Agent 入力・スキーマ定義（`inputs_schema` / `output_schema` /
`state_schema`）をガイド付きフォームで編集できます（[エディタの使い方](editor.md) を参照）。

## capability Node

既存 Capability を呼び出します。

```json
{
  "capability_key": "vault_write_file",
  "target": {},
  "inputs": {
    "relative_path": {"$ref": "run.inputs.output_path"},
    "content": {"$ref": "nodes.<agent_node_id>.output.note_body"}
  },
  "retry": {"max_attempts": 1, "backoff_seconds": 0}
}
```

- `capability_key` は `task_agent_capabilities` に存在し `enabled=1` である必要があります。
- `target` は target を持つ Capability（`specialist_agent` / `coding_cli`）で必須です。
  エディタでは target 欄が表示され、`specialist_agent` は委譲先 Agent、`coding_cli` は対象 Project を選びます。
  値に型付き参照は使えません。
- `inputs` は Capability の入力 schema に対応する値、または [型付き参照](data-flow.md) です。
- `retry` は任意。`max_attempts` は非負整数です。

### ワークフロー専用 Capability

`hitl_wait` はワークフロー専用の疑似 Capability で、常に有効・承認ポリシー `auto` です。
HITL へ質問を登録し、人間が回答するまで Node を `waiting_hitl` で待機させます。
回答後は自動的に再開します（[Run・承認・復旧](runs.md#hitl-待ち) を参照）。

## agent Node

既存の Agent を呼び出し、出力を JSON Schema で検証します。

```json
{
  "agent_id": "agent_abc123",
  "inputs": {
    "task": {"$ref": "run.inputs.task"},
    "context": {"$ref": "nodes.<capability_node_id>.output.results"}
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "plan": {"type": "string"},
      "risks": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["plan"]
  }
}
```

- `agent_id` は既存 Agent の ID。**Node ごとの prompt / model / tool 上書きはできません。**
- `output_schema` は必須で、JSON Schema サブセット（`object` / `properties` / `required`、primitive、`enum`、配列）のみ許可されます。
- 実行時は Agent の最新設定が使われ、開始時点の設定指紋が監査用に記録されます。
- Agent の最終出力が `output_schema` に合わない場合、Node は失敗します。

## loop Node

非循環の子グラフを反復実行します。

```json
{
  "state_schema": {
    "type": "object",
    "properties": {
      "draft": {"type": "string"},
      "review_comment": {"type": "string"},
      "iteration": {"type": "integer"}
    },
    "required": ["draft"]
  },
  "input_mapping": {
    "draft": {"$ref": "nodes.<plan_node_id>.output.plan"},
    "iteration": 0
  },
  "continuation_condition": {
    "from_path": "loop.state.review_comment",
    "operator": "equals",
    "value": ""
  },
  "max_iterations": 5,
  "entry_node_id": "<child_node_id>"
}
```

- `state_schema` — 反復状態の型。必須。
- `input_mapping` — 初回の `loop.state` 初期値。親スコープの参照を使えます。
- `continuation_condition` — 真の間、反復を続けます。必須（未指定は検証エラー）。
- `max_iterations` — 1〜50。上限到達時は `exit_reason=max_iterations_reached` で終了し、Run は `incomplete` になります。
- `entry_node_id` — 子グラフの開始 Node。子グラフ内の Node を指す必要があります。
- Loop 終了時、親グラフへ `final_state` / `iterations` / `exit_reason` を出力します。

## loop_result Node

Loop 子グラフの終端です。次の `loop.state` を返します。

```json
{
  "output_mapping": {
    "draft": {"$ref": "nodes.<draft_node_id>.output.draft"},
    "review_comment": {"$ref": "nodes.<review_node_id>.output.comment"},
    "iteration": {"$ref": "loop.iteration"}
  }
}
```

子グラフには `loop_result` がちょうど 1 つ必要です。

## text_template Node（テキスト組立）

複数の値を文章へ組み立てる純粋な Node です。出力は常に `nodes.<node_id>.output.text`
（string）で、後続 Node から型付き参照できます。

```json
{
  "inputs": {
    "events": {
      "$ref": "nodes.<calendar_node_id>.output.events",
      "pipe": [{ "op": "slice", "args": { "limit": 5 } }]
    }
  },
  "template": "今週の予定:\n{% for event in events %}- {{ event.title }}\n{% endfor %}"
}
```

- `inputs` は変数名 → 値・[型付き参照](data-flow.md)・日時式のマッピングです。参照には
  [パイプ](data-flow.md#パイプpipe)を付けられます。
- `template` は Jinja2。`{% if %}` / `{% for %}` と標準フィルターが使えます。未定義変数は
  失敗します（`StrictUndefined`）。
- テンプレート本文は 16 KiB、描画結果は 64 KiB までです。超過は Node 失敗になります。
- 副作用が無いため、単体では承認を必要としません。
- 外部 I/O の前処理はここで完結させ、Capability / Agent には整形済みの文字列を渡すのが
  基本です。

## terminal Node

グラフの終端です。

```json
{
  "outcome": "success"
}
```

`outcome` は `success` または `failure`。`failure` Terminal に到達すると Run は `failed` になります。
outgoing Edge は持てません。

## 子グラフ内で使える参照

Loop の子グラフ内では、親と同じ型付き参照に加えて次が使えます。

- `loop.state.<field>` — 現在の反復状態。
- `loop.input.<field>` — `input_mapping` で与えた初期入力。
- `loop.iteration` — 現在の反復番号（integer）。

`loop.*` は Loop 子グラフの外では使えません。

## 次に読む

- [データの受け渡し](data-flow.md)
- [制約とトラブルシューティング](limits.md)
