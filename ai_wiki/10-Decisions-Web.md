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

## Web AI エージェントのトークンストリーミングと安全なツール集約

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-24 |
| カテゴリ | Web API・フロントエンド・AIエージェント |
| 決定内容 | エージェントの全 LLM ターンを LangChain `astream()` で処理し、到着順の本文差分を SSE で配信する。同時にツール呼び出しはチャンク完結後にのみ検証・実行し、UI はフレーム単位で本文を反映する。 |

### 背景

2026-08-23 の逐次進捗表示では、ツール進捗だけを先行して可視化し、本文トークンの逐次表示は保留していた。待機時間をさらに明確にするには本文も即時表示する必要がある一方、provider ごとの差異があるツール引数チャンクを途中で解釈すると、未完結または不正な呼び出しを実行する危険がある。

### 仕様

1. **本文・実行ログの整合性**
   - 各 LLM ターンは `_logged_astream()` を通し、空でない本文差分を `text` SSE として到着順に送る。
   - `AIMessageChunk` は `+` で集約して通常の `AIMessage` に変換する。LLM 実行ログはストリーム完了時に集約済み本文、usage、finish reason を記録し、例外時は failed とする。
   - assistant 本文は送信済み全差分の連結値を保存する。これによりライブ Markdown、`done.message.content`、SQLite の内容が一致し、ツール前の中間本文も失われない。

2. **ツールチャンクの安全境界**
   - `tool_call_chunks` は `iteration:index` の `call_key` で追跡し、名前を初めて得た時点で `tool_call_detected` SSE を送る。`tool_call_start` と `tool_call_end` の `call_key` は optional とし、既存クライアントとの互換性を保つ。
   - 生のチャンク引数は実行用に復元しない。集約後の `tool_calls` だけを実引数として採用し、生 JSON は完結した object であることの検証に限る。
   - すべての call を、object 引数・allowlist 名・一意 ID として検証してから、既存順序で実行する。ID 欠落時はサーバーが一意な ID を採番する。不正 JSON、未完結、未知ツール、重複 ID はツール実行・HITL 登録を行わず run を failed にする。

3. **SSE クライアントと描画**
   - Fetch `ReadableStream` は行単位ではなく SSE イベント単位で解析する。`TextDecoder` のストリーム復号と CRLF 対応により、任意の byte 境界や UTF-8 分割でも JSON を壊さない。
   - `/agents` は本文差分を `requestAnimationFrame` ごとにまとめて Markdown へ反映する。完了・失敗・abort・エージェント/セッション切替時には保留フレームを無効化し、古いストリームが再表示されないようにする。
   - ライブツール表示は「準備中 → 実行中 → 成功/失敗」。準備中は部分引数を表示せず、`tool_call_start` 後の確定した構造化引数だけを詳細表示する。

4. **provider の扱い**
   - 既存の provider を同じ API パスで扱う。async token stream またはツール呼び出しを提供できないモデルは、provider 側の明確な実行失敗として run を failed にする。取消・再接続・バックグラウンド継続の扱いは変更しない。

### 検証

- Python の runtime/API テストで本文差分の順序・DB/`done` 整合、実行ログの usage/失敗、分割・交互ツールチャンク、ID 採番、不正 JSON の非実行を確認する。
- Vitest で CRLF/UTF-8 分割の SSE 解析、rAF 集約、準備中から完了までのツール表示、完了後の stale frame 抑止を確認する。

## ヘルスケア可視化ダッシュボード v1（小倍数・オンザフライ集計）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-24 |
| カテゴリ | ヘルスケア・Web API・フロントエンド |
| 決定内容 | `/healthcare` に Quantity 型の9指標（歩数・心拍数・安静時心拍・HRV・アクティブ/基礎エネルギー・距離・上階数・エクササイズ時間）の日次推移を small-multiples（1指標1カード＋ラインチャート）で概観できるダッシュボードを追加。集計は分離DB `healthcare.sqlite3` へのオンザフライ SQL、チャートはヘルスケア専用の手書き SVG。 |

### 背景

