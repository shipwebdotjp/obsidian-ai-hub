# 人物間リレーション v1 仕様書

関連文書: [実装計画](implementation-plan.md) / [作業チェックリスト](todo.md)

本書は仕様（何を作るか）を定める。実装順序・作業手順は実装計画に、進捗管理は作業チェックリストに記載し、本書には書かない。
いずれも概念仕様であり、コード実装済みであるかのように読まないこと。実装開始時に現行コードと再照合すること。

## 1. 目的とスコープ

- 人物DB上で、人物間の継続的な関係（例: 親子、雇用、援助、敵対）を管理できるようにする。
- Vault は従来どおり人物同定の入力・ヒントであり、人物間関係の正本にはしない。既存決定「Vaultは同定ヒント、DBは確定結果を保持する」（`ai_wiki/10-Decisions-People.md`）を継承する。
- 関係はDB専用とし、Vault同期・Vault編集によって上書きされない。`people_sync/sync.py:sync_people_in_tx()` は関係に触れない。
- v1 は Web UI の CRUD と人物画面での表示までを範囲とする。
- v1 に含めないもの: グラフ描画、人物イベント（Person Event / Action）、Vault への書き戻し、AI 公開（詳細は「11. v1対象外」）。

## 2. 用語と概念

本書では以下を厳密に区別する。混同しないこと。

- **Relation Type（関係タイプ）**: 関係の意味・方向性・表示名を定義する台帳レコード。例: 「親である／子である」。方向性（`directed` / `symmetric`）、正方向表示名（forward label）、逆方向表示名（reverse label）を持つ。人物同士を結ぶ辺そのものではない。
- **Person Relation（人物間リレーション本体）**: 特定の2人物間で、ある Relation Type が採用されているという継続的な状態・構造についての主張。両端点・型・期間・メモを持つ。単発の出来事ではない。
- **Relation Evidence（根拠）**: 関係を採用した根拠のレコード。関係1件につき0件以上。例: サマリの記述、日付つきメモ。「なぜそう判断したか」を保持し、手入力操作の監査情報（いつ誰が登録したか）とは別物として扱う。
- **Person Event / Action**: ある時点または期間に発生した単発の出来事・行為（例: 「援助した」）。継続状態である Person Relation（例: 「援助している」）とは別概念。v1 対象外であり、本書では将来の分離点だけを定める。
- **Episode**: 既存 memory 領域の長期記憶種別（`preference / decision_policy / fact / commitment / pattern / episode` の1つ）。ユーザー中心の記憶であり、人物グラフの正本ではない。`episode` を人物間リレーションの格納場所として流用しない。

## 3. 関係タイプ

### 3.1 組み込み型とユーザー定義型

- システムが初期提供する組み込み型（`is_builtin=true`）と、利用者が後から作成するユーザー定義型（`is_builtin=false`）を許容する。
- 初期組み込み型の具体的なセットは未確定（「12. 未確定事項」参照）。候補: 親子、雇用、援助、敵対、対称型1件。

### 3.2 識別子と表示

- 各タイプは不変 ID（`relation_type_id`、例: `rlt_xxx`）と一意な slug（例: `parent-child`）を持つ。slug は作成後不変を推奨（未確定事項参照）。
- `directed`（有向）と `symmetric`（対称）を扱う。方向性は `directionality` 列で保持する。
- 正方向表示名（forward label）と逆方向表示名（reverse label）を持つ。
  - directed の例: 正方向「親である」／逆方向「子である」、正方向「雇っている」／逆方向「雇われている」、正方向「援助している」／逆方向「援助されている」。
  - symmetric の例: 「仲が悪い」／「仲が悪い」（両方向同一）。
- 表示名と説明は変更可能とする。

### 3.3 ライフサイクル

