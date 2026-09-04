# HITL の決定記録

## HITL（Human-In-The-Loop）永続化モデルとコアサービスの実装

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-23 |
| カテゴリ | HITL管理・データベース |
| 決定内容 | SQLiteのスキーマをv13へ移行し、`hitl_runs` と `hitl_questions` テーブル、インデックス、および一意制約を追加。状態遷移・回答検証・アトミックなトランザクションを保証するストアとサービス層を実装する。 |

### 結論に至った経緯

1. **データベース・スキーマ設計 (v13):**
   - 実行制御（Run）と、個々の対話（Question）を完全に分離して管理。
   - `hitl_questions` 側で `(run_id, question_set_id, question_key)` の複合一意制約（UNIQUE）を定義し、同一質問セット内の重複登録を厳密に防止。
   - インデックスとして、Runsの `status`、およびQuestions の `(run_id, question_set_id)` および `status` を追加して、待機・再開検索を高速化。

2. **状態遷移と回答検証の保証:**
   - 単一トランザクションによる整合性担保: `register_run_and_questions`、`submit_answer`、`cancel_run`、`claim_run` などの操作は、それぞれSQLite接続のトランザクションコンテキスト（`with conn:`）で囲み、状態更新をアトミックに実行する。
   - 外部キー制約保護: 質問登録時は、まずRunの登録/更新を完了（`upsert_run`）させてから質問群をインサート（`insert_question`）することで、FK違反エラーを回避する。
   - 回答の検証（選択肢の合致確認）と一回のみの回答制限（finalized状態でない場合のみ受付）を厳格に行う。

3. **アトミックClaimと任意質問の自動スキップ:**
   - `claim_run` 実行時、Runの状態が `'ready_to_resume'`（またはリース切れ）であることをアトミックに検証したうえで、同一トランザクション内で未回答の任意質問（`is_required = 0` 且つ `status = 'pending'`) をすべて一括して `'skipped'` に確定させ、Runのリース情報を設定して `'running'` 状態へ移行する。
   - `cancel_run` 実行時には、active question setの待機中の質問を `'cancelled'` へと一括してステータス移行する。

## HITL 再開コントラクトとディスパッチャーの実装

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-23 |
| カテゴリ | HITL管理・実行制御 |
| 決定内容 | HITLの実行再開、再サスペンドのコントラクト（`HitlContext`, `HitlResult`）と、アトミックなポーリング・実行ディスパッチャーを導入する。 |

### 結論に至った経緯

1. **コンテキスト設計とドメイン疎結合 (`HitlContext` / `HitlResult`):**
   - HITLコアモジュールが各個別ドメイン（リサーチ、サマリなど）に依存するのを防ぐため、ドメインからのインポートを排除した独立したイベント駆動のコントラクトを設計。
   - 各ハンドラーは、現在状態を示す `checkpoint` と、ユーザー回答をまとめた `answers_by_question_key` に加え、同一トランザクション内で次回以降の質問票（次のサスペンド状態）を再登録可能なDBコネクション `conn` を含む `HitlContext` を受け取る。
   - ハンドラーの返却値は `HitlResult` クラスとして表現し、`completed`（正常完了）、`failed`（実行失敗）、`re_suspended`（再中断、次の質問セットを登録済み）の3状態を明示的に返す設計とした。

2. **原子性を担保したポーリングディスパッチャー (`dispatch_runs`):**
   - 多重起動時やバックグラウンドでの安定実行のため、`status = 'ready_to_resume'` の Run および `status = 'running'` かつ lease 期限切れ（タイムアウト）の Run のみを対象にポーリング。
   - ディスパッチャー実行時に `claim_run` を用いてアトミックにリースロックを確保し、他のワーカーとの競合を完全に排除する。
   - 登録されたハンドラーが例外をスローした、または未登録だった場合は、それを安全にキャッチして DB 内のステータスを `failed` にマークし、エラーメッセージとリトライ回数をインクリメントして、リースを確実に解放する。