`docs/healthcare-import/plan.md` で `health_daily_metrics` VIEW は将来拡張扱いだった。v1 ではまず「一定期間ごとの各数値推移をグラフで概観」したいという要求を満たすため、スキーマ変更なしで `health_records` を直接 GROUP BY する方式を採用する。

### 仕様

1. **データソースと集計方式（オンザフライ）**
   - `healthcare/queries.py::get_daily_aggregates` が `health_records` を `substr(start_date,1,10)` で日次 GROUP BY し `AVG/MIN/MAX/SUM/COUNT` を返す。`idx_hr_type_start(type,start_date)` に対し `type = ? AND start_date >= ? AND start_date < ?` の範囲スキャンで活用する。
   - `web/services/healthcare.py::get_healthcare_overview` は curated 9指標をループして日次集計を取得し、Python 側で granularity（≤60d→day / ≤366d→week / それ以上→month）へロールアップする。week は ISO 週（`Wxx`）、month は `YYYY/MM`。バケットは連続生成しデータ無しは `value:null` で欠損を明示。`latest_value` は最新非null バケット、`delta_pct` は直前非null との比率。
   - `health_daily_metrics` VIEW / refresh job は性能要件が出るまで導入しない。API 契約（`{start_date,end_date,granularity,metrics[].buckets[]}`）は VIEW 導入後も互換を保てる。

2. **API**
   - `GET /api/v1/healthcare/overview?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`。`require_bearer_token` 必須、`ValueError→400`、`401` は deps 一元。日付は `YYYY-MM-DD` 正規表現と `datetime.strptime` で厳密検証、`duration>3660→400`。`web/schemas.py` に `HealthcareOverviewResponse / HealthcareMetricSeries / HealthcareBucket` を追加。

3. **Curated 指標（Phase 1 は Quantity のみ）**
   - `steps (sum, count)` / `heart_rate (avg, count/min)` / `resting_heart_rate (avg)` / `hrv (avg, ms)` / `active_energy (sum, kcal)` / `basal_energy (sum, kcal)` / `distance (sum, km)` / `flights (sum, count)` / `exercise_time (sum, min)`。Category 型（`SleepAnalysis` / `AppleStandHour`）は期間計算が必要なため Phase 2 に繰越。

4. **フロントエンド**
   - `frontend/src/features/healthcare/` — `HealthcarePage.tsx`（コンテナ。preset 7/30/90/年/期間指定、`requestRef` 競合ガード）、`MetricCard.tsx`（最新値・前回比・件数表示。`formatMetricValue` で指標別桁数）、`charts.tsx`（`HealthcareTrendChart`。手書き SVG、Yドメインは `min/max` から pad→0クランプ、null での polyline 分割、Xラベル間引き、sr-only table で a11y）。`summary-dashboard/charts.tsx` は流用せず専用実装とし回帰を回避。
   - ルーティング: `constants/routes.ts::HEALTHCARE`、`App.tsx` に `<Route>`、`Sidebar.tsx` に `ヘルスケア` NavLink（`summary-dashboard` の直後）。
   - APIクライアント: `api/client.ts::getHealthcareOverview`、`api/types.ts` に `HealthcareOverviewResponse` 等。
   - 空データ時は `uv run python -m obsidian_ai_hub.import_apple_health --export-dir <dir>` への誘導をカードグリッド下に表示。

5. **レイアウト**
   - ページ全体 `bg-slate-50`、ヘッダ `bg-white border-b`、フィルタバー `rounded-xl border bg-white shadow-sm`（`StatsTab.tsx:41` と同スタイル）。カードは `grid-cols-1 md:grid-cols-2 xl:grid-cols-3` の small-multiples。モバイルは1列、xlで3列。

### トレードオフ

