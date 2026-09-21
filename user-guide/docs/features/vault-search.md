---
sidebar_position: 9
title: Vault 検索
---

# Vault 検索

**Vault 検索** 画面（`/vault-search`）では、インデックス化された Vault を
意味検索・キーワード検索・ハイブリッド検索できます。

## 検索する

1. **検索クエリ** を入力します（Enter でも検索できます）。
2. モードを選びます。
   - **Hybrid**（既定）
   - **Keyword**
   - **Similarity**
3. 件数を選びます（**5件** / **10件** / **20件** / **50件**）。
4. **検索** を押します。

## 検索履歴

**最近の検索** に直近の検索（最大 20 件）が保存され、再実行できます。
各項目には `mode / N件` が表示されます。履歴はブラウザの localStorage に保存されます。

## 結果を見る

一覧から結果を選ぶと **検索結果プレビュー** パネルが開きます。
検索結果が見つからない場合は「検索結果が見つかりませんでした」と表示されます。

## インデックスの更新

検索対象を最新にするには、Vault の同期を行います。

```bash
uv run -m obsidian_ai_hub --sync-vault
```

インデックスを完全に再構築する場合:

```bash
uv run -m obsidian_ai_hub --rebuild-vault
```

インデックスの保存先と埋め込みモデルは `config/config.yml` の `vault_index` で設定します。

## CLI から検索する

```bash
uv run -m obsidian_ai_hub --vault-search --query "project planning" \
  --k 5 --search-mode hybrid --json
```

`--k` は結果件数（既定 10）、`--search-mode` は `similarity` / `keyword` / `hybrid`（既定 hybrid）、
`--json` は機械可読の JSON 出力です。

## 次に読む

- [Inbox とデイリーノート](../daily/inbox-and-daily-note.md)
- [サマリダッシュボード](summary-dashboard.md)
