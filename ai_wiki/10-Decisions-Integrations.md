# 外部連携の決定記録

## OpenCode Go の GPT モデルは Responses API を使う

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-01 |
| カテゴリ | LLM連携 |
| 決定内容 | `provider: opencode_go` のうちモデルIDが `gpt-` で始まるものは OpenAI互換クライアントで処理し、`use_responses_api=True` を指定する |

### 結論に至った経緯

OpenCode Go 経由の GPT モデルも Responses API を必要とするため、同じ OpenAI互換ルーティングに含めたうえで GPT モデルに限って有効化する。他の OpenAI互換モデルと Anthropic互換モデルの既存API選択は変更しない。

## Web リサーチの OpenAI ツール呼び出しは Responses API を使う

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-19 |
| カテゴリ | リサーチ・LLM連携 |
| 決定内容 | `provider: openai` によるツール付き Web リサーチだけ、`ChatOpenAI` の `use_responses_api=True` を指定し、`store=False` とする |

### 結論に至った経緯

`gpt-5.6-terra` は Chat Completions API で reasoning を伴う function tools を受け付けず、
`/v1/responses` を使うか `reasoning_effort='none'` を指定するよう 400 エラーで要求された。
推論を無効化すると Web リサーチの品質を落とすため、Responses API を使用する。通常の LLM 呼び出し、
deep リサーチ、OpenAI 互換の OpenCode Go 呼び出しには適用しないため、Responses API 非対応の
プロバイダーやモデルへの影響を避ける。API 側にリサーチ内容を保持しないよう `store=False` を明示する。

## SQLite を LINE 日次通知時のサマリー正本とする

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-19 |
| カテゴリ | 通知・サマリー参照 |
| 決定内容 | LINE 通知における「昨日の要約」は Markdown ノートの `## AIによる要約` セクションを読まず、SQLite の summaries / summary_items を正本として取得する |

### 結論に至った経緯

日次サマリーは LLM 生成後、SQLite に保存される。従来はこれとは別に Markdown ノートにも同一内容を追記していたが、人間の記述と AI の記述を混在させないためにノートへの追記は 2026-07-19 に停止した。ノートへの追記停止後も通知処理 (`notify_today_schedule.py`) は依然としてノート上の `## AIによる要約` を読み取るコードが残っており、古いノートに残る stale な要約を参照し続けるリスクがあった。これを解消するため、通知時のサマリー取得元を SQLite に統一する。

### トレードオフ

SQLite がサマリーの唯一の正本となり、Markdown ファイルとの二重管理が解消される。Notification 送信前にサマリーが SQLite に存在しない場合は、今日のスケジュール情報のみが通知され、昨日の要約は省略される。古いノート上の `## AIによる要約` は参照されず放置されるが、人間の記述を汚染しないという方針と一貫する。

## LINE 通知での複数テキストメッセージ送信

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-19 |
| カテゴリ | 通知・LINE連携 |
| 決定内容 | 月曜日の日次通知時に前週の週次要約を2件目のテキストメッセージとして同時送信する。Flex Message は使わず、LINE Push API の `messages` 配列に複数の `text` メッセージを入れて1回のAPI呼び出しで送信する。上限5メッセージを超えない入力だけを受け付ける。 |

### 結論に至った経緯

従来は `send_line_push()` が1テキストのみ対応していた。月曜日に週次要約も通知する要件を実現するため、複数テキストに対応した `send_line_push_messages()` を新設する。Flex Message の導入はオーバースペックであり、テキスト複数送信で十分に目的を達成できる。

### 実装方針

- `send_line_push_messages(token, to, message_texts)` は1〜5件の文字列リストを受け取り、各文字列を `{"type": "text", "text": ...}` に変換して1回のPush API呼び出しで送る。
- 既存の `send_line_push()` は `send_line_push_messages()` への薄いラッパーとして維持する。
- HTTP送信・認証ヘッダ・成功判定の共通処理は `_post_line_push()` に集約する。
- 月曜判定と前週ISO週キー算出は日時指定可能な内部ヘルパー (`is_monday`, `prev_iso_week_key`) に分離する。

### トレードオフ

