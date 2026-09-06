# 人物間リレーション v1 実装計画

関連文書: [仕様書](specification.md) / [作業チェックリスト](todo.md)

本書は実装計画（どの順序で・どのファイルに・何を作るか）を定める。仕様の定義は仕様書に、進捗管理は作業チェックリストに記載し、本書には書かない。
今回はコード変更を行わないため、対象はすべて「候補」である。実装開始時に現行コードと再照合すること。

## 0. 前提と方針

- 現行構成: SQLite（raw `sqlite3`、ORM なし）、FastAPI（`web/api.py` の `APIRouter(prefix="/api/v1")`）、サービス層（`web/services/`）、React SPA（`frontend/src/features/people/`）。
- 人物系の既存実装を踏襲する: `with conn:` トランザクション境界、409 衝突拒否、プレビュー→実行の二段構え（`verify_people_merge()` / `merge_people()`）、Bearer 一元認証。
- E2E は追加・実行しない（リポジトリ方針: `AGENTS.md`「Frontend changes」、仕様書対象外にも明記）。
- `PersonDetail`（`web/schemas.py`）および `people_get`（`agents/registry.py`）を変更しない。
- `agents/registry.py` に relation ツールを登録しないことをテストで保証する。

## 1. フェーズ一覧と依存関係

```text
P0 事前意思決定の確定
 └→ P1 SQLite migration追加
      └→ P2 バックエンド schema/DTO
           └→ P3 サービス層（type・relation・evidence）
                ├→ P4 APIルート
                ├→ P5 人物削除への影響件数追加
                └→ P6 手動人物統合へのrelation移管追加
                     └→ P7 Vault同期の自動統合を共通処理へ接続
                          └→ P8 フロントAPIクライアント
                               ├→ P9 人物画面の関係セクション
                               └→ P10 関係タイプ作成・編集UI
P11 テスト（各フェーズに付随＋最終回帰）
P12 ドキュメント・ADR反映
P13 リリース前確認
```

## 2. P0 事前意思決定の確定

- 目的: 仕様書「12.1 実装開始前に決めるもの」を解消し、後続フェーズの手戻りを防ぐ。
- 対象ファイル候補: なし（文書作業）。出力は仕様書の未確定事項の更新ではなく、実装担当者の決定記録（ADR 起票は P12）。
- 具体的作業:
  - 初期組み込み型セット（slug・表示名・方向性）の確定。
  - `source_type` 初期 allowlist の確定。
  - 重複統合レスポンスの HTTP 表現（200 / 201 / 409）の確定。
  - タイプ作成・編集 UI の配置（人物画面内か管理画面か）の確定。
- 依存: なし。
- 完了条件: 4項目の決定が文書化され、P1 以降の作業者が参照できる。
- 主なリスク: 決定の先送りによる P3/P4 の作り直し。
- 必要なテスト: なし。

## 3. P1 SQLite migration 追加

- 目的: `person_relation_types` / `person_relations` / `person_relation_evidence` の3テーブルと索引を作成する。
- 対象ファイル候補:
  - `src/obsidian_ai_hub/database.py`（`get_db_connection()` 内の `PRAGMA user_version` 連鎖に新規ブロック追加）。
- 具体的作業:
  - migration の `PRAGMA user_version` は実装時点の最新値を再確認して採番する（本書作成時点の最新は 37。実装時に必ず再確認）。
  - 現行規約に合わせる: `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`、ブロック末尾で `PRAGMA user_version = N; conn.commit()`。
  - FK は `people(person_id)` への `ON DELETE CASCADE`、`person_relation_types` への参照は `ON DELETE RESTRICT` 概念＋サービス層検査の二重保証。
  - 意味的重複防止の一意索引と subject / object / type 検索用索引を作成する。NULL 含有時の UNIQUE 挙動（SQLite は NULL を相異とみなす）の対策は P3 のサービス層検査と組み合わせる。
