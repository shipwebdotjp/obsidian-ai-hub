# Worklog

一時的な進捗メモ・引き継ぎのみを記録する。恒久の決定は `00-Index.md` から適切な決定記録へ追加する。

## 次のセッションへの引き継ぎ（handoff）

### 2026-08-19: 1分間隔タスクのログ抑制（task_state + 日次クリーンアップ）実装済

決定記録: `10-Decisions-Architecture.md`「1分間隔タスク向けのログ抑制（task_state 集計 + 日次クリーンアップ）」。

実装完了・検証済:

- バックエンド: スキーマv19 `task_state`、`upsert_task_state` / `suppress_command_run` / `list_task_states` / `cleanup_old_logs_now`、`merge_inbox` のカウント返却、`run_and_log` の `task_id` / `empty_result_predicate`、`--cleanup-execution-logs`、`cleanup_execution_logs_daily`(03:20)、`GET /api/v1/task-states`。
- フロントエンド: 実行ログ画面の task-status パネル（30秒自動更新）。
- launchd: `scripts/launchd_log_wrapper.sh`（1 MiB・7世代ローテーション）を両 plist の起動コマンドに適用、`StandardOut/ErrorPath` を `/dev/null` に変更。
- 検証: `uv run pytest tests/` → `654 passed`（旧 `== 18` を主張していた 4 テストを `== 19` に更新）。Frontend `vitest` → `104 passed`、`npm run build` OK。E2E `make test-e2e` → `7 passed`。
- lint: 新規ファイル（`tests/test_task_state.py`, `web/routes/task_states.py`, `web/services/task_states.py`）は `ruff` clean。`service.py` の F401 は既存のファサード再エクスポート由来（変更前 74 → 変更後 75、追加1件は同パターン）。

残作業・注意:

- 変更は未 commit（ユーザーが commit を依頼していない）。
- 本番反映は未実施: plist 再ロード・`task_runner` 再起動はユーザー指示待ち。旧挙動（書き込み時クリーンアップ）は関数を残していないため、反映後に毎分空振りが `command_runs` に増えないことを確認する。
- `make logs` 系ターゲットが `/tmp/obsidian_merge.log` `/tmp/obsidian_merge.err` を参照している場合、ラッパー経由後もパスは不変（確認済み不要だが、次回動作確認時に実在を確認）。

### 2026-08-15: Bearer 認証一元化 — 検証・OCR 完了済

`feature/public-api-endpoint` の Bearer 認証変更（決定は `10-Decisions-Web.md` 参照）のフォローアップとして、
全 OCR 指摘対応後の再検証を完了した。

- 非 E2E: `526 passed`（`test_health` 追加込み）。既知の環境依存失敗
  （`test_apple_reminders.py`, `test_llm_client_*.py`, `test_youtube_webclip.py`）は除外。
- Frontend: `npm --prefix frontend run build` OK、vitest `102 passed`（non-401 エラー処理テスト追加込み）。
- E2E: `ENV=test uv run pytest -m e2e tests/e2e/ -q` → `7 passed`。
- OCR（`--audience agent`）再実行: working copy の追加変更（fail-closed テスト追加後の `tests/test_main.py`）1 file、
  `0 comments`。前回指摘はすべて対応済み。
- OCR pending 指摘（CLI `--serve` fail-closed テスト不足）を対応:
  `tests/test_main.py` に `test_serve_without_token_fails_closed` を追加。`test_main.py` は `24 passed`。

残作業: なし（他に保留なし）。変更は未 commit（ユーザーが commit を依頼していない）。
未追跡ファイル: `tests/e2e/test_people_scenario.py`, `docs/hitl-line-investigation.md`。

### 2026-08-01: ocr review で検出した既存問題（今回のリファクタで対応しない）

`refactor/split-web-api`（web/api.py の routes 分割）完了後、ocr review で検出した問題のうち、
**今回の分割以前から存在する**問題を以下に控える。すべて `web/api.py` の移動元コードに由来し、
今回のリファクタではロジック不変を優先して対処しない。次回以降に検討する。

> **UPDATE 2026-08-01:** 下記 1〜10 はすべて解消済み。詳細は各項目の対応を参照。

| # | 対象 | 種別 | 内容 | 対応 |
|---|------|------|------|------|
| 1 | `web/routes/people.py` get_vault_report | bug | `"synced": False` を常にハードコード返却。`sync_people` の `synced: True` とスキーマを共有するが意味が不整合。実状態の導出かフィールド意味の明確化が必要。 | 対応: `get_vault_report_dynamic` が `synced: False`（読み取り専用レポートのため同期を行わない）を導出して返し、スキーマに意味を明記。route はサービス返却値をそのまま返す。 |
| 2 | `web/routes/people.py` get_vault_report / sync_people | security | `except Exception` で `detail=str(e)` をそのまま返し、内部パス等を漏洩する可能性。汎用メッセージ化を推奨。 | 対応: 500 detail を汎用メッセージに変更。詳細は `logger.exception` のみに記録。 |
| 3 | `web/routes/people.py` assign/resolve/merge | maintainability | `response_model` 未指定で `{"success": True}` を生返し。`PersonActionResponse` 等の明示モデル化を推奨。 | 対応: `schemas.PersonActionResponse` を追加し、assign/resolve/merge に `response_model` を指定。 |
| 4 | `web/routes/people.py` 静的ルート順序 | maintainability | `/people/candidates` 等を `/people/{person_id}` より先に定義する規約が暗黙的。コメント等で明示化を推奨。 | 対応: ルーター定義直前に静的ルート優先順序のコメントを追加。 |
| 5 | `web/routes/deps.py` require_loopback_or_token | maintainability | ループバック判定が2関数で別実装。`require_loopback_or_token` は IPv4-mapped IPv6（`::ffff:127.0.0.1`）を許可せず 401 になり得る。共通ヘルパー `_is_loopback_host()` への集約を推奨。 | 対応: `_is_loopback_host()` へ集約し、両関数が利用。IPv4-mapped IPv6 もループバック扱い。 |
| 6 | `web/routes/deps.py` require_loopback_or_token | style | `headers.get("authorization") or headers.get("Authorization")` は Starlette の小文字化により冗長。単一参照へ統一。 | 対応: `headers.get("authorization")` の単一参照に統一。 |
| 7 | `web/routes/deps.py` require_localhost | bug | IPv4-mapped 判定が `startswith("::ffff:")` の大文字小文字依存。`IPv6Address.ipv4_mapped` を推奨。 | 対応: `_is_loopback_host()` で `IPv6Address.ipv4_mapped` を使用（大文字小文字非依存）。 |
| 8 | `web/routes/task_config.py` 全 3 エンドポイント | maintainability | 未使用の `request: Request` 引数が残っている。削除を推奨。 | 対応: 全エンドポイントから未使用引数と import を削除。 |
| 9 | `web/routes/task_config.py` | security | 想定外例外の `str(e)` を HTTP 500 detail で返却。汎用メッセージ化を推奨。 | 対応: 500 detail を汎用メッセージに変更。詳細は `logger.exception` のみに記録。 |
| 10 | `web/routes/dashboard.py` get_dashboard_summary | maintainability | `summary.store` の関数内インポート。トップレベルへ移動可（循環 import なし）。 | 対応: トップレベル import に移動。 |
