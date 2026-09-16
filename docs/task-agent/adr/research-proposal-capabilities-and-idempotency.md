# Task Agent ADR: リサーチ提案 Capability と自動候補登録の冪等性

## コンテキスト
ユーザーに最適なリサーチテーマを1件提案・登録する能力をTask Agentおよび通常AI Agentへ公開する必要があった。
従来の `--suggest-research-theme` は直接LLM生成を行っていたが、Task Agentのタスクキューへ投入する方式へ移行し、
オーケストレーション内で読取Capabilityおよび提案Capability（`research_theme_propose`）を連携実行する設計へ変更した。

## 決定事項

1. **Capabilityと読取・提案ツールの公開**
   - Agent Registryに 7 つのツールを追加した:
     - `research_context_snapshot`
     - `research_theme_history_search`
     - `activity_search`
     - `periodic_note_read`
     - `agent_conversation_search`
     - `coding_history_search`
     - `research_theme_propose`
   - 全ツールは Task Agent の `AUTO_POLICY_TOOL_IDS` に含め、承認ポリシー既定値を `auto` とした。
   - 提案登録 (`research_theme_propose`) は既存の提案HITL同様に直接のデータ書き換えを行わずHITL登録を行うため、`auto` ポリシーが安全に適用される。

2. **提案数制御と冪等性管理**
   - Task Agentにおいては 1 Task あたり最大1件の提案登録を認める。
   - SQLiteテーブル `research_suggestion_requests` を導入し、実行起点キー（`task:{task_id}` または `agent_run:{run_id}` 等）と `(theme_id, hitl_run_id)` を紐付けて記録する。
   - 同一実行コンテキストからの再実行時には既存の `theme_id` と `hitl_run_id` を返却し、二重登録を防止する。
   - Registry Tool Adapter は `research_theme_propose` に Task の合成コンテキスト（`task_id` を含む）を渡す。
     これにより候補登録の冪等性は表示名であるテーマ名ではなく、安定した **Task ID** 単位で保証される。

3. **安全契約と通知リカバリ**
   - テーマ候補およびHITL登録のコミット後に、LINE通知をベストエフォートで1回のみ試行する。
   - LINE通知失敗やその後のTask Event記録失敗が発生しても、候補およびHITL登録は取り消さず、自動再送は行わない。

## 二層ObservationとAction予算

リサーチ提案Taskは読取Capabilityを複数回呼ぶため、生のObservationを全履歴へ
連結すると過去の結論が押し出され、Action予算も読取りに使い切られやすかった。
次のように二層化する（実装: `tasks/observation.py`）。

- 各Actionは「履歴用要点」(約1,500文字、先頭の構造と末尾の結論を保持) を
  `capability_completed` Event の `observation_summary` として残し、常に次の
  Runtimeプロンプトへ渡す。
- 最新Actionだけは「表示/監査用詳細Observation」(`observation`) を
  Capability別上限（リサーチ系は最大6,000文字、汎用Registry toolは従来相当の
  2,000文字）でプロンプトへ渡す。全履歴の合計は60,000文字で上限を維持する。
- Registry Adapterの一律800文字切詰めは廃止し、Capability別上限は
  Orchestrator側で適用する。
- `research_context_snapshot` はfront matterと空テンプレートを除外し、
  活動・既存テーマ・却下フィードバック・ノート本文の有意味な抜粋を優先順で返す。
- PlannerとRuntimeプロンプトは `max_actions` / 完了済み数 / 残数を明示する。
  依頼または完了条件で提案が必須の場合、Plannerは提案とfinishの2枠を残し、
  Runtimeは残り2枠を読取りに使わない。自動完了・Action強制は導入しない。

## 操作シナリオ契約（HITL候補登録）

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 文脈読取 | Registry読取Capabilityのschema | `capability_key`、`action_index` | `capability_completed` (`observation` 詳細 / `observation_summary` 要点) | 次ターンOrchestrator、再開処理 | tool失敗はAction失敗。読取りは副作用なし | なし |
| 提案 | `ResearchThemeProposeInput` | `theme` と合成コンテキストの `task_id` | `research_suggestion_requests` (`request_key=task:<task_id>`、`theme_id`、`hitl_run_id`) | 再開時の再提案、WebUI HITL | 空テーマ・文字数超過・未知キーは登録せずエラー | テーマ候補とHITL runを1件作成 |
| 提案（重複） | 保存済み `request_key` | `task:<task_id>` | 変更なし | 次のOrchestrator | 既存 `theme_id` / `hitl_run_id` を返して停止 | なし |
| 登録後完了 | `finish` の要約 | `result_summary` | `completed` | 閲覧者 | — | なし |
| 再開 | `capability_completed` の `action_index` と `research_suggestion_requests` | `task:<task_id>` | 既存Event | Orchestrator | 提案Event未保存でもTask ID単位で再登録しない（at-most-once相当の候補） | 重複登録なし |

縦断テスト: `tests/test_tasks_research_proposal_flow.py`
（4読取り→提案→finishで候補1件、提案副作用後クラッシュからの再開でも候補が増えない）。