Flex Message を使わないため、リッチなレイアウトは不可能だが、テキストのみで十分な情報を伝えられる。週次未作成時は日次だけ、日次が空でも週次があれば週次だけ送ることで、欠損時も柔軟に対応する。

### 補足: 要約ヘッダの文言変更

`format_summary_for_line` を日次・週次で共有するため、要約ヘッダを「💡昨日の要約」から「💡要約」に変更した。ユーザ視点では日次通知のヘッダが「昨日の」修飾を失うが、関数共通化による見返りが大きく、月曜は日次と週次の2テキストが並ぶため文脈からどちらの要約か判別可能。

## リサーチテーマ提案へのフィードバック反映（v17）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-03 |
| カテゴリ | リサーチ・HITL・フィードバック |
| 決定内容 | 承認・却下の結果、却下理由、任意コメントを `research_themes` にフィードバックとして永続化し、次回の3件提案プロンプトへ嗜好データとして渡す。 |

### 経緯

従来、auto_suggestion テーマの HITL 確認は approve / reject の2値だけで、却下理由や利用者の補足は次回提案に反映されなかった。同じ系統のテーマを繰り返し提案してしまう問題を、軽量なローカルフィードバック基盤（追加の外部学習は不要）で改善する。

### データモデル（スキーマ v17）

- `research_themes` に `feedback_decision`（approved / rejected）、`feedback_reason`、`feedback_comment`、`feedback_at` を追加。
- フィードバックを持つのは HITL 確認を経る auto_suggestion テーマのみ。それ以外のテーマはフィールドが NULL のまま。

### HITL の action 選択肢

次の単一選択に変更。既存の任意コメント欄は補足理由として `feedback_comment` に保存する。

- `approve`（承認）
- `reject:not_interested`（却下: 関心外）
- `reject:low_utility`（却下: 実用性不足）
- `reject:vague`（却下: 抽象的・不明確）
- `reject:duplicate`（却下: 既知・重複）
- `reject:not_now`（却下: 今は優先外）
- `reject:other`（却下: その他）

`run_approved_suggestion` は選択値を承認/却下へ正規化し、テーマの状態更新（approved / rejected）とフィードバック保存を同一 DB 操作（`db.set_theme_feedback`）で行う。従来の `reject` 値も理由なし却下として引き続き受容する。承認コメントは従来どおり調査コンテキストへ引き渡す。

### 堅牢化（コードレビュー反映 2026-08-03）

- `db.set_theme_feedback` に不変条件の検証を追加した。`status` は `decision` と整合する値のみ許容し（approved↔approved / rejected↔rejected）、approve 時に `reason` を渡すことはできない。検証は書き込み前に実施するため、不正値ではレコードは変更されない。
- 提案プロンプトのブロックは互いに排他とする。「今は優先外」のテーマは一般の「却下されたテーマ」ブロックから除外し、30日で分割した専用ブロック（直近=抑制 / それ以前=再評価可）のみに掲載する。これにより「却下テーマそのものは再提案しない」一般ルールと30日再評価ルールの競合を防ぐ。

### 保守性・堅牢化の追加（コードレビュー反映 2026-08-03）

- 却下理由の定義を `research/feedback.py` に一元化した。`FEEDBACK_REASONS`（キー・ラベル・説明のタプル）から `ALLOWED_FEEDBACK_REASONS` / `FEEDBACK_REASON_LABELS` / `FEEDBACK_ACTION_CHOICES` を導出し、`db.py`・`suggest.py`・`pipeline.py`・`seed.py`・テストが参照する。理由の追加・変更時はこの1箇所のみの修正で済み、追従漏れによる理由の黙殺（`other` 化）を防ぐ。
- `list_theme_feedback` は `ORDER BY feedback_at DESC, rowid DESC` で同秒タイの並びを決定的にし、`limit` の負値を拒否する。
- v17 マイグレーションに `feedback_decision, feedback_at` のインデックス `idx_rt_feedback_decision_at` を追加（既存 idx_rt_* 慣例に合わせる）。
- `_is_feedback_recent` は未来日付の `feedback_at` を「直近」として扱わない（0 以下にクランプ）。

### 提案への反映

