---
sidebar_position: 2
title: インストールと初期設定
---

# インストールと初期設定

## 1. リポジトリを取得する

リポジトリを clone したディレクトリで作業します。

```bash
git clone <repository-url>
cd obsidian-daily-merge
```

## 2. 依存関係をインストールする

Python の依存関係は `uv` で管理されています。

```bash
uv sync
```

Web UI を使う場合は、フロントエンドもビルドします。

```bash
make build-web
```

`make build-web` は `frontend/` で `npm ci && npm run build` を実行し、`frontend/dist` を生成します。
Web UI を表示するにはこのビルドが必要です（未ビルドの場合、`http://127.0.0.1:8765` はセットアップ手順を返します）。

## 3. 設定ファイルを作る

設定は「秘密情報」と「公開設定」に分かれています。

```bash
cp config/config.example.yml config/config.yml
cp .env.example .env
```

| ファイル | 置くもの |
| --- | --- |
| `.env` | 秘密情報・API キー・トークン・マシン固有の絶対パス |
| `config/config.yml` | 秘密でないアプリ設定・Vault 内の相対パス・バックアップ対象・機能の既定値 |

### `.env` で最低限設定するもの

`.env.example` に記載されている主な項目:

- `OBSIDIAN_AI_HUB_API_TOKEN` — Web UI / API の Bearer トークン。**空だとサーバーは起動できません。**
- `VAULT_PATH` — Obsidian Vault の絶対パス。
- `LOCAL_MODEL_DIR` — ローカル埋め込みモデルのダウンロードキャッシュ。
- `AI_LOG_PATH` — AI ログの出力先。
- LLM / 外部サービスを使う場合: `OPENAI_API_KEY`、`GEMINI_API_KEY`、`TAVILY_API_KEY`、`OPENCODE_API_KEY`、`OPEN_WEB_UI_API_KEY` など。
- LINE 連携を使う場合: `LINE_MESSAGING_TOKEN`、`LINE_CHANNEL_SECRET`、`LINE_ALLOWED_USER_IDS`、`LINE_TARGET_ID`。
- Apple カレンダー連携を使う場合: `APPLE_CALENDAR_NAME`。
- `OBSIDIAN_AI_HUB_WEB_URL` — LINE 通知などに載せる公開ベース URL。

### `config/config.yml` で設定するもの

- `vault` / `files` — Vault 内のフォルダ名とファイル名。
- `backup.sync_folders` — `--backup` の rsync 対象（source / destination）。
- `llm.<name>` — 用途ごとの LLM プロバイダ・モデル・プロンプト上書き。
- `research` — リサーチの既定出力スタイル・文脈収集・ディープリサーチ設定。
- `vault_index` — Vault 検索インデックスの保存先と埋め込みモデル。
- `coding` — コーディングのオーケストレーターと OpenCode ACP 設定。
- `healthcare` — Apple Health の取り込み設定。
- `youtube` — 文字起こし言語や Whisper モデル。

詳細は [設定](../settings/configuration.md) を参照してください。

## 4. テストで動作確認する

データを書き込むテストは、隔離されたテスト環境で実行します。

```bash
uv run pytest tests/
```

`tests/conftest.py` が本番の `.env` を読み込まず、書き込み先を一時ディレクトリへリダイレクトするため、
本番データベースには影響しません。

## 5. LaunchAgent として常駐させる（任意）

日常的に自動実行する場合は LaunchAgent に登録します。

```bash
chmod +x install.sh
make install
make enable
make status
```

HITL の常駐ワーカーも使う場合:

```bash
make install-hitl-worker
make enable-hitl-worker
make status-hitl-worker
```

両方まとめて登録する場合は `make install-all` を使います。

| Make ターゲット | 目的 |
| --- | --- |
| `make start` / `make stop` / `make restart` | 本体サービスの起動・停止・再起動 |
| `make reload` | plist を再読み込みする（設定変更時） |
| `make logs` / `make errorlogs` | 標準ログ / エラーログを表示 |
| `make restart-hitl-worker` | HITL ワーカーを再起動 |

## プロンプトをカスタマイズする場合

同梱のプロンプトファイルを直接編集しないでください。標準プロンプトを任意のローカルパスへコピーし、
`config/config.yml` の `llm.<name>.prompt_path` をそのコピー先に向けます。

```bash
cp config/prompts/make_today_target.md ~/Documents/custom-make_today_target.md
```

```yaml
llm:
  make_today_target:
    provider: ollama
    model: glm-4.7:cloud
    prompt_path: /Users/you/Documents/custom-make_today_target.md
```

## 次に読む

- [サーバーと Web UI](web-ui.md)
- [設定](../settings/configuration.md)