- 110万 Record でも `(type,start_date)` インデックスで単一 type の範囲スキャンは効率的。30日×1指標=数千行の GROUP BY は sub-second、1年でも week に緩和される。事前集計 VIEW を持たないため書き込み不要だが、範囲が極めて広い場合や多指標同時取得は N (=9) 回の SELECT が発生。将来ボトルネックになれば `IN (types)` の単一クエリ化 or `health_daily_metrics` VIEW へ切替可能。
- 別実装のチャートは軽微な重複を許容するかわりに `summary-dashboard` への回帰リスクを排除。DRY より feature 隔離を優先（`AGENTS.md` の薄いラッパー方針と整合）。
- Category 型を v1 で除外したため睡眠・スタンド時間は表示されない。Phase 2 で `start_date/end_date` の期間差分集計を追加予定。

### 検証

- `uv run pytest tests/healthcare/test_queries.py tests/test_healthcare_web.py`（日次集計・week/month ロールアップ・平均/合計分岐・空DB・認証/バリデーション）。
- `npm --prefix frontend test -- src/features/healthcare/HealthcarePage.test.tsx`（描画・loading/error・preset遷移・空状態・最新値/delta・custom期間適用）。
- `npm --prefix frontend test` 138 passed、`uv run pytest tests/ 800 passed`、 `npx --prefix frontend tsc --project frontend/tsconfig.json --noEmit` クリーン。

## ヘルスケアダッシュボード v2（睡眠・スタンド Category 対応）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-24 |
| カテゴリ | ヘルスケア・Web API・フロントエンド |
| 決定内容 | Category 型の睡眠・スタンドをダッシュボードに追加。睡眠は `HKCategoryTypeIdentifierSleepAnalysis` の Asleep 系 `value_text` の `start/end` 期間を時間換算して日次合計、スタンドは `HKCategoryTypeIdentifierAppleStandHour` の `Stood` 件数を時間換算して日次合計する。 |

### 背景

v1 は Quantity 型（`value_numeric`）のみで、もっとも要望の高い睡眠時間とスタンド時間が未対応だった。Category 型は `value_numeric IS NULL` で `value_text/start/end` からの導出が必要なため別途実装が必要。

### 仕様

1. **バックエンド `healthcare/queries.py`**
   - `_parse_health_datetime(s)` — `"%Y-%m-%d %H:%M:%S %z"` を主とし `fromisoformat`（Python 3.11+ は `+0900` も許容）への単一フォールバックで `2026-08-20 23:00:00 +0900` / `T` 区切りを吸収。失敗は `None` で行スキップ（OCR で冗長な `:` 挿入分岐を削除）。
   - `get_daily_category_durations(conn, type_, start_date, end_date, allowed_values)` — `type = ? AND start_date >= ? AND start_date < ?` で取得後、カーソルを遅延イテレーション（`for row in cur:`）し Python で `(end-start).total_seconds()/3600` を `substr(start_date,1,10)` の開始日バケットへ加算。片方のみ tz-aware な場合は同一 offset を付与して `TypeError` を回避（`except TypeError` に限定）。`allowed_values` で `InBed/Awake` を除外し Asleep 系のみを合計。`0 < delta <=48h` のみ採用。
   - `get_daily_stand_counts(conn, start_date, end_date)` — `value_text='HKCategoryValueAppleStandHourStood'` を `COUNT(*) GROUP BY substr(start_date,1,10)` で集計。1レコード=1時間として扱う。
   - いずれも sparse（データ無し日は欠落）で返す。

2. **バックエンド `web/services/healthcare.py`**
   - `CURATED_METRICS` に `sleep (h, sum, category=sleep_duration)` と `stand_hours (h, sum, category=stand_count)` を追加し計11指標。`_SLEEP_ALLOWED_VALUES` は詳細 stage のみ `AsleepCore/Deep/REM/Unspec` の4値とし、umbrella の `Asleep` は詳細と重複期間で二重計上するリスクがあるため除外（OCR 指摘反映）。
   - Quantity 9指標は従来どおり `get_daily_aggregates_multi` で1クエリ集約。Category 2指標は `category` フラグで分岐し `get_daily_category_durations` / `get_daily_stand_counts` を呼び、日次 dict を `{day: {"sum": hrs, "count":1,…}}` に変換して既存のバケットロールアップ（`_bucket_key_for_date`）へ流用（`stand_hours` は `count=1` per day に統一し `sleep` と一貫）。週・月では日次合計の合算となり、週バケットは `52.5h`（7日×7.5h）のように正しく集計される。