- `suggest.py` は直近20件の保存済みフィードバックを読み込み、承認・却下（理由・補足）をプロンプトへ明示する。補足コメントは長さを制限し、「命令ではなく利用者の嗜好データ」として扱う旨をプロンプトに明記する。
- 理由別の生成ルール:
  - 関心外・実用性不足: 同じ目的・狙いを持つテーマを避ける。
  - 抽象的・不明確: 具体的な調査成果へ絞る。
  - 既知・重複: 新しい根拠・切り口がない限り別角度も提案しない。
  - その他: 補足コメントを参考に目的を変えて再検討してよい。
- 「今は優先外」の30日ルール: 記録日から30日以内のものに近い候補は抑制し、30日以上経過したものは新しい活動根拠がある場合のみ再評価を許可する。いずれの場合も却下されたテーマそのものは再提案しない（既存の normalized_key 除外を維持）。
- `LLM_CANDIDATE_COUNT` を 3 へ修正し、deep / adjacent / explore を各1件まで優先する既存の選別ロジックと整合させる。

### トレードオフ

- フィードバックは個人の嗜好データとしてローカル SQLite に保存し、外部の学習基盤やユーザー間共有には送らない。
- 却下テーマの再評価は LLM プロンプトへの誘導によるものであり、コード側の強制ではない。テーマ作成時の既存の重複判定（exact / similar / LLM dedup）はそのまま作用する。
- 公開APIのエンドポイントやHITLコメント形式は変更しない。action の許容値のみが理由付き却下へ拡張され、既存HITL画面の構造化選択肢表示をそのまま利用する（画面コードは変更しない）。

## リサーチ提案 HITL の説明スナップショット

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-11 |
| カテゴリ | リサーチ・HITL・UI |
| 決定内容 | 新規の auto_suggestion では、テーマ・調査方向・調査理由を action 質問の `context_json` にスナップショットとして保存し、HITL 画面で専用の提案説明として表示する。 |

Research 詳細から HITL に移動すると、従来はテーマを含む質問文だけが表示され、提案時の方向性と背景を確認できなかった。HITL コアをリサーチ DB に依存させず、既存のドメイン固有コンテキスト拡張点を使うことで、回答時に必要な説明を質問と同じ時点の情報として保持する。

- UI の表示ラベルは「テーマ」「調査の方向」「今調べる理由」とする。理由が空なら表示しない。
- 過去の HITL Run は更新・補完しない。既存レコードの意味を変えず、新規提案だけに適用する。
- API エンドポイントと DB マイグレーションは不要で、既存の HITL question context 契約の追加利用にとどめる。

# 欠損サマリの手動回復

一覧では、実際の入力データがあるのに未生成の日次サマリ、そこから導かれる週次サマリ、週次サマリから導かれる月次サマリを復旧対象として示す。日・週・月の順に手動生成できるようにし、既存サマリの再生成も同じAPIで upsert する。再生成は手編集を上書きするため、UIで明示的な確認を要求する。自動スケジューラの再試行方針はこの導線と分離して維持する。

## LINE Webhook と Web UI／業務APIの公開経路分離

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-15 |
| カテゴリ | LINE・Web API・ネットワーク境界 |
| 決定内容 | LINE WebhookはTailscale Funnel（`https://m1mbp.tail744355.ts.net/`）から専用Nginx（`127.0.0.1:8764`）を経由して公開する。Web UI／業務APIはTailscale Serve（`https://aihub.tail744355.ts.net/`）からFastAPI（`127.0.0.1:8765`）へ接続し、両経路を分離する。 |

### 結論に至った経緯

LINE PlatformからのWebhookは外部到達可能である必要がある一方、Web UI／業務APIを同じFunnel公開面に置く必要はない。Webhook専用のNginxを入口にすることで、LINEの署名検証をWebhook固有の認証境界として扱い、Web UI／業務APIはTailscale Serve経由の運用を維持する。

### 仕組みの概要

1. **Webhook経路:** `https://m1mbp.tail744355.ts.net/` のTailscale Funnelから、loopbackで待ち受けるNginx（`127.0.0.1:8764`）を経由してLINE Webhook APIへ渡す。Webhook APIはBearer tokenではなくLINE署名で検証する。
2. **Web UI／業務API経路:** `https://aihub.tail744355.ts.net/` のTailscale Serveから、loopbackのFastAPI（`127.0.0.1:8765`）へ渡す。
3. **認証を緩めない:** 2026-08-15のBearer認証一元化は維持する。Tailscale Serve経由であっても、Web UI／業務APIのBearer tokenは必須である。

