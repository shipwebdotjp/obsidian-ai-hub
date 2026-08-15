# HITL の LINE Messaging API 対応に向けた既存実装調査

調査日: 2026-08-15  
対象: 現行コードのみ。実装・設定・DBデータは変更していない。

## 公開経路の設計決定（2026-08-15追記）

WebhookとWeb UI／業務APIは同じ公開入口に置かず、次の経路に分離する。FastAPIにはLINE署名を検証して受信イベントを記録するWebhookルートを実装済みである。Funnel、専用Nginx、LINE ConsoleへのWebhook URL登録と常設運用は、引き続き運用側で整備する前提である。

```text
LINE Platform
  └─ Tailscale Funnel: https://m1mbp.tail744355.ts.net/
       └─ 専用 Nginx（127.0.0.1:8764）
            └─ LINE Webhook API

Web UI / API クライアント
  └─ Tailscale Serve: https://aihub.tail744355.ts.net/
       └─ FastAPI Web UI / 業務 API（127.0.0.1:8765）
```

Webhook経路ではLINEの署名検証を認証境界とし、Web UI／業務APIのBearer認証をWebhookへ流用しない。一方、Web UI／業務APIのBearer認証は接続元にかかわらず維持し、Tailscale Serveへの分離を理由に緩和しない。

## 1. 現在の処理フロー

### HITL の作成から実行まで

```text
ドメイン機能
  ├─ 自動リサーチ提案: research/pipeline.py
  ├─ 長期記憶保守: memory/maintenance.py
  └─ 週次メモリインタビュー: memory/interview.py
       │
       ▼
hitl.service.register_run_and_questions()
  └─ 同一SQLiteトランザクションで hitl_runs / hitl_questions を登録
     - Run: pending_user
     - 必須質問がすべて回答済みなら ready_to_resume
       │
       ├─ 現在: Web UI が一覧・詳細を取得して回答をPOST
       │       POST /api/v1/hitl/runs/{run_id}/questions/{question_key}/answer
       │
       ▼
hitl.service.submit_answer()
  - active question set だけを対象にする
  - 選択肢と必須コメントを検証する
  - status='pending' の行だけを条件付き更新（回答は一度だけ）
  - answer を {"value", "comment"} としてSQLiteへ保存
  - 必須回答がそろえば Run を ready_to_resume にする
       │
       ▼
CLI --hitl-dispatch / task_runner の定期タスク
       │
       ▼
hitl.dispatcher.dispatch_runs()
  - ready_to_resume または lease切れ running を原子的に claim
  - 任意未回答質問を skipped にする
  - handler registry からドメインhandlerを呼ぶ
  - completed / failed / pending_user（次ラウンド）のいずれかに確定
```

Web UI の回答POST自体は dispatcher を起動しない。そのため、回答後の実行は `--hitl-dispatch` が別途動くまで待つ。サンプル定期タスクには30秒ごとの dispatcher があるが、`tasks/tasks.local.sample.yml` では無効である。

HITLの質問作成者と回答後の処理は次の3系統である。

| 作成者 | 質問 | handlerの処理 |
| --- | --- | --- |
| `research/pipeline.py` | 自動提案したテーマを調査するか（承認または却下理由） | `research.run_approved_suggestion`: テーマのフィードバックを保存。承認なら research job を作成・同期実行し、Vaultへ保存。却下なら完了。 |
| `memory/maintenance.py` | 長期記憶の統合・訂正・期限切れ提案を適用／見送り／コメント付き再提案 | `memory.apply_maintenance_proposals`: snapshot競合を確認し、適用、再診断、次ラウンドの質問作成、投影更新を行う。 |
| `memory/interview.py` | 週次ノートからLLMが生成した最大3件の自由記述質問 | `memory.apply_interview_answers`: 回答から記憶候補を抽出・重複判定し、候補と監査イベントをSQLiteへ保存する。 |

質問セットは複数ラウンドを持てる。handlerは `HitlContext.register_next_questions()` を使って次のセットを同じRunに登録し、`re_suspend` を返せる。長期記憶保守がこの経路を利用する。質問の期限は `expires_at` として保存でき、dispatcher開始時に必須質問の期限切れRunを取消し、任意質問をskipする。

### 現在の LINE・予定通知フロー

```text
Apple Calendar / Reminders / 定期予定
  └─ write_today_schedule.py
      └─ Daily Note の「今日の予定」「今日のタスク」へ書き込む
           │
SQLiteの昨日の日次要約 + Daily Note の当日情報
  └─ line_notification/builder.py
      └─ notify_today_schedule.py
          └─ utils.line_messaging.send_line_push_messages()
              └─ LINE Push API（固定の LINE_TARGET_ID）
```

