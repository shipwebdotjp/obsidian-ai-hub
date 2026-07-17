# JSONL生ログのSQLite移行計画

  ## Phase 1. Activity

  ## 概要

  既存の MEMORY_SQLITE_PATH にActivityイベント用テーブルを追加し、logging_activity の記録・重複判定、日次要約、研究コンテキストの読取をSQLiteへ一括切替する。月次・週次・年次の集計JSONLは今回維持し、別フェーズで移行する。

  ## 実装変更

  - memory.get_db_connection() のSQLiteスキーマを次版へ移行し、activity_logs テーブルを追加する。
      - activity_id、activity_date、occurred_at、app_name、window_title、summary、category、keywords（JSON）、screenshots（JSON）を保存する。
      - 旧データの冪等取込用に source_path と source_line を持たせ、その組合せを一意化する。通常記録では両者をNULLにする。
      - 日付＋時刻の索引を作り、日別一覧・直近レコード取得・直近N日取得を効率化する。

  - Activity専用の永続化モジュールを追加し、次の内部インターフェースを提供する。
      - Activityの追加、指定日の時刻順一覧、指定日の最新レコード、直近N日分の要約付きActivity一覧。
      - logging_activity.py はSQLiteで直近のアプリ名・ウィンドウタイトルを確認して既存どおり重複を抑止し、LLM処理後にSQLiteへ追加する。
      - summerize_day.load_activity_logs() と research.db.list_recent_activity_days() はこのモジュールを使用する。研究側の要約重複除去は現行どおり維持する。

  - scripts/migrate_activity_jsonl_to_sqlite.py を単発の移行スクリプトとして追加する。CLIフラグは追加しない。
      - ACTIVITY_PATH/YYYY/MM/YYYY-MM-DD.jsonl だけを対象に走査し、月次・週次・年次サマリーJSONLは除外する。
      - ファイル日付を activity_date に使い、既存のタイムスタンプ文字列と各フィールドを保存する。欠けたカテゴリ・キーワードは現行読取時と同じ既定値へ正規化する。
      - 1トランザクションで取り込み、source_path＋行番号の競合はスキップするため、安全に再実行できる。空行・不正JSON行は警告と件数に記録して他の行は継続する。
      - 実行結果として、走査ファイル数・追加件数・既取込スキップ数・不正行数を表示する。JSONLは削除・更新せず、読取専用アーカイブとして残す。
      - 実行方法は uv run python scripts/migrate_activity_jsonl_to_sqlite.py とする。

  ## テスト

  - 一時SQLite DBを使い、スキーマ作成、追加、日別時刻順取得、直近レコード取得、直近日数取得を確認する。
  - 旧JSONLの移行で全フィールド、既定値、不正行スキップ、再実行時の冪等性を確認する。
  - logging_activity の同一ActivityスキップとSQLite保存、日次要約と研究候補生成がSQLiteデータを利用することを確認する。
  - 既存の集計JSONL利用（週次・月次・ダッシュボード・Memory抽出）が変更されないことを既存テストで確認する。

  ## 前提

  - 新規Activityの保存先は既存のMemory/Researchと同じ MEMORY_SQLITE_PATH。
  - 今回の対象はActivityの生ログのみで、集計JSONLのSQLite化は次フェーズ。
  - 既存JSONLは移行後も保持するが、通常処理の読取・追記先には使用しない。


  # Phase 2: 構造化サマリーのSQLite化とAPIダッシュボード化

  ## 概要

  Phase 1のActivity生ログ移行が件数照合・通常実行ともに安定した後、日次・週次・月次の集計JSONLを共通SQLiteスキーマへ一括移行する。既存JSONLはアーカイブとして残し、生成・読取・Memory・ダッシュボードを同じリリースでSQLiteへ切り替える。

  ## データモデルと要約生成

  - summaries を日・週・月共通テーブルにする。period_type、period_key、期間開始・終了、生成日時、summary、生の文字列配列としてのkeywordsを保存し、(period_type, period_key) を一意にする。
  - 日次だけ mood、sleep_raw、sleep_hours を持つ。週・月の気分分布と睡眠min/avg/maxは、日次データから集計APIが算出する。
  - summary_items に kind、本文、表示順を保存する。
      - 日次: highlights / activities / learnings / reflections / gratitude
      - 週次: highlights / progress / learnings / reflections / patterns / gratitude
      - 月次: highlights / progress / changes / learnings / reflections / patterns / gratitude
      - reflectionsは「自己の行動・思考・改善点に関する観察」に限定する。

  - topics、projects、people、open_loops と各 summary_* 関連テーブルを追加する。Unicode正規化・トリム・大小文字無視で自動統合し、初出表記を表示名として残す。
      - topicsは既存のTOPIC_ENUMのみ許容する。
      - peopleの要約固有メモはsummary_peopleに保存する。
      - questions / next_actionsはopen_loopsに関連付け、関係側で元の種別と表示順を保持する。状態管理は行わない。

  - 日・週・月のプロンプト、JSON解析、Markdownレンダリングを新スキーマに更新する。各期間は指定された項目だけを生成・表示し、旧source_statsは保存しない。
  - 日次→週次→月次の読取連鎖とMemoryの構造化日次レコード読取を、共通サマリーストア経由へ切り替える。

  ## 移行と切替

  - scripts/migrate_summary_jsonl_to_sqlite.py を単発スクリプトとして追加し、日次・週次・月次の既存JSONLを走査する。CLIフラグは追加しない。
  - 既存項目は対応する新テーブルへ移し、存在しない新項目は空として扱う。旧週次・月次のactivitiesはprogressへ移す。
  - 不正JSON行は警告・件数報告のうえ除外して継続する。同じ期間キーの複数正常行は最後の行を採用する。
  - 期間キーによるupsertで再実行可能にし、投入数・更新数・不正行数・重複件数を出力する。JSONLは更新・削除しない。
  - SQLiteへの切替後、dashboard.py、--build-dashboard、静的HTML/年別JSON出力、不要になったDashboard設定を削除する。

  ## APIとReactダッシュボード

  - 既存の認証済み /api/v1 に読み取り専用APIを追加する。
      - GET /summaries: 期間種別、期間、topic、project、person、open loopで絞り込む一覧。
      - GET /summaries/{summary_id}: items・正規化エンティティ・関連メモを含む詳細。
      - GET /summary-options: 絞込候補。
      - GET /summary-dashboard: 同じフィルタに対する件数、エンティティ頻度、項目種別集計、日次睡眠min/avg/max、気分分布、時系列データ。

  - Pydanticレスポンス型とサービス層を追加し、既存のループバック／Bearerトークン認証をそのまま適用する。
  - React SPAにDashboardルートとサイドバー項目を追加する。概要、フィルタ可能な一覧、詳細ビューを提供し、SQLite APIだけを読取元にする。

  ## 検証

  - 一時SQLite DBで、3期間のupsert・期間読取・関連エンティティ統合・表示順・日次睡眠集計を検証する。
  - 移行スクリプトの項目マッピング、不正行スキップ、重複期間の最終行優先、再実行安全性を検証する。
  - 日→週→月の生成連鎖、Memory入力、Markdown出力、APIフィルタ・集計、Reactの概要／一覧／詳細を最低限検証する。
  - 移行前後で期間別レコード数と主要項目を照合し、旧JSONLアーカイブから復元可能なことを確認してから静的ダッシュボードを廃止する。