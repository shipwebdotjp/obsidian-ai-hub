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

3. **安全契約と通知リカバリ**
   - テーマ候補およびHITL登録のコミット後に、LINE通知をベストエフォートで1回のみ試行する。
   - LINE通知失敗やその後のTask Event記録失敗が発生しても、候補およびHITL登録は取り消さず、自動再送は行わない。
