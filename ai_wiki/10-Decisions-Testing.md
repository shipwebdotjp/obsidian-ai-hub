# テスト・開発環境の決定記録

## テスト環境隔離 (ENV=test)

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-18 |
| カテゴリ | テスト環境隔離 |
| 決定内容 | `ENV=test` 環境変数による完全隔離テストモードを導入する |

### 結論に至った経緯

既存の pytest によるテストは conftest.py の機構でデータベースアクセスを隔離しているが、CLI
コマンドを直接 `uv run python -m ...` で実行するアドホックテストが本番データや外部サービスに
アクセスするリスクがあった。本番環境変数や API キーを継承したままテスト実行されるのを防ぐ
仕組みが必要。

### 仕組みの概要

1. `ENV=test` が設定されている場合、config.py のモジュール読込時に全アプリ固有の環境変数を
   `os.environ` から削除する。
2. `.env`（本番）は読まず、`.env.test` が存在すればそれを読む（pytest 実行時は
   `OAIHUB_SKIP_DOTENV=1` によりスキップ）。
3. 全書き込み先（VAULT_PATH, MEMORY_SQLITE_PATH, AI_LOG_PATH, その他）を
   `tempfile.TemporaryDirectory` が作成する一時ワークスペース配下に設定する。
4. `ensure_external_allowed()` 関数で外部アクセス（LLM API, LINE, YouTube, Calendar,
   Reminders, Web 検索, Open Web UI）をブロック。`ALLOW_EXTERNAL_IN_TEST=1` でのみ許可。
5. `config/config.test.yml` を設定ファイルとして使用。
6. `tasks/tasks.test.yml`（空リスト）をタスク定義として使用。

## Jules VM におけるテスト環境とセットアップの統一

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-22 |
| カテゴリ | テスト環境・開発効率 |
| 決定内容 | Jules VM用等の一時的なクリーンクローン環境向けに専用のセットアップ手段 `make jules-setup` を用意し、検証環境は `ENV=test` に統一して `ENV=jules` は廃止・使用禁止とする。 |

### 結論に至った経緯

JulesAgentによるコーディングと動作確認・テストを迅速かつ確実に実行するため、当初は専用の `ENV=jules` 等の環境追加が検討された。しかし、これを行うと新たな設定ファイル（`config.jules.yml` や `.env.jules`）や永続ディレクトリの管理コストが発生し、本番データへの誤書き込みリスク、またJules VMでのクリーンクローン直後のセットアップ難易度を上げる原因となっていた。
すでに強固なテスト環境分離として用意されている `ENV=test`（一時SQLite、一時Vault、自動起動Uvicorn、Playwright）と、追跡済みの依存解決・フロントエンドビルドコマンド群を最大限に活用し、共通化するのが最もシンプルで安全であるとの結論に至った。

### 仕組みの概要

1. **セットアップの自動化 (`make jules-setup`):**
   クリーンクローンされたVM環境において、以下の工程を一行で確実に自動実行できるMakefileターゲットを提供する。
   - `uv sync --frozen --all-extras` (Python依存関係の厳密な同期)
   - `npm --prefix frontend ci` (フロントエンド依存関係のインストール)
   - `uv run playwright install --with-deps chromium` (Playwright向けChromiumバイナリの取得)
2. **安全な Initial Setup スナップショット:**
   Jules VMの「Initial Setup」ステップに `make jules-setup && ENV=test uv run pytest tests/` を登録。これにより、ローカル上の `.env` や既存の `dist/` ビルド、ローカルモデル・個人Vaultの存在を前提にせず、スナップショットを安定して作成する。
3. **`ENV=test` の強制適用:**
   `ENV=jules` は完全に廃止。探索サーバー (`e2e_server.py`) は親プロセスの `ENV` の値を継承せず、実行時に内部で `ENV=test` を強制セットするようにした。これにより、誤った設定で本番用の `.env` やデータベースにアクセスしてしまう事故を完全に防止する。

## E2E を重大なユーザーフローに限定する (Phase 7〜9 追加検証)

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-24 |
| カテゴリ | テスト戦略・フロントエンド |
| 決定内容 | E2E は主要な操作が完了不能になる、データを失う・壊す、または認可境界を越える重大な回帰の防止に限定する。追加したUI要素、静的なプリセット・選択肢、文言、ステータス表示、スタイル、並び順だけを検証するE2Eは追加しない。 |

### 結論に至った経緯

ブラウザE2Eはフロントエンドのビルド、サーバー、ブラウザ自動化を必要とし、単体・結合テストより実行コストと保守コストが高い。UIにプリセットを1件追加した、文言を変えたといった変更ごとに存在確認テストを増やすと、利用者への重大な影響を検証しない脆いテストが蓄積する。表示の存在はコードレビューと必要な目視確認で判断できるため、E2Eの費用に見合わない。

### 適用基準

