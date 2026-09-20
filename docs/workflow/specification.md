# Workflow 仕様書（Graph / Agent Node / Loop Node 版）

Status: Accepted（再設計後 Phase 0 設計決定。実装未着手）

この文書は、`obsidian-ai-hub` における **Workflow** Bounded Context の外部契約と振る舞いを定める。
Workflow は人間が Web UI で設計する **Node / Edge グラフ** である。制御・データフローは決定的だが、
Agent Node の LLM 出力は確率的で、JSON Schema によって検証・型付きで後続 Node へ受け渡す。

再設計前の線形 Step モデルは撤回された。設計判断の正本は
[adr/workflow-graph-and-agent-node.md](adr/workflow-graph-and-agent-node.md) とする。

## 1. 目的、用語、スコープ

### 1.1 目的

- 人間が GUI で「計画 → レビュー → 改稿」や「文脈付きリサーチ」のような反復的・型付きの定型フローを
  設計・保存・検証・実行・監査できること。
- LLM 出力を安全に Capability 入力に連携しつつ、グラフ全体の制御は決定的に再現できること。
- Task Agent の承認境界・効果契約・HITL 基盤を再利用しつつ、Workflow 固有のグラフ実行・Agent Node・
  Loop Node の契約を追加すること。

### 1.2 用語

| 用語 | 定義 |
| --- | --- |
| **Workflow** | 恒久 ID・名前・説明を持つワークフロー本体。Revision の集合。 |
| **Workflow Revision** | 1 つのグラフ定義。`draft`/`published`/`superseded` の状態を持つ。 |
| **Node** | グラフ上の 1 つの処理単位。`capability` / `agent` / `loop` / `terminal` / `loop_result` の種別がある。 |
| **Edge** | Node 間の接続。条件付きの排他的分岐を持つ。 |
| **Capability Node** | 既存 Capability Adapter を呼び出す Node。 |
| **Agent Node** | 既存 `agents` テーブルの Agent を呼び出し、JSON Schema で出力を検証する Node。 |
| **Loop Node** | 非循環の子グラフを反復実行する Node。`loop.state` を所有する。 |
| **Loop Result Node** | Loop Node 子グラフの終端。次の `loop.state` を返す。 |
| **Terminal Node** | グラフの終端。`success` または `failure` の outcome を持つ。 |
| **Workflow Run** | Revision の 1 回の実行単位。 |
| **Activation** | ある Node が、ある Loop 反復・経路で論理的に 1 回起動された単位の永続 UUID。 |
| **InvocationContext** | Capability Adapter 実行時に渡される実行文脈（run_id, node_id, activation_id 等）。 |
| **型付き参照** | `run.inputs.*` / `nodes.<node_id>.output.*` / `loop.state.*` の形式で値を参照する仕組み。 |
| **Effect** | Capability が成功時に成立させる検査可能な事後条件。 |

### 1.3 スコープ

**範囲**: Workflow / Revision / Node / Edge / Loop 子グラフの CRUD・検証、Capability Node、
Agent Node、Loop Node（非ネスト）、terminal / loop_result Node、型付き inputs_schema、型付き参照、
条件付き排他的分岐、OR 合流、承認（`waiting_approval`）、HITL wait（`waiting_hitl`）、
`needs_attention` / `waiting_attention`、中断・再開・キャンセル、効果契約による動的完了判定、
Event 監査、redaction・30 日保持、バックエンド API、GUI / SSE（後続フェーズ）。

**対象外**: 並列 Node / fork / AND join、Loop ネスト、任意の循環 Edge、任意コード Node、
Agent Node ごとの prompt/model/tool 上書き、$ref/oneOf/再帰を含む JSON Schema、Workflow 独自の
長期 Artifact ストア、Scheduler Job からの Workflow 起動、専用 worker、完了通知外部入口、
定義のインポート / エクスポート。

## 2. 主要ユースケースと操作シナリオ

### 2.1 主要ユースケース

1. **機能追加の計画 → レビュー → 改稿 → 実行**
   - Planner Agent Node が計画を出力 → Reviewer Agent Node がレビュー → 条件分岐で改稿ループ
     （Loop Node）→ 承認後 Coding Capability Node で実行。
2. **文脈付きリサーチ**
   - Vault / Activity / 既存テーマを読み取る Capability Node → テーマ整形 Agent Node →
     `research_agent` Capability Node → Vault 書き込み Capability Node。
3. **定型タスクの承認付き自動化**
   - 人間が設計した Capability グラフを手動実行。`plan_required` Capability を含む場合は
     一括承認してから実行。

