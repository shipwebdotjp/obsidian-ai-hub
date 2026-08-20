# Web AI エージェント v1 ToDo

実装開始前。すべて未着手。 ← 2026-08-20 時点で 5 章まで実装完了、6 章は一部未完了

## 1. 永続化とドメインサービス

- [x] `database.py` を schema v21 へ移行する。 `src/obsidian_ai_hub/database.py:477-479,628-686`
  - [x] `agents`、`agent_sessions`、`agent_messages`、`agent_runs` を作成する。 `src/obsidian_ai_hub/database.py:628-680`
  - [x] 外部キー cascade、セッション内メッセージ順の一意制約、一覧用インデックスを追加する。 `src/obsidian_ai_hub/database.py:649-683` (`ON DELETE CASCADE` 3 箇所、`UNIQUE(session_id, sequence)` 660:661、`idx_*` 3 件)
  - [x] 既存の schema version 検証を v21 に更新する。 `src/obsidian_ai_hub/database.py:685`
- [x] `src/obsidian_ai_hub/agents/` を追加する。 `src/obsidian_ai_hub/agents/store.py` `registry.py` `runtime.py`
  - [x] `store.py` に agent / session / message / run CRUD を実装する。 `src/obsidian_ai_hub/agents/store.py:115-292,294-579`
  - [x] session 削除がメッセージと run を、agent 削除が session 以下を削除することを保証する。 `src/obsidian_ai_hub/database.py:649,659,676-677` + `tests/test_agents_store.py:130-159`
  - [x] エージェント名の一意性と、入力の長さ・空白を検証する。 `src/obsidian_ai_hub/agents/store.py:122-131,175-177,213-214` (`UNIQUE(name)` + `strip()` 空白検証、重複は `ValueError`) — 長さ上限は未設定だが空文字は検証済み
- [x] 永続化の単体テストを追加する。 `tests/test_agents_store.py`
  - [x] migration、新規作成、更新、削除 cascade、メッセージ順、run の成功／失敗を検証する。 `tests/test_agents_store.py:6-159` (`test_migration_v21_schema`, `test_agent_crud_and_validation`, `test_session_and_message_run_lifecycle`, `test_fail_run`, `test_cascade_deletions`)

## 2. ツールレジストリと安全境界

- [x] server 側ツールレジストリを実装する。 `src/obsidian_ai_hub/agents/registry.py:216-265`
  - [x] `web_search`、`web_extract`、`vault_search`、`vault_read_file` を公開する。 `src/obsidian_ai_hub/agents/registry.py:217-240`
  - [x] `calendar_read`、`reminders_read` を EventKit の読取りラッパーとして公開する。 `src/obsidian_ai_hub/agents/registry.py:241-252` (`planner.apple.fetch_calendar_events` / `fetch_incomplete_reminders`)
  - [x] `calendar_create_proposal`、`reminder_create_proposal` を既存 HITL Run 登録ラッパーとして公開する。 `src/obsidian_ai_hub/agents/registry.py:253-264` (`calendar.hitl.register_calendar_event_approval`, `reminders.hitl.register_reminder_approval`)
- [x] ツール ID の存在確認、重複除去、許可されたツールだけを runtime に渡す制約を実装する。 `src/obsidian_ai_hub/agents/registry.py:282-296` (`resolve_tools` deduplicate + unknown skip) と `src/obsidian_ai_hub/agents/store.py:34-43` (`_validate_tool_ids` で unknown → `ValueError`)
- [x] システム安全プロンプト、最大ツール反復回数、入力値／会話コンテキストの上限を実装する。 `src/obsidian_ai_hub/agents/runtime.py:28-36,69-99` (`SYSTEM_SAFETY_PROMPT`, `max_iterations=3` 69:138, `max_history_messages=20` 70:95-99, 入力は `strip()` 空チェック `src/obsidian_ai_hub/web/routes/agents.py:176-178` と `store.py:378-380`)
- [x] 書込み提案が Apple 作成ツールを直接呼ばず HITL Run を登録するテストを追加する。 `tests/test_agents_registry.py:36-77` (`test_calendar_create_proposal`, `test_reminder_create_proposal` で `hitl.store.get_run` が `pending_user` であることを検証)

## 3. エージェント実行と SSE