## Inbox分類にカレンダー登録カテゴリとHITL承認を追加

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-15 |
| カテゴリ | Inbox・HITL・カレンダー |
| 決定内容 | Inbox分類（`research` / `memo`）に第3カテゴリ `calendar` を追加し、カレンダー登録すべき予定を検出する。`calendar` に分類された内容は、承認/却下のHITL Run（handler `calendar.add_approved_event`）へ登録し、承認後に既存の `add_calendar_event` ツールでmacOS Calendarへ登録する。Daily Noteにはメモ欄に `[calendar]` タグで記録し、承認結果に関わらず内容を失わない。 |

### 結論に至った経緯

Inboxのメモ・音声転記に「明日14時から歯医者」のような予定が混ざっており、Daily Noteへの記録だけではリマインドが効かない。自動でカレンダーに書くと誤登録のリスクがあるため、既存のHITL（承認フロー + `--hitl-dispatch` + LINE通知）を流用して人確認を挟むことにした。カレンダー登録は実カレンダーへの副作用を伴うため、デフォルトでHITL経由とし、抽出詳細（タイトル・開始/終了・場所）は `context_json` の専用表示（`calendar_event` 型）としてHITL画面に提示する。承認/却下のみとし編集欄は設けない（誤りは却下＋コメントで拾う）。

### 仕組みの概要

1. **分類プロンプト:** `config/prompts/inbox_classification.md` に `calendar` カテゴリを追加。相対日時（「明日」「来週」）を解決できるよう `${today}` / `${created_at}` を注入し、`calendar_event`（title / start_time / end_time / location）をJSONで返させる。
2. **分類コード:** `obsidian_inbox_merge.py` の `InboxClassification` に `calendar_event` を追加し、`classify_inbox_content` は `effective_dt`（daily_file の日付 + hour_str）を受け取る。`merge_content_into_daily_note` が `category == "calendar"` のとき `calendar/hitl.py::register_calendar_event_approval` を呼ぶ。
3. **HITL登録:** コンテンツ＋開始時刻のSHA-1ダイジェストによる決定的 run_id（`hrun_inbox_calendar_{sha1[:12]}`）で冪等に登録。開始時刻をハッシュに含めることで、同一テキストでも抽出日時が異なる予定は別Runになり、上書き衝突を防ぐ。checkpoint に `calendar_event`・元content・phaseを持ち、commit後に既存の `notify_hitl_run` でLINE通知（ベストエフォート）。
4. **承認ハンドラ:** `calendar/hitl.py::add_approved_calendar_event`。却下は `phase=declined` でcomplete。承認時は `add_calendar_event.invoke(...)` を呼び、成功時 `phase=added` をcheckpointに含めた `HitlResult.complete` を返す。`phase=added` は handler 内で `update_checkpoint` せず、dispatcher の最終トランザクションで Run の status と同一トランザクション内に原子的に永続化する（handler 内の別個の非原子的書き込みによる二重登録窓を排除）。`phase=added` を再実行ガードに使い、部分失敗後の再dispatchで二重登録を防ぐ。登録は `main.py::register_hitl_handlers()` のコンポジションルートで行う。
5. **UI:** `HitlPage.tsx` に `calendar_event` 型の `context_json` 専用表示ブロックを追加（`research_suggestion` と同パターン）。編集欄は設けず既存の承認/却下選択UIを使用。

### トレードオフ

- カレンダー登録は `add_calendar_event` が既存イベントを毎回新規作成するため完全な冪等ではなく、イベント追加後のDB commit失敗時には重複登録の可能性が残る。`phase=added` チェックポイントで緩和するが、research のVault保存と同様の限界を持つ。
- 抽出した日時が誤っている場合、承認者は却下＋コメントで拾う前提。編集欄は設けない（HITL画面の複雑化を避ける）。
- 分類・抽出は同一LLM呼び出しで行うため、`calendar_event` の形式不正時は例外を握って `memo` へフォールバックする（安全性優先）。`parse_classification_response` で title/start_time の必須と、start_time/end_time がISO日時としてパース可能であることを検証し、不正な予定のHITL Run生成を防ぐ。
- 相対日付の解決基準は、分類プロンプトへ実行時に `YYYY/M/D` で渡すローカルの当日の日付とする。LLMの内部知識に依存すると年・月を誤るためであり、テストなどで明示された `effective_dt` があればそれを優先する。

