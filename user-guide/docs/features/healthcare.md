---
sidebar_position: 13
title: ヘルスケア
---

# ヘルスケア

**ヘルスケア** 画面（`/healthcare`）では、Apple Health の生体指標の推移を概観できます。
Quantity 型（歩数・心拍・エネルギーなど）と Category 型（睡眠・スタンド）を日次で集計します。

## データを取り込む

Apple Health のデータはメインのメモリ DB とは別の SQLite に保存されます。

```
~/.config/obsidian-ai-hub/healthcare.sqlite3
```

1. iPhone のヘルスケア App → プロフィール → **Export All Health Data**。
2. エクスポートした zip を展開します（例: `~/.config/obsidian-ai-hub/healthcare/apple_health_export`）。
3. 取り込みを実行します。

```bash
uv run -m obsidian_ai_hub --import-apple-health
```

オプション:

```bash
uv run -m obsidian_ai_hub --import-apple-health \
  --healthcare-export-dir /path/to/apple_health_export \
  --healthcare-batch-size 10000
```

データを書き込まずに件数だけ確認する場合:

```bash
uv run -m obsidian_ai_hub --import-apple-health --healthcare-dry-run
```

取り込みは冪等で、再実行しても重複しません。Web UI の **インポート** からも取り込めます。

## 画面で見る

- **集計期間:** **7日間** / **30日間** / **90日間** / **今年** / **期間指定**（開始日・終了日）。
- **推移** タブ — メトリクスカードと推移。粒度バッジ（日別 / 週別 / 月別）。
- **相関** タブ — **X軸メトリック** と **Y軸メトリック** を選ぶと相関散布図（Pearson + 回帰）を表示します。

データが無い場合は「ヘルスケアデータがまだありません」と表示され、インポートを促されます。

## 設定

```yaml
healthcare:
  sqlite_path: /Users/you/.config/obsidian-ai-hub/healthcare.sqlite3
  export_dir: /Users/you/.config/obsidian-ai-hub/healthcare/apple_health_export
```

環境変数 `HEALTHCARE_SQLITE_PATH` / `HEALTHCARE_EXPORT_DIR` でも上書きできます。

## 次に読む

- [設定](../settings/configuration.md)
- [サマリダッシュボード](summary-dashboard.md)