- 依存: P0。
- 完了条件: 空 DB で最新バージョンまで migration が通り、3テーブルと索引が存在する。
- 主なリスク: user_version 採番の競合（並行開発で番号が奪われる）。再確認で回避する。
- 必要なテスト: migration 適用テスト（一時 DB で `get_db_connection()` 実行→テーブル・索引存在確認）。

## 4. P2 バックエンド schema / DTO

- 目的: relation 系の Web API スキーマを定義する。AI ツールスキーマとは共用しない。
- 対象ファイル候補:
  - `src/obsidian_ai_hub/web/schemas.py`（`Person` / `PersonDetail`（同ファイル）周辺に新規 Pydantic モデル追加。既存モデルの変更はしない）。
- 具体的作業:
  - `PersonRelationType`、`PersonRelation`、`PersonRelationEvidence`、作成・更新リクエスト、重複統合レスポンス（`created` / `merged_into_existing`）、状態（`upcoming / active / ended / undated`）のスキーマ追加。
  - `PersonDeleteResponse` に発信・受信関係数と根拠数を追加する（P5 で使用。追加のみで既存フィールドは変更しない）。
  - 統合プレビュー（`PeopleMergePreviewResponse`）への関係影響フィールド追加は P6 で行う。
- 依存: P1。
- 完了条件: 新規スキーマが import 可能で、既存スキーマのテストが壊れない。
- 主なリスク: 既存 `PersonDetail` への混入（禁止）。レビューで差分確認する。
- 必要なテスト: スキーマのバリデーションテスト（暫定。P11 に統合可）。

## 5. P3 サービス層（type・relation・evidence）

- 目的: 関係タイプ・関係・根拠の永続化ロジックと共通規則を集約する。新規サービスモジュールを作成し、人物統合・Vault 同期から再利用する。
- 対象ファイル候補:
  - 新規 `src/obsidian_ai_hub/web/services/person_relations.py`（名称は仮。`people.py` / `people_merge.py` / `people_candidates.py` と同列）。
  - 参照のみ: `src/obsidian_ai_hub/summary/store.py:normalize_entity_name()`（表記正規化が必要な場合）。
- 具体的作業:
  - directionality に応じた端点正規化（directed は型の正規方向、symmetric は決定的規則）を共通サービス関数へ集約する。作成・更新・統合の全経路が同関数を使う。
  - 意味的重複判定・evidence 移管・note 統合を共通化する（`consolidate_summary_links()`（`people_merge.py`）の note 連結パターンを参照）。
  - 日付検証（`YYYY-MM-DD` または NULL、開始≦終了、境界含む）と状態判定（4値）を共通関数化する。
  - 自己関係の拒否、使用中タイプの削除禁止・非活性型の新規作成禁止、`directionality` 使用後不変を enforced する。
  - 作成 API の冪等処理: 重複検出時は新規作成せず、根拠追加＋メモ統合＋ `merged_into_existing` を返す。
- 依存: P2。
- 完了条件: サービス関数単体で CRUD・正規化・重複統合・状態判定が動作する。
- 主なリスク: SQLite UNIQUE の NULL 挙動に依存した実装（サービス層検査を主にする）。端点正規化の二重実装（共通化で回避）。
- 必要なテスト: サービステスト（一時 DB 使用。`docs/testing.md` の隔離規約に従う）。

## 6. P4 API ルート

- 目的: 仕様書 9.1 の7エンドポイントを公開する。すべて Bearer 保護。
- 対象ファイル候補:
  - `src/obsidian_ai_hub/web/routes/people.py`（既存人物ルート。静的プレフィックスを `/{person_id}` より前に宣言する注意書きに従う）または新規 `routes/person_relations.py` ＋ `web/api.py` への include。どちらに置くかは実装時に現行ルート構成と再照合して決める。
  - `src/obsidian_ai_hub/web/routes/deps.py:require_bearer_token`（利用のみ。変更しない）。
