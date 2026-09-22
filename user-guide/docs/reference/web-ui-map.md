---
sidebar_position: 3
title: Web UI マップ
---

# Web UI マップ

Web UI は `http://127.0.0.1:8765`（既定）で動作します。
すべての API は `/api/v1/...` 配下で Bearer トークン認証を要求します。

## 画面一覧

| 画面 | パス | 主な操作 |
| --- | --- | --- |
| メモリ | `/memories` | 長期メモリ候補の承認・却下・編集・一括処理、プロファイル生成 |
| リサーチ | `/research` | リサーチ実行、テーマ候補の確認 |
| AIエージェント | `/agents` | エージェント作成・編集、セッション会話 |
| コーディング | `/coding` | セッション作成、モデル・ツール設定、コーディング会話 |
| 確認待ち | `/hitl` | 質問への回答、実行全体のキャンセル |
| Vault 検索 | `/vault-search` | Vault の意味検索・キーワード検索・ハイブリッド検索 |
| サマリダッシュボード | `/summary-dashboard` | サマリの閲覧・編集・再生成・削除、統計 |
| ヘルスケア | `/healthcare` | Apple Health データの推移・相関、インポート |
| 人物管理 | `/people` | 人物候補の解決、重複統合、Vault 同期 |
| プロジェクト管理 | `/projects` | プロジェクト登録、候補解決、履歴 |
| ジョブ管理 | `/jobs` | 定期・ワンショットジョブの管理 |
| Task Agent | `/task-agent` | 依頼の投入、Plan 承認・差戻し・再計画 |
| Task Capability設定 | `/task-agent/capabilities` | Capability の有効化と承認ポリシー |
| ワークフロー | `/workflows` | 一覧・新規作成・テンプレートから作成 |
| Workflow 詳細 | `/workflows/:workflowId` | Revision 履歴、最近の Run、新しい下書き、改名・削除 |
| Workflow エディタ | `/workflows/revisions/:revisionId/edit` | グラフ編集、検証、公開、実行 |
| Workflow Run | `/workflows/runs/:runId` | 進捗・Node・Event、承認・再開・取消・再実行 |
| 実行ログ（ログ） | `/execution-logs/logs` | CLI / LLM 実行ログの閲覧 |
| 実行ログ（ジョブ状態） | `/execution-logs/job-states` | ジョブの稼働状態 |
| プランナー | `/planner` | AI 提案の確認、Apple への登録、却下 |
| 設定 | `/settings` | API トークン、チャット入力の送信方法 |

- `/` と未定義パスは `/memories` へリダイレクトされます。
- `/execution-logs` は `/execution-logs/logs` へリダイレクトされます。

## サイドバーの並び

メモリ → リサーチ → AIエージェント → コーディング → 確認待ち（バッジ付き） → Vault 検索 →
サマリダッシュボード → ヘルスケア → 人物管理 → プロジェクト管理 → ジョブ管理 →
Task Agent → ワークフロー → 実行ログ（ログ / ジョブ状態） → プランナー。最下部に **設定**。

## 認証

- `GET /health` は認証不要で `{"status":"ok","auth_required":true}` を返します。
- トークン未保存の場合、起動時にトークン入力画面が表示されます。
- 認可エラーは `401`、ジョブ管理のアクセス制限は `403` です。

## 次に読む

- [サーバーと Web UI](../getting-started/web-ui.md)
- [CLI リファレンス](cli.md)
