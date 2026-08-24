# TODO: Apple Health Import
Plan: docs/healthcare-import/plan.md

## Phase 1 — 基盤 (1–2日) — 完了 (745eb4d)

- [x] `src/obsidian_ai_hub/utils/config.py` に `HEALTHCARE_SQLITE_PATH` / `HEALTHCARE_EXPORT_DIR` 追加（`VAULT_INDEX_SQLITE_PATH` パターン踏襲、`ENV=test` 時は `TEST_WORKSPACE` 配下）
- [x] `src/obsidian_ai_hub/healthcare/` パッケージ雛形作成
  - [x] `store.py`: `get_healthcare_db_connection()`（`PRAGMA foreign_keys/journal_mode=WAL/busy_timeout`）、`init_schema()` で v1 DDL 実行、`PRAGMA user_version=1`
  - [x] `models.py`: dataclass / TypedDict 型定義（frozen + hash 対応、metadata tuple）
  - [x] `config.py`: 再export（`utils/config.py` で一元管理のため不要と判断）
- [x] `tests/conftest.py` に `_isolate_healthcare_db` autouse fixture 追加 + `_filesystem_sandbox` で `HEALTHCARE_EXPORT_DIR` リダイレクト（`HEALTHCARE_SQLITE_PATH` は `test_healthcare_db_path` 経由に一本化、ocr指摘で重複排除）
- [x] `store.py` に本番パス保護ガード（`database.py:10` `_assert_test_db_is_not_production` 同型 + MEMORY 分離ガード）追加 — ocr指摘で try/except の silent swallow を除去
- [x] `tests/healthcare/test_store.py` 作成（WAL/UNIQUE/ cascade / ECG read 検証、ocr指摘で ECG は malformed を ValueError に）
- [x] `uv run pytest tests/healthcare/test_store.py` で隔離動作確認 — 11 passed
- [x] ocr review 指摘18件を修正（config冗長expanduser、helpersのdead code/assert、fixtures DOCTYPE、conftestガード等）
- [x] `src/obsidian_ai_hub/healthcare/store.py` に `idx_hw_import` と `health_workout_routes PK(seq)` を追加（ocr指摘の性能対策）

## Phase 2 — インポータ MVP (2–3日) — 完了 (72ea966) + ocr修正 (9f2d935)

- [x] `src/obsidian_ai_hub/healthcare/importer.py` 実装
  - [x] `import_export(export_dir, batch_size=5000, dry_run=False)` — `iterparse` + `elem.clear()` + fingerprint (SHA256 `type|syncId` or `type|source|start|end|value|unit`) + `INSERT OR IGNORE` 冪等
  - [x] Record: `value_numeric`/`value_text` 振り分け、`health_record_metadata` / `health_hrv_beats` へ挿入（HealthRecordモデルを単一ソースとして利用）
  - [x] Workout: 4テーブル分割（metadata/events/statistics/routes, seq PK, idx_hw_import, HealthWorkoutモデル利用）
  - [x] ActivitySummary: `raw_json`/`raw_xml` 保存
  - [x] `health_imports` の `running`→`succeeded`/`failed` 更新と `stats_json` 集計（`cda_skipped=true`）
  - [x] 進捗ログ（batchごとに commit、batch毎に info）、`health_data_elem.clear()` でメモリ解放、例外は `rollback()` 後に `failed` 記録して再raise（ocr指摘の高バグ修正）
  - [x] ECG: `electrocardiograms/*.csv` をストリーミングで走査し `health_ecg` へ（relative file_path, sha256, file_size, header parse、UNIQUE(file_path)で冪等）
  - [x] `dry_run` は DB 書き込みなしで件数カウント
  - [x] `src/obsidian_ai_hub/healthcare/store.py` のECG関連をストリーミング＋non-finite検証＋ヘッダ欠損はValueErrorに
- [x] `src/obsidian_ai_hub/import_apple_health.py` 薄い CLI ラッパ（`--batch-size` は `_positive_int` で正数バリデーション、例外はtraceback出力に分岐）
- [x] `tests/healthcare/fixtures/export_mini.xml` / `fixtures/ecg_mini.csv` 作成（Phase1 で完了、helpers の定数化と `__getattr__`遅延＋ECG_DATE導出でocr対応）
- [x] `tests/healthcare/test_importer.py` 作成（7 records / 1 workout / 1 activity / 1 ecg、2回目冪等(ECG含む)、syncId fingerprint、dry_run、ECGなし、CLI、CLI dry-run/batch-sizeバリデーション、失敗時rollbackでpartial 0件、missing dir — 22 passed）
- [x] `uv run pytest tests/healthcare/` で全件通過確認 — 22 passed、実データdry_run 1,142,682 records/24 workoutsを4.2sで検証
- [x] ocr 26件を反映（batch-size検証、rollback、root clear、進捗ログ、malformed warning、二次例外ログ、hashlib重複除去、ECGヘッダストリーミング、modelsのhash/compare対称、storeのguard必須化、conftest改名等）

## Phase 3 — ECG と仕上げ (1日) — Phase2で先行完了

- [x] `importer.py` に `electrocardiograms/*.csv` スキャン追加 — Phase2で実装済み（ストリーミングheader parse、UNIQUEで冪等）
  - [x] ヘッダ8行 parse → `health_ecg` へ（`file_path` 相対保存、`sha256`/`file_size`）
  - [x] CSV 本体は DB 非格納、`store.read_ecg_samples()` でファイル参照（ストリーミング＋limit対応）
- [x] `--dry-run` / `--batch-size` オプション仕上げ — Phase2で実装・バリデーション済み
- [x] 実データ手動検証（`ENV=test` 一時DB）: `uv run python -m obsidian_ai_hub.healthcare.importer` で dry_run 1,142,682 records/24 workouts/1155 summaries/1 ecgを4.2sで確認、実ECG 15,360 samplesも検証済み（本番DB不使用）
- [ ] README / `docs/healthcare-import/plan.md` の「将来拡張」追記確認 — Phase4でまとめて対応

## Phase 4 — 統合 (0.5日)

- [ ] `src/obsidian_ai_hub/main.py:51` への `--import-apple-health` 追加要否を判断し、追加する場合は `run_and_log()` パターンで統合
- [ ] `config/config.yml` サンプル追記（`healthcare.sqlite_path` / `export_dir`）
- [ ] `ai_wiki/10-Decisions-Integrations.md` に決定記録（分離DB/全種raw/ECGファイル参照の rationale）
- [ ] `docs/testing.md` に `HEALTHCARE_SQLITE_PATH` 隔離の追記が必要か判断
- [ ] 最終 `uv run pytest tests/` + 手動 import 検証で完了確認

## 検証チェックリスト

- [ ] `ENV=test` で本番 `healthcare.sqlite3` が保護されること（`Refusing to open ...` ガード）
- [ ] 110万件 import で OOM せず 3–5分で完了すること
- [ ] 2回連続 import で 2回目は全 `IGNORE`（count 不変、`health_imports` 2行）
- [ ] ECG CSV の `file_path` が相対で保存され、`health_ecg_samples` テーブルが存在しないこと
- [ ] `export_cda.xml` がスキップされ `stats_json.cda_skipped=true` となること
