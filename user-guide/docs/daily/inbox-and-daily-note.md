---
sidebar_position: 2
title: Inbox とデイリーノート
---

# Inbox とデイリーノート

## Inbox をデイリーノートへ取り込む

Obsidian の Inbox フォルダに保存したメモを、デイリーノートへ取り込みます。

```bash
uv run -m obsidian_ai_hub --merge-inbox
```

- 取り込んだ件数と失敗件数が結果として表示されます。
- `processed == 0 and failed == 0` の場合は実行ログへの記録を抑えつつ、ジョブ状態は更新されます。

### 取り込みの挙動

- Inbox ファイルの更新直後の競合を避けるため、`mtime` が直近 5 秒以内のファイルは次回実行へ回されます（待機はせず、1 回の stat チェックのみ）。
- iCloud でオフロードされているファイルはダウンロードし、最大 60 秒待ちます。
- 音声の文字起こし（Whisper）はその CLI プロセス内でのみロードし、終了時に解放されます。

## 今日の目標を作る

過去のデイリーノートをもとに、今日の目標を生成して書き込みます。

```bash
uv run -m obsidian_ai_hub --make-target
```

生成には `llm.make_today_target` のプロバイダ・モデルが使われ、承認済みの長期メモリが文脈として自動的に付加されます（[長期メモリ](../features/memory.md) を参照）。

## Inbox を素早く処理する

ほぼリアルタイムに Inbox を処理したい場合は、ジョブで `merge_inbox` を `type: minutely` として登録します。
job runner は 60 秒ごとに起動するため、通常は保存から約 1 分以内に取り込まれます。
詳細は [ジョブ管理](../features/jobs.md) を参照してください。

## 画面キャプチャと活動ログ

macOS の画面キャプチャを Inbox に保存します。

```bash
uv run -m obsidian_ai_hub --screenshot --display 2
```

`--display` はキャプチャするディスプレイ番号（既定 `1`）です。

最前面の LINE ウィンドウから未読候補を抽出します。

```bash
uv run -m obsidian_ai_hub --scan-line-inbox
```

ウィンドウ情報・スクリーンショット・OCR・要約を含む活動ログを記録します。

```bash
uv run -m obsidian_ai_hub --log-activity
```

## Vault の同期とインデックス

Vault 全体を検索インデックス（`md-hybrid-search`）へ同期します。SQLite / Chroma のデータは既定で Vault の外に保存されます。

```bash
uv run -m obsidian_ai_hub --sync-vault
```

インデックスを完全に再構築します。

```bash
uv run -m obsidian_ai_hub --rebuild-vault
```

設定した Open WebUI のナレッジベースへ Vault を同期します。

```bash
uv run -m obsidian_ai_hub --sync-knowledge
```

人物候補の未解決分や重複した `people` 行を、Vault の人物ノート（`aliases` メタデータ）に対応する正規レコードへ統合します。

```bash
uv run -m obsidian_ai_hub --sync-people
```

## Vault を検索する

インデックス化された Vault を検索します。

```bash
uv run -m obsidian_ai_hub --vault-search --query "project planning" \
  --k 5 --search-mode hybrid --json
```

- `--k` は結果件数（既定 `10`）。
- `--search-mode` は `similarity` / `keyword` / `hybrid`（既定）。
- `--json` は機械可読な JSON を出力します。

Web UI の **Vault 検索**（`/vault-search`）からも同じ検索を実行できます。

## 次に読む

- [サマリ](summaries.md)
- [予定・目標・バックアップ](schedule-target-backup.md)