既存の通知機能は、`LINE_MESSAGING_TOKEN` と `LINE_TARGET_ID` を使うPush APIのテキスト送信である。週次レビュー草案も同じPush送信関数を使う。

受信側では、`POST /api/v1/line/webhook` が生のrequest bodyに対する`X-Line-Signature`検証、許可済み`source.userId`の確認、メッセージ／postbackイベントの重複排除付き記録を行い、即時に応答する。HITL回答への変換、Reply API、postbackの解釈、受信イベントを処理するworkerは未実装である。

## 2. 主要ファイルと責務

| ファイル | 責務 |
| --- | --- |
| `src/obsidian_ai_hub/hitl/service.py` | Run／質問セットの原子的登録、回答の検証・一度だけの保存、Run取消、lease claim、checkpoint更新。 |
| `src/obsidian_ai_hub/hitl/store.py` | `hitl_runs`／`hitl_questions` のSQLite CRUD、JSON列の直列化、質問の条件付き更新。 |
| `src/obsidian_ai_hub/hitl/dispatcher.py` | 再開対象の検索、期限処理、lease取得、handler呼出し、結果の状態遷移。固定leaseは5分。 |
| `src/obsidian_ai_hub/hitl/types.py` | 質問作成用の `QuestionDraft`。実際の作成者の多くは辞書を直接渡している。 |
| `src/obsidian_ai_hub/main.py` | composition root。3つのHITL handlerを登録し、`--hitl-dispatch` をCLIから実行する。 |
| `src/obsidian_ai_hub/web/routes/hitl.py` | Web UI向けのRun一覧、詳細、回答、取消API。既存のWeb認証依存を付与。 |
| `src/obsidian_ai_hub/web/services/hitl.py` | Web APIとHITLコアの橋渡し。active question setを解決して回答サービスを呼ぶ。 |
| `frontend/src/features/hitl/HitlPage.tsx` | Web UIの汎用質問表示、入力、回答送信、取消。質問type・choices・contextの一部を描画する。 |
| `src/obsidian_ai_hub/research/pipeline.py` / `research/runner.py` | リサーチ用Runの作成と、回答後のテーマ更新・調査・Vault保存。 |
| `src/obsidian_ai_hub/memory/maintenance.py` | 長期記憶保守の質問作成、再提案、回答適用。 |
| `src/obsidian_ai_hub/memory/interview.py` | 週次インタビューの質問生成、期限設定、回答からの候補作成。 |
| `src/obsidian_ai_hub/task_runner.py` | YAML定義の短命な定期コマンド実行、前回実行時刻の記録、プロセス間ロック。 |
| `jp.shipweb.obsidian-ai-hub.plist` / `batch/scheduler.sh` | macOS launchdから60秒ごとにtask runnerを起動する運用入口。 |
| `src/obsidian_ai_hub/utils/line_messaging.py` | LINE Push APIのHTTP送信。Bearer tokenと最大5件のテキストメッセージを扱う。 |
| `src/obsidian_ai_hub/notify_today_schedule.py` / `line_notification/builder.py` | 日次・週次要約とDaily NoteをLINE通知文へ組み立てる。 |
| `src/obsidian_ai_hub/write_today_schedule.py` | Apple Calendar、Reminders、設定済み定期予定をDaily Noteに転記する。 |
| `src/obsidian_ai_hub/handler/apple_reminders.py` / `handler/add_calendar_event.py` | AIツールからApple Reminders／Calendarへ書き込むmacOS EventKit連携。Inbox分類からの予定・タスク登録は `calendar/hitl.py`・`reminders/hitl.py` 経由でHITLと接続。 |
| `src/obsidian_ai_hub/reminders/hitl.py` | Inbox分類の `reminder` カテゴリに対する承認Run登録と、承認後の `add_reminder` 実行ハンドラ。 |
| `src/obsidian_ai_hub/web/app.py` / `web/routes/deps.py` | FastAPIアプリ、Web UI／業務APIのBearer認証、静的UI配信。`127.0.0.1:8765`はTailscale Serve経由でWeb UI／業務APIを提供する。 |
| `src/obsidian_ai_hub/web/routes/line.py` / `line_webhook/store.py` | LINE Webhookの署名・送信者検証、受信イベントの重複排除付きSQLite記録、即時応答。HITL回答処理やReply APIは担当しない。 |
| `src/obsidian_ai_hub/database.py` | SQLite migration v13〜v17を含む共有DB初期化。HITLは `hitl_runs` と `hitl_questions` に保存される。 |

## 3. 共通化できそうな処理