3. **フロントエンド**
   - `MetricCard.tsx` の `PALETTE` に `sleep: #0ea5e9 / stand_hours: #84cc16` を追加。`formatMetricValue` で `sleep/stand_hours` は `toFixed(1)`、単位 `h`。
   - `HealthcarePage.tsx` の説明文を「Quantity 型と Category 型（睡眠・スタンド）」に更新。
   - チャートは既存 `HealthcareTrendChart` を流用。睡眠は 0–9h、スタンドは 0–12h の Y ドメインで描画される。

### トレードオフ

- 睡眠の帰属は `start_date` の日付（夜の開始日）に固定。23:00–07:00 の睡眠は開始日へ 8h として計上し、日跨ぎの案分は行わない。日次で概観する用途では十分で、案分の複雑さを回避。
- `get_daily_category_durations` は SQL 集計ではなく Python で期間計算するため、1年で睡眠~2k行・スタンド~3k行程度だがいずれも軽量。将来行数が増えてもインデックス `idx_hr_type_start` の範囲スキャンで賄える。
- 新たに2クエリ（睡眠・スタンド）がリクエスト毎に追加されるが、Category は件数が少なく N+1 の影響は軽微。将来的に `health_daily_metrics` VIEW へ移行する際は API 契約を維持したまま置換可能。

### 検証

- `uv run pytest tests/healthcare/test_queries.py::test_category_sleep_and_stand` — InBed を除外して AsleepCore 7h50m=7.83h が 2026-08-20 に集計されること、stand 1h、週次 52.5h の合算を確認。
- `tests/test_healthcare_web.py` の `len(metrics)==11` と `sleep/stand_hours` キー存在、`HealthcarePage` の表示は既存 Vitest で回帰確認。
- `uv run pytest tests/ 800 passed` 維持、`npx --prefix frontend tsc --noEmit` クリーン。

## ヘルスケアダッシュボード v3（相関散布図・専用エンドポイント）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-24 |
| カテゴリ | ヘルスケア・Web API・フロントエンド |
| 決定内容 | `/healthcare` に「推移 / 相関」タブを追加。相関タブで2指標の日次ペアを散布図（X/Y 異単位対応）+ Pearson 相関係数 + 回帰直線で可視化する。相関は専用エンドポイント `GET /healthcare/correlation` で強制日次で取得しサーバー側で統計計算する。 |

### 背景

v2 までの推移グリッドでは各指標の時系列は見えるが指標間の関係は読み取れない。「歩数が多い日は睡眠が短いか」等の仮説検証のため、2指標の日次値をペアにした散布図が欲しい。既存 overview の粒度（>60日で週別）は散布のポイント数を減らすため相関用には日次を強制したい。

### 仕様

1. **バックエンド `web/schemas.py`**
   - `HealthcareCorrelationPoint {date, x, y}` / `HealthcareCorrelationResponse {metric_x, metric_y, x_label/y_label, x_unit/y_unit, x_type/y_type, start_date, end_date, granularity="day", n, pearson_r, regression_slope, regression_intercept, points[]}` を追加。`pearson_r/slope/intercept` は `n<2` や分散0で `null`。

2. **バックエンド `web/services/healthcare.py`**
   - `_daily_values_for_metric(conn, mdef, start, end)` — curated metric の日次スカラーを返すヘルパ。Quantity は `get_daily_aggregates` の `sum`（aggregation sum）/`avg`（aggregation avg）、Category は `get_daily_category_durations`（睡眠は Asleep 4値の時間合計）/`get_daily_stand_counts`（スタンドは Stood 件数）をそのまま日次値とする。
   - `get_healthcare_correlation(metric_x_key, metric_y_key, start, end)` — `CURATED_METRICS` から key→def を解決（未知は `ValueError→400`）、`_validate_date_str` と `duration>3660` を共有、日次 dict を両指標で取得し `set(x) & set(y)` の共通日でソートして `points` 化。`n>=2` のみ Pearson `r = Σ((xi-x̄)(yi-ȳ))/sqrt(Σ(xi-x̄)²Σ(yi-ȳ)²)` と回帰 `slope = Σ((xi-x̄)(yi-ȳ))/Σ(xi-x̄)², intercept = ȳ - slope·x̄` を計算。分母0は `null` にフォールバックし `r` は `[-1,1]` にクランプ。

