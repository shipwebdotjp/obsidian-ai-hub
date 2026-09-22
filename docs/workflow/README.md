# Workflow 文書群

Workflow は、人間が Web UI で設計する **Node / Edge グラフ** である。
制御・データフローは決定的だが、Agent Node の LLM 出力は確率的で、JSON Schema によって
検証・型付きで後続 Node へ受け渡す。既存 Task Agent（自由文を LLM が動的に解釈）とは
独立した Bounded Context である。

Status: 再設計後の仕様 Accepted (Phase 0 未実装)。実装はフェーズ計画に従う。

## 文書一覧

| 文書 | 役割 |
| --- | --- |
| [specification.md](specification.md) | 確定済みの外部契約と振る舞い（実装の正本） |
| [adr/workflow-graph-and-agent-node.md](adr/workflow-graph-and-agent-node.md) | グラフ / Agent Node / Loop Node / 承認境界の設計判断 ADR |
| [adr/workflow-revision-deletion.md](adr/workflow-revision-deletion.md) | Revision 削除ポリシー（draft / superseded のハード削除・Run 温存） |
| [adr/workflow-independent-context-shared-foundation.md](adr/workflow-independent-context-shared-foundation.md) | 撤回された旧 ADR（履歴） |
| [adr/workflow-editor-guided-forms.md](adr/workflow-editor-guided-forms.md) | エディタのガイド型フォーム（自前スキーマフォーム・型付き参照ピッカー） |

## 設計上の要点

- Workflow / Workflow Revision に分離。Revision は `draft` / `published` / `superseded` の
  ライフサイクルを持つ。Node / Edge ID は UUID。
- Node 種別: `capability`、`agent`、`loop`、`terminal`、`loop_result`。
- 反復は Loop Node の非循環子グラフで表現する。通常の Edge は循環不可。
- Node 間のデータ連携は型付き参照（`run.inputs.*`、`nodes.<node_id>.output.*`、`loop.state.*`）のみ。
- Capability Adapter には `InvocationContext`（`activation_id` 含む）を渡す。
- Agent Node は既存 `agents` テーブルから選択し、実行時点の最新設定を使う。設定指紋は監査用に保存。
- 承認は Capability Policy + 選択 Agent ID の範囲で行う。Agent 内部設定の変更は再承認しない。
- 完了判定は「成功 Terminal 到達 + 実行した効果的 Node がすべて効果を満たす」。
- 非冪等 Node（Agent / Coding）の外部操作中の中断は `needs_attention` / `waiting_attention` で停止し、
  人間が処置する。
- データは同一 SQLite に `workflow_` 接頭辞テーブルで置き、Event は追記のみ。
  秘密値 redact と 30 日保持は Task Agent と同型
  ([tasks/redaction.py](../../src/obsidian_ai_hub/tasks/redaction.py))。
