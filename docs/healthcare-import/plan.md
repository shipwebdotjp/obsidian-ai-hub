# Apple Health Export インポート計画

## 0. 合意事項

* **分離DB**: `memory.sqlite3` とは別に `healthcare.sqlite3` を新設。`PRAGMA user_version` は独立管理（v1起点）。
* **全種 raw 保存**: HealthKit の全 Record type を正規化せず保存。将来の集計は VIEW / 追加テーブルで対応。
* **ECG サンプルは DB 非格納**: `electrocardiograms/*.csv` はメタのみ DB、`file_path` 参照。サンプル波形はファイルから都度読む。

## 1. 背景と現状

* Export 実体: `/Users/ship/.config/obsidian-ai-hub/healthcare/apple_health_export` — `export.xml` 407MB / 2,116,935行 / Record約110万、`export_cda.xml` 353MB (HL7 CDA)、`electrocardiograms/ecg_2025-04-19.csv` (512Hz)
* DTD: `HealthData(ExportDate,Me,(Record|Correlation|Workout|ActivitySummary|ClinicalRecord|Audiogram|VisionPrescription)*)` — 実データは `Record` 30種、`Workout` 24件 (`Cycling 22`/`Walking 2`)、`ActivitySummary` 1155件、`Correlation/Clinical/Audiogram=0`
* 主要 Record: `HeartRate 356k`, `ActiveEnergyBurned 220k`, `DistanceWalkingRunning 142k`, `StepCount 136k`, `BasalEnergyBurned 79k`, `PhysicalEffort 51k`, `SleepAnalysis 22k` 他。`unit` は type 固定。
* 既存DB: `src/obsidian_ai_hub/database.py:142` `get_db_connection()` 単一 SQLite (`MEMORY_SQLITE_PATH`, `user_version=22`, WAL)。110万行を同居させると VACUUM/バックアップ影響が大きい。
* 既存規約: `AGENTS.md` — `src/obsidian_ai_hub/` 直下は薄いCLIラッパ、ロジックはサブパッケージ。防御的例外マスク禁止。テストは `uv run pytest` + `ENV=test` 隔離 (`tests/conftest.py:40`, `docs/testing.md:9`)。

## 2. アーキテクチャ

### 2.1 DB配置

* 新規パス `HEALTHCARE_SQLITE_PATH`
  * 解決: `src/obsidian_ai_hub/utils/config.py:221` `VAULT_INDEX_SQLITE_PATH` と同パターン `_optional_path("HEALTHCARE_SQLITE_PATH","healthcare","sqlite_path")`
  * 既定: `BASE_DIR / "data" / "healthcare" / "healthcare.sqlite3"`、本番上書き例 `~/.config/obsidian-ai-hub/healthcare.sqlite3`
  * `ENV=test` 時: `TEST_WORKSPACE / "healthcare.sqlite3"` (`src/obsidian_ai_hub/utils/config.py:9` 準拠)
  * `config/config.yml` 任意:
    ```yaml
    healthcare:
      sqlite_path: /Users/ship/.config/obsidian-ai-hub/healthcare.sqlite3
      export_dir: /Users/ship/.config/obsidian-ai-hub/healthcare/apple_health_export
    ```
* `memory.sqlite3` の `user_version` は触らない。`healthcare.sqlite3` は独自 `PRAGMA user_version=1` でマイグレーション管理。

### 2.2 パッケージ構成

```
src/obsidian_ai_hub/healthcare/
  __init__.py
  config.py          # HEALTHCARE_SQLITE_PATH / EXPORT_DIR 解決 (utils/config.py 拡張 or ここで再export)
  store.py           # get_healthcare_db_connection(), init_schema(), CRUD helpers
  importer.py        # iterparse, fingerprint, batch insert, ECG scan
  models.py          # dataclass / TypedDict 型定義のみ
src/obsidian_ai_hub/import_apple_health.py  # 薄い CLI ラッパ (argparseのみ)
tests/healthcare/
  test_store.py
  test_importer.py
  fixtures/export_mini.xml
  fixtures/ecg_mini.csv
```

### 2.3 スキーマ (healthcare.sqlite3 v1)

単一正規化テーブル + 付随テーブル。type 毎分割は HealthKit 追加時の破壊が大きいため不採用。

