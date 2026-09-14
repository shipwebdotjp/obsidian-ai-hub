# Task Agent TODO

仕様は [specification.md](specification.md)、実装順序は
[implementation-plan.md](implementation-plan.md) を正とする。

## 文書と判断記録

- [ ] `CONTEXT.md` とTask Agent文書群の状態・承認ポリシーを同期する
- [ ] 承認境界、Capability Manifest、Workspace信頼境界のADRを更新する
- [ ] Webサーバー同居workerと入力保存の運用をREADMEへ追記する

## 永続化とコア

- [ ] v44 migrationで `task_agent_*` の4テーブルと索引を追加する
- [ ] コード定義Capability catalogとDB seedを実装する
- [ ] Capability設定の `enabled` / `approval_policy` 更新を実装する
- [ ] Task受付、Plan版管理、Event追記、状態機械、30日purgeを実装する
- [ ] 既知秘密値のredactionをTask永続化に適用する

## Plannerとworker

- [ ] 構造化Plan/質問を返すPlannerを実装する
- [ ] auto-only Planとplan-required Planの分岐を実装する
- [ ] 既存HITLの質問とTask再キューhandlerを接続する
- [ ] FastAPI lifespanに単一Task workerとrecoveryを追加する
- [ ] 取消の子run伝播と `interrupted` 復旧を実装する

## Capability Adapter

- [ ] Registry読取・検索系の固定allowlist Adapterを実装する
- [ ] `memory_propose` Adapterを実装する
- [ ] 実行時の最新設定を使う `specialist_agent` Adapterを実装する
- [ ] Task専用の新規sessionを作る `coding_cli` Adapterを実装する
- [ ] 再承認自己申告を改訂Planと `waiting_reapproval` へ接続する
- [ ] shell、Skills、plugin、外部書込み提案が選択不能なことを保証する

## 入口とWebUI

- [ ] `--task-agent TEXT` の即時返却CLIを実装する
- [ ] Task一覧・詳細・承認・差戻し・取消・再計画APIを実装する
- [ ] Capability設定APIを実装する
- [ ] `/task-agent` と `/task-agent/:id` の画面を追加する
- [ ] Capability設定画面を追加する

## 検証

- [ ] migration、状態遷移、Plan版、purge、redactionのテストを追加する
- [ ] auto/承認必須/disabled/HITL質問の結合テストを追加する
- [ ] 子run、取消、recovery、再承認のテストを追加する
- [ ] CLI/API/フロントエンド単体テストを追加し、`uv run pytest tests/` を実行する
