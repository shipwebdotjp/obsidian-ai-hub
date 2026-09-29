---
sidebar_position: 1
title: 長期メモリ
---

# 長期メモリ

長期メモリは、ノートから抽出した「好み・方針・事実・約束・パターン・エピソード」を
レビューして承認し、生成処理の文脈として再利用する仕組みです。
**新しいメモリは必ず候補として作られ、人間のレビューを経てから使われます。**

## 候補を抽出する

直近の完了した月〜日曜の週から候補を抽出します。

```bash
uv run -m obsidian_ai_hub --memory-extract
uv run -m obsidian_ai_hub --memory-extract --week 2026-07-13
```

- 7 日分のデイリーノートと日次構造化レコードを対象にします。各ノートは `## AIによる要約` までを使い、活動ログは別途渡しません。
- [AIエージェント](agents.md) の **Webチャット会話** も対象にします（Task Agent・ワークフローのセッションは対象外）。
  - 候補になるのは **ユーザー自身の発話** だけです。エージェントの返答は文脈としてのみ渡され、根拠の検証で候補から除外されます。
  - この機能の導入前に作成されたセッションは対象外です（新規セッションから抽出します）。
  - 会話本文は抽出LLMプロバイダへ送信されます。扱いが気になる会話は送らないでください。
  - 週ごとの投入量は `memory.agent_conversation` で制限できます（[設定](../settings/configuration.md)）。
- カテゴリ: `preference` / `decision_policy` / `fact` / `commitment` / `pattern` / `episode`。
- 各候補は根拠・抽出信頼度・重複や置換の候補を持ちます。信頼度は承認推奨ではなく、**根拠を確認**してください。
- `pattern` は 2 日以上異なる日の根拠を要求します。

## インタビュー質問を生成する

週のデイリーノートからパーソナライズされた質問を生成し、LINE または Web UI で回答を集めて候補化します。

```bash
uv run -m obsidian_ai_hub --memory-interview
uv run -m obsidian_ai_hub --memory-interview --memory-interview-week 2026-07-13
```

## CLI でレビューする

候補 ID を指定して承認・却下します。

```bash
uv run -m obsidian_ai_hub --memory-review --id mem_20260713_51609b --approve
uv run -m obsidian_ai_hub --memory-review --id mem_20260713_3907c3 --reject
```

内容を修正して承認する場合:

```bash
uv run -m obsidian_ai_hub --memory-review --id mem_20260713_f2ec1b \
  --edit --content "Prefer concise Japanese responses."
```

完全に削除する場合（確認プロンプトあり、`--yes` で省略）:

```bash
uv run -m obsidian_ai_hub --memory-delete --id mem_20260713_f2ec1b
uv run -m obsidian_ai_hub --memory-delete --id mem_20260713_f2ec1b --yes
```

## Web UI でレビューする

**メモリ** 画面（`/memories`）では次ができます。

- ステータス（候補 / 承認済み / 却下済み / 期限切れ / 置換済み）・本文・種別・人物・トピックで絞り込む。
- 個別の **承認** / **却下**、詳細パネルでの **編集して承認** / **削除**。
- ページ全選択や選択行に対する **一括承認** / **一括却下** / **一括削除**。
- 詳細パネルで根拠、重複・置換提案、来歴を確認する。
- **重複・置換レビューと競合防止**: LLM 重複・置換判定が提示された候補に対してマージや置換を実行する際、対象の既存記憶が判定時点から変更・削除された場合や、判定時の指紋（fingerprint）情報が未保存の旧候補の場合、誤った上書きを防ぐため即座に操作が停止（HTTP 409 `dedup_reassessment_required`）し、候補は「再判定待ち」状態へ移行します。
- **再判定待ちの画面表示**: 再判定待ちの候補では画面上で注意バナーが表示され、対象メモリを書き換えるボタン（マージ、置換、既存を候補で更新など）が無効化されます。「新規として保存」や「編集して承認」はそのまま実行可能です。
- **プロファイル生成** で Copilot プロファイル（Vault 内の 7 ファイル）を生成・上書きする。

