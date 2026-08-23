# Web・フロントエンドの決定記録

## サマリ編集の上書きポリシー

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-18 |
| カテゴリ | サマリーダッシュボード |
| 決定内容 | ダッシュボード UI からの手動編集・削除は一時的なものであり、次回の自動再生成で上書きされる |

### 結論に至った経緯

サマリー生成パイプラインがソースオブトゥルースである。手動編集は再生成サイクルの間の
quick correction を意図している。編集の発生源を追跡する仕組みは、パーソナルツールとして
複雑性が高く、価値が薄い。

### トレードオフ

ユーザーは再生成後に編集を再適用する必要がある。再生成の頻度は予測可能で、編集は通常
minor であるため、これは許容可能である。

## タスク管理 Web UI (localhost 専用)

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-21 |
| カテゴリ | タスク管理・セキュリティ |
| 決定内容 | タスク YAML の Web UI 編集機能は、セキュリティ上の理由から localhost 専用 (ループバック限定) の高権限機能とし、LAN経由のアクセスは無条件で 403 Forbidden とする。 |

### 結論に至った経緯

タスク configuration の Web UI 編集は、実質的にローカル実行権限を委譲する高権限の操作である。もし Web サーバー全体を LAN や外部に公開して他のデバイスから長期記憶レビューなどを行う場合でも、タスク管理機能だけは同一マシン（localhost）からのみ操作される必要がある。

### 仕組みの概要

1. **アクセス制限:** FastAPI エンドポイント `GET`/`PUT` `/api/v1/task-config` および `/task-config/preview` は、接続元の IP がループバックアドレス（127.0.0.1, ::1）または testclient でない場合、トークンの有無にかかわらず無条件で `403 Forbidden` を返却する。
2. **プロセス間ロック:** `tasks/.task-config.lock` を共有の排他ファイルロック (`fcntl.flock`) として用い、YAML や `last_run.json` の読込・検証・書込操作を短時間のみ排他する。長時間にわたるタスクコマンドの実行中はロックを保持しないため、UI の描画や編集がブロックされない。
3. **安全な保存とアーム（Arm）:**
   - YAML の書き換えは一時ファイルへの書き出しと `os.replace` によるアトミック置換とする。
   - 新規タスクの追加、無効から有効への変更、スケジュール定義の変更、コマンドの変更があった場合は、保存時刻を `last_run.json` の `last_run` に設定（アーム）し、次回以降の未来の予定枠から実行されるようにする（過去枠の遡及実行を抑止）。

## タスク管理 Web UI (loopback または tailnet + トークン)

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-12 |
| カテゴリ | タスク管理・セキュリティ |
| 決定内容 | 「タスク管理 Web UI (localhost 専用)」を部分緩和し、Tailscale tailnet 内からのアクセスに限り、`OBSIDIAN_AI_HUB_API_TOKEN` の Bearer 認証と組み合わせてタスク管理 API の閲覧・編集を許可する。Funnel（インターネット公開）利用時の許可は明示的に禁止する。 |

### 結論に至った経緯

2026-07-21 の決定（本ファイル上の「タスク管理 Web UI (localhost 専用)」）は、タスク YAML 編集がローカルコマンド実行権限の委譲にあたるため、トークンを持っていても非ループバックからのアクセスを無条件 403 としていた。これは Web サーバーを LAN や外部に公開した場合の保険だった。

実運用では Web サーバーは Tailscale Serve（`tcp:443 -> http://127.0.0.1:8765`）経由で tailnet 内にのみ公開されており、FastAPI には tailnet クライアントの IP（100.64.0.0/10 帯）がそのまま到達する。tailnet は Tailscale 認証済みデバイスのみが入れるゼロトラスト境界であり、さらに既存の `OBSIDIAN_AI_HUB_API_TOKEN` による Bearer 認証を併用すれば、ローカル実行権限の委譲リスクは受容可能な水準と判断した。

### 仕組みの概要

1. **許可条件:** `GET`/`PUT` `/api/v1/task-config` および `/task-config/preview` は、以下のいずれかを満たす場合のみ許可する。
   - 接続元 IP がループバックアドレス（127.0.0.1, ::1, IPv4-mapped loopback）または testclient
   - 接続元 IP が tailnet 帯（IPv4 `100.64.0.0/10` / IPv6 `fd7a:115c:a1e0::/48`）**かつ** `OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS` が有効 **かつ** `OBSIDIAN_AI_HUB_API_TOKEN` の Bearer 検証が成功
