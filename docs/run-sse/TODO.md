# Run／再接続 SSE 実装 TODO

詳細な契約は [plan.md](plan.md) を正とする。完了の判定は「コードを書いた」ではなく、下記の該当テストと受入条件を満たした時点とする。

## 永続化と状態

- [x] 次のSQLite加算マイグレーションを追加する。`database.py:run_migration_v34`＋v35（single-active部分unique）
- [x] `agent_runs`／`coding_runs`へinstance所有情報とidempotency keyを追加する。
- [x] `agent_run_events`／`coding_run_events`、run内カーソル用インデックス、session内idempotency制約を追加する。
- [x] 非終端／終端状態と許可遷移をstore層に集約する。`agents/store.py:AGENT_*`、`coding/store.py:CODING_*`
- [x] sessionごとのactive run制約、実行中sessionの削除拒否、開始の冪等性を実装する。`start_queued_run`、`get_active_run_for_session`
- [x] 状態変更とイベント追記のトランザクション整合をテストする。`tests/test_run_sse_store.py:test_agent_status_event_transactional_integrity`

## ワーカー

- [x] HTTP応答から独立したAgent／Coding実行関数へ既存generatorの本体を抽出する。`runs/agent_worker.py:execute_agent_run`、`runs/coding_worker.py:execute_coding_run`
- [x] event append APIと、250ms／約4KB単位の`text_append`集約を実装する。`runs/events.py:TextAggregator`
- [x] FastAPI lifespanで開始・終了するAgent／Coding各1本のワーカーを実装する。`runs/manager.py:run_worker_lifespan`、`web/app.py:lifespan`
- [x] アプリプロセス存続中exclusive lock、`instance_id`、claimを実装する。`runs/instance.py:RunWorkerLock`
- [x] shutdown時に自インスタンスの非終端runだけを`interrupted`化し、cancel通知を行う。`runs/manager.py:shutdown_recovery`
- [x] 起動時はlock取得成功後に限り、停止済み前インスタンス所有の非終端runを`interrupted`化する。`runs/manager.py:startup_recovery`
- [x] Coding workerがCLI完了までrepo lockとcancel登録を維持することを確認する。`tests/test_run_sse_coding_api.py:test_coding_worker_holds_lock_and_cancel_registry_during_cli`

## APIとSSE

- [x] Agent／Codingのrun開始APIを追加し、202、run、`Idempotency-Key`の再送契約を実装する。`POST /agent-sessions/{id}/runs`、`POST /coding/sessions/{id}/runs`
- [x] Agent／Codingの`GET /runs/{run_id}/events`を追加する。
- [x] `Last-Event-ID`から `event_id > cursor` を昇順replayし、heartbeatとterminal closeを実装する。
- [x] SSEを`id:`付きで送る。payloadは永続イベント行と同じものを使う。
- [x] run単位の取消APIを状態遷移へ接続する。`POST /agent-runs/{id}/cancel`、`POST /coding/runs/{id}/cancel`
- [x] 旧`POST .../messages/stream` Web APIを削除する。
- [x] subscriberのdisconnect／`CancelledError`がrunを変更しないことをテストする。`tests/test_run_sse_agent_api.py`、`tests/test_run_sse_coding_api.py`

## フロントエンド

- [x] run開始と購読を分離するAPIクライアント・型を追加する。`api/client.ts:startAgentRun`、`api/coding.ts:startCodingRun`
- [x] `Last-Event-ID`を送るFetchベースの再接続subscriberを実装する。`api/runSse.ts:subscribeRunEvents`
- [x] event IDの重複除去と、`text_append.delta`のappend-only復元を実装する。`runSse.ts:foldTextDeltas`
- [x] sessionStorageを最終適用IDのキャッシュだけに限定する。`run-sse:{domain}:{run_id}:last-event-id`
- [x] AgentsPageの既存AbortControllerを購読専用に置き換える。
- [x] CodingPageへ同じ購読・復元処理と`session_id` URL選択を追加する。
- [x] active runを初期ロードで復元し、遷移／再読込後に自動購読する。

## 品質確認と文書

- [x] backendの切断・再購読・冪等性・startup/shutdown・CLI取消テストを追加する。`tests/test_run_sse_*.py`
- [x] Frontend Vitestで遷移、アンマウント、再購読、重複排除、URL復元を追加する。`runSse.test.ts`、`AgentsPageRunSse.test.tsx`、CodingPage tests
- [x] `uv run pytest tests/`（1009 passed、E2E 1件は既存 people シナリオの失敗で本件と無関係）、対象Vitest 284 passed、TypeScript型チェック clean を実行する。
- [x] `ai_wiki/10-Decisions-Web.md`と本ディレクトリを実装結果に合わせて更新する。