- 使用中タイプ（少なくとも1件の Person Relation が参照）は削除不可とする。
- 非活性化されたタイプ（`is_active=false`）は、既存関係の表示には使えるが、新規作成には使えない。
- `directionality` は使用開始後（参照する関係が1件でも存在する状態）に変更不可とする。未使用の間は変更可能とするかは実装時に定める。
- 表記類似だけで型を自動統合しない。別 slug の型の統合は v1 対象外の手動操作とし、自動マージ機能は作らない。

## 4. 関係の方向

- directed 型は、型で定義した正規方向の1辺だけを保存する。例: 「親である」型では常に親→子の向きで保存する。
- 逆方向の DB レコードを自動生成しない。逆辺の自動生成・自動同期は行わない。
- 逆側人物の画面では reverse label を使って表示する（例: 子の画面では「○○の子である」と表示）。表示時の反転であり、DB には1辺のみ存在する。
- symmetric 型は、人物 ID など決定的な規則で端点を正規化して保存する（例: `subject_person_id < object_person_id` の辞書順）。規則は共通サービス関数に集約し、作成・更新・統合の全経路で同一規則を使う。
- 自己関係（両端点が同一人物）は登録不可とする。作成・更新 API で拒否し、人物統合で自己関係化する場合も拒否する（「7. 人物統合」参照）。

## 5. 関係の期間

- `started_on`、`ended_on` は任意（NULL 許容）とする。
- v1 は厳密な `YYYY-MM-DD` または NULL だけを許容する。
- 年月だけ、年だけ、概算日（「90年代頃」等）は、偽の日付に補完せず v1 対象外とする。入力 UI では完全な日付か空欄かのいずれかのみ受け付ける。
- 開始日は終了日以前でなければならない（`started_on <= ended_on`、いずれか NULL の場合は検証対象外）。
- 境界日は期間に含む（`started_on <= today <= ended_on` は有効）。
- 状態を次の4値として共通規則で判定する。判定はサービス層の共通関数に集約する。
  - `upcoming`: 開始日が未来（`started_on > today`）。
  - `active`: 今日が期間内（開始日なし／開始日≦今日 かつ 終了日なし／今日≦終了日）。
  - `ended`: 終了日が過去（`ended_on < today`）。
  - `undated`: 開始・終了とも不明（両方 NULL）。
- 開始・終了とも不明なものを自動的に active と断定しない。`undated` として区別し、一覧の既定表示に含めるかは未確定事項とする。

## 6. 重複規則

### 6.1 意味的重複の定義

意味的重複は、正規化後の以下5要素が一致する関係とする。

- relation type（`relation_type_id`）
- subject person（端点正規化後）
- object person（端点正規化後）
- `started_on`（NULL は NULL 同士で一致）
- `ended_on`（同上）

表示ラベル・メモ・根拠の差異は重複判定に使わない。ラベルは型の表示名に従属するため、重複判定のキーに含めない。

### 6.2 ルール

- 同じ期間なら関係本体は1件とする。2件目は作成せず、根拠は既存関係へ追加する。
- 異なるメモは失わず統合する（統合フォーマットは未確定事項参照）。
- 期間が異なる場合は別関係として許容する（例: 雇用期間が2回ある場合）。
- 作成 API は結果が `created`（新規作成）か `merged_into_existing`（既存へ統合）かを返す（HTTP ステータスの表現は未確定事項参照）。
- 無制限な多重辺にはしない。上記定義外の重複（同一5要素の2件目）は作れない。

## 7. 人物統合

現行の人物統合（`web/services/people_merge.py:merge_people()`、プレビュー `verify_people_merge()`）に、関係移管を組み込む。

