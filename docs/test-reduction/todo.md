# テスト層再編 ToDo

Vitest を React の標準テスト層に格上げし、Playwright E2E を主要フロー 3 本へ縮小するための
作業項目。各タスクは「依存 → 作業内容 → 受け入れ条件」を簡潔に示す。

## Phase 0: 前提確認 — 完了 (2026-07-24)

- [x] `frontend/package.json` の Vite / Vitest / jsdom の組合せと `package-lock.json` の
      ネスト状況を再点検し、Vite 5 系維持のまま Vitest を動かすか、Vite を 6+ に揃えて
      Vitest 4 を正式採用するかを決定する。決定は本ドキュメント冒頭にリンクする ADR
      (`ai_wiki/10-Decisions.md` への追記) として残す。
      → Vite 6+ 揃えを採用。`frontend/package.json` の `vite` を `^6.0.0` に更新し、
      `overrides.vite: "^6.0.0"` を追加。lockfile 上の二重 Vite 状態 (root 5.4.21 +
      `node_modules/vitest/node_modules/vite@8.1.5`) を解消。ADR:
      [`ai_wiki/10-Decisions.md`](../../ai_wiki/10-Decisions.md#フロントエンドのツールチェーンポリシー-vite-6--vitest-4)。
- [x] CI 現状 (.github/workflows/pytest.yml) で Vitest・E2E が走っていないことを再確認し、
      着手前にステークホルダへ共有する。
      → `pytest.yml` のみが登録され、Node セットアップ・`npm ci`・`npm run build` なし。
      `tests/e2e/conftest.py:47-52` が `frontend/dist/index.html` 不在で skip するため、
      PR CI で Vitest・E2E は未検証。Phase 1 で `frontend-unit` ジョブを新設する。

## Phase 1: CI に Vitest とビルドを組込む — 完了 (2026-07-24)

- [x] `.github/workflows/frontend-unit.yml` を新設し、Node 24 (LTS、`jsdom@29` /
      `vitest@4` の engines 要件 `^20.19.0 || ^22.13.0 || >=24.0.0` を満たす) の
      セットアップ、`npm --prefix frontend ci`、`npm --prefix frontend test`、
      `npm --prefix frontend run build` を順次実行する。
      `cache: 'npm'` と `cache-dependency-path: frontend/package-lock.json` で
      `node_modules` インストール結果をキャッシュし、2 回目以降の PR での `npm ci` を高速化。
- [x] 既存 `pytest.yml` と並列で起動する (両 workflow とも `pull_request` トリガ)。
      YAML 妥当性を `yaml.safe_load` で確認済み。CI と同等コマンド列をローカル実行し、
      24/24 Vitest green + `vite build` 成功を確認。
- [x] E2E はまだ変更しない。`tests/e2e/conftest.py` のスキップ挙動も据え置き。

## Phase 2: Vitest の API クライアント契約テスト — 完了 (2026-07-24)

- [x] `frontend/src/api/client.test.ts` を新規作成 (26 テスト)。`globalThis.fetch` を
      `vi.stubGlobal` で差し替え、`api/client.ts` の `request` 関数の入出力を直接検証する。
      カバー範囲:
      - **token 管理**: `getToken` / `setToken("")` / `clearToken` の `localStorage` 連携。
        （2026-08-12 に `sessionStorage` → `localStorage` へ移行、キーは
        `obsidian-ai-hub:api-token`。401 時に `auth:expired` イベントを発火し App が
        TokenPrompt へ戻る。）
      - **リクエスト構築**: `listMemories` のクエリ文字列 (URL エンコード、空パラメータ省略、
        `+` エンコード)、`reviewMemory` の POST + JSON (action/new_content、省略時挙動)、
        特殊文字を含む `memoryId` の `encodeURIComponent` 動作、`submitHitlAnswer` の
        question-specific パス、`cancelHitlRun` / `renderCopilotProfile` の body なし POST、
        `deleteMemory` の DELETE、`updateSummary` の PATCH、`getMemory` の GET、`health` が
        `/health` を叩くこと。
      - **Authorization**: トークン未設定時は付与なし、設定時は `Bearer <token>`、呼び出し
        ごとに最新トークンが反映されること。
      - **エラー**: 401 で `clearToken` + `ApiError(401, "Authentication failed...")`、
        `detail` 文字列抽出、`detail.message` オブジェクト抽出、非 JSON body は statusText
        フォールバック、`detail` 欠落時も statusText フォールバック。
      - **204 No Content**: `deleteMemory` が `undefined` を返すこと。
      - 全 50 テスト (既存 24 + 新規 26) green、`tsc -b && vite build` 成功。

## Phase 3: `App` の Vitest 化 — 完了 (2026-07-24)

- [x] `frontend/src/App.test.tsx` を新規作成し、以下を検証する:
      - `health()` 成功時に `authed=true` で `/memories` がレンダリングされる。
      - `health()` が 401 のとき `TokenPrompt` が表示される (`needsToken=true`)。
      - `health()` が 401 以外で失敗したとき接続エラー画面と「再読み込み」ボタンが描画される。
      - `MemoryRouter` で `/` が `ROUTES.MEMORIES` にリダイレクトされる。
      - モバイルナビ: `aria-label="メニューを開く"` ボタンで開閉し、Esc で閉じる。
      - `Sidebar` の各リンクがそれぞれのルートに遷移する (`/memories`, `/research`, `/hitl`,
        `/vault-search`, `/summary-dashboard`, `/people`, `/projects`, `/tasks`,
        `/execution-logs`)。
      → 8 テスト green。`api/client` と各 feature ページを `vi.mock` でスタブし、
      ルーティング・health 状態遷移・ナビ動作のみを App 層で検証。

## Phase 4: Memory 画面の Vitest 化 — 完了 (2026-07-24)

- [x] `MemoryPage.test.tsx` を新規作成し、以下を検証する:
      - 初回ロードで `listMemories` と `getMemoryOptions` が呼ばれ、ステータス / 種別 /
        トピック / 検索のフィルタ UI が描画される。
      - 検索入力の 500ms デバウンス後に `listMemories` が発火し、進行中の入力では発火しない。
      - ステータス変更で行選択と詳細がリセットされる。
      - 「プロファイル生成」押下 → `window.confirm` 拒否で `renderCopilotProfile` が呼ばれず、
        受理で成功 / 失敗のトーストが表示される。
      → 7 テスト green。`vi.useFakeTimers()` でデバウンスを確定的に検証。
- [x] `MemoryList` の選択ロジック (行クリックで `data-selected="true"` になる、一意選択) を
      `MemoryList.test.tsx` として分離検証する。
      → 4 テスト green。一括承認 / 一括削除の confirm 受理分岐もカバー。
- [x] `MemoryDetailPanel` の検証 (行切替時の古い詳細の上書き抑止、API 失敗時のエラー表示) を
      解決順序制御したモック Promise で検証する。
      → 3 テスト green。`mockReturnValueOnce` チェーンで mem-1/mem-2 の解決順を反転させ、
      新しい詳細 (`mem-2`) が古い応答 (`mem-1`) で上書きされないことを検証。
- [x] 上記が揃った段階で `tests/e2e/test_memory_smoke.py` のうち以下 5 件を削除する:
      `test_candidate_list_shows_seeded_memories`,
      `test_candidate_detail_panel_shows_evidence`,
      `test_approved_seeded_memory_appears_in_approved_filter`,
      `test_row_click_highlights_selected_row`,
      `test_switching_rows_keeps_detail_panel_content`。

## Phase 5: HITL 画面の Vitest 化 — 完了 (2026-07-24)

- [x] `HitlPage.test.tsx` を新規作成し、以下を検証する:
      - 初回ロードで `listHitlRuns` が `pending_user` で呼ばれ、件数が表示される。
      - ステータスフィルター変更で `listHitlRuns` の第二引数が変化し、表示が更新される。
      - 行選択で `getHitlRun` が呼ばれ、必須質問の初期値 (`boolean` は `true`、それ以外は空文字)
        が `answers` にセットされる。
      - 必須質問が空のまま送信を押すと `setDetailError` が呼ばれ、API は叩かれない。
      - 送信成功後に `submitHitlAnswer` の戻り値に従い成功メッセージと質問ステータス
        (answered) が表示される。
      - 送信失敗 (`ApiError`) でエラーメッセージが表示される。
- [x] `HitlPage.test.tsx` で「キャンセル」ボタンの `window.confirm` 受理・拒否両分岐を検証する
      (UI 反応のみ。実 confirm ダイアログと実キャンセル遷移は Phase 7 の E2E に残す)。
      → 9 テスト green。`boolean` 質問の初期値も別ケースでカバー。
- [x] 上記が揃った段階で `tests/e2e/test_hitl_flow.py` のうち以下 3 件を削除する:
      `test_hitl_sidebar_link_and_navigation`,
      `test_hitl_list_and_details_rendering`,
      `test_hitl_list_status_filter`。

## Phase 6: 残画面の Vitest 化 (任意だが推奨)

- [ ] `ResearchPage` / `ResearchDetailPanel` の失敗ジョブ時の Markdown 非表示など、表示責務を
      追加検証する (`ResearchDetailPanel.test.tsx` は既に存在するため更新のみ)。
- [ ] `TaskPage` の localhost 403 応答 (API が `ApiError(403)` を投げる) 時の UI ハンドリングを
      検証する。コマンドプレビューのデバウンスが壊れていないかも含める。
- [ ] `PeoplePage` / `ProjectsPage` のマージ・削除確認 UI を検証する (実 API 呼び出しは
      ブラウザ E2E に残さない方針)。
- [ ] `ExecutionLogPage` / `VaultSearchPage` / `SummaryDashboardPage` の既存テストをレビューし、
      表示崩れや並び順だけをアサートしている箇所があれば削除または限定する。

## Phase 7: E2E を 3 本に統合 — 完了 (2026-07-24)

- [x] `obsidian_ai_hub.testing.seed` のシード関数を整備する。実装は当初案の
      `seed_memory_approval_scenario` / `seed_hitl_answer_scenario` /
      `seed_hitl_cancel_scenario` の 3 関数分割ではなく、`seed_memory_demo_data()` と
      `seed_hitl_demo_data()` の 2 関数にまとめ、`tests/e2e/conftest.py` のモジュール
      スコープ `e2e_seed_scenario` フィクスチャでシナリオ別 (`["memory"]` / `["hitl"]`)
      に振り分ける形を採用。機能的には等価で、ADR/usage.md もこの 2 関数 + フィクスチャ
      方式を前提に記述されている。
- [x] `tests/e2e/test_memory_smoke.py` を 1 シナリオ (承認フロー) に再構成し、
      `test_memory_scenario.py` にリネーム。ルート起動 + `/` → `/memories` リダイレクト、
      `/memories` 直接 URL、候補承認 + approved フィルター再表示、SPA フォールバック
      (任意パスで `index.html` 配信) を 3 テストで担保。
- [x] `tests/e2e/test_hitl_flow.py` を 2 シナリオ (回答送信、キャンセル) に分割し、
      `test_hitl_answer_scenario.py` / `test_hitl_cancel_scenario.py` を新設。各シナリオ
      は独立した `e2e_seed_scenario = ["hitl"]` で順序依存を排除。
- [x] `tests/e2e/conftest.py` の module-scope フィクスチャを、シナリオ別シードを引数で受ける
      形にリファクタする。`server` / `thread` は `None` 初期化 + finally で防御的に
      クリーンアップし、マイグレーション / シードの失敗が二重 cleanup でマスクされない
      構造に変更。失敗時のアーティファクト採取 (`test-results/e2e/`) は維持。
- [x] `docs/e2e-test/TODO.md` の Phase 3 〜 5 および Phase 7〜9 の項目を本プラン完了と整合
      する形に更新する。

## Phase 8: CI に E2E ジョブを追加 — 完了 (2026-07-24)

- [x] `.github/workflows/frontend-e2e.yml` を新設。Node 24 セットアップ → `uv sync --frozen
      --all-extras` → `uv run playwright install chromium` → `make test-e2e` を順次実行。
      `make jules-setup` 相当を workflow 内に閉じ込め、Jules VM と PR CI の双方で
      同一コマンド列を使う。
- [x] 失敗時のみ `test-results/e2e/` を `actions/upload-artifact@v4` でアップロード
      (`if: failure()` / `if-no-files-found: ignore` / `retention-days: 14`)。
- [x] `pytest.yml` / `frontend-unit.yml` / `frontend-e2e.yml` の 3 workflow を
      `pull_request` トリガで並列起動。両 frontend workflow は `ready_for_review`
      も含めてドラフト解除時に走らせる。

## Phase 9: ドキュメントと ADR — 完了 (2026-07-24)

- [x] `ai_wiki/10-Decisions.md` に「フロントエンドテストの Vitest 化と E2E テストの役割縮小
      (Phase 3〜5、および 7〜9)」と「E2E を重大なユーザーフローに限定する (Phase 7〜9
      追加検証)」の 2 件を ADR として追記。日付、カテゴリ、結論に至った経緯、トレードオフ
      (CI コスト、ローカル Vitest 拡張、MSW 不採用の理由) を含む。
- [x] `docs/testing.md` の「E2E の対象範囲」セクションに、Vitest で吸収できる範囲の例
      (UI 状態遷移、フィルター、選択、フォーム検証、ロード・失敗状態、API 契約) を追記。
- [x] `docs/e2e-test/usage.md` を新規作成し、3 本の E2E がどの主要導線を担保するかを簡潔に
      記載 (AI エージェントの参照用)。失敗時アーティファクトの `uv run playwright show-trace`
      手順も含む。

## 受け入れ基準 — 完了 (2026-07-24)

- [x] `npm --prefix frontend test` が CI で常時 green。
      → 81/81 (11 ファイル) green。`frontend-unit.yml` が毎 PR で実行。
- [x] `make test-e2e` が CI で 3 シナリオ green。`test-results/e2e/` に失敗時アーティファクト
      が残る。
      → `frontend-e2e.yml` 上で 5 テスト / 3 シナリオファイル (`test_memory_scenario.py`:
      3、`test_hitl_answer_scenario.py`: 1、`test_hitl_cancel_scenario.py`: 1) green。
      失敗時のみ `actions/upload-artifact@v4` で `test-results/e2e/` を 14 日保持。
- [x] `tests/e2e/` のファイル数がメモリ 1 + HITL 2 の合計 3 ファイルになり、いずれもモジュール
      間で状態を共有しない。
      → 各ファイルが `e2e_seed_scenario` モジュールフィクスチャで `["memory"]` / `["hitl"]`
      を宣言し、`conftest.py` がそれに応じてシードを振り分けるため、状態は共有されない。
- [x] 既存 Playwright 由来の `Memory` 5 件、`HITL` 3 件の計 8 件の E2E ロジックが Vitest で
      再現されている (削除前に同等の Vitest が green)。
      → Memory 側: `App.test.tsx` (8) + `MemoryPage.test.tsx` (7) +
      `MemoryList.test.tsx` (4) + `MemoryDetailPanel.test.tsx` (3) = 22 件でカバー。
      HITL 側: `HitlPage.test.tsx` 9 件でカバー。`api/client.test.ts` 26 件で API 契約
      も担保。
- [x] `ai_wiki/10-Decisions.md` に ADR が追記されている。
      → 「フロントエンドテストの Vitest 化と E2E テストの役割縮小 (Phase 3〜5、および 7〜9)」
      と「E2E を重大なユーザーフローに限定する (Phase 7〜9 追加検証)」の 2 件。