3. **バックエンド `web/routes/healthcare.py`**
   - `GET /healthcare/correlation?metric_x=&metric_y=&start_date=&end_date=` 追加。Bearer 認証、`ValueError→400`。既存 overview は変更なし。

4. **フロントエンド**
   - `api/types.ts` / `api/client.ts` に `HealthcareCorrelationResponse` と `getHealthcareCorrelation` を追加。
   - `features/healthcare/HealthcareScatterChart.tsx`（新規） — 手書き SVG。X/Y 各スケールに `xPad/yPad`（range 12%）と0クランプ、グリッド3本、点 `<circle>`、回帰直線 `<line strokeDasharray="6 4">`、軸タイトル、sr-only `<table>`。ヘッダに `r` と強弱ラベル（|r|>=0.7 強/0.4 中/0.2 弱）、`n`、回帰式を表示。空は「両方が揃った日がありません」。
   - `HealthcarePage.tsx` に `activeTab: "trend"|"correlation"` と `corrMetricX/corrMetricY/corrData/corrLoading/corrError` を追加。タブヘッダ、相関タブに X/Y `<select>`（`data.metrics` から生成、初期値 X=steps/Y=sleep）、散布図セクションを追加。期間 preset/カスタムは `load` と `loadCorrelation` の両方を発火。`requestRef/corrRequestRef` で競合ガード。

### トレードオフ

- 専用エンドポイントは overview と分離され相関計算をサーバーに集約できる。前端末は描画のみでよく、長期間でも常に日次ポイントを最大化（365日×1点/日）。代わりに `n=0/1` では統計量が `null` になることを UI で明示する必要がある。
- 既存 overview を流用する案はバックエンド不要だが、90日以上で週別になりポイントが激減し相関の診断力が落ちる。`force_daily` param 案は11指標全取得の無駄が大きい。専用エンドポイントが最もクリーン。
- UI は2指標選択の単一散布に絞り、全ペア行列は Phase 3b に回す。11×11 行列は一覧性は高いが実装量が増え、まず単一散布で相関の読み解き方を確立する。

### 検証

- `uv run pytest tests/test_healthcare_web.py::test_healthcare_correlation_success` — steps 3000+500*i と sleep 6+0.5*i の5日間で `n=5, r≈1.0, slope≈0.001` を検証。空・単一点・未知 metric の 400 も検証。
- `npm --prefix frontend test -- src/features/healthcare/HealthcareScatterChart.test.tsx` — 点描画・回帰線・Pearson 表示・空状態・負の相関。
- `HealthcarePage.test.tsx` に相関タブ切替と `getHealthcareCorrelation` 呼び出しを検証。
- `uv run pytest tests/ 807 passed`、`npm --prefix frontend test` 143 passed、`tsc --noEmit` クリーン。

## エージェント会話への画像添付（マルチモーダル LLM 渡し）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-25 |
| カテゴリ | AI エージェント・Web UI |
| 決定内容 | AgentsPage のチャット入力からローカル画像ファイルを添付し、LLM にマルチモーダル入力として渡す。画像はメッセージ履歴に永続化し、後続ターンでも LLM に再提示する。 |

### 結論に至った経緯

`llm_client.py` の `_prepare_messages` は既にマルチモーダル対応だったが、agent runtime（`runtime.py`）は system + 履歴 + 現在テキストで `HumanMessage(content=text)` を組み立てる経路のため、エージェントチャットに限っては LLM に画像を渡せていなかった。ChatGPT のように、ユーザーが手元の画像について会話したいユースケースが実用上あるため、軽量に実装する。

### 設計

