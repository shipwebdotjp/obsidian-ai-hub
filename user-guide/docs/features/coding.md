---
sidebar_position: 4
title: コーディング
---

# コーディング

**コーディング** 画面（`/coding`）は、リポジトリを対象にしたコーディング作業を
会話形式で進める機能です。バックエンドは **OpenCode ACP** に一本化されています。

## 二層構成

コーディングは次の二層で動きます。

- **Coordinator（進行役の LLM）** — 進捗・質問・最終要約だけを担当します。
- **Worker（外部 CLI）** — リポジトリ調査・実装・テスト・技術判断を担当します。

Coordinator は応答本文に `<cli_request>` を出力してタスクを委譲します。
アプリがそれを抽出して Worker を実行し、Worker の出力を次ターンの観測として返します。
Coordinator が `run_shell` などのツールで CLI を起動することはなく、バックエンド名は Coordinator に開示されません。

## Web UI で使う

1. 左サイドバーでプロジェクトとセッションを選びます。
2. セッションが無い場合は **+ 新規** で作成します（プロジェクトが必要）。
3. 入力欄からメッセージを送ります（**送信**）。実行中の会話は **キャンセル** できます。
4. Worker（実行担当の外部 CLI）のモデルを変えるには、入力欄の **Worker:** の横のセレクタで選びます（次回送信から適用）。
5. **会話設定 ⚙** で、そのセッションの **オーケストレーター（進行役）のモデル** と、許可するツールを調整できます。オーケストレーターを「既定を使用」にすると `coding.orchestrator` の設定が使われます。
6. **既定設定** で、新規会話に適用する既定ツールセットを設定できます。

セッションタイトルは **セッションタイトル** 入力で変更できます。

## CLI で使う

新規セッションは `--project-id`、再開は `--resume-session` を指定します。
プロンプトは位置引数として渡すか、stdin から読み取ります。

```bash
uv run -m obsidian_ai_hub --coding --project-id 42 "このモジュールのテストを追加して"
uv run -m obsidian_ai_hub --coding --resume-session asess_1234567890ab "続きを進めて"
cat prompt.txt | uv run -m obsidian_ai_hub --coding --project-id 42
```

`--json` で結果を JSON として出力できます。

## 設定

`config/config.yml` の `coding` で設定します。環境変数が YAML より優先されます。

```yaml
coding:
  orchestrator:
    provider: openai        # openai | ollama | gemini | opencode_go | local
    model: gpt-5.6-terra
  cli:
    opencode_path: /path/to/your/opencode   # 既定: PATH 上の opencode
  acp:
    opencode_model: opencode-go/muse-spark-1.3-contributor
    opencode_models:
      - opencode-go/muse-spark-1.3-contributor
```

| 設定 | 環境変数 | 既定 |
| --- | --- | --- |
| `coding.orchestrator.provider` | `CODING_ORCHESTRATOR_PROVIDER` | `openai` |
| `coding.orchestrator.model` | `CODING_ORCHESTRATOR_MODEL` | `gpt-5.6-terra` |
| `coding.cli.opencode_path` | `CODING_OPENCODE_CLI_PATH` | `opencode` |
| `coding.acp.opencode_model` | `CODING_OPENCODE_MODEL` | `opencode-go/muse-spark-1.3-contributor` |
| `coding.acp.opencode_models` | `CODING_OPENCODE_MODELS` | 上記 1 件 |

- 使用モデルは毎ターンの prompt 前に `session/set_model` で固定されます。拒否された場合はそのターンが失敗します。
- 選択できるモデルは `opencode_models` の許可リストに限られます。
- 旧 Direct CLI（Codex / OpenCode `run`）と Codex バックエンドは廃止済みです。既存の旧セッションは読み取り専用で、新しい実行には OpenCode ACP の新規セッションが必要です。

詳細は [コーディング設定](../settings/coding.md) を参照してください。

## 次に読む

- [Task Agent](task-agent.md)
- [コーディング設定](../settings/coding.md)
