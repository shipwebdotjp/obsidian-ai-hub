# Web AI エージェント v1 ToDo

実装開始前。すべて未着手。

## 1. 永続化とドメインサービス

- [ ] `database.py` を schema v21 へ移行する。
  - [ ] `agents`、`agent_sessions`、`agent_messages`、`agent_runs` を作成する。
  - [ ] 外部キー cascade、セッション内メッセージ順の一意制約、一覧用インデックスを追加する。
  - [ ] 既存の schema version 検証を v21 に更新する。
- [ ] `src/obsidian_ai_hub/agents/` を追加する。
  - [ ] `store.py` に agent / session / message / run CRUD を実装する。
  - [ ] session 削除がメッセージと run を、agent 削除が session 以下を削除することを保証する。
  - [ ] エージェント名の一意性と、入力の長さ・空白を検証する。
- [ ] 永続化の単体テストを追加する。
  - [ ] migration、新規作成、更新、削除 cascade、メッセージ順、run の成功／失敗を検証する。

## 2. ツールレジストリと安全境界

- [ ] server 側ツールレジストリを実装する。
  - [ ] `web_search`、`web_extract`、`vault_search`、`vault_read_file` を公開する。
  - [ ] `calendar_read`、`reminders_read` を EventKit の読取りラッパーとして公開する。
  - [ ] `calendar_create_proposal`、`reminder_create_proposal` を既存 HITL Run 登録ラッパーとして公開する。
- [ ] ツール ID の存在確認、重複除去、許可されたツールだけを runtime に渡す制約を実装する。
- [ ] システム安全プロンプト、最大ツール反復回数、入力値／会話コンテキストの上限を実装する。
- [ ] 書込み提案が Apple 作成ツールを直接呼ばず HITL Run を登録するテストを追加する。

## 3. エージェント実行と SSE

- [ ] provider / model の空欄時にアプリ既定 LLM 設定を解決する。
- [ ] 直近の会話履歴と system prompt から LangChain メッセージを構築する。
- [ ] LLM tool loop を実装する。
  - [ ] LLM 呼出を既存の LLM 実行ログへ記録する。
  - [ ] OpenAI tool call は Responses API、`store=False` を使用する。
  - [ ] ツール利用結果を assistant の最終回答生成へ渡す。
- [ ] user message、running run、完了 assistant message / failed run を整合して永続化する。
- [ ] `text`、`done`、`error` の SSE イベントを実装する。
- [ ] tool loop、max iteration、エラー確定、SSE のイベント列を単体テストする。

## 4. Web API

- [ ] Pydantic request / response schema を追加する。
- [ ] `web.services.agents` と `web.routes.agents` を追加する。
- [ ] agent CRUD、tool catalog、session CRUD、session 詳細、message stream を API router に登録する。
- [ ] 全エンドポイントの Bearer 認証、404、入力エラー、重複名を API テストする。
- [ ] SSE endpoint が Authorization ヘッダー付き Fetch から利用できることをテストする。

## 5. Web UI

- [ ] API 型と client 関数を追加する。
- [ ] `/agents` route とサイドバー導線を追加する。
- [ ] エージェント一覧・作成・編集・削除 UI を実装する。
  - [ ] 名前、システムプロンプト、provider、model、ツール選択を表示する。
  - [ ] provider / model の空欄が既定値を使うことを説明する。
  - [ ] 予定アシスタント用テンプレートを用意する。
- [ ] セッション一覧・新規会話・削除確認・メッセージ履歴を実装する。
- [ ] Fetch ReadableStream で SSE を読み、assistant 応答を逐次表示する。
- [ ] `done` の HITL Run ID から承認待ちリンクを描画する。
- [ ] Vitest を追加・更新する。

## 6. 結合検証と記録

- [ ] 外部サービスをモックして、予定アシスタントが calendar / reminders 読取りを使い回答する統合テストを追加する。
- [ ] HITL 提案が作成され、会話画面に承認待ちが表示される統合テストを追加する。
- [ ] 高影響フロー「エージェント作成 → 新規会話 → 応答表示」を E2E seed scenario として追加する。
- [ ] フロントエンド変更を seeded E2E サーバーで目視確認する。
- [ ] `uv run pytest tests/` を実行する。
- [ ] `make test-e2e` を実行する。
- [ ] 実装で追加・変更した恒久判断を `ai_wiki` の ADR と用語集へ追記する。

## v1 後の候補

- [ ] 書込み提案のチャット内編集と、承認後の会話自動再開。
- [ ] 予定・リマインダーの更新、削除、完了。
- [ ] 実行中の取消、バックグラウンド実行、再接続、詳細なツール進捗。
- [ ] ユーザー定義の外部ツール／MCP。ただし、権限・監査・ネットワーク境界を別途設計してから導入する。