2. **明示有効化（fail-closed）:** `OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS` 未設定（既定 0）では tailnet 経由の許可は発動しない。有効化時は `OBSIDIAN_AI_HUB_API_TOKEN` が必須で、未設定なら起動時に RuntimeError。
3. **Funnel 禁止:** Tailscale Funnel（インターネット全体公開）はタスク管理 API の許可対象外。Funnel でアクセスした場合も外部 IP として 403 が返る（tailnet 帯の判定で除外されるため）。
4. ループバック・テスト・YAML 保存の仕組み（プロセス間ロック・アトミック保存・アーム）は既存決定のまま変更しない。

## サマリダッシュボード統計タブの時間帯×カテゴリーヒートマップ

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-22 |
| カテゴリ | ダッシュボード統計 |
| 決定内容 | 統計タブに活動ログの `category` を用いた `時間帯 × カテゴリー` ヒートマップを追加する。母数は各時間帯のログ件数、セル値はその時刻内のカテゴリ構成比（%）とする。 |

### 実装方針

1. **データ元:** サマリートピックではなく `activity_logs.category` を使用する。
2. **集計単位:** 30分カバー時間の配分問題を避けるため、活動ログ1件を1観測として扱う。
3. **割合定義:** 時間帯内の構成比（各時刻の全ログを100%とし、カテゴリ別比率を出す）。
4. **未分類ログ:** `category = null` は `その他` に合算する。
5. **API:** 新規エンドポイントは作らず、既存 `GET /api/v1/summary-dashboard/stats` のレスポンスに `activity_categories` と `hourly_category_buckets` を追加する。
6. **フロントエンド:** 既存の手書き SVG チャート群に加えて、横スクロール可能な HTML テーブルベースのヒートマップを描画する。濃淡は青系で0%が白、100%が最も濃い色。新しいチャートライブラリは追加しない。
7. **カテゴリ定義:** `activity/categories.py` に固定9カテゴリを唯一の定義元として切り出した。`logging_activity.py` はそこから import する。

### トレードオフ

- 活動カバー時間ではなくログ件数を分母とするため、短時間に多数ログが集中すると実際の時間割合と乖離しうる。しかし重複カテゴリの時間配分ルールを導入する複雑さを回避でき、実装も単純である。
- カテゴリが存在しない時間帯はゼロ埋めせず「データなし」表示とし、0%との混同を防ぐ。

## プロジェクト別活動メモの導入

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-22 |
| カテゴリ | サマリーダッシュボード・プロジェクト管理 |
| 決定内容 | サマリーに紐付く既存プロジェクトごとに簡潔な活動メモ（自由文）を記録・表示・編集できるようにする。日次はLLMが抽出、週次・月次はサブ期間のメモを根拠にLLMが期間別要約を生成する。 |

### 詳細

1. **データモデル:**
   - `summary_projects` に `note TEXT` 列を追加（v12マイグレーション）。1サマリー・1既存プロジェクトにつき1つの自由文テキスト。
   - APIレスポンスに `project_notes: [{project_id, display_name, note, display_order}]` を追加。既存の `projects: string[]` と `project_ids: int[]` は後方互換のため維持。

2. **メモの所有と更新方針:**
   - メモの所有先は各サマリーの `summary_projects.note`。プロジェクトマスタにはメモを持たせない。
   - 日次プロンプトの `project_ids` 出力を `project_notes` に置換。LLMは既存プロジェクトごとに活動メモを抽出する。パーサーは存在するプロジェクトIDのみを受け入れ、空メモも許可する。
   - サマリー保存・取得・更新時に `summary_projects.note` を読み書きする。再生成では当該サマリーのメモをLLM出力で置き換える（手編集も上書き）。

3. **週次・月次要約:**
   - プロジェクトリンク（ID）の和集合継承は従来通り `inherit_projects_and_candidates` が行う。
   - 日次・週次の `project_notes` をプロンプトに渡し、LLM出力から継承済みプロジェクトだけの期間別要約メモを保存する。継承プロジェクトに含まれないIDの出力は無視する。
   - 継承プロジェクトのうちLLMがメモを出力しなかったものは空文字とする。