:::warning[一括削除は取り消せません]
**一括削除** と詳細の **削除** は完全削除で、取り消せません。
:::

## 生成処理での利用

承認済みメモリは、用途ごとの方針に従って小さな参照セクションとして生成プロンプトへ付加されます。
`--memory-compile --for <purpose>` で、実際に使われる文脈を確認できます。

```bash
uv run -m obsidian_ai_hub --memory-compile --for make-target
```

組み込みの用途:

| `--for` | 使う種類 |
| --- | --- |
| `make-target` | すべて。evidence 形式、ユーザースコープのみ |
| `planner` | すべて。evidence 形式、ユーザースコープのみ |
| `review-draft` | 好みと意思決定方針。Fenced 形式 |

日次・週次・月次の構造化要約には長期記憶を注入しません。対象期間の入力データだけを根拠に生成します。
`config/config.yml` に残っている `memory.purposes.summarize-day` / `summarize-week` / `summarize-month` の設定は要約生成では参照されないため、削除できます。

`--for` に未知の値を渡すと、既定（すべて・`memory.context_max_tokens`・evidence 形式・ユーザースコープのみ）にフォールバックします。
方針は `config/config.yml` の `memory.purposes` で上書きできます（全項目の例は [設定](../settings/configuration.md) を参照）。

## メンテナンス

承認済みメモリを診断し、キー・本文・ベクトル類似でグルーピングして、LLM がマージ・修正・失効のアクションを提案します。
提案は HITL の Run として登録され、**確認待ち** 画面でレビューします。

```bash
uv run -m obsidian_ai_hub --memory-maintain
```

- **月次競合再判定**: 実行開始時に「再判定待ち」の候補および旧形式の重複・置換候補を検出し、最新の承認済み記憶と照合して提案と指紋情報（fingerprint）を自動更新します。
- 照合の結果、重複対象が存在しなくなった候補は新規候補（New）に戻り、再び通常の承認レビューが可能になります。
- LLM 応答失敗時は「再判定待ち」を維持し、次回の実行時に再試行します。
- 再判定は提案の更新のみであり、対象メモリのマージや置換が自動適用されることはありません（最終的な適用は常にユーザーが行います）。

## Copilot プロファイルを生成する

現在有効な承認済みメモリから、Copilot 用のプロファイル指示ファイルを生成または完全上書きします。

```bash
uv run -m obsidian_ai_hub --render-copilot-profile
```

上書きされるファイル（Vault 配下）:

- `copilot/AI_README.md`
- `copilot/core/values.md`
- `copilot/core/response_style.md`
- `copilot/core/decision_policy.md`
- `copilot/core/risk_tolerance.md`
- `copilot/core/memory_rules.md`
- `copilot/core/current_projects.md`

:::warning[手書き内容は失われます]
生成はこれら 7 ファイルを完全に上書きします。手書きの内容がある場合は退避してください。
承認済みメモリが無い場合でも、全 7 ファイルがフォールバック文言「現時点で承認済みメモリなし」で生成されます。
:::

## 設定

```yaml
memory:
  context_max_tokens: 800
  extractor:
    provider: ollama
    model: glm-4.7:cloud
    # prompt_path: /Users/you/Documents/custom-memory-extract.md
  renderer:
    provider: openai
    model: gpt-4o
    prompt_path: /Users/you/Documents/custom-memory-render.md
```

`extractor` を省略すると、日次目標の LLM プロバイダ・モデルが使われます。
`renderer` は provider / model を省略すると extractor の設定を継承し、`prompt_path` は
既定で `config/prompts/memory_render.md` になります。

## 次に読む

- [サマリ](../daily/summaries.md)
- [設定](../settings/configuration.md)
