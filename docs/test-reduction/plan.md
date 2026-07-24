# テスト層再編プラン: Vitest 拡充と Playwright E2E 縮小

> Phase 0 (ツールチェーンポリシー) 完了: 2026-07-24
> 関連 ADR: [`ai_wiki/10-Decisions.md` の「フロントエンドのツールチェーンポリシー (Vite 6 + Vitest 4)」](../../ai_wiki/10-Decisions.md#フロントエンドのツールチェーンポリシー-vite-6--vitest-4)
> 進行管理: [`todo.md`](./todo.md)

## 背景

現行のフロントエンドテストは Vitest + React Testing Library が既に導入されているが、コンポーネント
単位の限定的な 24 件程度に留まっている。実ブラウザを通したリグレッション確認の多くを Python
Playwright E2E に依存しており、合計 13 件の E2E が走っている。E2E はビルド済み SPA・FastAPI
静的配信・Chromium・DB シード・Uvicorn 起動・スクリーンショット/トレース採取を伴うため、追加・
更新コストが高く、軽微な表示変更でも壊れやすい。

ブラウザでしか検証できないもの (静的アセット配信、SPA フォールバック、ネイティブダイアログ、
永続化を含む主要導線) だけが E2E の本来の守備範囲であり、表示や状態遷移は React 層で確定的に
検証できる。本プランでは Vitest を React の標準テスト層に格上げし、Playwright E2E は主要フロー
3 本に絞る方針を採る。

Vitest は新規導入ではなく既に `frontend/package.json` に含まれており、CI に乗っていないのが
現状の最大の課題である。

## 役割分担

| 層 | 担当 | 主な対象 |
| --- | --- | --- |
| Python 単体・API 結合 (FastAPI TestClient) | ドメイン規則、DB 永続化、API 入力検証、認可、リモートトークン規則、レスポンス契約 | メモリ承認/却下/編集/resolve、HITL 状態遷移、人物統合/削除、タスク設定の localhost 403、Vault 検索入力検証 |
| Vitest + React Testing Library (JSDOM) | React 上の状態遷移、フォーム検証、ロード/失敗状態、API 結果を受けた表示と再取得、`fetch` 契約、ルーティング、認証プロンプト | `App` の health/401/接続エラー/リダイレクト/モバイルナビ、Memory・HITL・Tasks・People・Projects ページのフィルター・選択・送信・キャンセル UI、競合エラー応答のハンドリング |
| Python Playwright E2E | ビルド済み SPA + FastAPI 静的配信、SPA フォールバック、ネイティブ `confirm`、実 API・実 DB・実ブラウザの主要導線 | 起動/直接 URL、メモリ承認、HITL 回答送信、HITL 実行キャンセル |

## Vitest の設計方針

- 既存の `vi.mock("../../api/client")` パターンを踏襲する。型付き API クライアントが明確な
  境界として機能しているため、MSW は当面追加しない。
- `api/client.ts` 自体を別ファイル (`api/client.test.ts`) で検証し、URL・HTTP メソッド・JSON
  ボディ・Bearer ヘッダ・401 時の `clearToken()`・`ApiError` 変換を押さえる。`fetch` の呼び出し
  が一箇所 (`frontend/src/api/client.ts:55-90`) に集約されている価値を高める。
- 各ページは成功だけでなく、ロード中、API 失敗 (`ApiError` 投入)、入力不備、409 競合、401
  ログアウトなど「利用者が操作継続できるかに影響する状態」を最低 1 ケースずつ検証する。
- 行切替時のレース条件 (古い詳細レスポンスの上書き) のような UI 特有の状態遷移は、解決順序を
  制御したモック Promise で決定的に検証する。
- `window.confirm` を含むフローはモックして UI 反応を検証する一方、ブラウザ確認ダイアログを
  含む実導線 (HITL キャンセル) は E2E に残す。
- ロール/ラベル/placeholder ベースのロケータを優先し、AGENTS.md の `data-testid` 規約と整合
  を取る。表示文言・Tailwind クラス・並び順だけのアサーションは追加しない。
- カバレッジ閾値は初期導入時には設けない。数値合わせの脆いテスト増加を防ぐ。レポート自体が
  必要になった時点で `@vitest/coverage-v8` 等を後付けする。

## 移行マッピング (現行 E2E 13 件 → E2E 3 本 + Vitest)

### Memory 8 件 (`tests/e2e/test_memory_smoke.py`)

| 現行ケース | 移行先 | 理由 |
| --- | --- | --- |
| `test_page_loads_and_redirects_to_memories` | E2E (Memory 主要導線に統合) | ビルド済み SPA 起動・SPA ルーティング検証 |
| `test_candidate_list_shows_seeded_memories` | Vitest | リスト描画と件数は React の責務 |
| `test_candidate_detail_panel_shows_evidence` | Vitest | 詳細表示はモックレスポンスで決定的に検証可能 |
| `test_approve_candidate_removes_from_list_and_shows_in_approved` | E2E (Memory 主要導線に統合) | ブラウザ → 実 API → 永続化 → 再描画の主要変更導線 |
| `test_approved_seeded_memory_appears_in_approved_filter` | Vitest | フィルター UI 動作は React 責務、API 契約は Python 側 |
| `test_spa_fallback_serves_memory_page` | E2E (Memory 主要導線に統合) | FastAPI の SPA フォールバックはブラウザでしか検証できない |
| `test_row_click_highlights_selected_row` | Vitest | `data-selected` はローカル UI 状態 |
| `test_switching_rows_keeps_detail_panel_content` | Vitest | 解決順序制御したモックで決定的に検証可能 |

### HITL 5 件 (`tests/e2e/test_hitl_flow.py`)

| 現行ケース | 移行先 | 理由 |
| --- | --- | --- |
| `test_hitl_sidebar_link_and_navigation` | Vitest | ルート設定と `Sidebar` の責務 |
| `test_hitl_list_and_details_rendering` | Vitest | 表示・選択・質問レンダリングはモックで検証可能 |
| `test_submit_hitl_answer_and_flow` | E2E (HITL 回答導線) | 主要タスクの完了可否 |
| `test_cancel_hitl_run` | E2E (HITL キャンセル導線) | ブラウザ `confirm` を含む破壊的操作 |
| `test_hitl_list_status_filter` | Vitest | フィルター UI は React 責務、API 側フィルターは Python 側 |

### 最終的な E2E 3 本

1. **Memory 承認フロー** — ルート起動 + `/` → `/memories` リダイレクト、`/memories` 直接アクセス、
   候補の承認、一覧から消えること、承認済みフィルターで再確認。
2. **HITL 回答フロー** — 一覧から詳細、回答タイプ別操作、必須検証、送信後の answered 表示、
   run 状態の反映。
3. **HITL キャンセルフロー** — 実行選択、`window.confirm` 受理、キャンセル済みステータスへの
   遷移確認。

### E2E のフィクスチャ改善

- 現状の `tests/e2e/test_hitl_flow.py` は先行テストで変更された状態を後続テストが前提にしてい
  る (`test_cancel_hitl_run` のコメント、`test_hitl_list_status_filter` の件数期待)。3 本に統合
  する際は、各フローが独立したシードデータで完結するようにする。
- `tests/e2e/conftest.py` の module-scope Uvicorn フィクスチャと seed 関数を維持しつつ、
  シナリオごとにシードを選択できる仕組み (例: `seed_memory_approval_scenario` /
  `seed_hitl_answer_scenario` / `seed_hitl_cancel_scenario`) を `obsidian_ai_hub.testing.seed`
  に追加する。
- 失敗時のアーティファクト採取 (`test-results/e2e/`) は維持する。3 本に絞った分、CI での
  アップロード容量も問題にならない。

## CI への組み込み

現状の `.github/workflows/pytest.yml` は Python 依存と Chromium 導入のみで、Vitest も SPA ビル
ドも走らない。E2E フィクスチャは `frontend/dist/index.html` 不在で `pytest.skip` するため、
クリーン checkout では 13 件すべてが事実上未検証である。

### 必須対応

1. Node セットアップ (バージョン固定: `>=20.19.0`) を CI に追加。
2. `npm --prefix frontend ci` で依存導入。
3. `npm --prefix frontend test` を Python テストと並列のジョブで毎 PR 実行。
4. `npm --prefix frontend run build` を実行 (Vitest は `tsc` ビルド検証を代替しないため)。
5. ブラウザ E2E 専用ジョブで `make test-e2e` を実行。3 本に絞ったことで毎 PR 実行可能。

### オプション

- `paths` フィルタでフロントエンド未変更時に E2E をスキップする案は、サーバー側ハンドラや
  FastAPI 静的配信の回帰を取り逃すリスクがあるため、最初は採用しない。スコープ縮小による
  コスト低下で全 PR 実行を維持する。
- 並列化は Vitest / Python / Build / E2E を 4 ジョブ並列で組む。

## ツールチェーンメモ

- Vite 5.4.x / Vitest 4.1.x の組合せは、Vitest が Vite 6〜8 を peer に取るため `package-lock.json`
  で Vite 8 がネスト導入されている。動作はするが、ビルドエンジンが二重に存在する状態のため、
  Vitest 拡充を始める前に「Vite 5 互換の Vitest 系に統一」または「Vite を 6+ へ揃えて Vitest
  4 を正式採用」を方針として選ぶこと。本プランでは Vite 5 系を維持する場合の Vitest 3 系ダウ
  ングレードを推奨案とする。
- 既存テストは globals なしの個別 import を採用している (`import { describe, it, expect, vi,
  beforeEach } from "vitest"`)。これに揃える。
- `@testing-library/jest-dom/vitest` は `frontend/src/test/setup.ts` で有効化済み。

## リスクと未決事項

- 破壊的操作の E2E カバー範囲: People のマージ/削除と Task configuration の PUT は現状 E2E が
  ない。Vitest + Python TestClient で十分か、別ブラウザ導線を起こすかは実装フェーズで判断。
- リモート Bearer トークン規則は Python TestClient で担保されている。`App` の 401 → トークン
  プロンプト遷移は Vitest で検証する。
- 既存 FastAPI の SPA フォールバック契約 (任意パスで `index.html`) は本プランでも E2E の守備
  範囲として 1 ケースに集約する。