```sql
CREATE TABLE health_imports (
  import_id TEXT PRIMARY KEY,
  export_dir TEXT NOT NULL,
  export_date TEXT,
  hk_export_version TEXT, -- "14"
  locale TEXT,
  me_json TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')),
  stats_json TEXT NOT NULL DEFAULT '{}',
  error TEXT
);

CREATE TABLE health_records (
  record_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_id TEXT NOT NULL REFERENCES health_imports(import_id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  value_text TEXT,
  value_numeric REAL,
  unit TEXT,
  source_name TEXT NOT NULL,
  source_version TEXT,
  device_raw TEXT,
  creation_date TEXT,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX idx_hr_type_start ON health_records(type, start_date);
CREATE INDEX idx_hr_start ON health_records(start_date);
CREATE INDEX idx_hr_import ON health_records(import_id);
CREATE INDEX idx_hr_source ON health_records(source_name);

CREATE TABLE health_record_metadata (
  record_id INTEGER NOT NULL REFERENCES health_records(record_id) ON DELETE CASCADE,
  mkey TEXT NOT NULL,
  mvalue TEXT NOT NULL,
  PRIMARY KEY(record_id, mkey)
);
CREATE INDEX idx_hrm_key ON health_record_metadata(mkey);

CREATE TABLE health_hrv_beats (
  record_id INTEGER NOT NULL REFERENCES health_records(record_id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  bpm REAL NOT NULL,
  time TEXT NOT NULL,
  PRIMARY KEY(record_id, seq)
);

CREATE TABLE health_workouts (
  workout_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_id TEXT NOT NULL REFERENCES health_imports(import_id) ON DELETE CASCADE,
  activity_type TEXT NOT NULL,
  duration REAL, duration_unit TEXT,
  total_distance REAL, total_distance_unit TEXT,
  total_energy_burned REAL, total_energy_burned_unit TEXT,
  source_name TEXT NOT NULL, source_version TEXT, device_raw TEXT,
  creation_date TEXT, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  fingerprint TEXT NOT NULL UNIQUE
);
CREATE TABLE health_workout_metadata (
  workout_id INTEGER NOT NULL REFERENCES health_workouts(workout_id) ON DELETE CASCADE,
  mkey TEXT NOT NULL, mvalue TEXT NOT NULL, PRIMARY KEY(workout_id,mkey)
);
CREATE TABLE health_workout_events (
  workout_id INTEGER NOT NULL REFERENCES health_workouts(workout_id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, type TEXT NOT NULL, date TEXT NOT NULL,
  duration REAL, duration_unit TEXT, PRIMARY KEY(workout_id,seq)
);
CREATE TABLE health_workout_statistics (
  workout_id INTEGER NOT NULL REFERENCES health_workouts(workout_id) ON DELETE CASCADE,
  type TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  average REAL, minimum REAL, maximum REAL, sum REAL, unit TEXT,
  PRIMARY KEY(workout_id,type)
);
CREATE TABLE health_workout_routes (
  workout_id INTEGER NOT NULL REFERENCES health_workouts(workout_id) ON DELETE CASCADE,
  source_name TEXT, source_version TEXT, device_raw TEXT,
  creation_date TEXT, start_date TEXT, end_date TEXT, file_path TEXT
);

CREATE TABLE health_activity_summaries (
  import_id TEXT NOT NULL REFERENCES health_imports(import_id) ON DELETE CASCADE,
  date_components TEXT PRIMARY KEY,
  raw_xml TEXT NOT NULL,
  raw_json TEXT NOT NULL
);

CREATE TABLE health_ecg (
  ecg_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_id TEXT NOT NULL REFERENCES health_imports(import_id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  file_name TEXT NOT NULL,
  recorded_at TEXT,
  classification TEXT,
  symptoms TEXT,
  software_version TEXT,
  device TEXT,
  sample_rate_hz INTEGER,
  lead TEXT,
  unit TEXT,
  sha256 TEXT,
  file_size INTEGER
);
-- samples は DB に入れない。必要時は file_path から読む。
```

将来拡張: `health_daily_metrics` は VIEW または refresh ジョブで追加。`export_cda.xml` 用 `health_clinical_records` も次 migration で追加可能（今回は `stats_json.cda_skipped=true` でスキップ）。

## 3. インポート機構

### 3.1 CLI

* `python -m obsidian_ai_hub.import_apple_health --export-dir <dir> [--batch-size 5000] [--dry-run]`
* `src/obsidian_ai_hub/import_apple_health.py` は `argparse` のみ、実体は `healthcare.importer.import_export()` に委譲（`AGENTS.md` 準拠、例外はマスクせず素通し）。
* `src/obsidian_ai_hub/main.py:51` への `--import-apple-health` 追加は Phase4 で判断（今回は独立モジュールで可、`run_and_log()` パターン `main.py:326` に乗せる場合は追加）。

### 3.2 パイプライン (`healthcare/importer.py`)

1. `store.get_healthcare_db_connection()` で `PRAGMA foreign_keys=ON, journal_mode=WAL, busy_timeout=30000` (`database.py:149` と同設定)。
2. `health_imports` に `running` 行 insert (`import_id=uuid4_hex`)。
3. `xml.etree.ElementTree.iterparse(export.xml, events=('end',))` で streaming。`Record|Workout|ActivitySummary` の `end` で処理し `elem.clear()` でメモリ解放。lxml があれば切替オプションを追加。
   * `ExportDate`/`Me` は最初に capture し `health_imports` に保存。