## Inbox分類にリマインダー登録カテゴリとHITL承認を追加

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-15 |
| カテゴリ | Inbox・HITL・リマインダー |
| 決定内容 | Inbox分類（`research` / `calendar` / `memo`）に第4カテゴリ `reminder` を追加し、リマインダー登録すべきタスク・やることを検出する。`reminder` に分類された内容は、承認/却下のHITL Run（handler `reminders.add_approved_reminder`）へ登録し、承認後に既存の `add_reminder` ツール（`handler/apple_reminders.py`）でApple Remindersへ登録する。Daily Noteにはメモ欄に `[reminder]` タグで記録し、承認結果に関わらず内容を失わない。 |

### 結論に至った経緯

Inboxのメモ・音声転記に「明日までに本を返す」のようなTodoが混ざっており、Daily Noteへの記録だけではリマインドが効かない。カレンダー登録（`calendar` カテゴリ）と同様の流れを踏襲し、実Remindersへの副作用を伴うためデフォルトでHITL経由とする。登録対象の抽出詳細（タイトル・期限）は `context_json` の専用表示（`reminder` 型）としてHITL画面に提示する。承認/却下のみとし編集欄は設けない（誤りは却下＋コメントで拾う）。

### 仕組みの概要

1. **分類プロンプト:** `config/prompts/inbox_classification.md` に `reminder` カテゴリを追加。Todo系内容（「〜しておく」「〜を忘れずに」「〜する必要がある」）を判定し、`reminder`（title 必須 / due_date 任意）をJSONで返させる。相対期限は `${today}` / `${created_at}` から `YYYY-MM-DDTHH:MM:SS` へ解決。
2. **分類コード:** `obsidian_inbox_merge.py` の `InboxClassification` に `reminder` を追加し、`parse_classification_response` で title 必須・due_date のISOパース検証（`_validate_reminder_due_date`）。`merge_content_into_daily_note` が `category == "reminder"` のとき `reminders/hitl.py::register_reminder_approval` を呼ぶ。
3. **HITL登録:** コンテンツ＋期限のSHA-1ダイジェストによる決定的 run_id（`hrun_inbox_reminder_{sha1[:12]}`）で冪等に登録。期限をハッシュに含めることで、同一テキストでも期限が異なるタスクは別Runになる。checkpoint に `reminder`・元content・phaseを持ち、commit後に既存の `notify_hitl_run` でLINE通知（ベストエフォート）。
4. **承認ハンドラ:** `reminders/hitl.py::add_approved_reminder`。却下は `phase=declined` でcomplete。承認時は `add_reminder.invoke({"title":..., "due_date":...})` を呼び、成功時 `phase=added` をcheckpointに含めた `HitlResult.complete` を返す。`phase=added` はhandler内で更新せず、dispatcherの最終トランザクションでRun statusと同一トランザクション内に原子的に永続化する（二重登録窓を排除）。登録は `main.py::register_hitl_handlers()` のコンポジションルートで行う。
5. **完了済みRunの再登録ガード:** `register_reminder_approval` は決定的 run_id を持つため、同じ内容の再マージで既存の完了済みRun（`status=completed`）が `register_run_and_questions` により `checkpoint=awaiting_approval` / `status=ready_to_resume` へ巻き戻され、既存のapprove回答が保持されたまま再dispatchで二重登録される問題があった。登録前に `get_run` で完了済みか確認し、完了済みなら再登録せず `run_id` を返すガードを追加した（`calendar/hitl.py` にも同一の潜伏バグがあるため同様に適用）。
5. **UI:** `HitlPage.tsx` に `reminder` 型の `context_json` 専用表示ブロックを追加（`calendar_event` と同パターン）。編集欄は設けず既存の承認/却下選択UIを使用。

### トレードオフ

