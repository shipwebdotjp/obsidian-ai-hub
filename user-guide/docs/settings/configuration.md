---
sidebar_position: 1
title: 設定の構成
---

# 設定の構成

設定は「秘密情報」と「公開設定」に分かれています。

| ファイル | 置くもの |
| --- | --- |
| `.env` | 秘密情報・API キー・トークン・マシン固有の絶対パス |
| `config/config.yml` | 秘密でないアプリ設定・Vault 内の相対パス・バックアップ対象・機能の既定値 |

`config/config.example.yml` と `.env.example` をコピーして編集します。

```bash
cp config/config.example.yml config/config.yml
cp .env.example .env
```

## `.env` の主な項目

### 必須

- `OBSIDIAN_AI_HUB_API_TOKEN` — Web UI / API の Bearer トークン。空だとサーバーは起動しません。
- `VAULT_PATH` — Obsidian Vault の絶対パス。

### 環境・保存先

- `LOCAL_MODEL_DIR` — ローカル埋め込みモデルのダウンロードキャッシュ。
- `AI_LOG_PATH` — AI ログ出力先。
- `OBSIDIAN_AI_HUB_HOST` / `OBSIDIAN_AI_HUB_PORT` — 待ち受けアドレス / ポート。
- `HEALTHCARE_SQLITE_PATH` / `HEALTHCARE_EXPORT_DIR` — ヘルスケア DB / エクスポート先。
- `VAULT_INDEX_SQLITE_PATH` / `VAULT_INDEX_CHROMA_PATH` — Vault インデックス保存先。

### 資格情報

- LLM: `OPENAI_API_KEY`、`GEMINI_API_KEY`、`OPENCODE_API_KEY`
- 検索 / 調査: `TAVILY_API_KEY`、`HUGGINGFACE_API_KEY`
- Open WebUI: `OPEN_WEB_UI_API_KEY`、`OPEN_WEB_UI_BASE_URL`
- LINE: `LINE_MESSAGING_TOKEN`、`LINE_CHANNEL_SECRET`、`LINE_ALLOWED_USER_IDS`、`LINE_TARGET_ID`
- Apple: `APPLE_CALENDAR_NAME`
- `OBSIDIAN_AI_HUB_WEB_URL` — LINE 通知などに載せる公開ベース URL

### コーディング（任意）

`CODING_ORCHESTRATOR_PROVIDER`、`CODING_ORCHESTRATOR_MODEL`、`CODING_OPENCODE_CLI_PATH`、
`CODING_OPENCODE_MODEL`、`CODING_OPENCODE_MODELS`。設定すると YAML より優先されます。

## `config/config.yml` の構成

`config/config.example.yml` に定義されている主なトップレベルキー:

| キー | 内容 |
| --- | --- |
| `ai_log_path` | AI ログのパス |
| `vault` | Vault 内のフォルダ名（`inbox` / `daily` / `template` / `knowledge` / `research` / `activity` / `webclip`） |
| `files` | ファイル名（日次ノート、週次テンプレート、リサーチ候補テーマリストなど） |
| `backup.sync_folders` | `--backup` の rsync 対象（source / destination / 任意の excludes） |
| `backup.rsync_executable` | `--backup` で使う rsync の実行ファイル絶対パス（未設定時は `rsync`） |
| `location_map` | 場所文字列 → 表示名の変換 |
| `regularly_date_events` / `regularly_weekday_events` | 定期的な予定の定義（時刻付きも可） |
| `llm` | 用途ごとの LLM プロバイダ・モデル・プロンプト上書き（[LLM プロバイダ](llm.md)） |
| `agent_skills.root` | Agent Skills のルート |
| `research` | リサーチの既定出力スタイル・文脈・ディープリサーチ設定 |
| `vault_index` | Vault 検索インデックスの collection / 保存先 / 埋め込みモデル |
| `coding` | コーディングのオーケストレーターと OpenCode ACP 設定（[コーディング設定](coding.md)） |
| `youtube` | 文字起こし言語・Whisper モデル・要約チャンク文字数 |

`memory` と `healthcare` は任意の追加セクションです。

```yaml
memory:
  context_max_tokens: 800
  extractor:
    provider: ollama
    model: glm-4.7:cloud
  agent_conversation:
    enabled: true          # Webチャット会話を週次メモリ抽出のソースに含める
    max_messages: 300      # 1週あたりに渡すメッセージ数
    max_total_chars: 60000 # 1週あたりの合計文字数
    max_user_chars: 4000   # ユーザー発話1件の上限（0で無制限）
    max_assistant_chars: 2000  # エージェント返答1件の上限（文脈用・0で無制限）
  purposes:
    summarize-day:
      kinds: [preference, decision_policy]
      budget: 600            # ユーザースコープの文脈上限
      format: evidence       # または "fenced"
      include_person: true
      person_kinds: [fact, commitment, episode, pattern]
      person_budget: 400     # 人物スコープの別枠上限

healthcare:
  sqlite_path: /Users/you/.config/obsidian-ai-hub/healthcare.sqlite3
  export_dir: /Users/you/.config/obsidian-ai-hub/healthcare/apple_health_export
```

## プロンプトの上書き

同梱のプロンプトは直接編集せず、コピー先を `llm.<name>.prompt_path` に向けます。
詳細は [LLM プロバイダ](llm.md) を参照してください。

## テスト環境の設定

`ENV=test` のときは `config/config.test.yml` が使われ、本番の `.env` は読み込まれません。
書き込み先は一時ディレクトリへリダイレクトされます（[CLI の基本](../daily/cli-basics.md#テストモードで安全に試す) を参照）。

## 次に読む

- [LLM プロバイダ](llm.md)
- [コーディング設定](coding.md)