4. **fingerprint**: `MetadataEntry[key=HKMetadataKeySyncIdentifier]` があれば `type|sync_id`、無ければ `type|sourceName|startDate|endDate|value|unit` の SHA256 hex。`UNIQUE` + `INSERT OR IGNORE` で再インポート冪等。
5. **Record**: `unit` 有無で `value_numeric` (float) vs `value_text` に振り分け。`MetadataEntry` → `health_record_metadata`、`HeartRateVariabilityMetadataList` → `health_hrv_beats` へ `executemany`。
6. **Workout**: 子要素を 4テーブルへ分割。
7. **ActivitySummary**: 属性を `raw_json`、行XMLを `raw_xml` に保存。
8. **ECG**: `electrocardiograms/*.csv` を glob。ヘッダ8行（名前/生年月日/記録日/分類/症状/software/device/sampleRate/lead/unit）を parse し `health_ecg` へ。`file_path` は相対保存、`sha256` 任意。CSV 本体は読まない。helper `read_ecg_samples(ecg_id)` がファイルを開く。
9. **CDA**: 今回スキップ。
10. コミットは `batch_size` (既定5000) ごと `executemany`。進捗は `logging.info` で10k件ごと。
11. 完了後 `health_imports` を `succeeded` に更新し `stats_json` に `{records, workouts, activity_summaries, ecg_files, ignored_duplicates}`。例外時は `failed` + `error`。

## 4. 設定

* `src/obsidian_ai_hub/utils/config.py:615` 近傍に追加:
  ```python
  HEALTHCARE_SQLITE_PATH = _optional_path("HEALTHCARE_SQLITE_PATH","healthcare","sqlite_path")
  if HEALTHCARE_SQLITE_PATH is None:
      HEALTHCARE_SQLITE_PATH = BASE_DIR / "data" / "healthcare" / "healthcare.sqlite3"
  if IS_TEST_ENV:
      HEALTHCARE_SQLITE_PATH = TEST_WORKSPACE / "healthcare.sqlite3"
  HEALTHCARE_EXPORT_DIR = _optional_path("HEALTHCARE_EXPORT_DIR","healthcare","export_dir")
  if HEALTHCARE_EXPORT_DIR is None:
      HEALTHCARE_EXPORT_DIR = Path("~/.config/obsidian-ai-hub/healthcare/apple_health_export").expanduser()
  ```

## 5. テスト戦略

* `tests/conftest.py:40` に倣い `HEALTHCARE_SQLITE_PATH` も `tmp_path` に差し替える autouse fixture `_isolate_healthcare_db` を追加。`_filesystem_sandbox` でもリダイレクト。
* `HEALTHCARE_SQLITE_PATH` の本番パス保護ガード (`database.py:10` 同型) を `store.py` に追加。
* `tests/healthcare/test_store.py`: WAL/foreign_keys、有効な UNIQUE 制約。
* `tests/healthcare/test_importer.py`: `fixtures/export_mini.xml` + `fixtures/ecg_mini.csv` を `tmp_path` に生成し `import_export()` 実行。`health_records`/`health_workouts`/`health_ecg` の件数、2回目実行で count 不変（冪等）、ECG は `file_path` のみ。
* 実データ手動検証: `ENV=test uv run python -m obsidian_ai_hub.import_apple_health --export-dir /Users/ship/.config/obsidian-ai-hub/healthcare/apple_health_export --dry-run` で `grep -c "<Record "` と `SELECT count(*) FROM health_records` を突合。本番DBは使わない (`docs/testing.md:33`)。

## 6. 運用・プライバシー

* `Me`（生年月日）や `HKDevice` は個人識別情報を含むためログ出力しない。LLM への送信は既定 OFF。
* 初回 import は 3–5分想定（5000件/batch, WAL）。`iterparse` でメモリ <100MB。
* バックアップは `healthcare.sqlite3` を `backup/sync_folders` に含めるか `config.yml` で iCloud 配下に配置。

## 7. 将来拡張

* `health_daily_metrics` VIEW / refresh ジョブ（睡眠・歩数・心拍の日次集計）
* `export_cda.xml` の `health_clinical_records` 対応
* ダッシュボード / `summerize_day` への自動注入
* `task_runner` への定期差分 import 登録

## 8. 参照

* `src/obsidian_ai_hub/database.py:26` migration パターン
* `src/obsidian_ai_hub/utils/config.py:221` vault_index 分離DBパターン
* `src/obsidian_ai_hub/sync_valut.py:45` storage path 準備
* `src/obsidian_ai_hub/summary/store.py:72` sleep パース
* `src/obsidian_ai_hub/main.py:326` run_and_log パターン
* `docs/testing.md:9` pytest 隔離規約
