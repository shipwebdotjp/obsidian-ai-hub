# Task Agent TODO

仕様は [specification.md](specification.md)、実装順序は
[implementation-plan.md](implementation-plan.md) を正とする。

## 文書と判断記録

- [x] `CONTEXT.md` とTask Agent文書群の状態・承認ポリシーを同期する
- [x] 承認境界、Capability Manifest、Workspace信頼境界のADRを更新する
- [ ] Webサーバー同居workerと入力保存の運用をREADMEへ追記する

## 永続化とコア

- [x] v44 migrationで `task_agent_*` の4テーブルと索引を追加する
- [x] コード定義Capability catalogとDB seedを実装する
- [ ] Capability設定の `enabled` / `approval_policy` 更新を実装する
- [x] Task受付、Plan版管理、Event追記、状態機械、30日purgeを実装する
- [x] 既知秘密値のredactionをTask永続化に適用する

## Plannerとworker

- [x] 構造化Plan/質問を返すPlannerを実装する
- [x] auto-only Planとplan-required Planの分岐を実装する
- [ ] 既存HITLの質問とTask再キューhandlerを接続する
- [x] FastAPI lifespanに単一Task workerとrecoveryを追加する
- [ ] 取消の子run伝播と `interrupted` 復旧を実装する

## Capability Adapter

- [x] Registry読取・検索系の固定allowlist Adapterを実装する
- [x] `memory_propose` Adapterを実装する
- [x] 実行時の最新設定を使う `specialist_agent` Adapterを実装する
- [x] Task専用の新規sessionを作る `coding_cli` Adapterを実装する
- [x] 再承認自己申告を改訂Planと `waiting_reapproval` へ接続する
- [x] shell、Skills、plugin、外部書込み提案が選択不能なことを保証する

## 入口とWebUI

- [x] `--task-agent TEXT` の即時返却CLIを実装する
- [x] Task一覧・詳細・承認・差戻し・取消・再計画APIを実装する
- [x] Capability設定APIを実装する
- [x] `/task-agent` と `/task-agent/:id` の画面を追加する
- [x] Capability設定画面を追加する

## 検証

- [x] migration、状態遷移、Plan版、purge、redactionのテストを追加する
- [x] auto/承認必須/disabled/HITL質問の結合テストを追加する
- [x] 子run、取消、recovery、再承認のテストを追加する
- [ ] CLI/API/フロントエンド単体テストを追加し、`uv run pytest tests/` を実行する
