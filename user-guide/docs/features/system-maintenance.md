---
sidebar_position: 14
title: システムメンテナンス診断
---

# システムメンテナンス診断

システムメンテナンス診断は、**CLI 実行ログ**（`command_runs`）と **LLM コール履歴**
（`llm_call_logs`）から失敗を検出し、原因と対策を LLM で診断して HITL に提案する仕組みです。
承認した提案は、対象プロジェクトの **コーディングタスク**として起票されます。

日次ジョブ `system_maintenance` として登録できます（`jobs/jobs.local.sample.yml` では
無効。`system_maintenance.project_id` の設定後に有効化してください）。手動でも実行できます。

```bash
uv run -m obsidian_ai_hub --system-maintenance
```

## 処理の流れ

1. 直近 24 時間（既定）の失敗と、長時間 `running` のままの実行を収集します。
2. `コマンド + 例外型 + 正規化した例外メッセージ` などの fingerprint でまとめます。
   LLM コールの失敗が CLI 実行に紐づく場合は、その実行の根拠としてまとめます。
3. 未診断の fingerprint だけを LLM に渡し、原因・対策・重要度・実装指示を
   JSON で受け取ります。**LLM に渡すのはメタデータと traceback のみ**で、
   プロンプト / レスポンス本文は渡しません。
4. 提案を HITL（`システム保守`）に登録します。LINE 通知は best-effort です。
5. 承認された提案ごとに、対象プロジェクトへコーディングタスクを 1 件起票します。
   実行は通常のコーディングワーカーが行います。

診断そのものは読み取りのみで、リポジトリを変更しません。変更は承認後の
コーディングタスクだけです。

## 設定

`config/config.yml`:

```yaml
system_maintenance:
  provider: openai
  model: gpt-5.6-terra
  project_id: 1          # 起票先の登録済みプロジェクト ID（必須）
  window_hours: 24
  max_findings: 10
  stale_running_hours: 6
  resolve_missing_runs: 3
  prompt_path: /path/to/your/config/prompts/system_maintenance_diagnosis.md
```

- `project_id` は Web UI の **プロジェクト** で登録済みの ID を指定します。
  未設定・不正な場合は診断開始時にエラーで停止し、起票は行われません。
- `window_hours` は収集対象の期間、`max_findings` は 1 回に診断する最大件数です。
- `resolve_missing_runs` 回連続で観測されなかった fingerprint は `resolved` になります。
- 環境変数（`SYSTEM_MAINTENANCE_PROJECT_ID` など）でも上書きできます。

## 提案のライフサイクル

同じ fingerprint を毎回提案しないよう、状態を `system_maintenance_findings`
テーブルに保持します。実行ログの 30 日クリーンアップとは独立しています。

| 状態 | 意味 |
| --- | --- |
| `open` | 未診断。次回の診断対象。 |
| `proposed` | HITL 提案中。 |
| `coding_created` | 承認済みでコーディングタスクを起票済み。 |
| `dismissed` | 見送り。 |
| `resolved` | 一定回数観測されず解消とみなした状態。再発時は `open` に戻る。 |

起票に失敗した場合（Web サーバー停止中など）は `open` に戻し、HITL 実行は
失敗理由を記録して終了します。次回の診断で再度提案されます。

セッションは fingerprint ごとに固定のタイトルで再利用し、`Idempotency-Key` により
再承認でも同じコーディング実行に集約されます。

## 制約

- 起票されるコーディングタスクの実行には Web サーバー（実行ワーカー）が必要です。
  承認時点でワーカーが停止している場合は起票せず、失敗として記録します。
- 収集できるのは実行ログに記録された失敗だけです。`main.py` の実行ログを通らない
  外部コマンドや、記録を経由しない一部の LLM コール（コーディングオーケストレーター、
  エージェントのサブエージェント呼び出し）は対象外です。
- 実行ログの保持は 30 日です。長期の傾向分析はこの期間に限られます。
- 自動修正は行いません。対策の適用はコーディングタスクのレビューと完了確認を経ます。

## 関連

- [実行ログ](../operations.md#実行ログを見る)
- [HITL](hitl.md)
- [コーディング](coding.md)
- [ジョブ管理](jobs.md)