4. **編集API:**
   - サマリー更新APIに `project_notes: [{project_id, note}]` を追加。編集できるのは既に紐付くプロジェクトのメモだけとし、未紐付けID・重複IDはエラーにする。
   - プロジェクトの追加・削除はUIから行わない（現行通り）。

5. **UI:**
   - サマリーダッシュボード詳細でプロジェクトを「名称: 活動メモ」として表示。編集画面で人物メモと同様に編集可能。
   - プロジェクト詳細画面の関連サマリー一覧に `note` を含め、時系列表示する。

6. **対象外:**
   - 未解決プロジェクト候補には活動メモを追加しない。
   - プロジェクト候補の保存・解決・移管の挙動は変更しない。
   - LINE通知のプロジェクト表示にはメモを追加しない。

### トレードオフ

編集は次回自動再生成で上書きされる（既存方針と同じ）。メモはあくまでLLM抽出の補助情報であり、正確なプロジェクト進捗記録を意図していない。

## サマリダッシュボードのコンポーネント分割（ビュー抽出方式）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-01 |
| カテゴリ | フロントエンド・構成 |
| 決定内容 | 肥大化した `SummaryDashboardPage.tsx`（約2,091行）を、タブ/パネル/フォーム/チャート単位のファイルに分割する。state・ローダー・ハンドラはコンテナに残し、ビューは props 経由で受け取るプレゼンテーショナル分割とする。 |

### 構造

- `SummaryDashboardPage.tsx` — コンテナ。全 state、APIローダー、編集/削除ハンドラ、エフェクト、ヘッダ/タブ切替、削除確認モーダル。
- `utils.ts` — `PALETTE`, `groupSummaryItemsByKind`, `formatPeriodKey`。
- `charts.tsx` — `SVGLineChart`, `SVGStackedBarChart`, `SVGCategoryHeatmap` を1ファイルに集約。
- `EditSummaryForm.tsx` — 既存の `EditForm` を移設。
- `HomeTab.tsx` / `BrowseTab.tsx` / `BrowseList.tsx` / `DetailPanel.tsx` / `StatsTab.tsx` — タブ・パネル単位のビュー。

### 結論に至った経緯

`projects`, `memories`, `research`, `vault-search` 各機能で確立済みの「コンテナ Page + ビュー別コンポーネント」パターン（props による受け渡し、カスタムフックなし）に合わせる。`selectedSummary` / `selectedDay` 等は Home→Browse 遷移（`goToBrowseForSummary`）やヘッダでクロスタブに共有されるため state はコンテナに残す。ロジックは一切変更せず純粋な移動・抽出のみとし、レース条件ガード（request ref 等）はコンテナに維持する。カスタムフックによる state カプセル化は変更範囲と回帰リスクが大きいため採用しない。

### 検証

- `npm --prefix frontend test`（Vitest 81件）全通過。`SummaryDashboardPage.test.tsx` は Page 経由のため分割後も回帰カバレッジを担保。
- `npx --prefix frontend tsc -b` で型チェック通過。
- 表示のみの変更のため E2E は追加しない（E2E 限定方針と整合）。

## 未生成サマリは完了期間のみを提示する

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-09 |
| カテゴリ | サマリダッシュボード・手動回復 |
| 決定内容 | 未生成候補は既存の入力・依存関係の条件を満たし、かつ対象期間の終了日がアプリ実行環境の当日より前の場合にのみ表示する。 |

日次は翌日から、ISO週次は日曜日の翌日から、月次は月末翌日から候補となる。これにより進行中の期間を未生成として促さず、完了後の手動回復だけを案内する。判定基準日は内部ヘルパーでのみ注入可能とし、通常のHTTP API、生成API、UI、スケジューラの契約は変更しない。

## サイドメニュー「確認待ち」の件数バッジ

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-12 |
| カテゴリ | フロントエンド・UI |
| 決定内容 | サイドメニューの「確認待ち」リンクに pending_user 件数のバッジを表示する。新規APIやグローバルステートは追加せず、Sidebar 内で `GET /api/v1/hitl/runs?status=pending_user&limit=1` を呼び出し `response.total` のみを表示する。 |

