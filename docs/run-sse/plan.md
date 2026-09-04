# 再接続可能な Run 実行・SSE 配信

## 目的

`/agents` と `/coding` において、HTTP/SSE 接続の生死が LLM、ツール、CLI ワーカーの実行を左右しないようにする。ブラウザの通信断、画面遷移、再読込後は、同じ run の未受信イベントを再生してライブ購読を再開する。

対象外はサーバー再起動後の自動再実行、LLM リクエスト途中からの復元、外部 CLI の途中からの自動継続である。これらは副作用の二重実行を避けるため、`interrupted` として利用者が新しい run を開始する。

## 現状と変更方針

現状の `POST .../messages/stream` は、HTTP 応答の async generator 内で user message 作成、LLM／オーケストレーター、ツール、CLI を実行している。そのためクライアント切断で generator がキャンセルされ、実行の完了、状態確定、ロック解放が不整合になり得る。イベント ID の保存・再生 API もない。

新構成では、開始 API は run を永続化して即時に返し、アプリ内常駐ワーカーが実行する。SSE は永続イベントを読むだけであり、切断されても run を変更・取消しない。

```text
POST /sessions/{id}/runs
  -> SQLite: user message + queued run + idempotency key
  -> 202 { run }

同一プロセスの run worker
  -> queued run を実行
  -> 状態変更・LLM本文・ツール進捗を SQLite event log へ追記

GET /runs/{run_id}/events + Last-Event-ID
  -> event_id > cursor を順序どおり replay
  -> 新規イベントを継続配信
```

## 永続化と状態遷移

### Run

既存の `agent_runs` と `coding_runs` を拡張する。既存の完了名は維持し、Agent は `succeeded`、Coding は `completed` を成功の terminal state とする。

- 非終端: `queued`、`running`、`cancelling`、`waiting_user`
- 終端: `succeeded` / `completed`、`failed`、`cancelled`、`interrupted`
- `idempotency_key`、`created_instance_id`、`worker_instance_id` を追加する。
- 同一 session に `queued`、`running`、`cancelling`、`waiting_user` の run がある場合は、新規開始を拒否する。
- 実行中または待機中の run を持つ session の削除は拒否し、先に明示キャンセルを要求する。

開始 API は、session ごとに一意な `Idempotency-Key` を受け取る。同じキーでの再送は、入力を二重保存・二重実行せず、最初に作成した run を返す。キーの衝突で本文または添付が異なる場合は 409 を返す。

### Event log

参照先が異なる run テーブルへ外部キーを張れるよう、次の二つのテーブルを追加する。

- `agent_run_events`
- `coding_run_events`

両者は次の同一形状を持つ。

| 列 | 意味 |
| --- | --- |
| `event_id INTEGER PRIMARY KEY AUTOINCREMENT` | ドメイン内で単調増加する再生カーソル |
| `run_id` | 親 run への外部キー |
| `event_type` | 下記の正規化済みイベント種別 |
| `payload_json` | UI が必要とする JSON payload |
| `created_at` | イベント確定時刻 |

関連する run、message、tool-call の変更とイベント行の追記は同じ SQLite トランザクションで確定する。これにより、画面には見えたが後から再生できない状態を作らない。

イベントは完了後7日を過ぎた terminal run から削除する。会話本文、run、tool call、CLI 出力など既存の確定データは削除しない。履歴が期限切れの run を開いた場合は既存の詳細 API で確定結果を表示し、ライブ進捗の再構築は行わない。

### 本文イベント

LLM 本文には `text_append` を使う。payload の `delta` は「現在までの全文」ではなく、直前までの本文の末尾へ追加する文字列である。クライアントは event ID 順に連結して表示する。

SQLite の書込みをトークン単位にしないため、最大250msまたは約4KBで複数トークンを一つの `text_append` イベントへ集約する。ワーカーはイベントを保存してから配信可能にする。クラッシュ時に失われ得るのは未コミットの集約バッファだけであり、run は `interrupted` になる。

既存の進捗イベントは payload を保ったまま event log に記録する。Agent では `thinking`、`tool_call_detected`、`tool_call_start`、`tool_call_end`、`text_append`、`user_question`、`done`、`error`、`cancelled` を、Coding では `orchestrator_start`、ツール進捗、`orchestrator_message`、`cli_request`、`worker_start`、`worker_done`、`done`、`error`、`cancelled` を記録する。

## API 契約

すべて Bearer 認証を必須とし、`EventSource` は使わない。既存と同じく Fetch `ReadableStream` を使い、Authorization と `Last-Event-ID` を送る。

| API | 振る舞い |
| --- | --- |
| `POST /api/v1/agent-sessions/{session_id}/runs` | Agent run をキュー投入し、202 と run を返す。 |
| `POST /api/v1/coding/sessions/{session_id}/runs` | Coding run をキュー投入し、202 と run を返す。 |
| `GET /api/v1/agent-runs/{run_id}/events` | Agent event log を SSE replay + follow する。 |
| `GET /api/v1/coding/runs/{run_id}/events` | Coding event log を SSE replay + follow する。 |
| `POST /api/v1/agent-runs/{run_id}/cancel` | queued/running run の取消を要求する。 |
| `POST /api/v1/coding/runs/{run_id}/cancel` | 既存 cancel API を同じ状態契約へ移す。 |

購読 API のアルゴリズムは次で固定する。