LINEを「別の回答チャネル」として扱うなら、次の既存部品をそのまま中心にできる。

| 共通化候補 | 現状 | LINE側での使い方 |
| --- | --- | --- |
| 回答確定 | `hitl.service.submit_answer()` がactive set、選択肢、コメント要件、一次性、状態遷移を一箇所で保証する。 | Web APIを経由せず、このサービスを呼ぶ受信アダプターにする。LINE固有の回答解析結果を `{value, comment}` に変換するだけに留める。 |
| 回答後の実行 | `dispatch_runs()` とhandler registryはチャネルを知らない。 | Web／LINEいずれの回答後も同じdispatcherが再開する。handlerをLINE webhookに重複実装しない。 |
| 質問の表示データ | Runのtitle/description/display_type、質問のtitle/prompt/choices/context/sequenceが永続化済み。 | LINEメッセージを生成するrendererの入力に使う。リサーチ、保守、インタビュー別の業務ロジックは持ち込まない。 |
| 一度だけの回答 | `UPDATE ... WHERE status = 'pending'` により競合時も二重保存を防ぐ。 | LINEの再送・連打で同じ質問へ届いても、保存段階では二重適用を防げる。受信イベント自体の重複防止は別途必要。 |
| 外向きLINE送信 | `_post_line_push()` にPush APIのHTTP共通処理がある。 | 質問通知の送信部分で再利用できる。ただしReply APIとPush APIのpayload／失敗管理は別途拡張が要る。 |
| 定期起動 | task runnerと`--hitl-dispatch`の既存入口がある。 | 常設worker導入前の暫定再開・期限処理には利用可能。 |

共通化の境界は、`HITL core ← チャネルアダプター（Web / LINE）` が自然である。LINE側は「通知を作る」「LINE入力を正規化する」「認証済み送信者と質問を対応付ける」に限定し、回答保存・状態遷移・業務handlerは既存HITL層に残す。

## 4. LINE対応で不足しているもの

### 受信・セキュリティ

次は運用配備と、受信イベントをHITL回答へ安全に処理するアダプターが必要である。

- LINE ConsoleへのWebhook URL登録、Tailscale Funnel → 専用Nginx → FastAPIの配備・ヘルスチェック・秘密情報注入・再起動手順。
- 実装済みの`LINE_CHANNEL_SECRET`による生bodyの署名検証と`LINE_ALLOWED_USER_IDS`による送信者認可を、運用設定とテストで継続検証すること。WebhookはBearer認証を使わず、LINE署名を認証境界とする。
- 複数利用者／グループを扱う場合の、利用者・Push宛先・HITL Run所有者の永続的な対応付け。現状は許可済みの個人送信者と固定`LINE_TARGET_ID`を前提とする。
- 記録済みWebhookイベントを処理済みに進めるworkerと、HITL回答への正規化。受信重複排除は実装済みだが、同一イベントへの返信や回答処理の監査状態は未実装である。

### LINEの会話・通知

- **決定済み・実装対象:** 各登録処理のコミット後に、既存Webフォームへの深いリンクをLINE Pushで送る。対象は自動リサーチ提案、長期記憶保守の初回登録と再提案ラウンド、週次メモリインタビューである。現状の実装は自動リサーチ提案のみであり、残りの通知と共通通知APIの追加が次の作業となる。
- 通知送信のoutbox／送信状態（宛先、質問set、作成時刻、送信試行、成功／失敗、LINE message ID等）。送信失敗時の再試行や、同じ質問の重複通知を抑える状態がない。
- LINE用の質問renderer。現在のLINE送信はtextだけで、HITLのselect、boolean、自由記述、複数必須質問、任意質問、comment必須の表現規約が未定義。
- 回答プロトコル。テキストの番号返信、Quick Reply、postback、Flex Messageのどれを使うか、および `run_id`・`question_key`・選択値を安全に識別する形式がない。
- Reply API呼出しとreply tokenの処理。既存実装は固定宛先へのPush APIだけで、受信メッセージに応答する機能はない。
- 受理、無効選択、回答済み、期限切れ、権限なし、実行開始／完了／失敗をLINEに返す文面と送信タイミング。
- LINEのメッセージ長・選択肢数・reply token有効時間などの制約に合わせて、長い`context_json`や複数質問を分割・Web UIへの導線へ退避させる設計。

### 運用・テスト

