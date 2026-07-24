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

- [x] `.github/workflows/frontend-unit.yml` を新設し、Node 24 (LTS、JSDOM 29 / Vitest 4
      の engines 要件 `>=24.0.0` を満たす) のセットアップ、`npm --prefix frontend ci`、
      `npm --prefix frontend test`、`npm --prefix frontend run build` を順次実行する。
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
      - **token 管理**: `getToken` / `setToken("")` / `clearToken` の `sessionStorage` 連携。
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

## Phase 3: `App` の Vitest 化

- [ ] `frontend/src/App.test.tsx` を新規作成し、以下を検証する:
      - `health()` 成功時に `authed=true` で `/memories` がレンダリングされる。
      - `health()` が 401 のとき `TokenPrompt` が表示される (`needsToken=true`)。
      - `health()` が 401 以外で失敗したとき接続エラー画面と「再読み込み」ボタンが描画される。
      - `MemoryRouter` で `/` が `ROUTES.MEMORIES` にリダイレクトされる。
      - モバイルナビ: `aria-label="メニューを開く"` ボタンで開閉し、Esc で閉じる。
      - `Sidebar` の各リンクがそれぞれのルートに遷移する (`/memories`, `/research`, `/hitl`,
        `/vault-search`, `/summary-dashboard`, `/people`, `/projects`, `/tasks`,
        `/execution-logs`)。

## Phase 4: Memory 画面の Vitest 化

- [ ] `MemoryPage.test.tsx` を新規作成し、以下を検証する:
      - 初回ロードで `listMemories` と `getMemoryOptions` が呼ばれ、ステータス / 種別 /
        トピック / 検索のフィルタ UI が描画される。
      - 検索入力の 500ms デバウンス後に `listMemories` が発火し、進行中の入力では発火しない。
      - ステータス変更で行選択と詳細がリセットされる。
      - 「プロファイル生成」押下 → `window.confirm` 拒否で `renderCopilotProfile` が呼ばれず、
        受理で成功 / 失敗のトーストが表示される。
- [ ] `MemoryList` の選択ロジック (行クリックで `data-selected="true"` になる、一意選択) を
      `MemoryList.test.tsx` として分離検証する。
- [ ] `MemoryDetailPanel` の検証 (行切替時の古い詳細の上書き抑止、API 失敗時のエラー表示) を
      解決順序制御したモック Promise で検証する。
- [ ] 上記が揃った段階で `tests/e2e/test_memory_smoke.py` のうち以下 4 件を削除する:
      `test_candidate_list_shows_seeded_memories`,
      `test_candidate_detail_panel_shows_evidence`,
      `test_approved_seeded_memory_appears_in_approved_filter`,
      `test_row_click_highlights_selected_row`,
      `test_switching_rows_keeps_detail_panel_content` の 5 件。

## Phase 5: HITL 画面の Vitest 化

- [ ] `HitlPage.test.tsx` を新規作成し、以下を検証する:
      - 初回ロードで `listHitlRuns` が `pending_user` で呼ばれ、件数が表示される。
      - ステータスフィルター変更で `listHitlRuns` の第二引数が変化し、表示が更新される。
      - 行選択で `getHitlRun` が呼ばれ、必須質問の初期値 (`boolean` は `true`、それ以外は空文字)
        が `answers` にセットされる。
      - 必須質問が空のまま送信を押すと `setDetailError` が呼ばれ、API は叩かれない。
      - 送信成功後に `submitHitlAnswer` の戻り値に従い成功メッセージと質問ステータス
        (answered) が表示される。
      - 送信失敗 (`ApiError`) でエラーメッセージが表示される。
- [ ] `HitlPage.test.tsx` で「キャンセル」ボタンの `window.confirm` 受理・拒否両分岐を検証する
      (UI 反応のみ。実 confirm ダイアログと実キャンセル遷移は Phase 7 の E2E に残す)。
- [ ] 上記が揃った段階で `tests/e2e/test_hitl_flow.py` のうち以下 3 件を削除する:
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

## Phase 7: E2E を 3 本に統合

- [ ] `obsidian_ai_hub.testing.seed` に以下 3 つのシナリオ別シード関数を追加する:
      `seed_memory_approval_scenario`, `seed_hitl_answer_scenario`,
      `seed_hitl_cancel_scenario`。既存 `seed_memory_demo_data` は内部で
      `seed_memory_approval_scenario` を呼ぶよう整理する。
- [ ] `tests/e2e/test_memory_smoke.py` を 1 シナリオ (承認フロー) に再構成する。直接 URL
      (`/memories`) と SPA フォールバック起動を 1 テストで担保する。
- [ ] `tests/e2e/test_hitl_flow.py` を 2 シナリオ (回答送信、キャンセル) に分割する。各シナリ
      オは独立したシードで順序依存を排除する。
- [ ] `tests/e2e/conftest.py` の module-scope フィクスチャを、シナリオ別シードを引数で受ける
      形にリファクタする。失敗時のアーティファクト採取は維持する。
- [ ] `docs/e2e-test/TODO.md` の Phase 3 〜 5 の項目を本プラン完了と整合する形に更新する。

## Phase 8: CI に E2E ジョブを追加

- [ ] `.github/workflows/` に `frontend-e2e` ジョブを新設する。`make jules-setup` 相当
      (uv sync / `npm --prefix frontend ci` / `uv run playwright install --with-deps chromium`)
      を実行し、`make test-e2e` を走らせる。
- [ ] 失敗時のみ `test-results/e2e/` を artifact としてアップロードする。
- [ ] フロントエンド・E2E・Python ジョブの 3 つを並列で起動する構成にする。

## Phase 9: ドキュメントと ADR

- [ ] `ai_wiki/10-Decisions.md` に「Vitest を React の標準テスト層とし、Playwright E2E は主要
      フロー 3 本に限定する」決定を ADR として追記する。日付、カテゴリ、結論に至った経緯、
      トレードオフ (CI コスト、ローカル Vitest 拡張、MSW 不採用の理由) を含める。
- [ ] `docs/testing.md` の「E2E の対象範囲」セクションに、Vitest で吸収できる範囲の例
      (UI 状態遷移、フィルター、選択、フォーム検証、ロード・失敗状態、API 契約) を追記する。
- [ ] `docs/e2e-test/usage.md` を新規作成し、3 本の E2E がどの主要導線を担保するかを簡潔に
      記載する (AI エージェントの参照用)。

## 受け入れ基準

- [ ] `npm --prefix frontend test` が CI で常時 green。
- [ ] `make test-e2e` が CI で 3 件 green。`test-results/e2e/` に失敗時アーティファクトが残る。
- [ ] `tests/e2e/` のファイル数がメモリ 1 + HITL 2 の合計 3 ファイルになり、いずれもモジュール
      間で状態を共有しない。
- [ ] 既存 Playwright 由来の `Memory` 5 件、`HITL` 3 件の計 8 件の E2E ロジックが Vitest で
      再現されている (削除前に同等の Vitest が green)。
- [ ] `ai_wiki/10-Decisions.md` に ADR が追記されている。
