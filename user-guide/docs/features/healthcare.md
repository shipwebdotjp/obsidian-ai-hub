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

1. iPhone のヘルスケア App → プロフィール → **Export All Health Data** で `export.zip` を書き出します。

### Web UI から取り込む（`export.zip` のまま）

zip を展開する必要はありません。

1. **ヘルスケア** 画面（`/healthcare`）のヘッダーにある **インポート** を押します。
2. **zip をアップロード** を選び、書き出した `export.zip` をドロップゾーンへドラッグ＆ドロップします（クリックしてファイル選択もできます）。
3. **インポート** を押します。取り込み中は「取り込み中です…（完了まで数分かかることがあります）」と表示されます。
4. 完了すると新規件数・重複として除外した件数・ECG ファイル件数が表示されます。

巨大な zip でブラウザからのアップロードが重い場合は、**サーバー上のパスを指定** に切り替え、Mac 上の zip パス（例: `~/Downloads/export.zip`）を入力して取り込めます。

### CLI から取り込む（展開済みディレクトリ）

1. エクスポートした zip を展開します（例: `~/.config/obsidian-ai-hub/healthcare/apple_health_export`）。
2. 取り込みを実行します。

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

取り込みは冪等で、再実行しても重複しません。既に取り込み済みの記録は重複として除外され、新しい記録だけが追加されます。

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