- 受信payloadの署名検証、イベント種別の選別、許可送信者、再送、競合回答、選択肢マッピングを隔離DBで検証するテスト。
- ログへchannel secret、access token、全文の個人情報を残さない方針と、失敗時に必要な相関IDの設計。
- 採用済みの公開経路を運用へ反映すること。LINE用はTailscale Funnel（`https://m1mbp.tail744355.ts.net/`）から専用Nginx（`127.0.0.1:8764`）を経由し、Web UI／業務APIはTailscale Serve（`https://aihub.tail744355.ts.net/`）からFastAPI（`127.0.0.1:8765`）へ接続する。各経路のTLS終端、ヘルスチェック、秘密情報注入、再起動を整備する。

## 5. 常設ワーカー対応で不足しているもの

現在の定期実行は「launchdが60秒ごとに`task_runner`を起動し、期限に該当する子プロセスを実行する」方式である。`--serve`のFastAPIは別途手動起動で、startup時には研究jobのstale cleanupのみを行う。LINE Webhookは受信イベントを記録して即時応答するが、HITL dispatcherや記録済みWebhookイベントを処理するworkerは常駐起動しない。

- Uvicorn/FastAPI、LINE Webhook API、専用Nginxを常設するプロセス管理（launchd、コンテナ、systemd等）。Webhookの外部到達経路はTailscale Funnel → `127.0.0.1:8764` のNginxと確定している。
- Webhook受信の即時ACKと後続処理の分離は、受信イベント記録まで実装済みである。次に、処理状態を持つworkerキュー、通知outbox、失敗復旧を設計する必要がある。
- webhook handler、通知送信、HITL dispatcherをどのworkerが担うかの責務分割。dispatcherは現在CLIの同期処理で、handler内ではLLM・Vault・Calendar等の長い／外部副作用を伴う操作を行い得る。
- 5分固定leaseの更新（heartbeat）または、長時間handlerに合わせたlease設計。今は実行中にleaseを延長しない。
- 再試行ポリシー。dispatcherでhandler例外はRunを直ちに`failed`にしretry_countを増やすが、自動リトライ、backoff、dead-letter、失敗したLINE送受信の復旧はない。
- Runと通知の冪等性境界。回答保存は一度だけだが、handlerの外部副作用（例: Vault出力、LINE通知、Calendar／Reminders書込み）の完全な再実行安全性はhandlerごとに異なる。
- 同じSQLiteをWebサーバー、短命task runner、常設workerが並行利用する際の稼働監視・容量・ロック待ちの運用。SQLiteはWALと30秒busy timeoutを設定済みだが、専用ジョブキューとしての監視指標はない。
- graceful shutdown時の受信中イベント、実行中lease、未送信outboxの引継ぎ。

常設化しても、既存の`dispatch_runs()`は再開処理の実体として流用できる。一方、WebhookのHTTPリクエスト内でhandlerまで同期実行する設計は避け、永続化後にworkerが処理する形を決める必要がある。

## 6. 設計上の未確認事項

次の判断が未確定であり、実装方針とデータモデルに影響する。

1. LINEの利用者は単一の自分だけか、複数のユーザー／グループか。現状の固定`LINE_TARGET_ID`と許可済み個人送信者の前提を、複数利用者へどう拡張するか。
2. LINE上で回答を完結させる必要が将来あるか。**現行決定は通知専用で、Web UIへの深いリンクを主導線とする。** 選択・コメント・取消は既存Web UIのBearer認証・HITL回答処理で完結させる。詳細は`ai_wiki/10-Decisions.md`の「LINE通知から既存Webフォームへ誘導するHITL v1」を参照。
3. LINE回答を導入する場合、1つのRunの複数質問をまとめて表示・一括送信するか、質問ごとに順番に送るか。また、任意質問とコメント必須の扱いをどうするか。
4. 通知のSLAと失敗時の期待値。未送信／重複送信／Webhook再送をどこまで許容し、outbox再試行、期限前リマインダー、実行結果通知を必要とするか。
5. LINEから回答を受ける場合、回答後にいつ実行するか。常設workerが即時dispatchするか、既存のポーリングを継続するか、重い処理は別キューに渡すか。
6. 外部副作用を伴うhandler（調査結果のVault保存、メモリ更新、将来のCalendar／Reminders操作）について、LINE回答後の自動実行範囲、失敗時の再試行・人への通知・手動復旧をどうするか。
## 参照した主な既存設計

- `docs/hitl/plan.md`: HITL MVPの状態遷移、dispatcher、外部通知／Webhookを当時のMVP対象外とした範囲。
- `ai_wiki/10-Decisions.md` の「LINE 通知での複数テキストメッセージ送信」: 既存LINE連携がPush APIとテキスト通知に限定される判断。
- `docs/testing.md`: DBを書き込む検証をpytest隔離環境に限定する規約。今回、テスト・DB操作は行っていない。
