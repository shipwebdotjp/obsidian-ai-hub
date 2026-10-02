---
sidebar_position: 2
title: LLM プロバイダ
---

# LLM プロバイダ

用途ごとに、`config/config.yml` の `llm.<name>` でプロバイダ・モデル・プロンプトを設定します。
プロバイダの資格情報は `.env` に置きます。

## 設定例

```yaml
llm:
  make_today_target:
    provider: ollama
    model: glm-4.7:cloud
    prompt_path: /path/to/your/config/prompts/make_today_target.md
  review_draft:
    provider: ollama
    model: glm-4.7:cloud
    prompt_path: /path/to/your/config/prompts/review_draft.md
  agent:
    provider: openai
    model: gpt-4o
  inbox_audio_correction:
    provider: ollama
    model: gpt-oss:120b-cloud
  inbox_web_summary:
    provider: openai
    model: gpt-5.4
    prompt_path: /path/to/your/config/prompts/inbox_web_summary.md
  inbox_classification:
    provider: openai
    model: gpt-5.4
    prompt_path: /path/to/your/config/prompts/inbox_classification.md
```

`review_draft` を省略した場合は `make_today_target` のプロバイダ・モデルが使われます。

## システムメンテナンス診断用の設定

```yaml
system_maintenance:
  provider: openai
  model: gpt-5.6-terra
  prompt_path: /path/to/your/config/prompts/system_maintenance_diagnosis.md
```

対象プロジェクト ID や収集期間も同じ `system_maintenance` で設定します。
詳細は [システムメンテナンス診断](../features/system-maintenance.md#設定) を参照してください。

## リサーチ用の設定

```yaml
llm:
  research:
    router:
      provider: openai
      model: gpt-5.4
      prompt_path: /path/to/your/config/prompts/research_router.md
    query_generation:
      provider: openai
      model: gpt-5.4
    title_generation:
      provider: openai
      model: gpt-5.4
    internal:
      provider: openai
      model: gpt-5.4
    web:
      provider: openai
      model: gpt-5.4
    deep:
      prompt_path: /path/to/your/config/prompts/research_deep.md
    theme_generation:
      provider: openai
      model: gpt-5.4
```

プロバイダ / モデルの選択は `config/config.yml` のみで行い、資格情報（`OPENAI_API_KEY`、
`TAVILY_API_KEY`、`OPENCODE_API_KEY` など）は `.env` に置きます。

## OpenCode Go を使う

`opencode_go` プロバイダを使うには `.env` の `OPENCODE_API_KEY` を設定します。
モデル ID の接頭辞に応じて、OpenAI 互換 / Anthropic 互換のクライアントへ自動的に振り分けられます。

- **OpenAI 互換**（`ChatOpenAI`）: `glm-`、`kimi-`、`deepseek-`、`mimo-`
- **Anthropic 互換**（`ChatAnthropic`）: `minimax-`、`qwen3.7-`、`qwen3.6-`

```yaml
llm:
  make_today_target:
    provider: opencode_go
    model: deepseek-v3
```

OpenCode Go の既定セッション識別子は `llm.opencode_go.session_id` で指定できます
（未指定時は `x-opencode-session` に送られ、既定は `obsidian-ai-hub`）。`OPENCODE_SESSION_ID` が上書きします。

```yaml
llm:
  opencode_go:
    session_id: obsidian-ai-hub
```

## メモリ抽出・生成のプロバイダ

`memory.extractor` / `memory.renderer` で指定します。詳細は [長期メモリ](../features/memory.md#設定) を参照してください。

## プロンプトのカスタマイズ

同梱プロンプトを直接編集せず、コピー先を `prompt_path` に向けます。

```bash
cp config/prompts/make_today_target.md ~/Documents/custom-make_today_target.md
```

## 次に読む

- [設定の構成](configuration.md)
- [コーディング設定](coding.md)
