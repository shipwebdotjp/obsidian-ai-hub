# HITL基盤MVP ToDo

## 1. 永続モデルとコアサービス

- [ ] `database.py` のスキーマをv13へ移行し、`hitl_runs` と `hitl_questions` を追加する。
  - [ ] Runにhandler、checkpoint、active question set、lease、試行回数、エラー、監査日時を持たせる。
  - [ ] Questionにset ID、key、表示順、必須フラグ、汎用表示データ、選択肢、回答、期限を持たせる。
  - [ ] `(run_id, question_set_id, question_key)` の一意制約と、待機・再開検索用インデックスを追加する。
- [ ] `obsidian_ai_hub.hitl` に、Run／質問セット登録、回答、Run取消、claim、checkpoint更新のストアとサービスを実装する。
- [ ] 質問セット登録、回答、取消を、Run状態更新を含む単一トランザクションにする。
- [ ] 必須質問が全て回答済みになったらRunを`ready_to_resume`にする。
- [ ] 任意質問はclaim時に未回答分を`skipped`へ確定し、Run取消時はactive setの待機質問をまとめて`cancelled`にする。

## 2. 再開契約とディスパッチャー

- [ ] handler registry、handler context、`answers_by_question_key`、再中断用の内部契約を定義する。
- [ ] HITLコアがドメインモジュールをimportしないよう、composition rootで機能側handlerを登録する。
- [ ] `--hitl-dispatch` を追加し、ready Runのatomic claim、handler実行、完了／失敗／再中断の状態反映を実装する。
- [ ] lease切れのrunning Runを回収し、checkpointの副作用記録を使って安全に再開する。
- [ ] 既存タスクスケジューラのプリセットに`--hitl-dispatch`を追加する。

## 3. リサーチ自動提案への接続

- [ ] `--suggest-research-theme` の重複でない自動提案だけを、即時調査ではなくHITL Run＋承認／却下質問セットとして登録する。
- [ ] テーマ作成とHITL待機登録を同一トランザクションにするため、research DB操作の接続受け渡しを整備する。
- [ ] `research.run_approved_suggestion` handlerを実装する。
  - [ ] 承認時はテーマをapprovedにし、job IDをcheckpointへ保存して調査を実行する。
  - [ ] 却下時はテーマをrejectedにし、jobを作らずRunを完了する。
  - [ ] 調査成功後はVaultへ保存してRunを完了する。
- [ ] `research_jobs` に出力先・公開完了の記録を追加し、job IDベースの決定的な出力先で再実行時の重複出力を防ぐ。
- [ ] CLI手動追加、Web新規リサーチ、`--research-agent`、再実行は即時実行・成功時自動保存を維持する。

## 4. APIとWeb UI

- [ ] `GET /api/v1/hitl/runs`、Run詳細、質問回答、Run取消APIとPydantic schemaを追加する。
- [ ] Reactに汎用の「確認待ち」画面とルート／サイドバー導線を追加する。
  - [ ] Run説明と質問セットを表示し、選択肢必須・任意コメントで回答できるようにする。
  - [ ] Run取消と、リサーチ候補から該当質問への導線を追加する。
  - [ ] リサーチ固有のフィールドを持たず、汎用title/prompt/options/contextだけで描画する。
- [ ] リサーチ画面とAPIから候補の直接承認／却下を削除し、自動提案の回答を質問キューへ一本化する。
- [ ] `frontend/AGENTS.md` の配色、カーソル、選択状態、E2E用属性の規約に従う。

## 5. テストと記録

- [ ] DB移行、複数質問セット、必須／任意質問、回答競合、Run取消、再中断、lease回収をテストする。
- [ ] リサーチの承認／却下、失敗回復、Vault出力の冪等性、自動提案のみ質問化されることをテストする。
- [ ] 手動リサーチ経路が即時実行・自動保存のまま維持されることを回帰テストする。
- [ ] API認可とReactの回答導線をテストし、重要フローのE2Eを追加する。
- [ ] `uv run pytest tests/` と `make test-e2e` を実行する。
- [ ] durableな設計判断を `ai_wiki/10-Decisions.md` に記録する。

## MVP外

- [ ] 通知、Webhook、Outbox、外部エージェント用の質問作成API。
- [ ] 期限切れの自動解決、回答履歴の改訂、質問単位の取消。