- [x] provider / model の空欄時にアプリ既定 LLM 設定を解決する。 `src/obsidian_ai_hub/agents/runtime.py:81-86` (`(agent.get("provider") or "").strip() or config.AGENT_PROVIDER or "openai"`)
- [x] 直近の会話履歴と system prompt から LangChain メッセージを構築する。 `src/obsidian_ai_hub/agents/runtime.py:92-112` (`SystemMessage` + `history_messages[-max_history_messages:]` → `HumanMessage`/`AIMessage`)
- [x] LLM tool loop を実装する。 `src/obsidian_ai_hub/agents/runtime.py:133-204`
  - [x] LLM 呼出を既存の LLM 実行ログへ記録する。 `src/obsidian_ai_hub/agents/runtime.py:141-149,195-204` (`_logged_invoke` 経由 → `utils.execution_logger`)
  - [x] OpenAI tool call は Responses API、`store=False` を使用する。 `src/obsidian_ai_hub/agents/runtime.py:114-120` と `src/obsidian_ai_hub/utils/llm_client.py:280-285,354-360`
  - [x] ツール利用結果を assistant の最終回答生成へ渡す。 `src/obsidian_ai_hub/agents/runtime.py:179-184` (`ToolMessage` 追加後にループ継続)
- [x] user message、running run、完了 assistant message / failed run を整合して永続化する。 `src/obsidian_ai_hub/agents/store.py:373-551` (`start_user_run` 389-397 で `running` 作成、`complete_run` 482-498 で `succeeded` + `assistant_message_id`, `fail_run` 532-537 で `failed`)
- [x] `text`、`done`、`error` の SSE イベントを実装する。 `src/obsidian_ai_hub/agents/runtime.py:58-60,208-245` (`_format_sse` と `type: text/done/error`) + `src/obsidian_ai_hub/web/routes/agents.py:172-203`
- [x] tool loop、max iteration、エラー確定、SSE のイベント列を単体テストする。 `tests/test_agents_runtime.py` (`test_agent_stream_simple_response`, `test_agent_stream_with_tool_call`, `test_agent_stream_error_handling`)

## 4. Web API

- [x] Pydantic request / response schema を追加する。 `src/obsidian_ai_hub/web/routes/agents.py:23-53` (`CreateAgentRequest`, `UpdateAgentRequest`, `CreateSessionRequest`, `StreamMessageRequest`) ※ `web/schemas.py` には未集約だが route 内で定義済み
- [x] `web.services.agents` と `web.routes.agents` を追加する。 `src/obsidian_ai_hub/web/services/agents.py` `src/obsidian_ai_hub/web/routes/agents.py`
- [x] agent CRUD、tool catalog、session CRUD、session 詳細、message stream を API router に登録する。 `src/obsidian_ai_hub/web/api.py:3,19,21` + `src/obsidian_ai_hub/web/routes/agents.py:58-203` (`/agents`, `/agent-tools`, `/agents/{id}/sessions`, `/agent-sessions/{id}`, `/agent-sessions/{id}/messages/stream`)
- [x] 全エンドポイントの Bearer 認証、404、入力エラー、重複名を API テストする。 `tests/test_agents_api.py:21-195` (`require_bearer_token` 依存 17:17, 401/404/400/409 を網羅)
- [x] SSE endpoint が Authorization ヘッダー付き Fetch から利用できることをテストする。 `tests/test_agents_api.py:130-164` (`TestClient` で `text/event-stream` 検証) + `frontend/src/api/client.ts:591-654` (`streamAgentMessage` が `Authorization: Bearer` を付与して `fetch` + `ReadableStream` で SSE 解析)

## 5. Web UI

- [x] API 型と client 関数を追加する。 `frontend/src/api/types.ts:587-646` (`Agent`, `AgentSession`, `AgentMessage`, `AgentRun`, `AgentStreamEvent`) と `frontend/src/api/client.ts:493-654` (`listAgents`, `createAgent`, `streamAgentMessage` 等)
- [x] `/agents` route とサイドバー導線を追加する。 `frontend/src/constants/routes.ts:4` (`AGENTS: "/agents"`), `frontend/src/App.tsx:7,174` (`<Route path={ROUTES.AGENTS} element={<AgentsPage />}>`), `frontend/src/components/Sidebar.tsx:58-60`
- [x] エージェント一覧・作成・編集・削除 UI を実装する。 `frontend/src/features/agents/AgentsPage.tsx:359-555`
  - [x] 名前、システムプロンプト、provider、model、ツール選択を表示する。 `frontend/src/features/agents/AgentsPage.tsx:438-534`
  - [x] provider / model の空欄が既定値を使うことを説明する。 `frontend/src/features/agents/AgentsPage.tsx:472-494` (placeholder「空欄でアプリ既定値」+ 説明文)
  - [x] 予定アシスタント用テンプレートを用意する。 `frontend/src/features/agents/AgentsPage.tsx:24-38,210-216`
