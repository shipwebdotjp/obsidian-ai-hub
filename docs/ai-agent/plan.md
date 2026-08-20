# Web AI エージェント v1 実装プラン

## 目的

Web UI から作成・管理できる AI エージェントを追加する。利用者はエージェントごとにシステムプロンプト、任意の provider / model 名、利用可能な登録ツールを設定し、継続セッションで会話できる。エージェントは必要に応じて情報を収集して最終回答を返す。

最初の代表エージェントは、予定・リマインダーを把握し、次に行うべきことを助言する「予定アシスタント」とする。

## 決定済みの要件

| 項目 | v1 の決定 |
| --- | --- |
| エージェント管理 | Web UI で作成・編集・削除する。 |
| LLM 設定 | provider と model は自由入力。空欄ならアプリ既定値を使う。 |
| 読み取りツール | Web 検索、Web 本文抽出、Vault 検索、Vault Markdown 読取、Calendar 読取、Reminders 読取。 |
| 書込みツール | Calendar / Reminders の新規作成だけ。直接実行せず、既存 HITL Run を登録する。 |
| 承認後 | 自動でエージェントを再開しない。エージェントは承認待ちを返し、利用者が必要なら次のメッセージを送る。 |
| 会話履歴 | ユーザーがセッションを削除するまで保存する。 |
| 実行 UI | SSE による assistant 応答のストリーミング表示を行う。進捗、取消、バックグラウンドジョブ、再接続は対象外。 |