- 具体的作業:
  - `GET /api/v1/people/{person_id}/relations`（状態フィルター対応）、`POST`（重複統合レスポンス）、`PATCH /api/v1/person-relations/{relation_id}`、`DELETE`（物理削除）。
  - `GET /api/v1/person-relation-types`、`POST`、`PATCH /api/v1/person-relation-types/{relation_type_id}`。
  - 409 衝突（自己関係・使用中タイプ削除・非活性型への作成等）は既存人物 API の `conflict_type` 形式に倣う。
- 依存: P3。
- 完了条件: 全エンドポイントが Bearer 必須で動作し、無トークンで 401 になる。
- 主なリスク: ルート順序の衝突（`/{person_id}` への吸収）。静的プレフィックス先行の規約を守る。
- 必要なテスト: API テスト（認証・CRUD・重複統合・409 系）。

## 7. P5 人物削除への影響件数追加

- 目的: 人物削除時に関係・根拠を連鎖削除し、件数を報告・確認表示する。
- 対象ファイル候補:
  - `src/obsidian_ai_hub/web/services/people.py:delete_person()`（明示 DELETE＋件数返却パターンを踏襲）。
  - `src/obsidian_ai_hub/web/schemas.py:PersonDeleteResponse`（P2 で拡張済み）。
  - `frontend/src/features/people/` の削除確認ダイアログ（P9 と連携）。
- 具体的作業:
  - `delete_person()` の同一 `with conn:` 内で `person_relations`（subject / object 両側）と `person_relation_evidence` を削除し、件数をレスポンスに追加する。
  - Vault 連携人物の削除確認に「再同期で人物は再作成され得るが関係は復元されない」警告文を追加する。
- 依存: P3、P4。
- 完了条件: 人物削除後に関係・根拠の孤立レコードが残らず、件数が正しく返る。
- 主なリスク: FK CASCADE と明示 DELETE の二重管理（既存も同方式のため許容。件数報告のため明示 DELETE を主にする）。
- 必要なテスト: 削除テスト（発信・受信・根拠あり人物の削除→件数・孤立なし）。

## 8. P6 手動人物統合への relation 移管追加

- 目的: `merge_people()` で関係・根拠を移管し、自己関係化・重複を処理する。
- 対象ファイル候補:
  - `src/obsidian_ai_hub/web/services/people_merge.py:verify_people_merge()`（プレビュー拡張）、`merge_people()`（移管実行）。
  - P3 の共通サービス関数（重複判定・移管・note 統合）を利用する。
- 具体的作業:
  - `verify_people_merge()` に自己関係化する関係と重複統合される関係の影響を追加表示する。
  - `merge_people()` の同一 `with conn:` 内で、統合元を端点に持つ辺を統合先へ付け替え、第三者重複は統合先 relation ID 存続＋根拠・メモ移管、期間相違は両残しとする。
  - 自己関係化は統合プレビューと実行直前の両方で再検証する。verify と execute の間の状態変化を考慮し、同一トランザクション内で再検証する（現行 `merge_people()` が `verify_people_merge()` を `with conn:` 内で再実行する構造を踏襲）。
  - 自己関係化する場合は関係の自動削除をせず、人物統合全体を拒否する。
- 依存: P3。
- 完了条件: プレビュー表示・移管・拒否・重複統合が仕様どおり動作する。
- 主なリスク: verify→execute 間の競合（同一トランザクション内再検証で回避）。移管漏れによる孤立（P11 の孤立検査で担保）。
- 必要なテスト: 人物統合テスト（移管・自己関係化拒否・第三者重複統合・期間相違の両残し）。

## 9. P7 Vault 同期の自動統合を共通処理へ接続

- 目的: Vault 同期内の人物吸収・統合でも P6 と同一の関係移管規則を適用する。二重実装しない。
- 対象ファイル候補:
  - `src/obsidian_ai_hub/people_sync/sync.py:sync_people_in_tx()`（自動吸収・統合箇所）。
  - `src/obsidian_ai_hub/web/services/people_sync.py:sync_people()`（呼び出し元。トランザクション境界の確認）。
  - P3 の共通サービス関数（P6 と共用）。
