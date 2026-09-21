---
sidebar_position: 5
title: Task Agent
---

# Task Agent

Task Agent は、自由文の依頼を内部で実行計画（Plan）へ変換し、承認ポリシーに従って
既存の AI Agent・Coding CLI・安全に限定したツールへ委譲する個人用オーケストレーターです。

## 依頼を投入する

```bash
uv run -m obsidian_ai_hub --task-agent "Summarize this week's schedule"
```

コマンドは Task を作成し、Task ID・状態・詳細 URL を表示してすぐ終了します。
計画と実行は Web サーバープロセスが行います。

Web UI の **Task Agent** 画面（`/task-agent`）では、**新規作成** から依頼を投入できます。

:::note[Workflow の実行は一覧に表示されません]
Workflow の Capability Node 実行は、内部の子 Run 連携・取消・監査のために短命の内部
Task（origin `workflow`）を使います。これは依頼した Task ではないため、Task Agent の
一覧・件数には表示されません。監査上必要な場合は Task 詳細 URL を直接開くと閲覧できます。
:::

## 承認と実行

- 計画に `plan_required` の Capability が含まれる場合だけ、Web UI で一括承認を求めます（`waiting_approval` / `waiting_reapproval`）。
- すべて `auto` Capability の計画は、記録を残して自律実行されます。

Task 詳細の操作:

| ボタン | 条件 |
| --- | --- |
| **承認** | `waiting_approval` / `waiting_reapproval` |
| **差戻し** | 理由（必須）を入力して計画を差し戻す |
| **取消** | 非終端。実行中は「実行中の子runを停止して取消」 |
| **再計画** | `interrupted` のとき |
| **対象を変更して再計画** | 対象 Project / 一般Task を変更する（現行 Plan は破棄される） |

:::note[承認対象]
承認対象は方向性（Directional Plan）と Capability の範囲です。
詳細な引数は実行時に確定し、履歴に記録されます。旧形式の静的 Plan は保存済み入力で実行されます。
:::

## Capability 設定

**Task Agent** 画面の歯車から **Task Capability設定**（`/task-agent/capabilities`）を開きます。
Adapter 定義はコードで固定されており、ここでは次だけを変更できます。

- **有効** — Capability の有効 / 無効。
- **承認ポリシー** — `auto(承認不要)` または `plan_required(Plan一括承認)`。

Capability の追加・削除はできません。

## 運用上の注意

- Task worker は Web サーバーの FastAPI lifespan に同居します。**サーバー停止中は新規の計画・実行を行わず、Task はキューに残ります。**
- 停止時に `planning` / `running` / `cancelling` だった Task は `interrupted` になり、自動再実行されません。Web UI の **再計画** で明示的に戻します。
- 終端化から 30 日後に Task・Plan・Event がまとめて削除されます。非終端 Task は削除されません。
- 依頼本文・Plan・Event・要約は既知の設定済み秘密値を redact して保存します。**未知の秘密値を依頼本文に含めないことは利用者の責任です。**
- 子 Agent / Coding Run の既存制限をそのまま継承します（例: Coding CLI の反復上限 50 回）。
- Task 固有の実行上限・自動リトライ・自動ロールバックはありません。

## 関連機能

- あらかじめ人間が設計した定型フローを繰り返す場合は [ワークフロー](../workflow/index.md)。
- 個別の会話は [AIエージェント](agents.md)、コーディングは [コーディング](coding.md)。

## 次に読む

- [ワークフロー](../workflow/index.md)
- [ジョブ管理](jobs.md)