バックエンド変更なしで済むよう既存APIを再利用する。データフロー層（react-query等）を持たないため、フェッチは `Sidebar` 内の `useEffect` に自己完結させ、`useLocation().pathname` を依存にルート遷移のたびに再取得する。これによりHITLページで回答送信後に別ページへ遷移すればバッジが更新される。0件時は非表示。スタイルは `pending_user` の既存パレット（`rounded-full bg-yellow-100 px-2 py-0.5 text-[10px] font-medium text-yellow-800`）に準拠し、E2EではなくVitestで表示・非表示を検証する。

## トークンの localStorage 移行と設定画面

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-12 |
| カテゴリ | フロントエンド・認証 |
| 決定内容 | APIトークンの保存先を `sessionStorage` から `localStorage`（キー `obsidian-ai-hub:api-token`）に変更し、サイドバー下部に設定リンクを追加して設定画面（`/settings`）からトークンを保存・削除できるようにする。401 応答時は `auth:expired` イベントを発火し、App がトークン認証画面へ戻る。 |

トークンをセッションをまたいで保持し、リクエストごとに `Authorization: Bearer` へ付与するため、保存先を `localStorage` へ変更した。設定UIはサイドバー下部の「設定」リンクから開き、パスワード入力で現在のトークンを表示する。保存時は `listMemories({status:"candidate"})` で検証し、失敗時はトークンを削除してエラーを表示する。トークン削除と401発生時は `auth:expired` イベントを `window.dispatchEvent` で通知し、App が認証必須サーバのときだけ `TokenPrompt` へ戻す（認証不要サーバでは何もしない）。

- XSSによるトークン漏えいの余地が残るため、httpOnlyクッキーへの移行は引き続きTODOとする。
- 初回認証は従来どおり `TokenPrompt` が担い、設定画面は認証後のトークン管理に使う。
- E2Eは追加せず、Vitest（`client.test.ts`・`SettingsPage.test.tsx`・`App.test.tsx`）で検証する。

## Web API の Bearer 認証一元化（ループバック・tailnet 免除の廃止）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-15 |
| カテゴリ | Web API・認証・セキュリティ |
| 決定内容 | Web API をインターネット公開可能にするため、認証を強化する。ループバック免除と tailnet 特例を全廃し、全エンドポイントで常に `Authorization: Bearer <token>` を強制する。 |

### 結論に至った経緯

Web API をインターネット公開するにあたり、従来の「ループバックは無条件許可」「tailnet は `ALLOW_TAILNET_TASKS` + token で許可」という境界は、接続元 IP に依存した判定であり公開時には意味をなさない。TLS はリバースプロキシ／トンネルで担保し、アプリは localhost bind 固定のまま、認証はすべてのクライアント（loopback・LAN・公開）で等しく単一の Bearer トークンに一本化する。これにより 2026-08-12 の「タスク管理 Web UI (loopback または tailnet + トークン)」決定は破棄・置換される。

### 仕組みの概要

1. **認証ヘルパー:** `web/routes/deps.py` は `require_bearer_token` に一本化。旧 `require_loopback_or_token` / `require_localhost_or_tailnet_token` / `require_localhost` と tailnet・loopback 判定ヘルパーは削除。`hmac.compare_digest` でトークンを検証し、失敗時は `401` + `WWW-Authenticate: Bearer`。
2. **起動時の fail-closed:** `create_app(..., token="")`（トークン空）は host によらず `RuntimeError`。`--serve` も `OBSIDIAN_AI_HUB_API_TOKEN` 未設定なら起動失敗。`/health` は `auth_required: true` を固定で返す（未認証でも疎通確認可能）。
3. **全ルーター:** 9 ルーターの全エンドポイントに `Depends(require_bearer_token)`。
4. **tailnet 廃止:** `OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS` とそれに関わる分岐は全削除。
5. **フロントエンド:** `frontend/src/api/client.ts` が `localStorage`（キー `obsidian-ai-hub:api-token`）からトークンを読み `Authorization: Bearer` を付与。`auth_required` が true で保存済みトークンが有効な場合はトークンで自動認証し `TokenPrompt` をスキップする（401 の場合はトークンを削除して `TokenPrompt` へ戻す）。

### トレードオフ

- ループバックからの操作にもトークンが必須になるため、ローカル利用時の初期導線が増える。保存済みトークンの自動認証により、トークン設定後の再訪は `TokenPrompt` を経由しない。
- トークンは `localStorage` に保持され XSS による漏えい余地が残るため、httpOnly クッキーへの移行は引き続き TODO。
- テストでは実トークン（`tests/conftest.py` の `TEST_API_TOKEN`）を Bearer ヘッダーで渡し、E2E ではブラウザ `localStorage` にトークンを注入して認証済み状態を再現する。