- リマインダー登録は `add_reminder` が既存リマインダーを毎回新規作成するため完全な冪等ではなく、登録後のDB commit失敗時には重複登録の可能性が残る。`phase=added` チェックポイントで緩和するが、カレンダーと同様の限界を持つ。
- 抽出した期限が誤っている場合、承認者は却下＋コメントで拾う前提。編集欄は設けない。
- 分類・抽出は同一LLM呼び出しで行うため、`reminder` の形式不正時は例外を握って `memo` へフォールバックする（安全性優先）。`parse_classification_response` で title 必須と、due_date がISO日時としてパース可能であることを検証する。

### 時刻なし期限（日付精度）の扱い（2026-08-16 追記）

リマインダー期限の時刻が読み取れない入力（例:「8月20日まで」）は `YYYY-MM-DD`（日付のみ）の ISO 期限として保持し、Apple Reminders には年・月・日のみを設定した `NSDateComponents` で「時刻なし」の期限として登録する。時刻が明示された入力（`T00:00:00` を含む）は従来どおり年・月・日・時・分・秒のコンポーネントで時刻付き期限として登録する。

- **分類プロンプト:** `config/prompts/inbox_classification.md` の reminder ルールで、時刻不明時は `due_date` を `YYYY-MM-DD` で、時刻明示時のみ `YYYY-MM-DDTHH:MM:SS` で返すよう明記する。カレンダー予定の開始時刻不明時 `00:00:00` ルールは変更しない。
- **登録:** `add_reminder`（`handler/apple_reminders.py`）は `YYYY-MM-DD` の日付のみ値を日時形式と区別して解析し、年・月・日のみの `NSDateComponents` を EventKit へ渡す。時刻付き ISO 値は従来どおり時刻コンポーネントを含めて登録する。
- **インターフェース:** `due_date` の既存形式と HITL の保存・引き渡しは変更しない。`YYYY-MM-DD` も `datetime.fromisoformat` が受理するため、検証・冪等ハッシュ・承認ハンドラはそのまま動作する。

### トレードオフ（日付精度）

- 「8月20日まで」のように日付は読めるが時刻が明示されない入力を時刻なし期限として登録する一方、「0時」のように時刻が明示された入力は `00:00` の時刻付き期限として登録する。抽出精度は LLM 次第で変わるため、承認者は HITL 画面に表示される期限で確認する。

## AIプランナー提案のプレイグラウンド（スキーマ v20）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-19 |
| カテゴリ | プランナー・LLM・カレンダー/リマインダー |
| 決定内容 | Inbox→HITL→Apple登録の既存フローは変更せず、低〜中確信度のAI提案を `planner_proposals` に保存し、Web画面（プランナー）で人が編集・却下・昇格してAppleに登録する「プレイグラウンド」を追加する。 |

### 結論に至った経緯

Inbox分類は高確信度の予定・Todoを HITL 承認で登録するフローだが、そこまで確信度の高くない候補（「来週あたり検診に行くと良さそう」「本の返却期限が近い」）を登録する導線がなかった。LLM が生成した候補を直接 Apple に書くと誤登録リスクがあるため、低〜中確信度の提案は DB に保存し、専用 Web 画面で人が確認・編集してから昇格させる。既存の Inbox→HITL フローは意図的に変更しない（確信度の高い登録導線として維持）。

### データモデル（スキーマ v20）

- `planner_proposals` テーブル: `proposal_id`（`pp_` プレフィックスの決定的ID）/ `kind`（calendar / reminder）/ `title` / `start_time` / `end_time` / `location` / `due_date` / `rationale` / `generation_source` / `status`（proposed / promoted / rejected / expired）/ `fingerprint` / `created_at` / `updated_at`。
- 状態遷移: `proposed → promoted | rejected | expired`。
- `fingerprint = sha1(kind \x00 norm_title \x00 anchor)[:12]`（anchor = start_time or due_date）。部分ユニーク索引 `idx_pp_active_fingerprint WHERE status IN ('proposed','promoted')` で同一内容の重複提案を防ぐ。reject / expire で解放され、同じ内容を再提案できる。

### 仕組みの概要

