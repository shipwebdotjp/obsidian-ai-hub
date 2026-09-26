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
  "retry": {"max_attempts": 1, "backoff_seconds": 0},
  "fail_on_output_mismatch": false
}
```

- `capability_key` は `task_agent_capabilities` に存在し `enabled=1` である必要があります。
- `target` は target を持つ Capability（`specialist_agent` / `coding_cli`）で必須です。
  エディタでは target 欄が表示され、`specialist_agent` は委譲先 Agent、`coding_cli` は対象 Project を選びます。
  値に型付き参照は使えません。
- `inputs` は Capability の入力 schema に対応する値、または [型付き参照](data-flow.md) です。
- `retry` は任意。`max_attempts` は非負整数です。
- `fail_on_output_mismatch`（既定オフ）をオンにすると、Capability が次の出力を返したとき Node を
  失敗させ、後続 Node へ渡しません（エディタの「エラー出力・schema不一致で失敗」）。
  指定できるのは structured の読み取り系（`vault_read_file`、`calendar_read`、
  `reminders_read`、`research_context_snapshot`）と `hitl_wait` だけです。
  それ以外の Capability での指定は検証エラーになります。
  - 出力が JSON object でない
  - 出力に `error` キーがある（例: `vault_read_file` のファイル不在 `{"error": "File not found"}`）
  - 宣言済みの出力 schema に一致しない（必須欠落・型違い・`null` を含む）
  - `calendar_read` / `reminders_read` で Apple / recurring の取得が不完全
    （部分結果はそのまま残りますが、strict Node は失敗して後続へ流しません）
  ファイル存在の確認など「無ければ止めたい」読み取り系で使います。新規の対象 Node は
  エディタで strict が既定オンになります。また、出力を参照するには参照先 Node の
  strict がオンであることが必要です。効果的 Capability の strict と
  `retry.max_attempts` の併用は、契約違反時に副作用が再実行されうるため、
  検証の警告を確認してください（読み取り系の retry は警告されません）。

### ワークフロー専用 Capability

`hitl_wait` はワークフロー専用の疑似 Capability で、常に有効・承認ポリシー `auto` です。
HITL へ質問を登録し、人間が回答するまで Node を `waiting_hitl` で待機させます。
回答後は `{"answer": "<文字列>"}` として自動的に再開します
（[Run・承認・復旧](runs.md#hitl-待ち) を参照）。`answer` は文字列へ正規化され、
`nodes.<node_id>.output.answer` で参照できます（strict が必要です）。

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

## llm Node（単発 LLM）

会話・ツールを持たない、1 回だけの LLM 呼び出しです。入力と `output_schema` を JSON で送り、
schema に沿った JSON を型付きで後続 Node へ渡します。Agent Node と違い会話・ツール・HITL を
持たないため、`agent_sessions` / `agent_messages` / `agent_runs` を作成しません。

```json
{
  "provider": "openai",
  "model": "gpt-5",
  "system_prompt": "入力テキストを分類してください。",
  "max_tokens": 4096,
  "reasoning_effort": "low",
  "inputs": {
    "text": {"$ref": "run.inputs.body"}
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "category": {"type": "string", "enum": ["a", "b"]},
      "confidence": {"type": "number"}
    },
    "required": ["category"]
  }
}
```

- `provider` — `openai` / `gemini` / `ollama` / `local` / `opencode_go` のいずれか。
- `model` — 必須。`max_tokens` — 必須の正整数。
- `system_prompt` — Revision に固定する文字列。動的な差し込みはできません。整形は前段の
  [テキスト組立](nodes.md#text_template-nodeテキスト組立) Node で行います。
- `reasoning_effort` — 任意。`openai` / `ollama` / `opencode_go` でのみ指定できます。
- `inputs` — 値または [型付き参照](data-flow.md) / 日時式のマッピングです。
- `output_schema` — 必須。Agent Node と同じ JSON Schema サブセットです。出力は
  `nodes.<node_id>.output.<field>` として参照できます。
- `temperature` は 0.7 固定です。`retry` など未知のキーは指定できません。
- エディタでは provider 選択、model、system prompt、max tokens、reasoning effort、inputs、
  output schema のフォームで編集できます。
- 出力が JSON object として解釈できない、または schema に一致しない場合、Node は失敗します。
  自動再送はしません（1 Activation につき外部送信は高々 1 回）。
- 副作用を持たず、Agent のような承認待ちにはなりません。request / response / token usage は
  実行ログ（LLM 呼び出しログ）に独立した行として記録されます。
- 外部 LLM への送信は取り消せません。送信前に取消が届いた場合は送信しません。送信中の取消は
  結果を監査用に残しつつ、後続 Node を実行せず Run を `cancelled` にします。

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

### エディタのプレビューと補完

- **描画プレビュー**: `サンプル値 (JSON)` に `inputs` の変数名をキーにしたサンプルを入力すると、
  実行を待たずに描画結果を確認できます。「雛形を生成」で型に応じた初期値を入れられます。
  サンプル値はエディタ内の一時状態で、Revision には保存されません。描画は実行時と同じ
  レンダラで行われるため、未定義変数・構文エラーもここで検出できます。
- **変数の補完**: 本文の `{{ }}` 内で入力変数名を補完します。`{% for event in events %}`
  のようなループでは `event.` に続けて参照先のフィールド（例: `event.title`）を補完します。
  変数チップをクリックするとカーソル位置に `{{ 変数名 }}` を挿入できます。

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
