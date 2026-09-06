# 人物間リレーション v1 作業チェックリスト

関連文書: [仕様書](specification.md) / [実装計画](implementation-plan.md)

上から順に進める。仕様の定義は仕様書に、実装順序の詳細は実装計画に記載し、本書は進捗管理に使う。
文書作成作業そのものは本書に記録しない。今後の実装作業のみを未チェックで記載する。

## P0: 実装開始前の意思決定

- [ ] 初期組み込み型セットを決定する（仕様書 3.1、12.1／計画 P0）
- [ ] `source_type` の初期 allowlist を決定する（仕様書 10.3、12.1／計画 P0）
- [ ] 重複統合レスポンスの HTTP 表現（200/201/409）を決定する（仕様書 6.2、12.1／計画 P0）
- [ ] 関係タイプ作成・編集 UI の配置（人物画面内か管理画面か）を決定する（仕様書 12.1／計画 P0・P10）

## P1: DB とバックエンド基盤

- [ ] migration 番号を実装時点で再確認する（現行最新 37。`src/obsidian_ai_hub/database.py`／計画 P1）
- [ ] `person_relation_types` テーブルを作成する（仕様書 10.1／計画 P1）
- [ ] `person_relations` テーブルを作成する（仕様書 10.2／計画 P1）
- [ ] `person_relation_evidence` テーブルを作成する（仕様書 10.3／計画 P1）
- [ ] 制約・インデックス（一意・検索用）を作成する（仕様書 10.2、10.4／計画 P1）
- [ ] 型 CRUD のスキーマ・DTO を追加する（`src/obsidian_ai_hub/web/schemas.py`／計画 P2）
- [ ] 関係・根拠 CRUD のスキーマ・DTO を追加する（`src/obsidian_ai_hub/web/schemas.py`／計画 P2）

## P2: CRUD API

- [ ] 型 CRUD のサービス層を実装する（新規 `web/services/person_relations.py` 想定／計画 P3）
- [ ] 関係 CRUD のサービス層を実装する（計画 P3）
- [ ] evidence 処理（追加・移管・連鎖削除）を実装する（仕様書 6.2、10.3／計画 P3）
- [ ] 日付検証（形式・開始≦終了・境界含む）と状態判定を実装する（仕様書 5／計画 P3）
- [ ] 正規方向変換（directed）を共通関数に集約する（仕様書 4／計画 P3）
- [ ] symmetric 端点正規化を共通関数に集約する（仕様書 4／計画 P3）
- [ ] 重複統合（`created` / `merged_into_existing`）を実装する（仕様書 6／計画 P3）
- [ ] relation 系 API ルートを公開する（`web/routes/people.py` または新規ルート＋`web/api.py`／計画 P4）

## P3: 削除・統合・Vault 同期

- [ ] 人物削除の連鎖削除と影響件数（発信・受信・根拠数）を追加する（`web/services/people.py:delete_person`／仕様書 8／計画 P5）
- [ ] 統合プレビューに自己関係化・重複統合の影響を表示する（`web/services/people_merge.py:verify_people_merge`／仕様書 7／計画 P6）
- [ ] 手動統合の relation 移管を同一トランザクションで実装する（`web/services/people_merge.py:merge_people`／仕様書 7／計画 P6）
- [ ] 自己関係化する統合を拒否する（プレビュー＋実行直前の再検証）（仕様書 7／計画 P6）
- [ ] 第三者重複統合（統合先 ID 存続＋根拠・メモ移管）を実装する（仕様書 7／計画 P6）
- [ ] Vault 同期の自動統合を共通処理へ接続し二重実装を避ける（`people_sync/sync.py:sync_people_in_tx`／仕様書 7／計画 P7）

## P4: フロントエンド

- [ ] フロント API クライアントに関係・タイプ関数を追加する（`frontend/src/features/people/peopleApi.ts`／計画 P8）
- [ ] 人物画面に関係一覧・作成・編集・削除を追加する（`frontend/src/features/people/PeoplePage.tsx`／計画 P9）
- [ ] forward/reverse 自然言語表示を実装する（仕様書 9.1／計画 P9）
- [ ] 状態フィルター（`upcoming/active/ended/undated`）を実装する（仕様書 5、9.1／計画 P9）
- [ ] 関係タイプ作成・編集 UI を実装する（仕様書 12.1 の配置決定に従う／計画 P10）

## P5: テストと品質保証

- [ ] API テストを追加する（計画 P11）
- [ ] サービステストを追加する（計画 P11）
- [ ] 人物統合テスト（移管・拒否・重複統合・両残し）を追加する（計画 P11）
- [ ] Vault 同期テスト（自動統合時の移管）を追加する（`tests/test_sync_people.py` 系／計画 P11）
- [ ] フロントエンドテストを追加する（モック境界許容、E2E は追加しない）（計画 P11）
- [ ] AI 非公開回帰テストを追加する（`agents/registry.py` 未登録、`people_get` 不変）（計画 P11）
- [ ] 既存人物関連テストを回帰実行する（`tests/test_people_api.py`、`tests/test_sync_people.py`、`tests/test_people_loader.py`、`tests/test_people_manual_assignment.py`、`tests/test_summary_store.py`、`tests/test_agents_registry.py`）（計画 P11）
- [ ] ロールバック／失敗時に部分移管を残さないことを確認する（計画 P11）

## P6: ドキュメントとリリース確認

- [ ] ADR を更新する（`ai_wiki/10-Decisions-People.md` に追記。既存節の上書き・削除なし）（計画 P12）
- [ ] 用語集を更新する（`ai_wiki/30-Glossary.md`）（計画 P12）
- [ ] 手動確認する（関係セクション、削除確認、統合プレビュー）（計画 P13）
- [ ] v1 対象外項目を誤って実装していないことを確認する（グラフ描画・イベント・Vault 書き戻し・AI 公開・汎用グラフ）（仕様書 11／計画 P13）

## Deferred / v1 対象外

実装しない。混入防止のための確認用リスト。

- [ ] グラフ描画を実装しない（仕様書 11）
- [ ] 多段グラフ探索最適化を実装しない（仕様書 11）
- [ ] Person Event / Action モデルを実装しない（仕様書 11）
- [ ] relation と event の自動導出を実装しない（仕様書 11）
- [ ] 型階層・推移性・排他制約・関係推論を実装しない（仕様書 11）
- [ ] 部分日付・概算日を実装しない（仕様書 11）
- [ ] 完全な変更履歴・削除監査を実装しない（仕様書 11）
- [ ] Vault への書き戻しを実装しない（仕様書 11）
- [ ] AI 公開を実装しない（仕様書 11）
- [ ] 人物以外を含む汎用グラフを実装しない（仕様書 11）