## HITL モバイル一覧詳細のスクロール修正（列フレックス min-height 問題）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-16 |
| カテゴリ | フロントエンド・UI（モバイル対応） |
| 決定内容 | 一覧⇔詳細の2ペイン画面では、スクロールさせるパネル（詳細側）に `min-h-0` と `overflow-hidden`、外側コンテナに `overflow-hidden` を付与し、内側のスクロール領域を `min-h-0 flex-1 overflow-y-auto` で受ける構成を標準とする。 |

### 事件の経緯

HITL ページ（`frontend/src/features/hitl/HitlPage.tsx`）は従来 `lg:flex-row` の横並び2ペインで、モバイルでは一覧パネルが `h-full` を占めるため詳細パネルが高さ0になり「詳細が開かない」状態だった。Memory / Research ページと同じ `mobileDetailOpen` による一覧⇔詳細切替を導入したところ、次に「詳細画面へ遷移した後、下にスクロールできない」事象が発生した。

### 根本原因

モバイルでは外側コンテナが列フレックス（`flex-col`）になり、詳細パネルの高さがフレックス主軸となる。フレックスアイテムの既定 `min-height: auto` が内容の min-content 高さまで縮小を拒否するため、パネルはビューポート高さ（例 783px）ではなく内容全体の高さ（例 8771px）に成長する。`<main>` は `overflow-hidden` のためその先はクリップされ、どこにもスクロールバーが発生しない。デスクトップ（行フレックス）では高さが交差軸（stretch）になるためこの問題は起きない。

### 対処

1. 詳細パネルに `min-h-0 overflow-hidden` を付与し、内側の `min-h-0 flex-1 overflow-y-auto`（スクロール本体）が残り高さを占有してスクロールするようにする。
2. 外側コンテナに `overflow-hidden`、一覧パネルに `min-h-0` を付与（同種の回帰防止）。
3. モバイル専用の「← 一覧」戻るヘッダー（`lg:hidden`）を詳細パネル先頭に配置し、戻る操作で `run_id` を URL から除去して未選択状態へ戻す。

### 検証

- Playwright（モバイル 390×844 / デスクトップ 1280×800）で実ブラウザ確認。一覧（`<ul>`）・詳細（内側スクロール領域）とも `scrollHeight > clientHeight` のスクロールコンテナとして機能し、`scrollTop` の変更が反映される。戻るボタンはモバイルのみ表示され一覧へ復帰する。デスクトップ表示は不変。
- Frontend Vitest 103 passed、`tsc -b` クリーン。
- 以降の新規2ペイン画面は同構成を踏襲する。

## Web AI エージェント v1 の Web API / React UI 実装と動作契約

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-20 |
| カテゴリ | Web API・フロントエンド・AIエージェント |
| 決定内容 | エージェント管理・会話ストリーミング API (`/api/v1/agents`, `/api/v1/agent-tools`, `/api/v1/agent-sessions/*`) と `/agents` 画面を実装する。全 API は Bearer 認証を必須とし、応答は Fetch ReadableStream で SSE 解析し、HITL Run 作成時は承認待ち画面へのリンクを描画する。 |

### 詳細

1. **データモデル・永続化 (schema v21):**
   - SQLite スキーマ v21: `agents`, `agent_sessions`, `agent_messages`, `agent_runs` テーブルを作成。
   - 削除カスケード (`ON DELETE CASCADE`): セッション削除でメッセージ・実行記録を回収し、エージェント削除で配下セッションすべてを回収する。

2. **ツールレジストリと安全境界:**
   - 固定8ツール (`web_search`, `web_extract`, `vault_search`, `vault_read_file`, `calendar_read`, `reminders_read`, `calendar_create_proposal`, `reminder_create_proposal`) のみを公開。
   - カレンダー／リマインダーの新規作成提案は直接書き込まず、既存の HITL Run 登録ラッパーを介して `pending_user` 状態の HITL Run を登録する。

3. **SSE ストリーミングと UI 契約:**
   - `POST /api/v1/agent-sessions/{session_id}/messages/stream` エンドポイントが Bearer 認証付き Fetch ReadableStream を経由して `text` (逐次トークン), `done` (確定メッセージとHITL Run ID群), `error` イベントを送信する。
   - UI は `done` イベントで `hitl_run_ids` を受け取った場合、「承認待ちの登録申請が作成されました」のアラートと `/hitl` へのリンクを描画する。