3. **チェックポイントによる重複実行の安全性:**
   - リース切れによって再度ポーリング・実行された場合、ハンドラーは `context.checkpoint` を参照してどこまで実行したかを確認できる。これにより、重複した副作用（外部API呼び出しやファイル書き出しなど）を防ぐべき冪等な制御ロジックをハンドラー側で柔軟に実現できるように設計。

4. **コンポジションルートでのアセンブリ:**
   - `src/obsidian_ai_hub/main.py` (アプリケーションのコンポジションルート) 内に `register_hitl_handlers()` を配置し、そこで必要な機能ハンドラーを登録するアプローチをとることで、コア（HITLモジュール）がドメイン層をインポートする逆流依存を完全に排除。

## HITL スキーマ v14 とテスト実行結果

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-23 |
| カテゴリ | HITL テスト・検証 |
| 決定内容 | スキーマバージョン v14 を採用し、テスト網羅性検証を完了。全既存テスト・新規追加テスト・E2E を通過。 |

### スキーマ v14 への移行経緯

- 設計ドキュメントでは v13 が想定されていたが、実装過程で user_version 14 に落ち着いた。
- `tests/test_hitl.py::test_hitl_db_migration_and_structure` で `PRAGMA user_version = 14` を検証している。
- v14 で定義されたカラム: `hitl_runs` (run_id, handler, status, checkpoint, active_question_set_id, lease_owner, lease_expires_at, retry_count, error_message, created_at, updated_at) および `hitl_questions` (question_id, run_id, question_set_id, question_key, status, question_type, display_text, choices, answer, is_required, expires_at, answered_at, created_at, updated_at)。

### テスト網羅性

セクション 5 の全項目を検証するテストを追加:
- DB ロールバック (`test_register_run_and_questions_rollback_on_failure`)
- CLI フラグ発火 (`test_dispatch_cli_flag_processes_runs`)
- 複数 Run 同時 dispatch (`test_dispatch_processes_multiple_runs_in_single_call`)
- 完全ライフサイクル (`test_full_happy_path_dispatch`)
- API 認可 (`test_hitl_api_requires_token_when_not_loopback`)
- ページネーションとフィルタ (`test_hitl_api_list_pagination_and_status_filter`)
- Vault 出力冪等性 (`test_suggestion_hitl_run_approve_then_redispatch_idempotent`)
- Handler 失敗復旧 (`test_suggestion_hitl_run_handler_failure_records_failed_status`)
- 手動リサーチ経路が HITL を作らない回帰 (`test_web_manual_research_paths_do_not_create_hitl_runs`)
- パッケージ独立性 (`test_hitl_package_does_not_import_research_at_import_time`)
- タスクスケジューラプリセット (`test_task_runner_preset_contains_hitl_dispatch`)
- Vitest: ステータスフィルター (`HitlPage.test.tsx` の `filters runs by status when dropdown changes`)

## 長期記憶の自動診断メンテナンスとHITL連携

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-31 |
| カテゴリ | 長期記憶・HITL・保守 |
| 決定内容 | 手動CLI `--memory-maintain` による長期記憶の自動保守診断と、独立したHITLハンドラ `memory.apply_maintenance_proposals` による段階的かつ冪等なDB適用を導入する |

### 結論に至った経緯

長期記憶（承認済みメモリ）は蓄積されるにつれて、情報の重複・古さ・矛盾が生じる。既存のHITLコア（`src/obsidian_ai_hub/hitl/`）にドメイン依存のクエリや適用ロジックを混入させることなく、疎結合かつ拡張性の高い形でメンテナンスを実現するために、ドメイン側（`src/obsidian_ai_hub/memory/maintenance.py`）にロジックを閉じ込めて実装する。

## 週次メモリ質問の登録と材料

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-03 |
| カテゴリ | 長期記憶・HITL・週次インタビュー |
| 決定内容 | 直近完了週の記録と、4000トークンを上限とする有効な承認済みメモリから、最大3問の週次インタビュー質問を生成し、ISO週に基づく決定的なRun IDでHITLへ登録する。 |

### 仕組みの概要

1. **一意のRun IDと冪等性**:
   - 登録されるRun IDは `mem_interview_{iso_year}-W{iso_week:02d}` のフォーマット（例: `mem_interview_2026-W30`）。
   - すでにその週のRunが登録されている場合は、再生成や質問の上書きを行わず処理をスキップ（冪等性の担保）。
