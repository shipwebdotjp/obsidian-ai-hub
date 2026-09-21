---
sidebar_position: 3
title: サマリ
---

# サマリ

デイリーノートと構造化データから、日次・週次・月次のサマリを生成します。
生成結果は SQLite に保存され、Web UI の **サマリダッシュボード** で閲覧・編集・再生成できます。

## 日次サマリ

現在のデイリーノートを対象に生成します。日付を指定する場合は `--day-date`（`YYYY-MM-DD`）を使います。

```bash
uv run -m obsidian_ai_hub --summerize-day
uv run -m obsidian_ai_hub --summerize-day --day-date 2026-07-15
```

## 週次サマリ

指定した週のサマリを生成します。`--week-date` にはその週の任意の日付（`YYYY-MM-DD`）を渡します。

```bash
uv run -m obsidian_ai_hub --summerize-week
uv run -m obsidian_ai_hub --summerize-week --week-date 2026-06-15
```

## 月次サマリ

前月分を生成します。`--month` で `YYYY-MM` を指定できます。

```bash
uv run -m obsidian_ai_hub --summerize-month
uv run -m obsidian_ai_hub --summerize-month --month 2026-07
```

## 週次レビューの下書き（review draft）

週次ノートの `result::` 行が空のものに対して、レビュー下書きを生成し、LINE へ通知します。
下書きは `result::` の直下に保存されてから通知が送られます。

```bash
uv run -m obsidian_ai_hub --review-draft
uv run -m obsidian_ai_hub --review-draft --review-week-date 2026-07-12
```

日曜夜のレビュー下書きを自動化するには、ジョブ `review_draft_sunday_evening` の例を
プロジェクトパスに合わせて有効化します（[ジョブ管理](../features/jobs.md) を参照）。

## 長期メモリの利用

`--make-target`、`--generate-planner-proposals`、`--summerize-day`、`--summerize-week`、
`--summerize-month`、`--review-draft` を実行すると、用途別に選ばれた承認済みメモリが
プロンプトへ自動的に付加されます。どの種類が使われるか（`--for` の対応）は
[長期メモリ](../features/memory.md#生成処理での利用) を参照してください。

## Web UI で扱う

**サマリダッシュボード**（`/summary-dashboard`）では次のタブがあります。

- **ホーム** — 今月の月次、最新の週次、昨日の日次をカードで表示する。未生成のものは「未生成」と表示される。
- **一覧** — 期間ごとにサマリを閲覧し、**再生成**・**編集**・**削除** を行う。未生成の期間は作成できる。
- **統計** — 期間プリセット（7日間 / 30日間 / 90日間 / 今年 / 期間指定）でトピックやキーワードを集計する。

:::warning[再生成は手編集を上書きします]
**再生成** は「手編集した内容も含め、現在のサマリを新しい生成結果で上書きします」。
必要な内容は再生成前に退避してください。削除は取り消せません。
:::

## 次に読む

- [予定・目標・バックアップ](schedule-target-backup.md)
- [サマリダッシュボード](../features/summary-dashboard.md)