### 2.2 操作シナリオ契約

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 定義作成 | Capability schema / Agent 選択 / Edge 条件 | `node_id` / `edge_id` | `workflow_nodes` / `workflow_edges` | 静的検証・公開 | schema 不一致は保存 / 検証拒否 | なし |
| Revision 公開 | 検証済みグラフ + inputs_schema | `revision_id` / `version` | `workflow_revision` status 更新 | Run 作成 | 未検証は公開不可 | なし |
| Run 作成 | `revision_id` + 利用者入力 | `run_id` | `workflow_runs` + スナップショット | worker | archived / 未公開は拒否 | なし |
| 承認判定 | `task_agent_capabilities.approval_policy` + 選択 Agent ID | policy snapshot | `workflow_events` | worker | `plan_required` あれば `waiting_approval` | なし |
| Node 実行 | 検証済み入力 + InvocationContext | `activation_id` / `node_id` | `workflow_run_nodes` / `workflow_activations` | 次 Edge | validation 失敗は実行しない | Capability 副作用 |
| Loop 反復 | 子グラフ + `loop.state` | `iteration` / activation_id | `workflow_events` | Loop Node | 上限到達は `incomplete` | 子 Capability 副作用 |
| Agent Node | Agent 選択 + 期待 schema | `agent_id` / child_run_id | Agent 会話 + `workflow_events` | 後続 Node | JSON 検証失敗は Node 失敗 | Agent 子 Run 作成 |
| HITL 質問 | `hitl_wait` Capability | `hitl_run_id` | `workflow_events` | HITL 回答後の worker | — | HITL run 作成 |
| needs_attention | 子 Run 結果 | `node_id` | `workflow_events` | 人間 | 自動再開しない | 子 Run 継続の可能性 |
| 完了 | 成功 Terminal + 効果集合 | `run_id` | `workflow_runs` | 閲覧者 | 効果未達は `incomplete` | — |

## 3. Workflow / Revision / Node / Edge

### 3.1 Workflow

