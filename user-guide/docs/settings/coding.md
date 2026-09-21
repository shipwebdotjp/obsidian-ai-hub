---
sidebar_position: 3
title: コーディング設定
---

# コーディング設定

コーディングは、進行役の Coordinator LLM と、技術的な実行を担う外部 CLI Worker（OpenCode ACP）の
二層構成です。`config/config.yml` の `coding` で設定します。環境変数が設定されている場合は YAML より優先されます。

```yaml
coding:
  orchestrator:
    provider: openai        # openai | ollama | gemini | opencode_go | local
    model: gpt-5.6-terra
  cli:
    opencode_path: /path/to/your/opencode
  acp:
    opencode_model: opencode-go/muse-spark-1.3-contributor
    opencode_models:
      - opencode-go/muse-spark-1.3-contributor
```

| 設定 | 環境変数 | 既定 |
| --- | --- | --- |
| `coding.orchestrator.provider` | `CODING_ORCHESTRATOR_PROVIDER` | `openai` |
| `coding.orchestrator.model` | `CODING_ORCHESTRATOR_MODEL` | `gpt-5.6-terra` |
| `coding.cli.opencode_path` | `CODING_OPENCODE_CLI_PATH` | `opencode`（PATH 上） |
| `coding.acp.opencode_model` | `CODING_OPENCODE_MODEL` | `opencode-go/muse-spark-1.3-contributor` |
| `coding.acp.opencode_models` | `CODING_OPENCODE_MODELS`（カンマ区切り） | `opencode_model` の 1 件 |

## Coordinator の役割

- Coordinator は進捗・質問・最終要約だけを扱います。
- リポジトリ調査・実装・テスト・技術判断は Worker が担います。
- Coordinator は応答本文に `<cli_request>` を出力して委譲し、アプリが Worker を実行して結果を次の観測として返します。
- Coordinator がツール経由で外部 CLI を起動することはなく、バックエンド名は開示されません。

## Worker（OpenCode ACP）のモデル

- 使用モデルは毎ターンの prompt 前に `session/set_model` で固定されます。拒否された場合、そのターンは失敗します。
- セッション作成時・ステータスバーで選択できるモデルは `opencode_models` の許可リストに限られ、自由入力は拒否されます。

## バックエンド

コーディングは **ACP 一本化（OpenCode のみ）** です。
旧 Direct CLI（Codex / OpenCode `run`）と Codex バックエンドは削除済みで、
既存の Direct CLI / Codex セッションは読み取り専用です。新しい実行には OpenCode ACP の新規セッションが必要です。

## トラブルシューティング

- **Coordinator が応答しない / 委譲しない** — `coding.orchestrator` のプロバイダ・モデルと資格情報を確認します。
- **Worker が起動しない** — `coding.cli.opencode_path` が実行可能な `opencode` を指しているか、PATH が通っているか確認します。
- **モデル変更が反映されない** — モデル変更は **次回送信から** 適用されます。また許可リスト外のモデルは拒否されます。

## 次に読む

- [コーディング](../features/coding.md)
- [設定の構成](configuration.md)