- **送信方式**: 既存の `POST /agent-sessions/{id}/messages/stream` を JSON のまま拡張し、ボディを `{content, images: [{name, mime_type, data(base64)}]}` とする。`images` 省略時は従来動作で完全な後方互換。
- **永続化先**: `agent_messages.attachments_json TEXT NOT NULL DEFAULT '[]'`（migration v24）に `{name, mime_type, data}` の JSON 配列を保存する。ディスクストアは複雑性が高く不要。SQLite の TEXT 列に base64 そのまま保存する既存パターン（`used_tools_json` / `tool_calls_json` / `advanced_params_json`）に揃える。
- **runtime のマルチモーダル化**: `_build_user_message(provider, text, attachments)` を新設。`provider != "local"` なら `[text, ...image_url data:URL ブロック]` のリストを返し、`local`（llama-cpp）は画像非対応なのでテキストにフォールバックして warning をログする（既存 `llm_client` 挙動と一貫）。履歴の user メッセージも同じヘルパで再構築するため、後続ターンでも画像が LLM に届く。
- **上限**: 1 メッセージ 5 枚 / 1 枚 8MB（base64 含む）。`mime_type` は `image/*` のみ許可。バリデーション違反は 400。
- **UI**: AgentsPage に「画像」ボタン + 非表示 `<input accept="image/*" multiple>`。FileReader で dataURL 化し、`{name, mime_type, data, size, previewUrl}` を `PendingAttachment[]` に保持。送信前プレビュー行にサムネイル＋個別 ✕ ボタン。送信後クリア、楽観 user bubble と履歴 user bubble 両方にサムネイルを表示。
- **Phase 2 以降**: ドラッグ&ドロップ対応（入力フォームへの DnD、クリップボード貼付け対応）を別途計画。

### トレードオフ

- 永続化により、長大化したセッションで SQLite のサイズが大きくなり得る。1 枚 8MB 上限で現実的な線引きをする。
- 各ターンで履歴の user メッセージ（attachments 込み）を再送するため、画像は LLM トークン消費にも影響する。ChatGPT 同様、画像付き会話の自然な挙動として受け入れる。
- base64 の JSON ペイロードは multipart より約 33% 増。個人用途では十分小さく、エンドポイント契約の変更なしで済む点を優先して JSON を採用。
- 画像の実体検証（ピクセル数や正確な MIME）は緩め（`image/*` プレフィックスチェック + サイズ上限のみ）。悪意ある payload は業務用途ではないため深掘りしない。

### 検証

- backend: `uv run pytest tests/` 837 passed。新規 — `test_agents_api.py` の画像付与・MIME 不正・枚数上限・base64 不正の 4 ケース、`test_agents_store.py` の `attachments_json` 列追加と round trip、`test_agents_runtime.py` の現在ターン＋履歴の両方が LLM に `image_url` ブロックとして届くことと、`local` プロバイダで画像が無視されること（警告ログ）。
- frontend: `npm --prefix frontend test` 150 passed（既存 148 + 新規 2 — `client.test.ts` の `images` フィールドJSON化、`AgentsPage.test.tsx` の添付フロー + 非画像ファイルの拒否）、`tsc -b && vite build` クリーン。
- 手動確認: AgentsPage で画像添付→サムネイル→送信→履歴再表示で再表示されること、後続ターンで画像が文脈として LLM に届くこと。
- **画像のみ送信（テキスト空）も許可**: `start_user_run` / route の空コンテンツ禁止を撤廃し、image が 1 枚以上あれば text 空でも送れる。送信後のセッションタイトル自動付与では `画像を送りました` をフォールバックに使用。フロントの送信ボタンは「添付あり OR テキストあり」で活性化。
- **読み込み中ガード**: フロントで `attachmentReadsPending` カウンタを持ち、FileReader の read 中は「画像」ボタンに「読込中…」を出して非活性化、送信ボタンも非活性化して read 完了前の送信によるロスを防ぐ。
- **MIME 不正 attachment の安全な無視**: `_build_user_message` が空 `mime_type`/空 `data` のブロックを `application/octet-stream` フォールバックで送ってしまっていた。LLM 非互換なブロックを送らないために該当 attachment を skip + warning ログに変更。
- 最終: `uv run pytest tests/` 841 passed、`npm --prefix frontend test` 151 passed、`tsc --noEmit` クリーン。