```text
workflow_id TEXT PRIMARY KEY
name TEXT NOT NULL
description TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

Workflow は名前・説明の恒久 ID だけを持ち、グラフの実体は Revision に属する。

### 3.2 Workflow Revision

```text
revision_id TEXT PRIMARY KEY
workflow_id TEXT NOT NULL
version INTEGER NOT NULL
status TEXT NOT NULL CHECK(status IN ('draft','published','superseded'))
inputs_schema TEXT NOT NULL  -- JSON Schema（サブセット）
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
```

- `draft` のみ編集可能。`published` は不変。
- `published` を編集する場合、新しい `version` の `draft` を作成する。
- Run は `revision_id` とその時点のグラフ・inputs をスナップショットして実行する。

### 3.3 Node

```text
node_id TEXT PRIMARY KEY
revision_id TEXT NOT NULL
node_type TEXT NOT NULL CHECK(node_type IN ('capability','agent','loop','terminal','loop_result'))
label TEXT
config_json TEXT NOT NULL
parent_loop_node_id TEXT        -- Loop 子グラフ内の Node のみ非 NULL
ui_position_json TEXT
```

`config_json` は Node 種別ごとに異なる。

#### capability

```json
{
  "capability_key": "vault_write_file",
  "inputs": {
    "relative_path": "notes/{{run.inputs.title}}.md",
    "content": {"$ref": "nodes.agent_xxx.output.note_body"}
  },
  "retry": {"max_attempts": 1, "backoff_seconds": 0}
}
```

- `inputs` は Capability の Pydantic schema に対応する値または型付き参照。
- `retry` は非負整数。

#### agent

```json
{
  "agent_id": "agent_abc123",
  "inputs": {
    "task": {"$ref": "run.inputs.task"},
    "context": {"$ref": "nodes.cap_xxx.output.results"}
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

- `agent_id` は既存 `agents` テーブルの ID。
- `output_schema` は JSON Schema サブセット。
- Node ごとの prompt/model/tool 上書きは v1 では行わない。

#### loop

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
    "draft": {"$ref": "nodes.plan_agent.output.plan"},
    "iteration": 0
  },
  "continuation_condition": {
    "from_path": "loop.state.review_comment",
    "operator": "equals",
    "value": ""
  },
  "max_iterations": 5,
  "entry_node_id": "node_draft_agent"
}
```

- `state_schema` は反復状態の型。
- `input_mapping` は初回の `loop.state` 初期値。
- `continuation_condition` が真の間反復を続ける。
- `entry_node_id` は子グラフ内の開始 Node。

#### terminal

```json
{
  "outcome": "success"
}
```

`outcome` は `success` または `failure`。

#### loop_result

```json
{
  "output_mapping": {
    "draft": {"$ref": "nodes.draft_agent.output.draft"},
    "review_comment": {"$ref": "nodes.review_agent.output.comment"},
    "iteration": {"$ref": "loop.state.iteration"}
  }
}
```

- 子グラフ内の終端 Node。
- 出力は `state_schema` と一致する。

### 3.4 Edge

```text
edge_id TEXT PRIMARY KEY
revision_id TEXT NOT NULL
source_node_id TEXT NOT NULL
target_node_id TEXT NOT NULL
condition_json TEXT            -- NULL なら常に真
order_index INTEGER NOT NULL
```

- 条件付き Edge は **排他的** に評価する。source Node からの outgoing Edge を `order_index` 順に評価し、
  最初に真になった Edge の target へ進む。
- 条件がすべて偽で default Edge（条件なし）もない場合、Run は `failed` とする。
- 複数の Edge が同じ target を指す **OR 合流** を許可する。Node は最初に到達した一度だけ実行する。

### 3.5 型付き参照

Node 間のデータ連携は文字列テンプレート展開ではなく、以下の型付き参照のみとする。

- `run.inputs.<field_path>` — Run 開始時の入力値。
- `nodes.<node_id>.output.<field_path>` — 先行 Node の出力。
- `loop.state.<field_path>` — Loop Node 子グラフ内でのみ利用可能な反復状態。

参照は静的検証で解決可能性を確認し、実行直前に値を解決してから Pydantic / JSON Schema で検証する。

## 4. グラフの構造規約

### 4.1 非循環性

- 通常の Edge は循環不可。静的検証で DAG を検証する。
- 反復は Loop Node 子グラフ内で完結する。子グラフも非循環。
- Loop Node はネスト不可。子グラフ内に `loop` 型 Node があれば静的検証エラー。

### 4.2 Loop Node の子グラフ

- 子グラフは親と独立した `node_id` / `edge_id` 集合を持ち、`parent_loop_node_id` で所有関係を記録する。
- 子 Node から親 Node へ直接 Edge を張らない。
- 子グラフは必ず 1 つの `loop_result` Node で終わる。すべてのパスが `loop_result` に到達することを
  静的検証で確認する。
- 子グラフ内では `loop.input` / `loop.iteration` / `loop.state` を型付き参照できる。
- Loop Result Node の出力が次の `loop.state` となる。
- Loop Node は継続条件と `max_iterations` を判定し、終了時に親グラフへ
  `final_state`、`iterations`、`exit_reason` を出力する。
- `exit_reason`:
  - `condition_satisfied` — 継続条件が偽になり正常終了。
  - `max_iterations_reached` — 上限到達。

### 4.3 合流

- OR 合流のみ許可する。複数の source Node から同じ target Node へ Edge を張れる。
- target Node は最初に到達した active path で一度だけ実行する。
- AND join / 並列実行は v1 では行わない。

## 5. Revision のライフサイクル

| From | To | 条件 |
| --- | --- | --- |
| `draft` | `published` | 静的検証に合格したとき |
| `published` | `superseded` | 新しい `published` Revision が作成されたとき |
| `published` | `archived`（将来） | 手動。v1 では `superseded` で代替。 |
| `draft` | `draft`（新 version） | 公開済み Revision を編集する場合 |

- `published` Revision のグラフは不変。
- Run は `revision_id` をスナップショットとして保持する。公開後の Capability / Agent / Policy 変更は
  既存 Run には影響しない。

## 6. 静的検証と動的検証

### 6.1 静的検証（保存 / 公開 / 検証 API）

- `inputs_schema` / `output_schema` / `state_schema` が許可された JSON Schema サブセット内であること。
- 全 Node ID / Edge ID が UUID 形式で一意であること。
- `capability_key` が `task_agent_capabilities` に存在し `enabled=1` であること。
- `agent_id` が `agents` テーブルに存在すること。
- Edge の source/target が同一 Revision（または同一 Loop 子グラフ）内に存在すること。
- 通常 Edge が循環していないこと。
- Loop Node の子グラフが非循環で、1 つの `loop_result` に到達すること。
- Loop Node がネストされていないこと。
- Terminal Node に outgoing Edge がないこと。
- 型付き参照が解決可能であり、参照先の型と一致すること。
- 秘密値を含む入力が固定値として保存されていないこと（UI 警告 + 検証ヒューリスティック）。

### 6.2 動的検証（Run 開始直前 / Node 実行直前）

- Revision が `published` であること。
- Capability / Agent がまだ有効であること。無効化されていれば `interrupted` 停止。
- `plan_required` Capability または Agent Node を含む場合、`waiting_approval` へ遷移する。
- Node 入力の型付き参照を解決し、schema で完全検証する。
- 実行時に Loop 子グラフの entry_node_id / loop_result 到達可能性を再確認する。

## 7. Run と Node の状態遷移

### 7.1 Run の状態

| 状態 | 意味 |
| --- | --- |
| `queued` | Run 作成済み。worker claim 待ち。 |
| `waiting_approval` | `plan_required` Capability / Agent を含み、承認待ち。 |
| `running` | Node 実行中。 |
| `waiting_hitl` | HITL 質問登録済み、回答待ち。worker claim を解放。 |
| `waiting_attention` | 非冪等 Node が中断し、人間対応待ち。worker claim を解放。 |
| `cancelling` | 取消要求を受け、協調的取消処理中。 |
| `interrupted` | worker 停止により中断。明示再開が必要。 |
| `completed` | 成功 Terminal 到達し、実行した効果的 Node がすべて効果を満たした終端状態。 |
| `incomplete` | 実行は終端に到達したが、効果未達または Loop 上限到達。失敗ではない。 |
| `failed` | 失敗 Terminal 到達または実行時エラーにより終端。 |
| `cancelled` | 取消により終端。 |

### 7.2 Run の許可遷移

| From | To |
| --- | --- |
| `queued` | `waiting_approval`, `running`, `cancelled`, `failed` |
| `waiting_approval` | `running`, `cancelled` |
| `running` | `completed`, `incomplete`, `failed`, `cancelling`, `interrupted`, `waiting_hitl`, `waiting_attention` |
| `waiting_hitl` | `running`, `cancelled` |
| `waiting_attention` | `running`, `failed`, `interrupted`, `cancelled` |
| `cancelling` | `cancelled`, `failed`, `interrupted` |
| `interrupted` | `queued`(再開), `cancelled` |

終端状態からの遷移は禁止する。

### 7.3 Node の状態

| 状態 | 意味 |
| --- | --- |
| `pending` | 未実行。 |
| `running` | 実行中。 |
| `waiting_hitl` | HITL 質問登録済み、回答待ち。 |
| `succeeded` | 成功。 |
| `skipped` | 分岐により到達しなかった。 |
| `failed` | 実行または検証に失敗。 |
| `needs_attention` | 非冪等 Node が外部操作中に中断。人間対応待ち。 |
| `cancelled` | 取消により終端。 |

## 8. Capability Node と InvocationContext

### 8.1 Capability Node の実行

- Node 入力を Capability の Pydantic schema で検証する。
- 論理的な 1 回起動単位ごとに `activation_id`（永続 UUID）を生成または再利用する。
- Capability Adapter を `(validated_inputs, invocation_context)` の形で呼び出す。
- Adapter は `StepResult` を返す。`satisfied_effects` があれば Event として記録する。

### 8.2 InvocationContext

```json
{
  "run_id": "run_xxx",
  "workflow_id": "wf_xxx",
  "revision_id": "rev_xxx",
  "node_id": "node_xxx",
  "activation_id": "act_xxx",
  "retry_count": 0,
  "loop_context": {
    "loop_node_id": "node_loop_xxx",
    "iteration": 2
  }
}
```

- `loop_context` は Loop Node 子グラフ内の Node のみ含む。
- Capability 側が冪等キーを利用可能かは `CapabilityDefinition` で宣言する。
- Adapter は `activation_id` を外部 API の idempotency key 等に変換して利用する。
- `activation_id` は retry で同一、Loop の次反復では新規作成する。

### 8.3 冪等性と Activation

- `workflow_activations` テーブルで `activation_id` を永続化する。
- 書込み Capability は `activation_id` 由来の冪等キーを使い、同一 Activation の重複副作用を防ぐ。
- Capability が冪等キー非対応でも、`activation_id` は監査・再開時の重複排除に使う。

## 9. Agent Node

### 9.1 実行フロー

- Node 入力を `output_schema` を含むプロトコル指示と組み立てる。
- 選択された `agent_id` の最新設定（system prompt、model、許可ツール）で Agent 子 Run を作成する。
- Agent の最終出力を `output_schema` で検証する。検証に失敗すれば Node は `failed`。
- 子 Run ID と Agent 設定の指紋を監査用に記録する。

### 9.2 出力 Schema

- JSON Schema サブセット：`object` / `properties` / `required`、primitive（string/integer/number/boolean）、
  `enum`、配列（primitive または object）。
- `$ref` / `oneOf` / `anyOf` / `allOf` / 再帰は v1 対象外。
- UI は schema から動的フォームを生成し、テンプレートからの複製も提供する。

### 9.3 権限と承認

- Agent Node ごとに `agent_id` を Revision 内で固定する。
- Run 開始時の一括承認は、使用する `plan_required` Capability と Agent ID の範囲に対して行う。
- **Agent 内部設定は実行時点の最新版を使う**。承認 UI には「現在および将来の Agent 権限で実行される」と明示する。
- Agent Node 開始時の設定指紋を `workflow_events` に記録し、監査に使用する。

## 10. HITL Wait

HITL 待ちは Capability Node として実装する。`hitl_wait` Capability は以下を行う。

- HITL へ質問を登録する。
- Node 状態を `waiting_hitl`、Run 状態を `waiting_hitl` とし、worker claim を解放する。
- HITL 回答後、回答値を型付き出力として返し、Node を `succeeded` とする。
- HITL 回答は既存 `/hitl` UI で処理する。Workflow UI にはリンクを表示する。

このため HITL 専用の Node 実装や状態機械を増やさず、Capability の入力 schema・監査・取消・再開の
枠組みを共有する。

## 11. 効果契約による完了判定

- Capability Node は `CapabilityDefinition.satisfied_effects` で宣言可能な効果を持つ。
- Agent Node は原則として効果を宣言しない（Agent 出力の事後条件をコードで検証するのは困難なため）。
- Workflow は **実際に実行された Node** から返された `satisfied_effects` を収集する。
- 成功 Terminal Node に到達した時点で、収集された効果集合が「実行された効果的 Node が宣言した効果の和」
  を満たしていれば `completed` とする。
- 満たしていなければ `incomplete` とする（失敗ではない）。
- Loop 上限到達（`exit_reason=max_iterations_reached`）の場合も `incomplete` とする。
- 失敗 Terminal Node に到達、または実行時エラーが発生した場合は `failed` とする。

## 12. 再試行、タイムアウト、実行上限

### 12.1 再試行

- Capability Node の `retry.max_attempts`（既定 0）で制御する。
- Retry は同じ `activation_id` を使う。
- 動的検証エラー（参照未解決、schema 不一致）は再試行しない。
- Agent Node / Coding Capability 等の子 Run を伴う Node は retry ポリシーを無視し、子 Run の
  既存上限を継承する。

### 12.2 タイムアウト

- Workflow 全体のタイムアウトは v1 では持たない。
- 各 Capability Adapter または子 Run が独自のタイムアウトを持つ。

### 12.3 実行上限

- `max_nodes`: 1 Revision あたりの Node 数上限。Task Agent の `MAX_ACTIONS_HARD_LIMIT=30`
  (`directional.py:20`) を踏襲する。
- `max_iterations`: Loop Node の反復上限。正の整数。
- Loop Node はネスト不可。
- これらを超える定義は静的検証で拒否する。

## 13. 中断、明示再開、キャンセル、needs_attention

### 13.1 中断

- worker 停止時（`shutdown_recovery`）、自 instance が所有する `running` Run を `interrupted` にする。
- `waiting_approval` / `waiting_hitl` / `waiting_attention` は維持する。
- 中断後は自動再実行しない。

### 13.2 明示再開

- API: `POST /api/v1/workflows/runs/:run_id/resume`。
- `interrupted` のみ `queued` に遷移可能。
- 完了済み Node を `activation_id` ベースで重複実行しない。

### 13.3 キャンセル

- API: `POST /api/v1/workflows/runs/:run_id/cancel`。
- `queued` / `waiting_approval` / `waiting_hitl` / `waiting_attention` なら即時 `cancelled`。
- `running` / `cancelling` なら協調的取消を伝播して `cancelled` とする。
- 実施済み副作用は巻き戻さない（自動ロールバックなし ADR に準拠）。

### 13.4 needs_attention

非冪等 Node（Agent / Coding 等）が外部操作中に中断した場合、自動再開せず以下の状態にする。

- Node 状態: `needs_attention`
- Run 状態: `waiting_attention`

人間は以下を選択できる。

1. **子 Run 結果を採用して続行**
   - 子 Run が実際に成功済みで、出力 schema と Effect を再検証できる場合のみ許可する。
2. **失敗として処理**
   - 明示的な error Edge があればそこへ進み、なければ Run を `failed` にする。
3. **新しい Activation として再実行**
   - 重複副作用の可能性を警告し、明示確認後に実行する。

`waiting_attention` から `interrupted` への移行も許可し、再開時は `running` ではなく
`waiting_attention` に戻す。

## 14. イベント、監査、redaction、保持期間

### 14.1 Event

`workflow_events` は追記のみの監査テーブル。

主要 Event 型:

- `run_created`, `run_input_submitted`, `run_status_changed`
- `node_started`, `node_completed`, `node_failed`, `node_skipped`, `node_cancelled`
- `loop_iteration_started`, `loop_iteration_completed`
- `hitl_question_asked`, `hitl_answer_received`
- `node_needs_attention`, `attention_resolved`
- `effect_satisfied`
- `agent_config_fingerprint`

payload には node_id、activation_id、子 run ID、HITL run ID、Capability key、
inputs/output 要約、effects、Agent 指紋を含む。

### 14.2 Redaction

- 入力、出力、エラーは `tasks/redaction.py` と同じルールで既知の秘密値を redact して保存する。
- LLM 非公開思考過程や未確定中間トークンは保存しない。
- Run 入力に API キー等の秘密値を入れない。資格情報は Capability 側で実行時注入する。

### 14.3 保持期間

- 終端 Run とその Node・Activation・Event は 30 日後に削除する。
- 非終端 Run は削除しない。
- 長期成果物（Vault ノート、Research Job、Agent 会話）は Workflow 側では削除しない。

## 15. Web UI

### 15.1 画面構成

- `/workflows` — Workflow 一覧。
- `/workflows/:id` — Revision 履歴と最近の Run。
- `/workflows/:id/revisions/:revision_id/edit` — グラフエディタ（キャンバス）。
  - Node カタログ（Capability / Agent / Loop / Terminal）。
  - Node ごとの config 編集（schema 入力、Agent 選択、Loop 設定）。
  - Edge 追加と条件編集。
  - Loop Node 子グラフの編集。
  - 公開前検証ボタン。
- `/workflows/runs/:run_id` — Run 詳細。
  - グラフ上の Node 状態表示。
  - 入出力、Error、Effect の閲覧。
  - 承認 / 取消 / 再開 / needs_attention 処置ボタン。
  - 子 Run / HITL へのリンク。
- `/workflows/runs/:run_id/attention` — needs_attention 対応画面。

### 15.2 実装順序

- Phase 1: バックエンド（Graph / Revision / Run / Node 状態 / Edge 実行 / Loop / Agent Node /
  HITL wait / needs_attention / 検証）。
- Phase 2: Web UI キャンバス・Node カタログ・入力フォーム・承認・Run 詳細。
- Phase 3: SSE 進捗・スターターテンプレート。

## 16. API、永続化、worker、SSE の責務レベルの契約

### 16.1 API

すべて既存 Bearer 認証に従う(`web/app.py`)。

| エンドポイント | 責務 |
| --- | --- |
| `GET /api/v1/workflows` | Workflow 一覧（ページ送り）。 |
| `POST /api/v1/workflows` | 新規 Workflow + 初期 draft Revision 作成。 |
| `GET /api/v1/workflows/:id` | Workflow + Revision 履歴 + 最近 Run。 |
| `POST /api/v1/workflows/:id/revisions` | 新しい draft Revision を作成。 |
| `GET /api/v1/workflows/revisions/:revision_id` | Revision + Node/Edge グラフ。 |
| `PUT /api/v1/workflows/revisions/:revision_id` | draft Revision の更新。 |
| `POST /api/v1/workflows/revisions/:revision_id/publish` | draft → published。 |
| `POST /api/v1/workflows/revisions/:revision_id/validate` | 静的検証。 |
| `POST /api/v1/workflows/revisions/:revision_id/runs` | Run 作成 + 入力フォーム schema 返却。 |
| `POST /api/v1/workflows/runs/:run_id/start` | 入力値を保存し実行開始。 |
| `GET /api/v1/workflows/runs/:run_id` | Run + Node 状態 + Events。 |
| `POST /api/v1/workflows/runs/:run_id/approve` | 承認。`waiting_approval` → `running`。 |
| `POST /api/v1/workflows/runs/:run_id/cancel` | 取消。 |
| `POST /api/v1/workflows/runs/:run_id/resume` | 明示再開。`interrupted` → `queued`。 |
| `POST /api/v1/workflows/runs/:run_id/attention` | needs_attention 処置（採用 / 失敗 / 再実行 / interrupted）。 |
| `GET /api/v1/workflows/runs/:run_id/events` | SSE 進捗（または long-polling 代替）。 |

### 16.2 永続化

SQLite に `PRAGMA user_version = 53` マイグレーションで追加する(`database.py`)。

```text
workflows
  workflow_id TEXT PRIMARY KEY
  name TEXT NOT NULL
  description TEXT
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL

