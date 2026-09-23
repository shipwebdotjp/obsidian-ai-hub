---
sidebar_position: 4
title: 予定・目標・バックアップ
---

# 予定・目標・バックアップ

## 今日の予定をノートへ書き出す

Apple カレンダー / リマインダーの予定・タスクを、今日のノートへ書き出します。

```bash
uv run -m obsidian_ai_hub --write-today-schedule
```

## 今日の予定を LINE へ通知する

今日の予定を LINE へ通知します。

```bash
uv run -m obsidian_ai_hub --notify-today-schedule
```

LINE 連携には `LINE_MESSAGING_TOKEN`、`LINE_TARGET_ID` などが必要です。

## AI プランナー提案を生成する

直近のノート・サマリ・予定の文脈から、カレンダー予定やリマインダーの提案を生成します。
提案は `planner_proposals` に保存され、LINE へ通知されます。**自動で Apple カレンダー / リマインダーへ書き込まれることはありません。**
人間が **プランナー** 画面で登録・却下します。

```bash
uv run -m obsidian_ai_hub --generate-planner-proposals
```

詳細は [プランナー](../features/planner.md) を参照してください。

## バックアップ

`config/config.yml` の `backup.sync_folders` に指定したフォルダを rsync でバックアップします。

```bash
uv run -m obsidian_ai_hub --backup
```

各ペアには任意で `excludes` を指定できます（固定の `--exclude=.DS_Store` の直後に、列挙順でそのまま渡されます）。

```yaml
backup:
  sync_folders:
    - source: /path/to/your/obsidian/Default
      destination: /path/to/your/backup/Obsidian/Default
    - source: /path/to/your/obsidian/Inbox
      destination: /path/to/your/backup/Obsidian/Inbox
      excludes:
        - node_modules/
        - "*.tmp"
```

### rsync の実行ファイルを指定する

macOS 同梱の `/usr/bin/rsync` は openrsync であり、`--delete` の削除走査中に assertion で abort することがあります。Homebrew の GNU rsync を導入し、実行ファイルを絶対パスで指定してください。

```bash
brew install rsync
brew --prefix rsync
```

`brew --prefix rsync` の出力に `/bin/rsync` を付けた絶対パスを `backup.rsync_executable` に設定します。

```yaml
backup:
  rsync_executable: /opt/homebrew/opt/rsync/bin/rsync
  sync_folders:
    - source: /path/to/your/obsidian/Default
      destination: /path/to/your/backup/Obsidian/Default
```

バックアップ開始時に、指定した実行ファイルへ `--version` を 1 度だけ実行します。起動できない場合や、設定値が空・不正な場合は、宛先ディレクトリを作成する前に停止します。出力が openrsync の場合は警告をログに残しますが、指定どおり実行を継続します（自動での再試行は行いません）。未設定の場合は従来どおり `rsync` を使用するため、openrsync の失敗が再発し得ます。


## 古いレコードのクリーンアップ

次の 2 つのコマンドは 30 日より古いレコードを削除します。

```bash
uv run -m obsidian_ai_hub --cleanup-line-webhooks
uv run -m obsidian_ai_hub --cleanup-execution-logs
```

## 次に読む

- [ワークフロー（グラフ実行）](../workflow/index.md)
- [ジョブ管理](../features/jobs.md)