- 人物統合と関係移管は同一トランザクションで行う。関係だけが移管されずに残る、または人物だけが消えて関係が孤立する中間状態を作らない。
- 手動統合（`POST /api/v1/people/merge`）と Vault 同期による自動統合（`people_sync/sync.py:sync_people_in_tx()` 内の吸収・統合）は、同じ共通規則（共通サービス関数）を利用し、二重実装しない。
- 統合によって自己関係化する関係が生じる場合、関係を自動削除せず、人物統合全体を拒否する。既存の第三者衝突拒否（`verify_people_merge()` の衝突検査）と同列の扱いとする。
- 統合プレビューに、自己関係化する関係と重複統合される関係の影響を表示する。プレビュー項目: 対象関係の件数・相手人物・型・期間、自己関係化で拒否される場合はその旨。
- 第三者との意味的重複が生じる場合（統合元の辺の移管先に、統合先が既に同一5要素の辺を持つ場合）、統合先側の relation ID を存続させ、根拠とメモを移管先へ移す。移管元の辺は残さない。
- 期間が異なる関係は両方残す（重複定義の期間不一致に該当するため）。

## 8. 削除

- 人物削除（`web/services/people.py:delete_person()`）では、関連する関係と根拠を連鎖削除する。発信辺（subject 側）と受信辺（object 側）の双方を対象とする。既存の `ON DELETE CASCADE` 方針（人物系 FK は全て CASCADE）と整合させる。
- 人物削除確認・レスポンスに、発信関係数・受信関係数と根拠数を含める。既存 `PersonDeleteResponse`（`web/schemas.py`）の `deleted_summary_people / deleted_aliases / deleted_assignments` に倣い、関係・根拠の削除件数を追加する。
- Vault 連携人物は、再同期で人物が再作成されても削除した関係は復元されない旨を、削除確認 UI で警告する。現行の「Vaultノートは残るため次回同期で再作成され得る」警告と同位置に表示する。
- 関係単体は v1 では物理削除とする。論理削除フラグは持たない。
- v1 では変更履歴・削除監査を保存しないことを制約として明記する。将来の `relation_events` 的な履歴は v1 対象外。
- 関係タイプは原則非活性化で運用し、使用中タイプの削除は禁止する（3.3 参照）。

## 9. API / UI / AI 境界

### 9.1 推奨 API（仕様）

```text
GET    /api/v1/people/{person_id}/relations
POST   /api/v1/people/{person_id}/relations
PATCH  /api/v1/person-relations/{relation_id}
DELETE /api/v1/person-relations/{relation_id}

GET    /api/v1/person-relation-types
POST   /api/v1/person-relation-types
PATCH  /api/v1/person-relation-types/{relation_type_id}
```

- 関係タイプの削除・非活性化の表現（`DELETE` とするか `PATCH is_active=false` のみとするか）は実装計画で確定する。本仕様では「使用中タイプの削除は禁止」「原則非活性化」のみを制約とする。
- 既存人物詳細 DTO（`PersonDetail`）には関係を追加せず、relation 専用 API を使う。人物詳細の肥大化と `people_get` への波及を避ける。
- 既存 `people_get`（`agents/registry.py`）の出力は変更しない。
- relation 用 AI ツールを登録しない。`agents/registry.py:_BUILTIN_TOOL_DEFINITIONS` に追加しないことをテストで保証する。
- API は既存 Bearer 認証（`web/routes/deps.py:require_bearer_token`）で保護する。無認証の relation API は作らない。
- Web API スキーマと AI ツールスキーマを共用しない。relation の Pydantic スキーマを AI ツール入力に転用しない。
- UI は人物画面内（`frontend/src/features/people/PeoplePage.tsx`）で一覧・追加・編集・削除を提供する。独立ページは作らない。
- 対象人物は既存の確定人物（`people` テーブル）から選択する。未解決候補（`person_candidates`）を関係端点には選べない。
- 型は既存型の選択またはユーザー定義型の作成が可能とする。作成・編集の配置（人物画面内か管理画面か）は未確定事項とする。
- 自然言語表示では、閲覧人物との位置関係に応じて forward / reverse label を使う。例: A の画面で A→B「雇っている」は「B を雇っている」、B の画面では「A に雇われている」と表示する。
- 全期間を表示可能とし、状態（`upcoming / active / ended / undated`）で絞り込み可能にする。既定フィルターは未確定事項とする。

