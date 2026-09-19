# Apple Health Export インポート（現行仕様と将来拡張）

`src/obsidian_ai_hub/healthcare/store.py` が参照する schema v1 の仕様メモ。実装の詳細（DDL・
パイプライン・テスト）はコードと Git 履歴を正とする。決定理由は
`ai_wiki/10-Decisions-Integrations.md`「ヘルスケア: Apple Health export の分離DB・全種raw保存」を参照。

## 合意事項

- **分離DB**: `memory.sqlite3` とは別に `healthcare.sqlite3` を新設し、`PRAGMA user_version` を独立管理する
  （v1 起点）。`ENV=test` では `TEST_WORKSPACE/healthcare.sqlite3` に隔離する。
- **全種 raw 保存**: HealthKit の全 Record type を正規化せず保存する。将来の集計は VIEW / 追加テーブルで対応。
- **ECG サンプルは DB 非格納**: `electrocardiograms/*.csv` はメタのみ DB に持ち、波形は `file_path` から
  `read_ecg_samples()` で都度読む。

## 設定

- `HEALTHCARE_SQLITE_PATH` / `HEALTHCARE_EXPORT_DIR` / `HEALTHCARE_IMPORT_STAGING_DIR`
  （env または `config.yml: healthcare.*`）。既定は `~/.config/obsidian-ai-hub/healthcare.sqlite3`、
  `~/.config/obsidian-ai-hub/healthcare/apple_health_export`、
  `~/.config/obsidian-ai-hub/healthcare/staging`。
- CLI: `python -m obsidian_ai_hub --import-apple-health`
  （`--healthcare-export-dir` / `--healthcare-batch-size` / `--healthcare-dry-run`）。
- Web: `POST /api/v1/healthcare/import`（multipart。`file` か `path` の一方を必須）。

## Web からの差分インポート

`/healthcare` のインポートダイアログから Apple Health の `export.zip` を取り込む。

- 受領: D&D アップロード（上限 4GiB）またはサーバー側パス指定。同期リクエストで、
  ルートは `def` のため FastAPI threadpool 実行（event loop 非ブロック）。
- 展開: `healthcare/export_zip.py` が `export.xml` と `electrocardiograms/*.csv` のみを
  staging へ安全に展開（zip slip / zip bomb / symlink / 暗号化を拒否、非圧縮合計・entry 数・
  圧縮率を展開前に検証）。ネストした `apple_health_export/` prefix は strip。
- 取込: `importer.import_export_zip()` → 既存 `import_export()`。差分は
  `fingerprint UNIQUE` ＋ `INSERT OR IGNORE` で成立し、`stats_json` の
  `records_inserted` / `workouts_inserted` / `activity_summaries_inserted` と
  `ignored_duplicates` を UI に表示。失敗時は `rollback` 後に `failed` 記録して再raise。
- 後始末: アップロード zip と展開 staging は `finally` で削除。`Me`（生年月日）等の
  PII はログ出力しない。
- 同時実行: プロセス内ロックで直列化し、実行中は 409 を返す。

## スキーマ v1（テーブル一覧）

- `health_imports` — 取込実行の状態（`running` / `succeeded` / `failed`）、`stats_json`。
- `health_records` — 単一の Record テーブル。`fingerprint UNIQUE` で再取込を冪等化、`(type, start_date)` 索引。
- `health_record_metadata` / `health_hrv_beats` — Record 付随データ。
- `health_workouts` ＋ metadata / events / statistics / routes — Workout の正規化。
- `health_activity_summaries` — ActivitySummary を raw XML/JSON で保持。
- `health_ecg` — ECG メタ（`file_path UNIQUE`、sha256 / file_size）。波形はファイル参照。

fingerprint は `SHA256(type|syncId)`（syncId 存在時）、無ければ
`SHA256(type|source|version|start|end|value|unit)`。Workout は別途
`SHA256(activityType|source|version|start|end)`。`INSERT OR IGNORE` により再取込で重複しない。

## 運用・プライバシー

- `Me`（生年月日）や `HKDevice` は個人識別情報を含むためログ出力しない。LLM への送信は既定 OFF。
- 分離DBのため、バックアップ対象は `memory.sqlite3` とは別に `healthcare.sqlite3` を含める必要がある。
- 初回 import は 3〜5 分想定（batch 5000、WAL、`iterparse` でメモリ <100MB）。

## 未実装の将来拡張

- `health_daily_metrics` の VIEW / refresh ジョブ（睡眠・歩数・心拍の日次集計）。
- `export_cda.xml` の `health_clinical_records` 対応（現状は `stats_json.cda_skipped=true`）。
- ダッシュボード / `summerize_day` への健康集計の自動注入（集計のみ・opt-in）。
- `job_runner` への定期差分 import 登録。