workflow_revisions
  revision_id TEXT PRIMARY KEY
  workflow_id TEXT NOT NULL
  version INTEGER NOT NULL
  status TEXT NOT NULL CHECK(status IN ('draft','published','superseded'))
  inputs_schema TEXT NOT NULL
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL

workflow_nodes
  node_id TEXT PRIMARY KEY
  revision_id TEXT NOT NULL
  node_type TEXT NOT NULL
  label TEXT
  config_json TEXT NOT NULL
  parent_loop_node_id TEXT
  ui_position_json TEXT

workflow_edges
  edge_id TEXT PRIMARY KEY
  revision_id TEXT NOT NULL
  source_node_id TEXT NOT NULL
  target_node_id TEXT NOT NULL
  condition_json TEXT
  order_index INTEGER NOT NULL

workflow_runs
  run_id TEXT PRIMARY KEY
  workflow_id TEXT NOT NULL
  revision_id TEXT NOT NULL
  status TEXT NOT NULL
  inputs_json TEXT
  worker_instance_id TEXT
  result_summary TEXT
  error_summary TEXT
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL
  started_at TEXT
  finished_at TEXT

workflow_run_nodes
  run_id TEXT NOT NULL
  node_id TEXT NOT NULL
  activation_id TEXT NOT NULL
  attempt INTEGER NOT NULL DEFAULT 1
  status TEXT NOT NULL
  inputs_json TEXT
  output_json TEXT
  output_summary TEXT
  error_summary TEXT
  started_at TEXT
  finished_at TEXT
  PRIMARY KEY (run_id, node_id, attempt)