2. **質問期限 (`expires_at`)**:
   - 質問の期限は「翌週月曜朝 09:00:00 JST」に固定。相対日数（7日等）ではなく、生成日時より後に来る最初の月曜09:00 JSTを算出し、ISO 8601フォーマットで検証して保存する。
3. **文脈制限**:
   - 生成プロンプトに渡す「有効な承認済みメモリ」の上限は、既存の `MEMORY_CONTEXT_MAX_TOKENS`（800）とは独立させ、インタビュー機能専用に4000トークンとする。

## 汎用HITLの期限処理

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-03 |
| カテゴリ | HITL・期限処理 |
| 決定内容 | ディスパッチ処理実行時、事前に全ペンディング質問の期限超過を走査し、必須質問が期限切れならRun全体をキャンセル、任意質問なら当該質問をスキップ（skipped）にする。 |

### 処理の挙動

- `dispatch_runs` 実行の最初（Claim処理前）に `process_expired_questions(conn)` を実行する。
- 期限切れの **必須（`is_required = 1`）質問** が1件でもある場合、そのRunを `cancelled` とし、アクティブセットの全ペンディング質問を `cancelled` にする。
- 期限切れの **任意（`is_required = 0`）質問** のみの場合、対象質問のみを `skipped` に変更する。これによって必須質問のペンディングが残っていなければ、Runのステータスを自動的に `ready_to_resume` に引き上げる。

## インタビュー回答の処理とメモリ候補抽出

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-03 |
| カテゴリ | 長期記憶・抽出・検証 |
| 決定内容 | インタビューに全回答が集まった後、ディスパッチ契機で `memory.apply_interview_answers` ハンドラが各回答から最大1件のメモリ候補を抽出・重複判定し保存する。 |

### 抽出と一括保存の挙動

1. **All-or-NothingのLLM抽出**:
   - 登録されたすべての質問に対する回答をループし、LLMに渡してメモリ候補を抽出する。
   - LLM呼び出しの失敗やJSONパースエラーなどの予期される不具合があった場合は、部分的な候補保存を行わず、ログに詳細を記録した上で `HitlResult.fail` を返却し、Runを失敗状態にする。
2. **コード側による確定根拠（provenance, evidence）の付与**:
   - `evidence` には `path = "hitl://runs/{run_id}/questions/{question_key}"`、`quote = "ユーザーの回答原文"`、`observed_at` を設定。
   - `provenance` には `extraction_method = "weekly_hitl_interview"` などの詳細メタデータをコード側で確実に設定する。
3. **重複判定**:
   - 抽出された各候補は、既存の抽出器と同様に「完全一致 normalized content による自動却下（rejected）」および「ベクトル類似度・LLMによる3ウェイ重複評価（dedup_suggestions）」を適用してからDBに保存する。

## LINE通知から既存Webフォームへ誘導するHITL v1

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-15 |
| カテゴリ | LINE・HITL・通知 |
| 決定内容 | LINE上で回答状態を管理せず、LINEはHITL Runの通知専用にする。通知リンクは既存の `/hitl?run_id=…` を開き、選択・自由コメント・取消は既存Web UIと同じBearer認証・HITL回答処理で完結させる。通知対象は自動リサーチ提案、長期記憶保守の初回登録とフィードバック再提案ラウンド、週次メモリインタビューの3系統に拡張する。 |

### 結論に至った経緯

HITLの回答チャネルをLINE上で完結させるには、LINE Webhook、LIFF、postback／自由記述の状態管理、会話セッション、常設workerが必要になり複雑度が高い。一方、`research/pipeline.py` は auto_suggestion テーマの承認Runを既にWeb向けHITLとして登録しており、フロントエンド `HitlPage.tsx` は `/hitl?run_id=…` の深いリンクを既に処理できる。そこでv1ではLINEを「通知専用」に絞り、選択・コメント・取消は既存Web UIへ誘導する。スマホはtailnet参加を前提とし、初回のみ既存のToken PromptでBearerトークンを入力、以後はブラウザのlocalStorage（`obsidian-ai-hub:api-token`）を使う。

