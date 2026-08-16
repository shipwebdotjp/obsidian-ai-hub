# アーキテクチャ決定記録

決定記録は領域別に管理する。新しい決定は、[AI Wiki Index](00-Index.md) を参照して最も関係の深い記録へ追加する。

このページは旧リンクの互換案内である。以下の見出しは移転前と同じアンカーを維持し、各決定の本文はリンク先にある。

## バックアップ失敗の実行ログ記録

[移転先: 10-Decisions-Architecture.md](10-Decisions-Architecture.md)

## OpenCode Go の GPT モデルは Responses API を使う

[移転先: 10-Decisions-Integrations.md](10-Decisions-Integrations.md)

## Web リサーチの OpenAI ツール呼び出しは Responses API を使う

[移転先: 10-Decisions-Integrations.md](10-Decisions-Integrations.md)

## テスト環境隔離 (ENV=test)

[移転先: 10-Decisions-Testing.md](10-Decisions-Testing.md)

## サマリ編集の上書きポリシー

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## SQLite を LINE 日次通知時のサマリー正本とする

[移転先: 10-Decisions-Integrations.md](10-Decisions-Integrations.md)

## 未連携人物の編集・人物削除とサマリ数順表示

[移転先: 10-Decisions-People.md](10-Decisions-People.md)

## 人物編集競合時の統合自動提案

[移転先: 10-Decisions-People.md](10-Decisions-People.md)

## LINE 通知での複数テキストメッセージ送信

[移転先: 10-Decisions-Integrations.md](10-Decisions-Integrations.md)

## 共有SQLiteの所有者はdatabase.py、長期記憶はmemoryパッケージ

[移転先: 10-Decisions-Architecture.md](10-Decisions-Architecture.md)

## プロジェクト追跡機能の導入と設計

[移転先: 10-Decisions-Architecture.md](10-Decisions-Architecture.md)

## タスク管理 Web UI (localhost 専用)

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## タスク管理 Web UI (loopback または tailnet + トークン)

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## Web サーバー環境変数の OBSIDIAN_AI_HUB_ プレフィックス統一

[移転先: 10-Decisions-Architecture.md](10-Decisions-Architecture.md)

## 実行・LLMログ基盤と30日保持期限の導入

[移転先: 10-Decisions-Architecture.md](10-Decisions-Architecture.md)

## サマリダッシュボード統計タブの時間帯×カテゴリーヒートマップ

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## アクティビティログへの既存プロジェクト紐付け

[移転先: 10-Decisions-Architecture.md](10-Decisions-Architecture.md)

## プロジェクト別活動メモの導入

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## Jules VM におけるテスト環境とセットアップの統一

[移転先: 10-Decisions-Testing.md](10-Decisions-Testing.md)

## HITL（Human-In-The-Loop）永続化モデルとコアサービスの実装

[移転先: 10-Decisions-HITL.md](10-Decisions-HITL.md)

## HITL 再開コントラクトとディスパッチャーの実装

[移転先: 10-Decisions-HITL.md](10-Decisions-HITL.md)

## HITL スキーマ v14 とテスト実行結果

[移転先: 10-Decisions-HITL.md](10-Decisions-HITL.md)

## E2E を重大なユーザーフローに限定する (Phase 7〜9 追加検証)

[移転先: 10-Decisions-Testing.md](10-Decisions-Testing.md)

## フロントエンドのツールチェーンポリシー (Vite 6 + Vitest 4)

[移転先: 10-Decisions-Testing.md](10-Decisions-Testing.md)

## フロントエンドテストの Vitest 化と E2E テストの役割縮小 (Phase 3〜5、および 7〜9)

[移転先: 10-Decisions-Testing.md](10-Decisions-Testing.md)

## 長期記憶の自動診断メンテナンスとHITL連携

[移転先: 10-Decisions-HITL.md](10-Decisions-HITL.md)

## PeoplePage 分割リファクタリング

[移転先: 10-Decisions-People.md](10-Decisions-People.md)

## サマリダッシュボードのコンポーネント分割（ビュー抽出方式）

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## Web サービス層の分割リファクタリング

[移転先: 10-Decisions-Architecture.md](10-Decisions-Architecture.md)

## 週次メモリ質問の登録と材料

[移転先: 10-Decisions-HITL.md](10-Decisions-HITL.md)

## 汎用HITLの期限処理

[移転先: 10-Decisions-HITL.md](10-Decisions-HITL.md)

## インタビュー回答の処理とメモリ候補抽出

[移転先: 10-Decisions-HITL.md](10-Decisions-HITL.md)

## リサーチテーマ提案へのフィードバック反映（v17）

[移転先: 10-Decisions-Integrations.md](10-Decisions-Integrations.md)

## リサーチ提案 HITL の説明スナップショット

[移転先: 10-Decisions-Integrations.md](10-Decisions-Integrations.md)

## 未生成サマリは完了期間のみを提示する

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## サイドメニュー「確認待ち」の件数バッジ

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## トークンの localStorage 移行と設定画面

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## 未連携人物への候補一括解決

[移転先: 10-Decisions-People.md](10-Decisions-People.md)

## Web API の Bearer 認証一元化（ループバック・tailnet 免除の廃止）

[移転先: 10-Decisions-Web.md](10-Decisions-Web.md)

## LINE Webhook と Web UI／業務APIの公開経路分離

[移転先: 10-Decisions-Integrations.md](10-Decisions-Integrations.md)

## LINE通知から既存Webフォームへ誘導するHITL v1

[移転先: 10-Decisions-HITL.md](10-Decisions-HITL.md)

## pytestプロセスからの本番シークレット遮断（conftest強制ENV=test）

[移転先: 10-Decisions-Testing.md](10-Decisions-Testing.md)

## Inbox分類にカレンダー登録カテゴリとHITL承認を追加

[移転先: 10-Decisions-Integrations.md](10-Decisions-Integrations.md)

## Inbox分類にリマインダー登録カテゴリとHITL承認を追加

[移転先: 10-Decisions-Integrations.md](10-Decisions-Integrations.md)

## SQLiteベースの常駐HITL Dispatcher Worker

[移転先: 10-Decisions-HITL.md](10-Decisions-HITL.md)
