---
sidebar_position: 2
title: リサーチ
---

# リサーチ

テーマを指定して調査を実行し、結果を Vault に保存する機能です。
テーマ候補の登録・提案も行えます。

## CLI で実行する

テーマは必須です。`--context` で背景や理由、`--output-style` で長さ（`short` / `medium` / `long`）を指定できます。

```bash
uv run -m obsidian_ai_hub --research-agent --theme "Local-first AI tools" \
  --context "Compare options for personal knowledge management" \
  --output-style medium
```

調査モードは `--research-mode` で指定します（既定は `auto`）。

| モード | 内容 |
| --- | --- |
| `auto` | ルーターが自動選択 |
| `internal` | 内省 |
| `web` | Web 検索 |
| `deep` | ディープリサーチ（GPT Researcher） |
| `project` | コードベース調査。`--project-id` が必要 |

`auto` は、テーマが登録済みの Git プロジェクト（プロジェクト画面で `project_path` が有効なリポジトリとして設定されているもの）に強く関連すると判断した場合、そのコードベースを読み取り専用で調査することがあります。その場合は自動で `project` が選ばれ、対象プロジェクトがテーマとジョブに保存されます。関連が弱い、または候補が複数ある場合は `internal` / `web` / `deep` のいずれかになります。コードベース調査が失敗した場合、他のモードへは切り替えず、そのジョブは失敗になります。

テーマ候補に追加します（任意で方向性を指定）。

```bash
uv run -m obsidian_ai_hub --add-research-theme --theme "Local-first AI tools" \
  --direction "Compare privacy and offline capabilities"
```

直近 30 日のノートからテーマ候補を 3 件生成します。

```bash
uv run -m obsidian_ai_hub --suggest-research-theme
```

`--research-agent`、`--add-research-theme`、`--suggest-research-theme` は相互に排他的です。

## Web UI で実行する

**リサーチ** 画面（`/research`）で、ステータス・テーマ・direction で絞り込み、
**新規リサーチ** から実行します。

モーダルの **モード** 選択肢:

- **自動（router）**
- **内省 (internal)**
- **ウェブ検索 (web)**
- **ディープリサーチ (deep)**
- **コードベース調査 (project)** — **対象プロジェクト** を選びます。有効な Git リポジトリのみ選べます。

実行はバックグラウンドで進み、完了すると「調査・保存・承認が完了しました」と通知されます。
つまり Web UI からのリサーチは、調査・保存・**承認まで自動**で行います（画面に個別の承認操作はありません）。

## 一覧を見る

一覧では、調査ジョブの状態を日本語バッジ（実行待ち / 実行中 / リサーチ済み / 失敗）で表示します。
ジョブがないテーマには未リサーチと表示します。
リサーチ済みの行は、入力したテーマの代わりに生成タイトルを見出しに表示し、元のテーマは副行に併記します。
リサーチ済みの行には、調査モード（内省 / ウェブ検索 / ディープリサーチ / コードベース調査）のバッジも表示します。

## 結果を見る

詳細パネルには次が表示されます。

- テーマ・ステータス・種別・confidence
- **direction**、**why_now**
- 重複情報（重複先へのリンク）、関連テーマ
- 調査メタ情報のカード（状態・モード・生成タイトル・生成日時・source・output_style）
- 結果 Markdown の本文（先頭のメタ情報行は除いて表示します）

操作:

- **HITLで回答** — ステータスが候補かつ `origin` が自動提案で `hitl_run_id` がある場合のみ表示されます。
- **再実行** — 直近のジョブが失敗した場合のみ表示されます。

## テーマ候補の提案との関係

`--suggest-research-theme` は Task Agent にジョブを投入し、最適なテーマを選んで
HITL の提案候補として登録します。候補は **確認待ち** 画面で回答・承認します。
Task Agent 側のテーマ提案では、テーマ名ではなく Task ID を冪等キーとし、1 Task につき最大 1 件を登録します。

## 設定

```yaml
research:
  default_output_style: long
  context:
    lookback_days: 7
    max_notes: 3
  deep:
    gpt_researcher:
      retriever: tavily,mcp
      fast_llm: openai:gpt-5.6-terra
      smart_llm: openai:gpt-5.6-sol
      strategic_llm: openai:gpt-5.6-terra
```

ディープリサーチ（GPT Researcher）を使うには、`TAVILY_API_KEY` などの資格情報が必要です。

## 次に読む

- [ワークフロー](workflow/index.md) の「文脈付きリサーチ」テンプレート
- [設定](../settings/configuration.md)