### 仕組みの概要

1. **設定:** `OBSIDIAN_AI_HUB_WEB_URL` を追加し、Tailscale Serveの `https://aihub.tail744355.ts.net` を通知リンクの基底URLとする。URLには `run_id` 以外の秘密情報を含めない（BearerトークンはURL・LINE本文のどちらにも載せない）。
2. **通知文組み立て:** `line_notification` に、任意のHITL Run向け通知文（種別・タイトル・説明・深いリンク）を組み立てる共通内部API（`build_hitl_run_text` / `notify_hitl_run`）と、リサーチ提案用の文面（`build_research_suggestion_text` / `build_suggestion_link` / `notify_research_suggestion`）を追加する。`run_id` はURLエンコードする。送信共通処理（設定解決・ベストエフォートPush・失敗時の秘密情報を含まない警告ログ）は `line_notification.push.push_best_effort` に集約し、全系統が再利用する。
3. **送信タイミング:** 各登録処理のDBコミット**後**に、既存の `LINE_MESSAGING_TOKEN` / `LINE_TARGET_ID` とPush APIで通知を1回送る。
   - **自動リサーチ提案:** `origin=auto_suggestion` のリサーチ承認Runだけ（`notify_research_suggestion`）。手動リサーチ、完了・失敗通知は対象外。
   - **長期記憶保守:** 初回Run登録後に通知し、フィードバックから生成される次ラウンド（`round_2` 以降）も登録・コミット後に「再提案・ラウンド番号」が分かる文面で通知する（`notify_hitl_run`）。
   - **週次メモリインタビュー:** Run登録後に、対象週の説明（期間）を含む通知を送る（`notify_hitl_run`）。
   - 設定不足・Push失敗は登録処理を失敗させず、秘密情報や通知本文を出さない警告ログだけを残す（ベストエフォート）。outbox、再送、送信済み永続化は作らない。障害復旧時に通知が漏れる、または再実行時に重複し得ることを許容する。
4. **変更しない範囲:** Web UI・HITLコア・回答API・dispatcher起動タイミングは変更しない。LINE Webhook、LIFF、Funnel、会話セッション、ワーカー自動再開は実装しない。

### トレードオフ

- LINE上では回答を完結できない（通知を開いた先でWeb UIの認証と回答が必要）。
- 通知はベストエフォートであり、送信失敗時の再試行・永続化がないため、通知漏れや再実行時の重複が起こり得る。この性質は3系統すべてと保守の再提案ラウンドに等しく適用される。
- 回答後のdispatcher起動は既存Webと同じく後続作業とし、今回変更しない。

## SQLiteベースの常駐HITL Dispatcher Worker

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-16 |
| カテゴリ | HITL・実行制御・ワーカー運用 |
| 決定内容 | 専用LaunchAgent（`jp.shipweb.obsidian-ai-hub.hitl-worker`）で単一の常駐workerプロセスを運用し、5秒周期のポーリングとバックグラウンドHeartbeat、所有権付き条件確定、SIGTERM/SIGINTの優雅なドレインを導入する。 |

### 結論に至った経緯

Web UI や LINE からの回答入力後、HITL Run が `ready_to_resume` に遷移してから実行開始されるまでの最大遅延を5秒以内にするため、定期起動スケジューラ（毎分 dispatch）から常駐 worker への運用に移行した。外部キュー（Redis等）や新規スキーマは導入せず、既存の `hitl_runs.status = 'ready_to_resume'` と `lease_owner` / `lease_expires_at` を耐久キューとしてそのまま再利用する。

### 仕組みの概要

1. **常駐ワーカー・ループ (`HitlWorker`):**
   - `python -m obsidian_ai_hub --hitl-worker` で起動。起動直後および5秒ごとに `process_expired_questions` と `get_eligible_runs` を実行し、Run を直列に処理する。