### Phase 2: ドラッグ&ドロップ + クリップボード貼付け

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-25 |
| カテゴリ | AI エージェント・Web UI |
| 決定内容 | AgentsPage のチャット入力に DnD / ペースト経由の画像添付を追加。バックエンド・DB 変更ゼロで Phase 1 の `handleFilesSelected` パイプラインを再利用する。 |

### 結論に至った経緯

スクリーンショットやエクスプローラからのドロップでも同じ UX を提供したい。両経路とも最終的に `File` の配列になり既存の `handleFilesSelected` がそのまま使えるため、同一フェーズで実装する。共有部分は多い（上限検証、`attachmentReadsPending`、プレビュー、送信）。分割すると同じ箇所を2回触ることになり、ドリフトのリスクが高い。

### 設計

- **DnD**: 入力 `<form>` に `onDragEnter/onDragOver/onDragLeave/onDrop` を付与。`e.dataTransfer.types.includes("Files")` をガードとして、誤ドラッグ（テキストや URL の選択ドラッグ等）で反応しないようにする。`dropEffect = "copy"` を設定。`isDragOver` state で「ここに画像をドロップ」オーバーレイ（form 内の絶対配置、z-index で既存プレビューより上、`pointer-events: none`）を表示。`dragleave` のフリッカは `relatedTarget` が `currentTarget` 内のとき無視して抑制。
- **Paste**: `<textarea>` の `onPaste` で `clipboardData.items` を走査し、`kind === "file"` かつ `type.startsWith("image/")` の item を `getAsFile()` で `File[]` に変換して `handleFilesSelected` に渡す。画像 item が 1 つでもあれば `e.preventDefault()`（テキストのみの場合は何もしず、ブラウザ既定の動作を保持）。
- **共通化**: `handleFilesSelected` のシグネチャを `FileList | File[] | null` に拡張（中身は `Array.from(files)` で共通化）。`PendingAttachment.name` を `file.name || "image.png"` にフォールバック（ペースト画像は name が空になり得る）。
- **ガード**: `isStreaming` / `selectedSessionId` 未選択 / `activeAgent` 未選択時は DnD と paste を無視。
- **テスト**: `fireEvent.drop` と `fireEvent.paste` を `dataTransfer` / `clipboardData` を直接注入して実行（`userEvent.upload` の `accept` フィルタ問題を回避）。

### トレードオフ

- `dataTransfer.types` ガードがあるため外部アプリからのテキストドラッグ（例: URL）などを誤って処理しない。選択テキストの drag-drop は no-op になる。
- `dragleave` の `relatedTarget` 判定は単純実装。子要素が多数ある複雑なレイアウトでフリッカが出る場合は `dragenter`/`dragleave` カウンタ方式に切替（Phase 3 以降）。
- Safari の paste は一部 `getAsFile()` が画像を返さないケースがあり、その場合は添付されない（テキストに影響なし）。`navigator.clipboard.read()`（要権限）対応は Phase 3 候補。
- 画像のリサイズ/圧縮は未実装（8MB 上限の超過はエラー）。`canvas` で縮小してから base64 化する Phase 3 を検討。

### 検証

- `npm --prefix frontend test` 155 passed（Phase 1 末 151 から +4 件: DnD 画像添付成功、非画像 drop 拒否、画像 paste 添付成功、テキストのみ paste の no-op）。
- `tsc --noEmit` クリーン、`vite build` クリーン。
- バックエンド変更なしのため `pytest` は今回未実行。
- 手動確認: 入力フォームへの画像 drop、スクリーンショットを Ctrl+V で paste、テキスト paste が従来どおり動作、ストリーミング中は両方無効。

## エージェント会話履歴の横断メッセージ検索

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-26 |
| カテゴリ | Web API・AI エージェント・Web UI |
| 決定内容 | 会話履歴はエージェント単位ではなく全エージェントを横断して、保存済みメッセージ本文をメッセージ単位で検索する。 |

