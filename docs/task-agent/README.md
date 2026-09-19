# Task Agent 文書群

Task Agent は、自由文の依頼を内部で実行計画へ変換し、既存の AI Agent、Coding CLI、
安全に限定した既存ツールへ委譲する個人用オーケストレーターである。

計画に `plan_required` Capability が含まれるときだけ、WebUI で一括承認を求める。
すべてが `auto` Capability の計画は、記録を残して自律実行する。MVP は、実行能力を
増やすことより、承認境界、停止、結果追跡を既存基盤に重複なく統合することを優先する。

## 文書一覧

| 文書 | 役割 |
| --- | --- |
| [CONTEXT.md](../../CONTEXT.md) | 用語、境界、不変条件 |
| [specification.md](specification.md) | 確定済みの外部契約と振る舞い（MVP 実装済み） |
| [post-mvp.md](post-mvp.md) | MVP後に再検討する未実装の機能・運用項目 |
| [proactive-plan.md](proactive-plan.md) | 自発性・成長支援のロードマップと設計候補（Phase A-C、実装未着手） |
| [adr/](adr/) | 変更コストが高い設計判断 |

実装手順・完了済み TODO は Git 履歴に残し、恒久の判断は [adr/](adr/) と `ai_wiki/` の決定記録を正とする。

## 設計上の要点

- CLI の入口は `python -m obsidian_ai_hub --task-agent "依頼"`。Task ID、状態、
  詳細URLを返して終了する。
- WebUI は `/task-agent/:id` にTask一覧・詳細を置き、既存の Scheduler Job 管理画面 `/jobs`
  と分ける（2026-09 の改称で `/tasks` から移動。詳細は [README.md](../../README.md#job-runner)）。
- Task worker は FastAPI の既存 worker lifespan に同居する。Webサーバー停止中は新規の
  計画・実行を行わない。
- Capability のAdapter定義はコードで固定し、DBと設定UIでは有効/無効と承認ポリシーだけを
  管理する。任意shell、Skills、カスタムプラグインは Capability 自動同期により既定
  `plan_required` で公開済み（[post-mvp.md](post-mvp.md#実装済みになった候補) 参照）。`ask_user` と
  `agent_delegate` は Task Capability から除外する。
- 外部への直接書込み（カレンダー、リマインダー）は対象外。カレンダー/リマインダーへの追加は既存の提案HITL登録ツール（`calendar_create_proposal` / `reminder_create_proposal`）経由のみ行い、人間の承認はHITL側で行うため、auto時のPlan確認は不要。Vault直接編集は `vault_write_file` Capability経由のみ許可し、既定 `plan_required` でPlan一括承認を要する。

## 運用上の要点

- Task worker は Web サーバーの FastAPI worker lifespan に同居する。
  **Web サーバー停止中は新規の計画・実行を行わず、Task はキューに残る。**
  停止時に `planning` / `running` / `cancelling` だった Task は `interrupted`
  になり、自動再実行はしない。WebUI の再計画から明示的に `queued` へ戻す。
- 終端化から 30 日後の起動時 maintenance で Task・Plan・Event をまとめて削除
  する（cascade）。非終端 Task は削除しない。
- 依頼本文・Plan・Event・要約は既知の設定済み秘密値を redact して保存する。
  LLM の非公開思考過程や全出力は保存しない。**未知の秘密値を依頼本文に
  含めないことは利用者の運用責任である。**
- 子 Agent / Coding run の既存制限はそのまま継承する（Coding CLI 反復上限
  50 回など）。Task 固有の実行上限・自動リトライ・自動ロールバックは持たない。

## 実装の進め方

フェーズ単位で次のループを回す。

1. フェーズごとにプランを作成して提案する
2. プラン承諾後に Build モードへ移行して実装する
3. 実装後、テスト通過を確認して `ocr` でレビューする(1回目)
4. レビュー指摘のうち正当なものだけを修正する
5. 再レビューはせずコミットする
6. 次のフェーズへ進む

## 文書同期規則

1. 状態識別子とCapability keyは [specification.md](specification.md) を正とする。
2. 振る舞いは仕様書、判断理由はADRに記す。実装手順や進捗はリポジトリ文書として維持しない。
3. 承認ポリシー、Capability登録、実行境界を変更する際は、対応するADRと `CONTEXT.md` を
   同時に更新する。