2. **Heartbeat と所有権付き確定:**
   - Run の claim 後、ハンドラー実行と並行してバックグラウンドスレッド (`HeartbeatRunner`) が専用の SQLite 接続を用いて 60 秒ごとに `lease_expires_at` を「現在時刻 + 5分」に延長する。
   - 更新条件は `status = 'running'` かつ `lease_owner == worker_id` かつ `lease_expires_at >= now` である。
   - Heartbeat が失敗（DBロック喪失や別プロセスによる上書き）した場合は worker を unhealthy とし、以後の Run は claim しない。
   - ハンドラー終了後の結果確定 (`settle_run_outcome`) も同一の所有権・期限条件を満たし、かつ worker が healthy である場合のみコミットを許可する。満たさない場合は結果を保存せず、worker を exit code 1 で終了する。
3. **優雅な停止 (SIGTERM / SIGINT Drain):**
   - シグナル受信時は draining モードへ移行し、新規 Run の claim を停止する。
   - 実行中の Run がある場合は Heartbeat を継続し、現在のハンドラーの完了と条件付き確定を待って正常終了（exit code 0）する。実行中 Run がなければ直ちに exit code 0 で終了する。
4. **LaunchAgent 設定 (`jp.shipweb.obsidian-ai-hub.hitl-worker.plist`):**
   - `RunAtLoad`, `KeepAlive`, `ExitTimeOut=360`, `ThrottleInterval=10`, `StandardOutPath`, `StandardErrorPath` を設定。
   - `KeepAlive: true` のため、再配置・停止は `bootout` → `bootstrap` で行う。
5. **手動復旧とスケジューラ:**
   - `--hitl-dispatch` は手動復旧・障害調査用として維持する。二重実行を防ぐため `tasks/tasks.local.sample.yml` のサンプル設定では無効化（`enabled: false`）とし、注釈コメントを追加した。

## 会話内 ask_user HITL（複数質問対応）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-09-04 |
| カテゴリ | Agents・Coding Workspace・対話制御 |
| 決定内容 | Agents および Coding の上位オーケストレーターが要件確認を行える常時有効なシステムツール `ask_user` を追加し、既存HITLの永続化・回答・worker再開を流用して耐久的な中断・再開フローを導入する。 |

### 結論に至った経緯

1. **常時有効なシステムツール方針:**
   - `ask_user` は Agents および Coding オーケストレーターで常時有効なシステムツールとして登録する（UI上での無効化不可）。
   - 引数は `questions` 配列とし、各質問に安定した質問ID (`question_id`)、質問文、選択肢リスト (`choices`) を持たせる。
   - 固定選択肢として `{"value": "other", label: "その他（自由入力）"}` を自動付与し、選択時は自由入力テキストを必須とする。`"other"` は予約値とし、通常選択肢の `value` としての使用を禁止する。
   - CLIワーカー（Codex/OpenCode）の対話化、および `--agent-chat` / `--coding` などの非対話CLI経路は対象外とする。

2. **単一呼出し制限:**
   - 1回のLLMターンで `ask_user` と他ツールが混在した場合はいずれのツールも実行せず、全 tool call ID に対して「`ask_user` は単独で呼び出し、複数質問は `questions` 配列へまとめる」旨の ToolMessage エラーを返し、次のLLMターンで再要求させる。

3. **耐久的な中断・チェックポイントと再開:**
   - 質問時、Run のステータスを `waiting_user` に遷移させ、現在の tool call ID、会話履歴、実行設定、質問内容を HITL checkpoint へ保存する。
   - terminal `user_question` SSE イベントを発行し、待機中は同一セッションへの新規送信を拒否する。
   - 回答時は既存HITL回答API (`submit_answer`) を使用し、HITL workerが `agents.ask_user` または `coding.ask_user` ハンドラー経由でチェックポイントから再開する。
   - LLMへは `{"answers": {"<question_id>": {"selection": "<選択値>", "text": "<入力またはnull>"}}}` の構造化 ToolMessage として回答を返す。
   - ユーザーによる取消時は、HITL Run と元の Agent/Coding Run の双方を `cancelled` に更新する。

4. **共通UIコンポーネント (`WaitingRunQuestionCard`):**
   - `AgentsPage`、`CodingPage`、`HitlPage` で共有する質問カード `WaitingRunQuestionCard` を導入し、ラジオ選択・「その他」条件付きテキストエリア・送信・取消・処理中/エラー表示を統一的に提供する。