### 設計

- `GET /api/v1/agent-sessions/search?q=...` は Bearer 認証を必須とし、ヒットごとにエージェント名、会話情報、メッセージ ID、role、snippet を返す。`/agent-sessions/{session_id}` より先に静的ルートを登録する。
- SQLite の `agent_messages.content` に対するリテラル LIKE 検索を用いる。`%`、`_`、バックスラッシュは利用者の入力どおりに扱い、空白のみは 400、結果は最大100件とする。現時点では FTS5・スキーマ変更を導入しない。
- `/agents` は 200ms debounce で検索し、検索結果を通常の会話一覧の代わりに表示する。結果の選択では対象のエージェント／セッションを開き、レンダリング済みメッセージ要素へスクロールする。

### トレードオフ

- 先頭ワイルドカードを含む LIKE は大規模データでは最適化できないが、現状の個人利用規模ではスキーマと運用を増やさない利点を優先する。検索体感が悪化する、またはメッセージ数が十分に増えた時点で FTS5 を別途導入する。

## Web AI エージェントの `/` コマンドパレット（プロンプトテンプレート呼び出し）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-26 |
| カテゴリ | AI エージェント・Web UI |
| 決定内容 | AgentsPage のチャット入力欄で先頭が `/` の時、既存の `PromptTemplate[]` を呼び出すインクリメンタルなコマンドパレットを表示する。既存の `+ → テンプレート` ボタンとスラッシュ入力が共存する。 |

### 結論に至った経緯

テンプレートの呼び出しにおいて、マウスでの `+ → テンプレート` ボタン操作に加えて、キーボード操作で完結するスラッシュ（`/`）コマンド入力の方が直感的かつ高速である。既存のボタン導線も発見性（Discoverability）のために維持し、両方の呼び出し方法を共存させる。

### 設計と動作契約

1. **コマンド構文と絞り込み規則:**
   - 入力の先頭が `/` の時に textarea 直上にパレットを表示。
   - `/` 単体で全テンプレート（最大 8 件）を表示。
   - 短縮形 (`/テンプレート名`) と明示形 (`/template テンプレート名`) の両方をサポート。
   - 末尾スペース無しの `/template` は名前に 'template' を含む/で始まる短縮形フィルターとして処理。
   - ケースインセンシティブにマッチングし、`startsWith` 該当候補を第 1 ランク、`includes` 該当候補を第 2 ランクとして順序付け。同ランク内では API から読み込まれた既存の `display_order`（配列順序）を維持。
   - 該当候補が 0 件の場合は「該当するテンプレートがありません」の空状態を表示。

2. **キーボード・ポインター操作:**
   - `ArrowUp` / `ArrowDown`: ハイライト表示中の候補位置をラップアラウンド移動。
   - `Enter`（単体）: ハイライト表示中のテンプレートを選択し、入力テキスト全体をテンプレート本文で置換。メッセージの送信は行わず、フォーカスを `<textarea>` に維持する。
   - `Escape`: 候補を選択せずにパレットを閉じる。
   - `Ctrl+Enter` / `Cmd+Enter`: パレット開閉状態にかかわらず現在の入力テキストを即時送信（テンプレート選択より送信を優先）。
   - マウスクリック: 対象候補を選択して入力テキスト全体を置換し、フォーカスを `<textarea>` に維持。

3. **入力状態と復帰:**
   - 入力が `/` で始まらなくなった時点でパレットは自動的に閉じる。
   - テンプレートを選択すると入力がテンプレート本文に置き換わり、パレットは閉じる。

### 検証

- Frontend Vitest（`AgentsPage.test.tsx`）で単体・結合テストを実施。`/` 単体での全件表示、短縮形/明示形/スペース無しの絞り込み、空状態、キーボードラップアラウンド、Enter非送信、Escapeでの閉鎖、Ctrl+Enter即時送信、および `+ → テンプレート` 既存導線の互換性を検証。
- TypeScript チェック (`tsc -b`) および Vite ビルド (`vite build`) がクリーンに通過。