1. クライアントは最後に**適用した** event ID を `Last-Event-ID` に送る。未指定時は 0 とする。
2. サーバーは `WHERE run_id = ? AND event_id > ? ORDER BY event_id ASC` で取得し、各行を `id: <event_id>` と JSON `data:` で送る。
3. 最後に送った ID をカーソルにして同じクエリを繰り返す。新規行がなければ15秒ごとに SSE comment heartbeat を送る。
4. terminal event まで追従したらストリームを閉じる。接続失敗時はクライアントが同じ手順で再接続する。

配送は at-least-once である。クライアントは `event_id <= lastAppliedEventId` を無視して、ネットワーク再送による二重表示を防ぐ。

旧 `POST .../messages/stream` のWeb APIは削除する。HTTP ストリーム上で実行を開始する経路を残さない。`agents/cli.py` と `coding/cli.py` はHTTP APIを使わないため、既存の内部 generator 適応を維持できる。

## ワーカーとプロセス生存性

FastAPI の lifespan 内で、Agent 用と Coding 用を各1本持つワーカーを開始する。両者は同じプロセス存続中exclusive lockを共有し、二つ目のアプリプロセスが lock を取得できなければ、ワーカーを起動せず、既存runを更新しない。個人運用では単一ASGI workerを前提とする。

ワーカーは `queued` run を claim して `worker_instance_id` を設定し、現行の実行ロジックを HTTP generator から切り出して呼ぶ。SSE購読の取消や `ClientDisconnect` は購読ループだけを止め、run の状態・キャンセルイベント・実行タスクには触れない。

明示キャンセルでは run を `cancelling` として永続化してから、所有ワーカーへ通知する。Coding は既存の `threading.Event` によりCLIのprocess groupを停止する。Agent の同期ツールは現在の呼出し単位でしか停止できないため、取消はそのツール呼出しが戻った後に反映される場合がある。

正常shutdownでは、lockを保持する自身の `queued`／`running`／`cancelling` run だけを `interrupted` にしてから lock を解放する。新プロセスはlockの取得に成功した場合だけ、異なる `created_instance_id` または `worker_instance_id` を持つ非終端runを `interrupted` にする。lock取得に失敗する、生存中の別プロセスは絶対に `interrupted` 化しない。

この保証はアプリ実行プロセスに対するものだ。OS強制終了後にCLI子プロセスだけが残る可能性はあるため、再起動後に同じリポジトリの新規Coding runを自動開始・自動再試行しない。残留プロセスの検出・終了を将来追加する場合も、PID／process group の所有性確認なしに kill しない。

## フロントエンド

- 開始成功後、返された`run_id`で即座に購読する。開始と購読の間に発生したイベントも event log から取得できる。
- `sessionStorage`は `run-sse:{domain}:{run_id}:last-event-id` だけを保存する補助キャッシュとする。サーバーの event log が復元の正本であり、storage 消失時は先頭から再生する。
- 接続が切れた場合は指数バックオフで再購読する。terminal state、認証失効、明示キャンセル時は再接続しない。
- アンマウント・session切替では購読用 `AbortController` だけを abort する。実行取消はキャンセルボタンだけが行う。
- Agent は既存の`session_id` URL deep linkを維持する。Codingにも`session_id` URLパラメータを追加し、ページを離れて戻っても元のsessionとactive runを選択する。
- 初期ロード時はsession詳細からactive runを検出し、イベントをfoldして本文・ツール進捗・worker状態を復元してから購読を開始する。

## 実装順序

1. 次の加算マイグレーションでrunの所有・冪等性列と2種類のevent tableを追加し、store APIと状態遷移の単体テストを作る。
2. 共通のevent append／replay helper、lifespan worker、instance lock、shutdown recoveryを追加する。
3. Agentの実行本体をHTTP generatorからワーカーへ抽出し、開始・購読・取消APIに切り替える。
4. Codingも同じ構造へ移し、repo lockとCLI cancelがworkerの生存期間まで保持されることを確認する。
5. API TypeScript型、Fetch購読クライアント、AgentsPage／CodingPageの再接続・復元・URL選択を実装する。
6. 旧Web stream endpointとそれに依存するテストを削除し、決定記録と関連TODOを更新する。

## 受入条件

- Agent／Codingとも、SSE接続を切断してもrunは完了または明示取消まで継続する。
- `Last-Event-ID=N`で再購読すると、Nより大きいIDだけが昇順で届く。
- 再読込後、active runの本文・ツール進捗・CLI進捗が同じrunから復元され、重複表示されない。
- 開始APIの同一idempotency key再送は同じrunを返し、LLM／CLIを二重実行しない。
- lockを保持する生存中プロセスのrunを、二つ目のプロセスが`interrupted`へ変更しない。
- graceful shutdownまたは次回起動時に、停止済み前インスタンス所有の非終端runだけが`interrupted`になる。
- SSE接続の切断でFastAPIがrun実行をキャンセルする経路がWeb APIに存在しない。

## 検証

- backend: 冪等開始、状態遷移、event appendとトランザクション整合、`id > Last-Event-ID`再生、replay中の新規イベント、subscriber切断後の実行継続、取消、shutdown／startup recovery、session削除拒否をテストする。
- Coding: CLI実行中にsubscriberを切ってもrepo lockとcancel登録が維持されること、明示取消でprocess group停止とterminal event記録が行われることをテストする。
- frontend: 開始→購読、通信断後の再購読、event ID重複除去、画面遷移・アンマウントでrunを取り消さないこと、再読込時のactive run復元、Coding URL選択をVitestでテストする。
- database-writing testsは `uv run pytest tests/` 経由で実行する。Frontend E2Eは追加・更新しない。