## 10. 推奨論理データモデル

以下は実マイグレーションではなく、仕様上のカラム・制約・インデックス案である。SQL を載せる場合は概念案であり、実装時に現行 migration 規約（`database.py:get_db_connection()` 内の `PRAGMA user_version` 連鎖、`CREATE TABLE IF NOT EXISTS` + `ALTER` ガード方式）へ合わせて確定する。

### 10.1 `person_relation_types`（関係タイプ台帳）

- `relation_type_id TEXT PRIMARY KEY`: 安定 ID（例: `rlt_xxx`、UUID hex 方式。人物 ID `peo_xxx` の採番規則に倣う）。
- `slug TEXT NOT NULL UNIQUE`: 機械キー（例: `parent-child`）。作成後不変を推奨。
- `forward_label TEXT NOT NULL`: 正方向表示名（例: 「親である」）。
- `reverse_label TEXT NOT NULL`: 逆方向表示名（例: 「子である」）。symmetric 型では forward と同一値を許容する。
- `directionality TEXT NOT NULL`: `directed` または `symmetric`。使用開始後の変更不可。
- `description TEXT NULL`: 説明文。変更可能。
- `is_builtin INTEGER NOT NULL DEFAULT 0`: 組み込み型か。
- `is_active INTEGER NOT NULL DEFAULT 1`: 非活性は新規作成不可、既存表示は可。
- `created_at TEXT NOT NULL` / `updated_at TEXT NOT NULL`: 日時文字列（既存 `projects` 等の `created_at/updated_at TEXT` パターンに倣う）。人物系テーブルには本列がないため、relation 系では新規に持つ。
- FK なし（独立台帳）。`ON DELETE` 該当なし。使用中タイプの削除禁止はサービス層で保証する。

### 10.2 `person_relations`（関係本体）

- `relation_id TEXT PRIMARY KEY`: 安定 ID（例: `rel_xxx`）。将来の参照（履歴・イベント）に備える。
- `subject_person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE`
- `object_person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE`
- `relation_type_id TEXT NOT NULL REFERENCES person_relation_types(relation_type_id) ON DELETE RESTRICT`（使用中タイプ削除禁止に対応。SQLite の `RESTRICT` はサービス層でも二重検査する）。
- `started_on TEXT NULL`: `YYYY-MM-DD` または NULL。
- `ended_on TEXT NULL`: 同上。
- `note TEXT NULL`: メモ。重複統合時は失わず統合する。
- `created_at TEXT NOT NULL` / `updated_at TEXT NOT NULL`: トランザクション時刻（transaction time）。期間（valid time）と区別する。
- 制約（概念）: `subject != object`（自己関係禁止）、`started_on <= ended_on`（NULL 除外）。
- 一意インデックス（意味的重複防止）: `(relation_type_id, subject_person_id, object_person_id, started_on, ended_on)`。NULL 含有時の扱いは「実装時の注意」参照。
- 検索用インデックス: `(subject_person_id)`、`(object_person_id)`、`(relation_type_id)` を含む複合。人物画面の発信・受信一覧、型使用中判定に使う。

### 10.3 `person_relation_evidence`（根拠）

- `evidence_id TEXT PRIMARY KEY`: 安定 ID（例: `rle_xxx`）。
- `relation_id TEXT NOT NULL REFERENCES person_relations(relation_id) ON DELETE CASCADE`
- `source_type TEXT NOT NULL`: 由来源（例: `manual`）。初期 allowlist は未確定事項とする。
- `source_ref TEXT NULL`: 参照先（例: 将来の `summary_id`）。v1 では NULL 許容の自由記述参照とし、FK は張らない。
- `quote TEXT NULL`: 引用文。
- `note TEXT NULL`: 補足メモ。
- `observed_at TEXT NULL`: 事実の観測日（`YYYY-MM-DD` または日時文字列。形式は実装時に確定）。
- `created_at TEXT NOT NULL` / `updated_at TEXT NOT NULL`: 手入力操作の監査時刻。事実の根拠（`observed_at`）と混同しない。
- インデックス: `(relation_id)`。
- `confidence` は v1 必須ではなく将来拡張とする。列自体を持たせるかも実装時に確定する。

