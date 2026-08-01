# Worklog

一時的な進捗メモ・引き継ぎのみを記録する。恒久の決定は `10-Decisions.md` へ。

## 次のセッションへの引き継ぎ（handoff）

### 2026-08-01: ocr review で検出した既存問題（今回のリファクタで対応しない）

`refactor/split-web-api`（web/api.py の routes 分割）完了後、ocr review で検出した問題のうち、
**今回の分割以前から存在する**問題を以下に控える。すべて `web/api.py` の移動元コードに由来し、
今回のリファクタではロジック不変を優先して対処しない。次回以降に検討する。

| # | 対象 | 種別 | 内容 |
|---|------|------|------|
| 1 | `web/routes/people.py` get_vault_report | bug | `"synced": False` を常にハードコード返却。`sync_people` の `synced: True` とスキーマを共有するが意味が不整合。実状態の導出かフィールド意味の明確化が必要。 |
| 2 | `web/routes/people.py` get_vault_report / sync_people | security | `except Exception` で `detail=str(e)` をそのまま返し、内部パス等を漏洩する可能性。汎用メッセージ化を推奨。 |
| 3 | `web/routes/people.py` assign/resolve/merge | maintainability | `response_model` 未指定で `{"success": True}` を生返し。`PersonActionResponse` 等の明示モデル化を推奨。 |
| 4 | `web/routes/people.py` 静的ルート順序 | maintainability | `/people/candidates` 等を `/people/{person_id}` より先に定義する規約が暗黙的。コメント等で明示化を推奨。 |
| 5 | `web/routes/deps.py` require_loopback_or_token | maintainability | ループバック判定が2関数で別実装。`require_loopback_or_token` は IPv4-mapped IPv6（`::ffff:127.0.0.1`）を許可せず 401 になり得る。共通ヘルパー `_is_loopback_host()` への集約を推奨。 |
| 6 | `web/routes/deps.py` require_loopback_or_token | style | `headers.get("authorization") or headers.get("Authorization")` は Starlette の小文字化により冗長。単一参照へ統一。 |
| 7 | `web/routes/deps.py` require_localhost | bug | IPv4-mapped 判定が `startswith("::ffff:")` の大文字小文字依存。`IPv6Address.ipv4_mapped` を推奨。 |
| 8 | `web/routes/task_config.py` 全 3 エンドポイント | maintainability | 未使用の `request: Request` 引数が残っている。削除を推奨。 |
| 9 | `web/routes/task_config.py` | security | 想定外例外の `str(e)` を HTTP 500 detail で返却。汎用メッセージ化を推奨。 |
| 10 | `web/routes/dashboard.py` get_dashboard_summary | maintainability | `summary.store` の関数内インポート。トップレベルへ移動可（循環 import なし）。 |