1. **昇格は HITL を使わない:** planner は HITL Run を介さず、planner 専用 API の `POST /planner/proposals/{id}/promote` が直接 `promote_proposal` を呼ぶ。Apple への副作用を伴うため編集可能なプレイグラウンドとして扱い、既存 HITL フローを汚染しない。`register_hitl_handlers()` は変更しない。
2. **Apple は外部システムとして扱う:** `planner/apple.py` が EventKit（PyObjC）経由でカレンダーとリマインダーを取得。SQLite には保存せず、表示範囲キー（`("apple", start, end)`）の60秒TTLインメモリキャッシュで負荷を抑える。EventKit 不可・失敗時は空リスト＋エラー表示で安全に縮退する。
3. **コンテキスト8源:** Daily Note / 日次・週次サマリ / アクティビティ / リサーチ+フィードバック / プロジェクト / 長期記憶 / 今後30日間の正本スケジュール / 未確認提案履歴。各ブロックは単独で失敗しても空文字へ縮退し、提案生成を止めない。
4. **生成:** `--generate-planner-proposals`（daily 06:00 にタスクランナーで実行）。`planner/suggest.py` が `ai_planner.md` プロンプトで最大10件の候補（calendar / reminder）を JSON 生成し、`_validate_candidate` で検証して保存。既存の `llm_client.generate_llm_response` + `prompt.render_prompt`（`${name}` 形式）を再利用する。
5. **定期ルール:** 設定の `regularly_weekday_events` / `regularly_date_events` を正本とする読み取り専用の参照（`planner/recurring.py`）。`CAT_TASK=1` / `CAT_EVENT=2`。書き込み・UI 編集はしない（将来の管理画面を別途検討）。
6. **UI:** `/planner` に週グリッド（月〜日）を表示し、Apple 予定・Apple リマインダー・定期イベント・Inbox 保留・AI 提案を4レイヤーで重ねる。日付未定の提案は「日付未定のAI提案」セクションに分離。詳細パネルでタイトル・種別・日時・場所・根拠を編集して保存できる。昇格・却下は詳細パネルから実行。
7. **通知:** 生成後、新規提案の要約（件名＋種別＋日付、最大10件）を LINE にベストエフォート通知し、`/planner` へのリンクを添える。

### 提案生成時の正本スケジュール参照（2026-08-20 追記）

提案生成は、生成日を含む30日間について、Apple Calendar・未完了Apple Reminders・`regularly_weekday_events` / `regularly_date_events` から展開したCONFIG定期予定を、既存のLLMコンテキストに読み取り専用で含める。Apple は既存のEventKit取得・60秒キャッシュと `APPLE_CALENDAR_NAME` フィルターをそのまま利用し、定期予定は既存のCONFIG正本から展開する。これらを保存したり、提案生成でAppleへ書き込んだりはしない。

プロンプトでは、正本スケジュールと実質同じ提案を避け、時刻指定の候補を既存の時刻指定予定と重複させないよう指示する。これは生成時の制約であり、提案候補を機械的に棄却する新しい衝突判定は導入しないため、従来どおり人がプレイグラウンドで最終確認・編集する。

Apple取得が失敗・利用不能の場合は、Apple項目だけを空としてログへ記録し、定期予定および他のコンテキストを用いて生成を継続する。

### トレードオフ

- 昇格は HITL 承認を介さないため、既存 HITL フローの二重登録ガード（`phase=added`）は適用されない。昇格の原子性は「Apple 書き込み成功 → `transition_status('promoted')`」の順で担保し、Apple 書き込み失敗時は proposed のまま残す。Apple ツール自体は既存の `add_calendar_event` / `add_reminder` を再利用するため、登録 API の冪等性の限界は既存 HITL フローと同様に残る。
- 編集は保存時に fingerprint を再計算するため、重複提案を避けつつユーザーが内容を自由に修正できる。
- 提案の質は LLM とコンテキストに依存し、確信度の低い候補を含むため誤提案もあり得る。人が確認するプレイグラウンドとしての位置づけを維持する。
- Apple データをキャッシュするため、他のプロセスが Apple を更新しても最短60秒は画面に反映されない。明示的な再読み込み・昇格成功・表示期間変更ではキャッシュを無効化する。

