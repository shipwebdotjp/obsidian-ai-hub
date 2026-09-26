# Workflow 文書群

Workflow は、人間が Web UI で設計する **Node / Edge グラフ** である。
制御・データフローは決定的だが、Agent Node の LLM 出力は確率的で、JSON Schema によって
検証・型付きで後続 Node へ受け渡す。既存 Task Agent（自由文を LLM が動的に解釈）とは
独立した Bounded Context である。

Status: Accepted。仕様は実装済みで、変更は specification.md と ADR を正本とする。

## 文書一覧

| 文書 | 役割 |
| --- | --- |
| [specification.md](specification.md) | 確定済みの外部契約と振る舞い（実装の正本） |
| [adr/workflow-graph-and-agent-node.md](adr/workflow-graph-and-agent-node.md) | グラフ / Agent Node / Loop Node / 承認境界の設計判断 ADR |
| [adr/workflow-revision-deletion.md](adr/workflow-revision-deletion.md) | Revision 削除ポリシー（draft / superseded のハード削除・Run 温存） |
| [adr/workflow-deletion.md](adr/workflow-deletion.md) | Workflow aggregate 削除ポリシー（非終端 Run・Scheduler 参照を拒否） |
| [adr/workflow-run-deletion.md](adr/workflow-run-deletion.md) | 終端 Run 削除ポリシー（soft link 解除・子 Run 温存） |
| [adr/workflow-independent-context-shared-foundation.md](adr/workflow-independent-context-shared-foundation.md) | 撤回された旧 ADR（履歴） |
| [adr/workflow-editor-guided-forms.md](adr/workflow-editor-guided-forms.md) | エディタのガイド型フォーム（自前スキーマフォーム・型付き参照ピッカー） |
| [adr/capability-input-output-contracts.md](adr/capability-input-output-contracts.md) | Capability 入出力契約の段階的厳格化（strict 入力・出力契約クラス・副作用での strict 利用境界） |

`adr/workflow-graph-and-agent-node.md` は本文内 Amendment による追補を含む。
機能理解には該当節を読むこと。

| 追補（Amendment） | 内容 |
| --- | --- |
| 「Amendment (Capability ブリッジ Task の隔離)」 | Capability Node 実行時の短命ブリッジ Task と Task Agent からの隔離 |
| 「Amendment (取消・不確実結果の追跡)」 | 取消の状態遷移（`cancelling` / `waiting_attention`）と子 Run 参照の正本 |
| 「Amendment (Scheduler Job からの公開 Workflow 起動)」 | Scheduler 発火による公開 Workflow の起動と最新公開版追従 |
| 「Amendment (User Template と Workflow Definition Package)」 | User Template と定義 package v1 の import / export |
| 「Amendment (Workflow 単位の承認スキップ)」 | `skip_approval` による承認ゲートの解除 |
| 「Amendment (会話型 Agent と単発 LLM Node の責務分離)」 | 会話を持たない単発 `llm` Node の追加 |
| 「Amendment (Capability Node の strict 出力)」 | `fail_on_output_mismatch` による出力契約違反時の Node 失敗 |

## 設計上の要点

- Workflow / Workflow Revision に分離。Revision は `draft` / `published` / `superseded` の
  ライフサイクルを持つ。Node / Edge ID は UUID。
- Node 種別: `capability`、`agent`、`llm`、`loop`、`terminal`、`loop_result`、`text_template`。
- 反復は Loop Node の非循環子グラフで表現する。通常の Edge は循環不可。
- Node 間のデータ連携は型付き参照（`run.inputs.*`、`nodes.<node_id>.output.*`、`loop.state.*`）のみ。
- Capability Adapter には `InvocationContext`（`activation_id` 含む）を渡す。
- Agent Node は既存 `agents` テーブルから選択し、実行時点の最新設定を使う。設定指紋は監査用に保存。
- 単発 LLM Node（`llm`）は会話・ツールを持たず、承認対象外。入力と `output_schema` だけを送り、
  出力を JSON Schema で検証して型付きで渡す（[ADR amendment](adr/workflow-graph-and-agent-node.md#amendment-会話型-agent-と単発-llm-node-の責務分離)）。
- 承認は Capability Policy + 選択 Agent ID の範囲で行う。Agent 内部設定の変更は再承認しない。
- 完了判定は「成功 Terminal 到達 + 実行した効果的 Node がすべて効果を満たす」。
- 非冪等 Node（Agent / Coding）の外部操作中の中断は `needs_attention` / `waiting_attention` で停止し、
  人間が処置する。
- データは同一 SQLite に `workflow_` 接頭辞テーブルで置き、Event は追記のみ。
  秘密値 redact と 30 日保持は Task Agent と同型
  ([tasks/redaction.py](../../src/obsidian_ai_hub/tasks/redaction.py))。