## Web AI エージェントの逐次進捗表示（SSE thinking/tool_call_start/tool_call_end）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-23 |
| カテゴリ | Web API・フロントエンド・AIエージェント |
| 決定内容 | `/agents` 会話ストリーミングで「考え中」に代えて、LLM思考中・ツール呼び出し開始/終了を逐次 SSE イベントとして送出し、フロントエンドでライブ進捗パネル（思考インジケータ＋ツール呼び出し一覧＋結果）として描画する。LLMトークンの逐次ストリーミング（Phase 3）は見送る。 |

### 背景

v1 では `generate_agent_stream()` がツールループ中一切イベントを送らず、最後に `text` と `done` を一括送信していた。フロントエンドは長時間 `考え中…` のままとなり、ツール呼び出しも永続化後の再読込でしか表示されなかった。

### 仕様

1. **新規 SSE イベント型（既存 `text`/`done`/`error` に追加、破壊的変更なし）:**
   - `thinking` — 各 LLM invoke 直前に送出。`{"type":"thinking","iteration":int}`。最終フォールバック invoke 前も含む。
   - `tool_call_start` — ツール実行直前に送出。`{"type":"tool_call_start","call_id":str,"tool_name":str,"args":dict,"iteration":int}`
   - `tool_call_end` — ツール実行直後に送出。`{"type":"tool_call_end","call_id":str,"tool_name":str,"status":"succeeded"|"failed","result":str,"hitl_run_id":str|null,"error":str|null,"iteration":int}`。`result` はライブ表示用の軽量化として 2000 字で切り詰め（DB 永続化は 20000 字のまま、末尾に `…(truncated for live view)` を付与）。未知ツールの場合も `tool_call_end`（failed）を必ず送出する。
2. **バックエンド実装 (`src/obsidian_ai_hub/agents/runtime.py:194`):**
   - 定数 `_LIVE_RESULT_MAX_CHARS = 2000` を新設。`stored_result`（DB 用、20000 字）からさらに 2000 字へ二次切り詰めして `live_result` を生成。
   - `while iterations < max_iterations` 内の各 invoke 前とフォールバック invoke 前に `thinking` を yield。
   - `for call in tool_calls` 内で `tool_call_start` → invoke → `tool_call_end` の順に yield。
3. **フロントエンド契約 (`frontend/src/api/types.ts:658` / `frontend/src/features/agents/AgentsPage.tsx:65`):**
   - `AgentLiveToolCall`（`status: "running"|"succeeded"|"failed"`）と拡張 `AgentStreamEvent` 型を追加。
   - `streamingToolCalls` / `streamingPhase` / `streamingIteration` を state として保持。`thinking`/`tool_call_start`/`tool_call_end` をハンドルし、ストリーミング中は既存の永続化済みツール表示と同 UI（`<details>`）でライブ進捗パネルを描画する（`running` は amber バッジ＋スピナー、`succeeded`/`failed` は emerald/rose バッジ）。フェーズ表示は「LLMが考え中…」「ツール実行中…」のアニメーション付きインジケータ。
   - `done` でライブ state をクリアし `loadSessionDetail()` で確定データに切替。セッション/エージェント切替時もライブ state をクリア。
   - スクロール追従は `streamingToolCalls` / `streamingPhase` の変化でも発火する。
4. **トークンストリーミング（Phase 3）を今回見送る理由:**
   - `llm.invoke()` → `llm.stream()` 切替は `tool_call_chunks` の蓄積、`execution_logger` 対応、共有 `_logged_invoke` への影響など回帰範囲が広い。ツール進捗の可視化だけで UX の主要課題（「考え中」の真っ暗時間）は解消できるため、Phase 1+2 に絞る。

### 検証

- `uv run pytest tests/test_agents_runtime.py` の単純応答テストは `thinking`→`text`→`done` の順序と件数を検証、ツール呼び出しテストは `thinking`/`tool_call_start`/`tool_call_end` の順序と内容を検証。
- 既存の `done` 型フィルタで探すテスト（`tests/test_agents_integration.py` / `tests/test_memory_agent_tools.py`）は追加イベントに影響されないことを確認。