workflow_activations
  activation_id TEXT PRIMARY KEY
  run_id TEXT NOT NULL
  node_id TEXT NOT NULL
  iteration_context TEXT
  created_at TEXT NOT NULL

workflow_events
  event_id TEXT PRIMARY KEY
  run_id TEXT NOT NULL
  seq INTEGER NOT NULL
  event_type TEXT NOT NULL
  payload_json TEXT NOT NULL
  created_at TEXT NOT NULL
```

インデックス:

- `workflow_revisions(workflow_id, status)`
- `workflow_nodes(revision_id)`
- `workflow_edges(revision_id, source_node_id)`
- `workflow_runs(status)`
- `workflow_runs(worker_instance_id)`
- `workflow_runs(finished_at)`
- `workflow_run_nodes(run_id, node_id)`
- `workflow_events(run_id, seq)`

### 16.3 Worker

- FastAPI lifespan 内の同居 worker(`runs/manager.py`)に Workflow worker ループを追加する。
- worker は `queued` または再開された `running` 状態の Run を claim する。
- `waiting_hitl` / `waiting_attention` / `waiting_approval` 状態の Run は claim せず、
  外部イベントまたは人間操作で `queued`/`running` に戻る。
- 停止時は自 instance が所有する `running` / `cancelling` Run を `interrupted` にする。

### 16.4 SSE

- 進捗通知は既存 fetch ベース SSE パターン(`frontend/src/api/runSse.ts`、
  `web/routes/coding.py`)を再利用する。
- 切断時の再接続、last-event-id による差分取得、heartbeat は coding run と同水準を目指す。
- MVP では long-polling でも代替可能（仕様としては SSE を正とする）。

## 17. エラー分類とセキュリティ境界

### 17.1 エラー分類

| 種別 | 例 | HTTP / Run 状態 | 備考 |
| --- | --- | --- | --- |
| 定義検証エラー | 未知 capability、循環 Edge、loop ネスト | 422 | 保存 / 公開時に返す。 |
| 動的検証エラー | 参照未解決、実行時無効 Capability | 422 / `failed` | 実行直前に返す。 |
| 実行エラー | Capability 失敗、子 run 失敗、Agent JSON 検証失敗 | `failed` | Event に詳細を記録。 |
| 承認エラー | 未承認で承認 API 呼び出し | 409 | 状態不整合。 |
| attention エラー | 非冪等 Node 中断 | `waiting_attention` | 人間対応待ち。 |
| 同時実行競合 | 他 worker が claim 中 | 409 | 短期リトライで解決。 |
| 認可エラー | 無効 / 未提供 Bearer トークン | 401 / 403 | 既存 middleware。 |

### 17.2 セキュリティ境界

- 認証: 既存 Bearer トークン必須。localhost/tailnet 個人用途を継続。
- Capability 信頼境界: Adapter 実装は既存のまま。Workflow は `InvocationContext` 経由で
  `activation_id` を渡すだけで、Capability 内部の権限は Capability 側に委ねる。
- Agent 権限: 実行時点の最新 Agent 設定を使う。承認 UI で利用者に明示する。
- 任意コード実行: v1 では追加しない。将来追加する場合は別 ADR + 品質ゲート必須。
- 秘密値: Run 入力に API キー等を含めない。Capability 側の runtime 注入に委ねる。

## 18. 機能要件・非機能要件

### 18.1 機能要件

1. Web UI で Node / Edge グラフを作成・編集・公開できる。
2. Capability Node、Agent Node、Loop Node、Terminal Node、Loop Result Node を使える。
3. Capability / Agent 入力は schema 単一正本から生成されたフォームで入力できる。
4. Agent Node の出力 schema を UI で定義・テンプレートから複製できる。
5. 型付き参照（`run.inputs.*`、`nodes.<node_id>.output.*`、`loop.state.*`）で Node 間を連携できる。
6. Loop Node が上限付きで反復し、反復状態を型付きで管理できる。
7. `plan_required` Capability / Agent を含む Run は実行前に承認を要求する。
8. HITL wait は Capability Node として動作し、回答後に自動的に再開する。
9. 非冪等 Node の中断は `needs_attention`/`waiting_attention` で停止し、人間が処置できる。
10. 実行状況を SSE（または long-polling）で確認できる。

### 18.2 非機能要件

- 可用性: worker 停止後も承認待ち / HITL 待ち / attention 待ち Run は維持される。
- 観測性: Event と既存 Activity ログに追記される。
- 安全性: 承認前に外部副作用を起こさない。自動ロールバックは行わない。
- テスト: 縦断テストは fake Capability / fake Agent Adapter を用いる。ブラウザ E2E は追加しない。

## 19. 操作シナリオ別の受入条件

1. グラフ作成: Capability / Agent / Loop / Terminal Node がキャンバス上で追加・接続できる。
2. 静的検証: 循環 Edge、未知 capability、存在しない agent_id、Loop ネスト、未解決の型付き参照は
   検証エラーとして返る。
3. Revision 公開: 未検証の draft は公開できない。公開後は編集不可。
4. Run 作成: `published` Revision から Run を作成。`inputs_schema` に従う入力フォームを表示する。
5. 承認: `plan_required` Capability / Agent を含む Run は `waiting_approval` になる。
   承認前に Capability / Agent は実行されない。
6. 自動実行: `auto` のみの Run は承認なしで実行される。
7. 条件分岐: Edge 条件が真の target へ進み、偽の経路の Node は `skipped` とする。
8. Loop: 継続条件が真の間反復し、`max_iterations` に達しても条件が真なら `incomplete` で停止する。
9. Agent Node: 最終出力が `output_schema` に合わなければ `failed`。合えば後続 Node へ型付きで受け渡す。
10. HITL: `hitl_wait` Capability で HITL 質問を登録し、回答後に同じ Node が `succeeded` になる。
11. needs_attention: 非冪等 Node 中断後、人間が「採用して続行」「失敗扱い」「新 Activation で再実行」
    のいずれかを選べる。
12. 再開: worker 停止後、明示再開で完了済み Activation を再実行しない。
13. 完了: 成功 Terminal 到達し、実行した効果的 Node がすべて効果を満たせば `completed`、
    そうでなければ `incomplete`。
14. キャンセル: 実行中の Capability / 子 run へ取消が伝播し、Run は `cancelled` になる。
15. 保持: 終端 Run・Node・Activation・Event は 30 日後に削除される。非終端 Run は削除されない。
16. 秘密値: Run 入力・Event 内の既知秘密値は redact される。

## 20. MVP 対象外、将来拡張、未決事項、リスク

### 20.1 MVP 対象外

- 並列 Node / fork / AND join
- Loop ネスト
- 任意の循環 Edge
- 任意コード Node
- Agent Node ごとの prompt/model/tool 上書き
- $ref / oneOf / 再帰を含む JSON Schema
- Workflow 独自の長期 Artifact ストア
- Scheduler Job からの Workflow 起動
- 専用 launchd worker
- 完了 / 失敗 / 承認待ちの外部通知（LINE / Push）
- 定義の JSON / YAML インポート・エクスポート

### 20.2 将来拡張（優先順位未定）

1. Scheduler からの `workflow run <id>` 起動コマンド。
2. スターターテンプレートの JSON ファイル化と UI インポート。
3. Loop ネスト（子グラフ内に子 Loop）。
4. Agent Node ごとの軽微な上書き（承認境界を含む ADR で検討）。
5. 完了通知（軽量 outbox）。

### 20.3 未決事項

| 項目 | 選択肢 | 推奨 / 備考 |
| --- | --- | --- |
| `max_nodes` 上限値 | 30 / 50 等 | Task Agent の 30 を踏襲。実装時に確定 |
| Loop entry_node_id | 明示指定 / 入辺なし Node 自動 | 明示 `entry_node_id` を採用（v1） |
| `loop.iteration` の型 | integer のみ / 追加メタ | integer のみを v1 で提供 |
| Agent Node の子 Run 作成方式 | 既存 agent chat API / 専用 Runner | 実装時に既存 `agents` 機構を再利用 |
| Capability への InvocationContext 導入方法 | 新引数 / コンテキストマネージャー | Adapter 関数シグネチャを拡張 |
| `incomplete` の運用上の扱い | 手動再実行 / 差分承認 | Run を複製して再実行する UI を後続で検討 |

### 20.4 リスク

- **Agent 設定の動的変更**: 承認後に Agent の許可ツールが拡大すると、承認時の想定を超える副作用が
  起こりうる。承認 UI で明示し、指紋を監査保存することで緩和。
- **Loop 上限の誤設定**: `max_iterations` が大きいと長時間実行になる。UI で既定値・上限を制限する。
- **型付き参照の複雑化**: `loop.state` や多段 Node 参照が増えると静的検証が重くなる。
  v1 では object/properties のみを許可し、深いネストを制限する。
- **非冪等 Node の needs_attention 頻発**: Agent / Coding Node が長時間実行中に worker が停止すると、
  人間対応が必要になる。専用 worker 導入までの運用負荷。

## 21. 関連文書・コード

- [adr/workflow-graph-and-agent-node.md](adr/workflow-graph-and-agent-node.md) — 設計判断 ADR
- [adr/workflow-independent-context-shared-foundation.md](adr/workflow-independent-context-shared-foundation.md) — 撤回された旧 ADR
- [../task-agent/specification.md](../task-agent/specification.md) — Task Agent 契約
- [../task-agent/adr/approved-plan-as-execution-boundary.md](../task-agent/adr/approved-plan-as-execution-boundary.md) — Approval Policy
- [../task-agent/adr/effect-contract-completion.md](../task-agent/adr/effect-contract-completion.md) — 効果契約
- [../task-agent/adr/no-automatic-rollback-recovery-via-trace-and-hitl.md](../task-agent/adr/no-automatic-rollback-recovery-via-trace-and-hitl.md) — 自動ロールバックなし
- [../task-agent/adr/sqlite-as-task-state-source-of-truth.md](../task-agent/adr/sqlite-as-task-state-source-of-truth.md) — SQLite 正本
- [../development-quality-playbook.md](../development-quality-playbook.md) — 不可逆操作の品質ゲート
- [../testing.md](../testing.md) — テスト規約
- [../../src/obsidian_ai_hub/tasks/capabilities.py](../../src/obsidian_ai_hub/tasks/capabilities.py) — Capability 定義
- [../../src/obsidian_ai_hub/tasks/capability_schemas.py](../../src/obsidian_ai_hub/tasks/capability_schemas.py) — schema 検証
- [../../src/obsidian_ai_hub/tasks/store.py](../../src/obsidian_ai_hub/tasks/store.py) — Task 状態 / Event パターン
- [../../src/obsidian_ai_hub/runs/manager.py](../../src/obsidian_ai_hub/runs/manager.py) — lifespan 同居 worker
- [../../src/obsidian_ai_hub/database.py](../../src/obsidian_ai_hub/database.py) — マイグレーション
- [../../src/obsidian_ai_hub/web/app.py](../../src/obsidian_ai_hub/web/app.py) — Bearer 認証
- [../../frontend/src/api/runSse.ts](../../frontend/src/api/runSse.ts) — fetch ベース SSE
- [../../ai_wiki/10-Decisions-Web.md](../../ai_wiki/10-Decisions-Web.md) — Web 関連決定
- [../../ai_wiki/10-Decisions-Testing.md](../../ai_wiki/10-Decisions-Testing.md) — テスト関連決定