- E2Eは、画面の起動・遷移、主要なデータ変更、破壊的操作の安全性、認可・権限などの一連の操作と結果を検証する。
- 追加・変更したUI要素自体の存在、固定文言、静的な選択肢やプリセット、見た目だけを検証するテストは書かない。
- ドメインロジックの状態遷移やデータ整合性は、より軽量で原因を特定しやすい単体テストまたは結合テストで検証する。
- コードレビューで表示確認だけのE2E追加を求められても、具体的な重大障害シナリオがなければ追加しない。

### トレードオフ

軽微な表示崩れや静的な選択肢の欠落を自動検知する範囲は狭くなる。一方で、E2Eは重大な利用不能・データ損失・認可不備に集中でき、変更のたびに保守負債となるテストが増えることを防げる。

## フロントエンドのツールチェーンポリシー (Vite 6 + Vitest 4)

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-24 |
| カテゴリ | フロントエンド・テスト基盤 |
| 決定内容 | フロントエンドの Vite を `^6.0.0` に揃え、Vitest 4 系を正式採用する。`package.json` に `overrides.vite: "^6.0.0"` を設定し、lockfile 上で Vite のバージョンを一本化する。 |

### 結論に至った経緯

`frontend/package.json` で Vite 5.4 系と Vitest 4.1 系が同居していた。Vitest 4 は peer dependency で `vite: ^6 || ^7 || ^8` を要求するため、lockfile は root に Vite 5.4.21 を残しつつ `node_modules/vitest/node_modules/vite@8.1.5` をネスト導入し、ビルドエンジンが二重に存在する状態になっていた。JSDOM 29 が `node >=20.19` を要求するため CI の Node 固定も必須となる。

選択肢として以下を比較した。

- **Vite 6+ に揃える (採用)**: アプリケーションの Vite を `^6.0.0` にバンプし、Vitest 4 の peer 条件と整合させる。`@vitejs/plugin-react@4.7.0` と `@tailwindcss/vite@4.3.x` はいずれも Vite 6 を peer に含む。`overrides.vite` で lockfile のネストも解消できる。
- **Vite 5 維持 + Vitest 3 系へ下げる**: 変更は devDependencies の vitest バージョンのみで小さいが、Vitest 4 の機能 (browser provider, expect API 改善) を活用できない。
- **現状維持**: 動作はするが二重 Vite 状態が残り、依存解決の透明性が下がる。

Vite 6 は現在の安定 LTS ラインであり、Vitest 4 を本格活用する前提で揃えるほうが将来コストが低いと判断した。

### 適用範囲

- `frontend/package.json` の `vite` を `^6.0.0` に固定する。
- `frontend/package.json` に `overrides: { "vite": "^6.0.0" }` を追加し、lockfile 上で Vite のバージョンを一本化する。
- CI における Node の最低バージョンを `>=20.19.0` とする (JSDOM 29 / Vitest 4 の engines 要件)。
- `@vitejs/plugin-react@4.7.0` の `esbuild` 設定由来の deprecation 警告は動作に影響しないため、別フェーズで `oxc` 移行を検討する。

### トレードオフ

- Vite 5 → 6 の破壊的変更 (主に plugin API と環境変数) を将来踏む可能性は残るが、現状のプラグインは Vite 6 互換のため即時の修正は不要。
- ローカル開発では `node_modules/vitest/node_modules/vite` 由来のビルドサイズ・型解決の不整合がなくなる。
- Node バージョンを `>=20.19.0` に引き上げる必要があり、CI の Node セットアップを明示する。

## フロントエンドテストの Vitest 化と E2E テストの役割縮小 (Phase 3〜5、および 7〜9)

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-24 |
| カテゴリ | フロントエンド・テスト戦略 |
| 決定内容 | UIの表示状態、フィルター操作、非同期処理の競合、デバウンス、およびダイアログ制御は Vitest (React Testing Library) で網羅検証し、Playwright E2E は真に重要な結合ユーザーフローに限定して役割を縮小する。さらに Phase 7〜9 でシナリオベースに再編し、テスト・データのセットアップをクリーンにモジュール化する。 |

### 結論に至った経緯

以前のフロントエンドテストでは、微細なUIの変更や非同期処理の検証をすべて実ブラウザを通した Playwright E2E テスト（13件）に依存していた。しかし、E2Eは起動やシード、環境構築のオーバーヘッドが大きく動作が非常に遅いこと、また表示文言や見た目の些細な変化でテストが破損しやすいため、開発・メンテナンスコストを高めていた。

表示や状態遷移は React 層（JSDOM）で確定的かつ軽量に検証できるため、Vitest + React Testing Library によるテスト層を標準に据える。

### 変更点と役割分担

