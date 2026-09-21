---
slug: /
sidebar_position: 1
title: obsidian-ai-hub ユーザーガイド
---

# obsidian-ai-hub ユーザーガイド

obsidian-ai-hub は、Obsidian のデイリーノートを中心とした個人向けの自動化ツールキットです。
Inbox の取り込み、日次・週次・月次のサマリ生成、今日の予定通知、リサーチ収集、
AI エージェントやコーディング CLI の実行、承認待ち（HITL）の処理などを、CLI とローカル Web UI から操作できます。

このガイドは、導入手順から日常利用、主要機能、設定、トラブル対応までを
実際の操作に沿って説明します。

## このガイドの読み進め方

1. **[はじめに](getting-started/overview.md)** — 製品の全体像、インストール、Web UI の起動。
2. **[日常のワークフロー](daily/cli-basics.md)** — CLI の基本と、日々の自動化コマンド。
3. **[ワークフロー（グラフ実行）](workflow/index.md)** — 人間が GUI で設計する Node / Edge グラフの使い方。
4. **[主な機能](features/memory.md)** — メモリ、リサーチ、AI エージェント、ジョブ管理など各機能の操作。
5. **[設定](settings/configuration.md)** — `.env` と `config/config.yml` の役割分担。
6. **[運用](operations.md)** / **[トラブルシューティング](troubleshooting.md)** — サーバー運用と困ったときの対処。
7. **[リファレンス](reference/cli.md)** — CLI 一覧、ジョブのスケジュール指定、Web UI の画面マップ。

## 前提

- macOS 上での個人利用を想定しています。カレンダー・リマインダー連携や画面キャプチャは macOS の機能を使います。
- Python の依存関係は `uv` で管理されています。
- Web UI はローカル（既定 `http://127.0.0.1:8765`）で動作し、すべての API は Bearer トークン認証を要求します。

:::note[表記について]
コマンド例の `python -m obsidian_ai_hub` は、リポジトリを `uv` でセットアップした環境では
`uv run -m obsidian_ai_hub` としても実行できます。以降は特に断りのない限り `uv run -m obsidian_ai_hub` を用います。
:::