- 具体的作業:
  - `sync_people_in_tx()` 内の人物統合・吸収経路から P3/P6 の共通移管関数を呼び出す。同期固有の移管ロジックは書かない。
  - Vault 同期は関係に触れない（Vault を正本にしない）原則を維持し、移管は人物統合に付随する場合のみ行う。
- 依存: P6。
- 完了条件: 自動統合で関係が P6 と同一規則で移管され、同期が関係を直接作成・更新・削除しない。
- 主なリスク: 同期トランザクション境界の違い（`sync_people_in_tx(conn, ...)` は接続受取型）。共通関数の接続・カーソル受け渡し設計に注意する。
- 必要なテスト: Vault 同期テスト（`tests/test_sync_people.py` 系に追加。自動統合時の関係移管）。

## 10. P8 フロントエンド API クライアント

- 目的: relation 系 API の薄いラッパーを追加する。
- 対象ファイル候補:
  - `frontend/src/features/people/peopleApi.ts`（既存 `fetchPeople` 等と同列に関数追加。`apiGet/apiPost/apiPatch/apiDelete` 経由）。
  - `frontend/src/api/client.ts`（変更不要見込み。Bearer 付与は既存流用）。
- 具体的作業: 関係一覧・作成・更新・削除、タイプ一覧・作成・更新のラッパー関数追加。型定義は `frontend/src/features/people/types.ts` 系に倣う。
- 依存: P4。
- 完了条件: 全 relation API に対応するクライアント関数が存在する。
- 主なリスク: なし（薄いラッパー）。モック境界でのテスト方針は P11。
- 必要なテスト: フロントエンド単体テスト（モック境界許容。リポジトリ方針）。

## 11. P9 人物画面の関係セクション

- 目的: 人物画面内で関係の一覧・追加・編集・削除を提供する。
- 対象ファイル候補:
  - `frontend/src/features/people/PeoplePage.tsx`（親が状態所有。表示分割の規約に従う）。
  - `frontend/src/features/people/peopleApi.ts`（P8）。
- 具体的作業:
  - 人物詳細内に発信・受信を統合した関係一覧（状態フィルター付き）、追加・編集・削除 UI。
  - 対象人物は確定人物から選択。型は既存型選択またはユーザー定義型作成。
  - 自然言語表示で閲覧人物との位置関係に応じて forward / reverse label を使い分ける。
  - 人物削除確認に P5 の件数と Vault 再作成警告を表示する。
- 依存: P8（P5 の件数表示は P5 完了後）。
- 完了条件: 一覧・追加・編集・削除・フィルター・自然言語表示が手動確認できる。
- 主なリスク: PeoplePage の肥大化（既存分割規約に従い、表示コンポーネントは無状態化して親が統括する）。
- 必要なテスト: フロントエンド単体テスト＋手動確認（E2E は追加しない）。

## 12. P10 関係タイプ作成・編集 UI

- 目的: Relation Type の作成・編集・非活性化 UI を提供する。
- 対象ファイル候補: P9 と同じ。配置は P0 の決定に従う（人物画面内か管理画面か）。
- 具体的作業:
  - タイプ一覧・作成（slug・表示名・方向性・説明）・編集（表示名・説明のみ）・非活性化。
  - 使用中タイプの削除・非活性化後の新規作成・`directionality` 変更の抑止表示。
- 依存: P8、P0 の配置決定。
- 完了条件: タイプ CRUD が UI から操作でき、制約違反が明示される。
- 主なリスク: 配置決定の遅延（P0 で解消済みのはず）。
- 必要なテスト: P9 と同様。

## 13. P11 テスト