1. **Vitest (React Testing Library) の拡充**:
   - `App.tsx` の認証状態、健康チェック失敗、ルートリダイレクト、モバイルナビ、サイドバー遷移。
   - `MemoryPage` / `MemoryList` / `MemoryDetailPanel` の初回ロード、フィルター連動、500msデバウンス、選択リセット、一意選択状態、レース条件抑止、詳細API失敗ハンドリング。
   - `HitlPage` の初期ロード、フィルター、行選択、必須検証、回答送信、キャンセル確認ダイアログ。
2. **Playwright E2E の縮小・再編 (Phase 7〜9 完了)**:
   - 旧 E2E の 5 件のテストを、役割と関心に応じて 3 つのシナリオベースのファイル（1つのメモリシナリオ、2つの HITL シナリオ）へ整理統合。
     - `test_memory_scenario.py` (メモリ承認・ロード関連)
     - `test_hitl_answer_scenario.py` (HITL 回答送信フロー)
     - `test_hitl_cancel_scenario.py` (HITL キャンセルフロー)
   - `conftest.py` にモジュール単位でシードするシナリオを指定できるパラメータ化（`e2e_seed_scenario`）を導入。
   - テストシードデータを DB 操作 API などでクリーンに構築する処理を `src/obsidian_ai_hub/testing/seed.py` の `seed_hitl_demo_data()` に集約し、テストファイル内の不透明な SQL べた書きを廃止。
   - 結果として、E2Eは起動・SPAフォールバック・主要データ永続化を含む3つの高インパクト導線シナリオのみに限定・整理された。

### トレードオフ

- ローカルおよびCIでのテスト実行速度が飛躍的に向上した（E2E実行数の削減と高速なJSDOMテスト）。
- 静的なアサーションによるテストの脆さが解消され、ロジック変更に対するリグレッション耐性が向上した。
- シードシナリオが疎結合かつ構造化されたため、将来の追加の際も既存テストのシードとの干渉や無駄なオーバーヘッドが最小化される。
- 実ブラウザでしか発生しない特殊なアセット崩れや一部ブラウザ仕様の不整合を網羅する範囲は狭まるが、目視およびレビュー、縮小後のコアE2Eで実質的な品質担保を補完する。

## pytestプロセスからの本番シークレット遮断（conftest強制ENV=test）

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-15 |
| カテゴリ | テスト基盤・セキュリティ |
| 決定内容 | `tests/conftest.py` が import 直前に `ENV=test` を強制し、アプリ設定の `IS_TEST_ENV` を本番のテスト実行時にも有効にする。`_APP_ENV_VARS`（LINEトークン、APIキー等）はテストプロセスから剥がされ、本番 `.env` は読み込まれない。 |

### 結論に至った経緯

HITL v1 の `notify_research_suggestion` 追加後、`uv run pytest tests/`（`ENV=test` 指定なし）を実行したところ、実機のLINEへテスト由来の通知が1件送信された。`tests/conftest.py` は従来 `OAIHUB_SKIP_DOTENV=1` のみを設定し `ENV=test` を設定していなかったため、`config.IS_TEST_ENV` が `False` になり、`else` 分岐で本番 `.env`（実LINEシークレット）が読み込まれて `ALLOW_EXTERNAL_IN_TEST=True` になっていた。その結果 `test_main_creates_themes_and_researches` が呼ぶ `notify_research_suggestion` が実LINEのPush APIを叩いた。AGENTS.mdが要求する「テストは `ENV=test` で実行」を実行時に自動化できていなかったのが根本原因。

### 仕組みの概要

1. **強制:** `conftest.py` は `obsidian_ai_hub.utils.config` の import より前で、`ENV` が未設定なら `ENV=test` に設定する。これによりテストプロセスは常に `IS_TEST_ENV=True` となり、`_APP_ENV_VARS` の剥離と本番 `.env` の非読込が効く。`ENV` を明示指定した場合は上書きしない。
2. **外部アクセス維持:** 既存スイートのうちApple Reminders/EventKit・LLMクライアント・YouTubeを実際に呼ぶ13件は `ensure_external_allowed` を通過して動いているため、import 後に `app_config.ALLOW_EXTERNAL_IN_TEST = True` で従来挙動を維持する。ただし `ENV=test` により実クレデンシャルは剥がれているため、実LINE・実LLM・実キーへの到達は不可能なままである（従来比で厳密に安全側）。
3. **検証:** `uv run pytest tests/`（プレフィックスなし）で582件全通過。プロセス内で `config.LINE_MESSAGING_TOKEN` / `LINE_TARGET_ID` / `OBSIDIAN_AI_HUB_WEB_URL` が空であることを確認した。

### トレードオフ

- テストプロセスは `config.test.yml` を使用し、本番 `config.yml` の値を参照しない。依存するテストは各fixtureで必要な値を上書きする。
- `ALLOW_EXTERNAL_IN_TEST` をスイート全体で有効化するため、`ensure_external_allowed` の遮断はテストプロセスでは働かないが、クレデンシャル非存在が一次防御となる。

