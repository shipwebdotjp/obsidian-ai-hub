---
sidebar_position: 3
title: サーバーと Web UI
---

# サーバーと Web UI

## サーバーを起動する

```bash
make serve
# または
uv run -m obsidian_ai_hub --serve
```

既定では `http://127.0.0.1:8765` で待ち受けます。ブラウザで開いてください。

:::warning[トークンは必須です]
`OBSIDIAN_AI_HUB_API_TOKEN` が空の場合、サーバーは起動に失敗します。
ループバック（`127.0.0.1`）にバインドしていても認証は免除されません。
:::

### オプション

| オプション | 既定 | 説明 |
| --- | --- | --- |
| `--serve-host` | `OBSIDIAN_AI_HUB_HOST` または `127.0.0.1` | 待ち受けアドレス |
| `--serve-port` | `OBSIDIAN_AI_HUB_PORT` または `8765` | 待ち受けポート |
| `--debug` | 無効 | `--serve` と併用すると自動リロードと詳細ログを有効化 |

```bash
uv run -m obsidian_ai_hub --serve --serve-port 9000
uv run -m obsidian_ai_hub --serve --debug
```

`--serve-host` で外部に公開する場合は、リバースプロキシ等で TLS を終端し、
`OBSIDIAN_AI_HUB_API_TOKEN` を設定したうえで利用してください。

## トークンを入力する

初回アクセス時、トークンが未保存なら入力画面（TokenPrompt）が表示されます。
`.env` の `OBSIDIAN_AI_HUB_API_TOKEN` と同じ値を入力してください。
トークンはブラウザのローカルストレージに保存され、以降の API リクエストの
`Authorization: Bearer <token>` ヘッダーに付与されます。

- トークンを変更・削除するには、サイドバー最下部の **設定**（`/settings`）を開きます。
- トークンが失効すると、再度入力画面が表示されます。

## 接続の確認

認証不要のヘルスチェックがあります。

```bash
curl http://127.0.0.1:8765/health
# {"status":"ok","auth_required":true}
```

API はすべて `/api/v1/...` 配下にあり、Bearer トークンが必要です。

## 画面構成

サイドバーから次の画面へ移動できます。

| 画面 | パス | 用途 |
| --- | --- | --- |
| メモリ | `/memories` | 長期メモリ候補のレビュー・承認 |
| リサーチ | `/research` | リサーチの実行と結果確認 |
| AIエージェント | `/agents` | 汎用エージェントとの会話 |
| コーディング | `/coding` | OpenCode ACP によるコーディング会話 |
| 確認待ち | `/hitl` | 承認・回答待ちタスクの処理 |
| Vault 検索 | `/vault-search` | Vault の全文／意味検索 |
| サマリダッシュボード | `/summary-dashboard` | 日次・週次・月次サマリの閲覧・編集 |
| ヘルスケア | `/healthcare` | Apple Health データの可視化 |
| 人物管理 | `/people` | 人物候補の解決・重複統合 |
| プロジェクト管理 | `/projects` | プロジェクトの追跡 |
| ジョブ管理 | `/jobs` | 定期・ワンショットジョブの管理 |
| Task Agent | `/task-agent` | 自由文依頼の計画・承認・実行 |
| ワークフロー | `/workflows` | Node / Edge グラフの設計と実行 |
| 実行ログ | `/execution-logs/logs`, `/execution-logs/job-states` | CLI / LLM 実行ログ、ジョブ状態 |
| プランナー | `/planner` | AI 提案の確認と Apple への登録 |
| 設定 | `/settings` | API トークン、チャット入力の送信方法 |

アプリのルート `/` と未定義のパスは `/memories` へリダイレクトされます。

## チャット入力の送信キー

**設定** 画面で、メッセージ入力欄の Enter の挙動を選べます。

- **Enter で送信（Shift+Enter で改行）**
- **Enter で改行（Ctrl/Cmd+Enter で送信）**

## 次に読む

- [CLI の基本](../daily/cli-basics.md)
- [運用](../operations.md)