- 目的: relation 機能の品質担保と既存人物機能の回帰確認。
- 対象ファイル候補:
  - 新規: `tests/test_person_relations*.py`（API・サービス・統合・同期のいずれかに分割）。
  - 既存回帰: `tests/test_people_api.py`、`tests/test_sync_people.py`、`tests/test_people_loader.py`、`tests/test_people_manual_assignment.py`、`tests/test_summary_store.py`、`tests/test_agents_registry.py`。
  - フロント: `frontend/src/features/people/` の Vitest。
- 具体的作業:
  - DB 書き込みテストは `uv run pytest tests/` 経由で実行し、`docs/testing.md` の隔離規約を守る（本番 DB 厳禁、一時 DB 使用）。
  - API テスト、サービステスト、人物統合テスト、Vault 同期テスト、フロントエンドテスト、AI 非公開回帰テスト（`registry.py` に relation ツールが登録されていないこと、`people_get` 出力が変わらないこと）。
  - 既存人物関連テストを回帰テストとして実行する。
  - ロールバック／失敗時に部分移管を残さないこと（統合・削除の失敗系テスト）。
  - E2E は追加・実行しない。
- 依存: 各対応フェーズ。
- 完了条件: 新規テストが通り、既存人物関連テストが全件通る。
- 主なリスク: テスト DB 隔離違反（ガードに反したら即修正。中断しない）。

## 14. P12 ドキュメント・ADR 反映

- 目的: 決定記録と用語集へ反映する。本タスクでは行わない（実装フェーズの作業）。
- 対象ファイル候補:
  - `ai_wiki/10-Decisions-People.md`（関係する領域ファイルに決定記録を追加）。
  - `ai_wiki/30-Glossary.md`（relation / type / evidence / event の用語追加）。
  - `docs/person-relation/`（仕様の確定反映。必要時のみ）。
- 具体的作業: ADR 起票基準（`AGENTS.md`: 変更困難・横断影響等のうち2件以上）に該当する決定を記録する。候補: Vault 非連携、AI 非公開、正規方向1辺、統合時移管規則。
- 依存: P0–P11 の確定事項。
- 完了条件: 該当する決定が領域ファイルに記録される。
- 主なリスク: 既存 ADR の無断書き換え（追記のみ。既存節の上書き・削除はしない）。
- 必要なテスト: なし。

## 15. P13 リリース前確認

- 目的: 出荷可否の最終確認。
- 具体的作業:
  - `git diff --check`、`git status --short` で意図しない変更の混入を確認する。
  - 既存人物関連テストの最終実行。
  - 手動確認: 人物画面の関係セクション（一覧・追加・編集・削除・フィルター・自然言語表示）、人物削除確認の件数・警告、統合プレビューの関係影響表示。
  - v1 対象外項目（グラフ描画・イベント・Vault 書き戻し・AI 公開・汎用グラフ）を誤って実装・公開していないことを確認する。
- 依存: P11、P12。
- 完了条件: 全確認項目が満たされる。
- 主なリスク: スコープクリープ（対象外の混入）。チェックリストで抑止する。
- 必要なテスト: 既存人物関連テストの再実行。

## 16. 実装コミットの推奨分割

Git 操作は行わない。実装時に以下の単位でのコミットを推奨する。

1. `P1 migration`（3テーブル＋索引）。
2. `P2 schemas`（DTO 追加のみ）。
3. `P3 services`（type・relation・evidence＋共通関数）。
4. `P4 routes`（API 公開）。
5. `P5 delete`（削除連鎖＋件数）。
6. `P6 merge`（手動統合の移管＋プレビュー）。
7. `P7 sync`（Vault 同期の共通化接続）。
8. `P8–P10 frontend`（クライアント＋人物画面＋タイプ UI）。
9. `P11 tests`（各コミットに付随したテストを含む場合は分割不要）。
10. `P12 docs`（ADR・用語集反映）。

各コミット前に `git status --short` で対象外ファイルの混入を確認する。作業開始前から存在した未コミット変更には触れない。