### 10.4 実装時の注意（SQLite 制約）

- SQLite の UNIQUE 制約は NULL を相異なる値として扱うため、`(…, started_on, ended_on)` の素朴な UNIQUE では「期間 NULL 同士の重複」を防げない。対策候補: 正規化列（空文字代替）の併用、式インデックス、サービス層での事前検査（既存 `verify_people_merge()` の衝突検査パターン）。いずれを採用するかは実装時に確定し、本書の重複定義は変えない。
- SQLite の式インデックスは利用可能だが、バージョン・マイグレーション規約との相性を確認する。
- テーブル横断 CHECK（例: タイプの方向性に応じた端点順序）は SQLite では書けないため、端点正規化・方向検証は共通サービス関数で保証する。
- `ON DELETE RESTRICT` の実効は SQLite でも有効だが、既存コードは人物系 FK を全て CASCADE で統一しているため、サービス層の使用中判定を主、FK を従として二重に保証する。

## 11. v1対象外

以下は v1 に含めない。実装中に混入させないこと。

- グラフ描画（可視化 UI）。
- 多段グラフ探索最適化（再帰クエリ・専用索引・グラフ DB 化）。
- Person Event / Action モデル（単発出来事のテーブル化）。
- relation と event の自動導出（行為→状態、状態→行為の推論）。
- 型階層、推移性、排他制約、関係推論（例: 親の親は祖父母）。
- 部分日付、概算日（年月・年・「頃」）。
- 完全な変更履歴・削除監査。
- Vault への書き戻し（人物ノートへの関係投影）。
- AI 公開（relation 用ツール、LLM による自動抽出、`people_get` への関係付与）。
- 人物以外（プロジェクト・トピック等）を含む汎用グラフ。

## 12. 確定事項（旧未確定事項）

本仕様の設計決定事項および確定内容（Phase 1〜4で全決定済み）。

### 12.1 初期設計決定事項

- **初期組み込み型セット**: 計25件の組み込み型（`rlt_builtin_<slug>`）をマイグレーション v38 で自動投入済み（家族・親族6件、仕事・組織8件、教育・指導4件、社交・友人4件、援助・取引3件）。
- **`source_type` の初期 allowlist**: v1 では手動入力 `manual` のみを許可し、Pydantic / DB CHECK 制約で検証・固定。
- **重複統合時のレスポンス表現**: 新規作成時は `HTTP 201 Created`（`action="created"`）、意味的重複統合時は `HTTP 200 OK`（`action="merged_into_existing"`）を返却。自己関係化や非活性型使用は `HTTP 409 Conflict` で拒否。
- **関係タイプ作成・編集 UI の配置**: 人物画面（`PeoplePage`）内の専用タブ「関係タイプ」として統合配置。

### 12.2 実装確定事項

- **重複時の note 統合フォーマット**: 改行連結（`\n`）を採用（既存 `consolidate_summary_links()` パターンを共通継承）。
- **関係一覧の既定フィルター**: 全件表示（`status` クエリ非指定時）とし、UI 上で `upcoming` / `active` / `ended` / `undated` のタブ切り替えフィルタを提供。
- **型 slug の変更可否**: `slug` は作成後不変（Immutable）。更新 API では `forward_label`, `reverse_label`, `description`, `is_active` のみ更新可。
- **期間基準日**: 日本標準時（Asia/Tokyo JST）の本日日付を基準に `upcoming / active / ended / undated` を動的算出。
