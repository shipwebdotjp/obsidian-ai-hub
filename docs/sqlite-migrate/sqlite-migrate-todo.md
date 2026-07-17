# SQLite移行 TODO

対象計画: [sqlite-migrate-plan.md](sqlite-migrate-plan.md)

## 計画の検証結果

- [x] Phase 1の対象は現行実装と一致する。Activity生ログは
  `logging_activity.py` が日別JSONLへ書き、日次要約と研究テーマ提案が直接読む。
- [x] Phase 2の対象は現行実装と一致する。日次・週次・月次サマリーはそれぞれJSONLへ
  upsertされ、日→週→月の連鎖、`memory.py`、静的ダッシュボードが読む。
- [x] ダッシュボードの現状はReact SPAではなく、`dashboard.py` と
  `--build-dashboard` による静的HTML/JSON生成である。Phase 2ではCLI、設定、関連テストも
  削除または置換する必要がある。
- [ ] Phase 1・Phase 2とも未実装。以下のチェック完了まで、JSONLを通常処理から削除しない。

## Phase 1 — Activity生ログ

### スキーマとストア

- [ ] `MEMORY_SQLITE_PATH` のマイグレーションに `activity_logs` を追加する。
  - `activity_id`、`activity_date`、`occurred_at`、アプリ・ウィンドウ情報、要約、カテゴリ、
    keywords JSON、screenshots JSONを保存する。
  - 旧JSONL取込用の相対`source_path`と`source_line`を保存し、その組合せを一意にする。
  - 日付・時刻順の一覧、日別最新、直近N日の読取に必要な索引を作る。
- [ ] Activity永続化モジュールを追加し、追加・日別一覧・日別最新・直近日数一覧を提供する。

### 呼出元の切替

- [ ] `logging_activity.py` の重複判定と記録先をSQLiteへ切り替える。
- [ ] `summerize_day.load_activity_logs()` をSQLite読取へ切り替える。
- [ ] `research.db.list_recent_activity_days()` をSQLite読取へ切り替え、既存の要約重複除去を維持する。

### 旧データ移行と検証

- [ ] `scripts/migrate_activity_jsonl_to_sqlite.py` を追加する。日別の
  `YYYY-MM-DD.jsonl` のみを走査し、集計JSONLは除外する。
- [ ] 取込を再実行可能にし、追加・既取込・不正JSONの件数を表示する。不正行は警告して継続する。
- [ ] JSONLとSQLiteの件数・代表レコードを照合し、JSONLを読み取り専用アーカイブとして残す。
- [ ] 一時DBを使うユニットテストで、順序、重複判定、既定値、移行の冪等性を確認する。

## Phase 2 — 構造化サマリーとダッシュボード

### 共通サマリースキーマ

- [ ] `summaries` を追加する。`period_type`（day/week/month）と`period_key`を一意にし、
  期間開始・終了、生成日時、summary、keywordsの生文字列配列を保存する。
- [ ] 日次のみに`mood`、`sleep_raw`、`sleep_hours`を保存する。
  - `sleep_hours` は数値として解釈できる値だけを保存し、解釈不能な値はNULLにする。
  - 週・月の睡眠min/avg/maxと気分分布は、日次データを集計して返す。
- [ ] `summary_items` を追加する。`summary_id`、`kind`、本文、表示順を保存する。
  - day: highlights, activities, learnings, reflections, gratitude
  - week: highlights, progress, learnings, reflections, patterns, gratitude
  - month: highlights, progress, changes, learnings, reflections, patterns, gratitude
- [ ] `topics`、`projects`、`people`、`open_loops` と各関連テーブルを追加する。
  - 表記はUnicode正規化・トリム・大小文字無視で統合し、初出表記を表示名にする。
  - topicsは`TOPIC_ENUM`の候補だけを保存する。
  - `summary_people`には要約ごとのnote、`summary_open_loops`にはquestions / next_actionsの種別と表示順を保存する。
  - open loopの完了状態は管理しない。

### 生成・読取の切替

- [ ] 日・週・月のプロンプトを新しい期間別JSONスキーマへ更新する。
  - reflectionsは自己の行動・思考・改善点に関する観察に限定する。
  - highlightsは重要な出来事・成果・決定、progressは目標・プロジェクトの前進、patternsは繰返し・傾向・相関、changesは前月からの変化として扱う。
- [ ] 各要約器のJSON解析、SQLite upsert、Markdownレンダリングを新スキーマへ切り替える。
- [ ] 週次は日次SQLiteレコード、月次は週次SQLiteレコードを入力にする。
- [ ] `memory.py` の構造化日次レコード読取をSQLiteへ切り替える。
- [ ] 旧`source_stats`は移行・新規保存ともに保持しない。

### サマリーJSONL移行

- [ ] `scripts/migrate_summary_jsonl_to_sqlite.py` を追加する。日次、週次、月次の集計JSONLを走査する。
- [ ] 旧週次・月次の`activities`を`summary_items.kind=progress`へ移す。旧データに存在しない新規項目は空にする。
- [ ] 不正JSON行は警告・件数報告のうえスキップする。
- [ ] 同じ期間キーの複数正常行は最後の行を採用し、重複件数を報告する。
- [ ] 期間キーupsertによって安全に再実行できるようにする。旧サマリーJSONLはアーカイブとして残す。

### APIとReactダッシュボード

- [ ] 読み取り専用の`/api/v1/summaries`一覧・`/api/v1/summaries/{summary_id}`詳細を追加する。
  期間、topic、project、person、open loopで絞り込めるようにする。
- [ ] `/api/v1/summary-options` と `/api/v1/summary-dashboard` を追加する。
  後者は同じフィルタに対し、要約数、エンティティ頻度、項目種別、睡眠min/avg/max、気分分布、時系列を返す。
- [ ] Pydanticスキーマ、サービス層、APIクライアント型を追加し、既存のループバック／Bearer認証を再利用する。
- [ ] React SPAにDashboardルートとサイドバー項目を追加する。
  概要、フィルタ可能な一覧、要約詳細を実装する。
- [ ] 静的`dashboard.py`、`--build-dashboard`、`--dashboard-year`、Dashboard設定、静的ダッシュボードテストを削除または新API/Reactテストへ置換する。

## 完了条件

- [ ] すべてのDB書込みテストが一時SQLite DBだけを使う。
- [ ] 各移行スクリプトは本番DBに対して一度だけ実行し、出力件数を旧JSONLと照合する。
- [ ] Activityの定期記録、日次・週次・月次要約、Memory抽出がJSONL読取なしで正常に動く。
- [ ] APIは認証規則、フィルタ、詳細、集計をテストで確認する。
- [ ] Reactダッシュボードで概要・一覧・詳細を確認し、旧静的ダッシュボードを削除する。
- [ ] `uv run pytest tests/` が成功する。