関連する恒久判断は [AI エージェント ADR](../../ai_wiki/10-Decisions-Architecture.md#web-ui-管理の-ai-エージェント永続会話およびツール境界)、用語は [用語集](../../ai_wiki/30-Glossary.md) を正本とする。

## 設計

### モジュール境界

```text
src/obsidian_ai_hub/
  agents/
    store.py          # agents / sessions / messages / runs の SQLite CRUD
    registry.py       # ツール ID、公開名、説明、引数スキーマ、生成関数
    runtime.py        # 会話コンテキスト、LLM tool loop、SSEイベント生成
    __init__.py       # 安定した公開 API のみ
  web/
    routes/agents.py  # Bearer 保護された REST / SSE エンドポイント
    services/agents.py
```

`src/obsidian_ai_hub/` 直下には新しいロジックを置かず、CLI が必要になった場合だけ薄いラッパーを追加する。`agents` は Web 層に依存せず、Web は service 経由で `agents` を呼ぶ。

### SQLite モデル（schema v21）

- `agents`
  - `agent_id`、一意の `name`、`system_prompt`、nullable `provider` / `model`、`tool_ids_json`、作成・更新日時。
  - ツール設定には registry の固定 ID の配列のみを保存し、任意の Python コード、URL、ツール定義は保存しない。
- `agent_sessions`
  - `session_id`、`agent_id`、表示用 `title`、作成・更新日時。
- `agent_messages`
  - `message_id`、`session_id`、セッション内一意の `sequence`、`role`（`user` / `assistant`）、確定した `content`、作成日時。
- `agent_runs`
  - `run_id`、`session_id`、対応する user / assistant message ID、状態、利用ツールの要約 JSON、作成された HITL Run ID 群、エラー、開始・終了日時。

全ての子テーブルは外部キー `ON DELETE CASCADE` を持つ。セッション削除によりメッセージと実行記録を回収し、エージェント削除により配下セッションも削除する。スレッド安全性・メッセージ順を保つため、メッセージ追加と session 更新は一つの SQLite トランザクションで確定する。

### ツールレジストリと安全境界

ツールは次の固定 ID を最初に提供する。編集画面はこの一覧のみを表示する。

| ID | 実装元 | 作用 |
| --- | --- | --- |
| `web_search` | `handler.web_search` | 読取り |
| `web_extract` | `handler.web_extract` | 読取り |
| `vault_search` | `handler.obsidian_vault_retriever` | 読取り |
| `vault_read_file` | `web.services.vault.get_vault_file` を安全な引数スキーマで包む | 読取り |
| `calendar_read` | `planner.apple.fetch_calendar_events` | 読取り |
| `reminders_read` | `planner.apple.fetch_incomplete_reminders` | 読取り |
| `calendar_create_proposal` | `calendar.hitl.register_calendar_event_approval` を包む | HITL 提案 |
| `reminder_create_proposal` | `reminders.hitl.register_reminder_approval` を包む | HITL 提案 |

Calendar / Reminders の作成ラッパーは `add_calendar_event` / `add_reminder` を直接公開しない。ツール結果には作成した HITL Run ID と要約を返す。会話 API はそれを終端 SSE イベントにも含め、UI は `/hitl?run_id=…` への承認待ちリンクを表示する。

ツール出力・Web 本文・Vault 本文は信頼できない参考情報として system prompt に明示し、外部内容に含まれる命令をツール実行条件として扱わない。ツール数、各ツール引数の上限、ツール反復回数（初期値 3）と会話コンテキスト量をコード側で制限する。

### LLM 実行と SSE

1. `POST /api/v1/agent-sessions/{session_id}/messages/stream` が user text を受け取る。
2. user message と running `agent_run` を永続化する。
3. system prompt、直近の確定会話、現在の user message、選択済み tool を使い、LangChain の tool loop を実行する。
4. 読み取りツールを必要なだけ実行し、最終 assistant 応答を `text/event-stream` として送る。
5. 最終応答、利用ツールの要約、HITL Run ID を保存し、`done` イベントを送る。失敗時は `error` イベントと failed run を確定する。

SSE のイベント形式は、少なくとも `text`、`done`、`error` を持つ。`done` は message / run / hitl_run_ids を含む。クライアントは Fetch の ReadableStream を使う。`EventSource` は Bearer Authorization ヘッダーを付けられないため使わない。

LLM 呼出は既存の LLM ログ基盤へ記録する。OpenAI provider で function tool を使う場合は既存の Responses API + `store=False` の方針を引き継ぐ。

### Web API

すべて既存の Bearer 認証を必須にする。

- `GET /agents`、`POST /agents`
- `GET /agents/{agent_id}`、`PATCH /agents/{agent_id}`、`DELETE /agents/{agent_id}`
- `GET /agent-tools` — レジストリの表示専用一覧
- `GET /agents/{agent_id}/sessions`、`POST /agents/{agent_id}/sessions`
- `GET /agent-sessions/{session_id}` — エージェント情報とメッセージ一覧
- `DELETE /agent-sessions/{session_id}`
- `POST /agent-sessions/{session_id}/messages/stream` — SSE

ID が見つからないときは 404、不正な tool ID、重複名、空白の name / system prompt は 400 / 409 を明確に返す。エージェントのツール変更は新しい実行から反映し、保存済みの run の履歴は変更しない。

### React UI

`/agents` を追加し、サイドバーへ「AI エージェント」を置く。

- 左ペイン: 作成済みエージェントと新規作成導線。
- エージェント編集: 名前、システムプロンプト、provider、model、登録ツールのチェックボックス。既定の予定アシスタントを作るテンプレートを用意する。
- 会話: 選択エージェントのセッション一覧、新規会話、メッセージ履歴、入力欄、ストリーム中の assistant 吹き出し。
- `done.hitl_run_ids` を受けたら「承認待ち」と HITL Run へのリンクを表示する。
- セッション・エージェント削除は確認 UI を出す。削除対象（会話・メッセージ・実行記録）を明示する。

ストリーム中は送信ボタンを無効化する。v1 では取消を提供しないため、画面離脱時もサーバー処理は中断しない。

## 実装順序

1. schema v21、`agents.store`、最小の単体テストを追加する。
2. registry と Calendar / Reminders / Vault の安全なラッパーを追加し、HITL 提案の回帰テストを行う。
3. runtime と LLM tool loop、実行記録、SSE API を追加する。
4. REST API / schemas / services と API テストを追加する。
5. React 型、クライアント、ルート、管理・会話 UI と Vitest を追加する。
6. 予定アシスタントのテンプレートを実装し、既定のモデルが未設定時に使われることを確認する。
7. `uv run pytest tests/`、`make test-e2e`、実サーバーでの目視確認を行う。

## 検証方針

- DB、registry、runtime、API は pytest を使い、外部 LLM / Web / EventKit はモックする。
- Calendar / Reminders の書込みは、直接 Apple ツールが呼ばれず、HITL Run が登録されることを確認する。
- SSE は API テストで `text` → `done`、失敗時 `error`、Bearer 認証を検証する。
- フロントエンドは Vitest で設定保存・会話ストリーム表示・HITL 承認待ちリンクを検証する。
- E2E は「エージェント作成 → 会話送信 → 応答完了」が主要フローを操作不能にする回帰を防ぐため追加する。外部依存をモックした seed scenario を使う。

## v1 の対象外

- Calendar / Reminders の更新・削除・完了操作。
- 任意のコード、MCP サーバー、URL をユーザーがツールとして登録する機能。
- 承認後の自動会話再開、ツール実行の取消、バックグラウンドジョブ、再接続、詳細な進捗表示。
- ユーザー／権限のマルチテナント化。既存 Web の単一 Bearer 認証境界を継続する。