- [x] セッション一覧・新規会話・削除確認・メッセージ履歴を実装する。 `frontend/src/features/agents/AgentsPage.tsx:588-693` (セッションバー、モーダル、メッセージ描画)
- [x] Fetch ReadableStream で SSE を読み、assistant 応答を逐次表示する。 `frontend/src/api/client.ts:633-654` (`getReader` + `TextDecoder` + `split("\n\n")`) と `frontend/src/features/agents/AgentsPage.tsx:302-355,658-665` (`streamingText`)
- [x] `done` の HITL Run ID から承認待ちリンクを描画する。 `frontend/src/features/agents/AgentsPage.tsx:668-683` (`hitlLinks` → `<Link to={ROUTES.HITL}>`)
- [x] Vitest を追加・更新する。 `frontend/package.json:31` (`vitest: ^4.1.10`) と `frontend/src/features/agents/__tests__/AgentsPage.test.tsx` (4 ケース: 一覧読込、テンプレート適用、ストリーミング HITL リンク、エラー表示)

## 6. 結合検証と記録

- [ ] 外部サービスをモックして、予定アシスタントが calendar / reminders 読取りを使い回答する統合テストを追加する。 — 現状 `tests/test_agents_integration.py` は `calendar_create_proposal` の HITL 生成をモックして検証するが、**読取り (calendar_read / reminders_read) → 回答** の統合フローは未カバー。`tests/test_agents_registry.py:85-97` の `test_calendar_read_mocked` は単体テストのみ。読取り→回答の統合テストを追加すれば完了。
- [x] HITL 提案が作成され、会話画面に承認待ちが表示される統合テストを追加する。 `tests/test_agents_integration.py:11-85` (`test_schedule_assistant_integration` で `done.hitl_run_ids` と `hitl.store.get_run` を検証) + `frontend/src/features/agents/__tests__/AgentsPage.test.tsx:158-218` (ストリーミング `done` 後に「承認待ちの登録申請」アラートと `/hitl` リンクを検証)
- [ ] 高影響フロー「エージェント作成 → 新規会話 → 応答表示」を E2E seed scenario として追加する。 — 未実装。`tests/e2e/conftest.py:63-68` は `memory/hitl/people/planner/summary_recovery` のみ対応、`src/obsidian_ai_hub/testing/seed.py` に `seed_agent_*` なし、`tests/e2e/test_*` に agents シナリオなし。
- [ ] フロントエンド変更を seeded E2E サーバーで目視確認する。 — `frontend/dist` は E2E `frontend_dist` fixture で検証されるが、`/agents` の手動確認記録なし。`ai_wiki/20-Worklog.md` にも記載なし。
- [ ] `uv run pytest tests/` を実行する。 — コマンド自体は `tests/conftest.py` の隔離で実行可能だが、本タスク内での実行証跡なし（CI での通過は別途確認要）。
- [ ] `make test-e2e` を実行する。 — 同上、実行証跡なし。E2E は `make jules-setup` + `ENV=test` が前提。
- [x] 実装で追加・変更した恒久判断を `ai_wiki` の ADR と用語集へ追記する。 `ai_wiki/10-Decisions-Architecture.md:3-34` (データモデル・実行と UI)、`ai_wiki/10-Decisions-Web.md:243-263` (Web API / UI 契約)、`ai_wiki/30-Glossary.md:3-21` (AI エージェント/セッション/メッセージ/ツールレジストリ/書込み提案)

## v1 後の候補

- [ ] 書込み提案のチャット内編集と、承認後の会話自動再開。
- [ ] 予定・リマインダーの更新、削除、完了。
- [ ] 実行中の取消、バックグラウンド実行、再接続、詳細なツール進捗。
- [ ] ユーザー定義の外部ツール／MCP。ただし、権限・監査・ネットワーク境界を別途設計してから導入する。