## ヘルスケア: Apple Health export の分離DB・全種raw保存（スキーマ v1）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-24 |
| カテゴリ | ヘルスケア・外部連携・DB分離 |
| 決定内容 | iPhone のヘルスケア export（`export.xml` 407MB / 2.1M行）を分離DB `healthcare.sqlite3` に全種 raw 保存。ECG 波形はファイル参照（`health_ecg.file_path`）で DB 非格納。 |

### 結論に至った経緯

407MB / Record 約110万のヘルスデータを `memory.sqlite3` に同居させると VACUUM/WAL/バックアップへ影響するため、既存の `vault_index` と同様に `_optional_path("HEALTHCARE_SQLITE_PATH","healthcare","sqlite_path")` で分離。`ENV=test` 時は `TEST_WORKSPACE/healthcare.sqlite3` に隔離し、`OBSIDIAN_AI_HUB_TESTING=1` 時の本番DB保護ガードと `MEMORY` との分離ガードを `healthcare/store.py` で実装。HealthKit の将来 type 追加に耐えるよう type 毎テーブル分割を避け、単一 `health_records` ＋メタデータ/HRV/Workout/Activity/ECG の正規化テーブルを採用。ECG は 512Hz・30秒で15k samples と肥大化するため CSV 参照とし、`read_ecg_samples()` でストリーミング読込・`limit` 対応・`ValueError` で欠落を顕在化。

### データモデル（スキーマ v1）

- `health_imports`（`running→succeeded/failed`、locale/Me/export_date、stats_json）
- `health_records`（fingerprint UNIQUE、type/value_text/value_numeric/unit、source/device、start/end）
- `health_record_metadata` / `health_hrv_beats` / `health_workouts` 系4テーブル / `health_activity_summaries` / `health_ecg`（file_path UNIQUE、sha256/file_size）
- fingerprint: `SHA256(type|syncId)`（syncId 存在時）else `SHA256(type|source|version|start|end|value|unit)`、Workout は `SHA256(activityType|source|version|start|end)`。`INSERT OR IGNORE` で冪等。
- `models.py` の `HealthRecord/HealthWorkout` を `importer._handle_*` の単一ソースとして利用（`metadata` は `tuple[tuple[str,str]]` で `compare/hash=False`）。

### 仕組みの概要

1. **Importer** (`healthcare/importer.py`): `iterparse(start/end)`＋`health_data_elem.clear()` で streaming、batch 5000 ごとに `commit`＋`clear`。`dry_run` は DB 無しで件数カウント。失敗時は `rollback()` 後に `failed` 記録して再raise（部分batchの半端な永続化を防止）。
2. **ECG** (`_parse_ecg_csv_header`): 先頭15行を `csv` モジュールでストリーミング parse、`read_ecg_samples` は `limit` で早期 break し `non-finite`/`comma` を `ValueError` に。
3. **CLI** (`import_apple_health.py` 薄ラッパ＋`main.py --import-apple-health` 統合): `--healthcare-export-dir/--healthcare-batch-size/--healthcare-dry-run` を `run_and_log("import_apple_health")` で実行。`--batch-size` は `_positive_int` で正数バリデーション。
4. **設定** (`config.yml`): `healthcare: { sqlite_path, export_dir }` を既定 `~/.config/obsidian-ai-hub/healthcare.*` に追加。
5. **テスト** (`tests/healthcare/`): `fixtures/export_mini.xml`（7 records/1 workout/1 activity）＋`ecg_mini.csv`、helpers の遅延読込（`lru_cache`＋`__getattr__`）と `ECG_DATE` 導出、22 passed（ECG冪等・失敗時rollback・dry-run/batch-sizeバリデーション含む）。

### トレードオフ

- 分離DBのためバックアップ対象は `memory.sqlite3` とは別に `healthcare.sqlite3` を `backup/sync_folders` に含める必要がある。将来の `health_daily_metrics` 集計は VIEW/refresh ジョブで追加予定。
- ECG 波形を DB に持たないため検索はファイルI/O依存だが、医療データの肥大化と `health_ecg_samples` の `WITHOUT ROWID` 運用コストを回避。
- re-import は fingerprint UNIQUE で `ignored_duplicates` として集計し、2回目は `health_records` 不変・`health_imports` のみ追加。ECG も `UNIQUE(file_path)` で同様。
