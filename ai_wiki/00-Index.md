# ai_wiki Index

- 決定記録は、最も関係の深い領域のファイルに追加する。過去の `10-Decisions.md` へのリンクは、[互換案内](10-Decisions.md) から移転先を辿れる。

## 決定記録

- [アーキテクチャ・運用](10-Decisions-Architecture.md)
- [Web・フロントエンド](10-Decisions-Web.md)
- [HITL](10-Decisions-HITL.md)
- [外部連携](10-Decisions-Integrations.md)
- [テスト・開発環境](10-Decisions-Testing.md)
- [人物同定・人物管理](10-Decisions-People.md)

## 用語集

- [ドメイン用語集](30-Glossary.md)
- [タスクオーケストレーション CONTEXT.md](../CONTEXT.md)（Bounded Context とユビキタス言語）

## 開発ガイド

- [不可逆変更の設計・実装品質ガイド](../docs/development-quality-playbook.md)

## 主要な決定

- [テスト層再編プラン (Phase 0 完了)](../docs/test-reduction/plan.md)
- [個人開発ではブラウザ E2E を追加・更新しない](10-Decisions-Testing.md#個人開発ではブラウザ-e2e-を追加更新しない)
- [フロントエンドのツールチェーンポリシー (Vite 6 + Vitest 4)](10-Decisions-Testing.md#フロントエンドのツールチェーンポリシー-vite-6--vitest-4)
- [タスク管理 Web UI (loopback または tailnet + トークン)](10-Decisions-Web.md#タスク管理-web-ui-loopback-または-tailnet--トークン)（2026-08-15 の [Bearer 認証一元化](10-Decisions-Web.md#web-api-の-bearer-認証一元化ループバックtailnet-免除の廃止) で置換）
- [LINE通知から既存Webフォームへ誘導するHITL v1](10-Decisions-HITL.md#line通知から既存webフォームへ誘導するhitl-v1)（2026-08-15）
- [Inbox分類にカレンダー登録カテゴリとHITL承認を追加](10-Decisions-Integrations.md#inbox分類にカレンダー登録カテゴリとhitl承認を追加)（2026-08-15）
- [Inbox分類にリマインダー登録カテゴリとHITL承認を追加](10-Decisions-Integrations.md#inbox分類にリマインダー登録カテゴリとhitl承認を追加)（2026-08-15）
- [pytestプロセスからの本番シークレット遮断（conftest強制ENV=test）](10-Decisions-Testing.md#pytestプロセスからの本番シークレット遮断conftest強制envtest)（2026-08-15）
- [HITLモバイル一覧詳細のスクロール修正（列フレックス min-height 問題）](10-Decisions-Web.md#hitlモバイル一覧詳細のスクロール修正列フレックス-min-height-問題)（2026-08-16）
- [AIプランナー提案のプレイグラウンド（スキーマ v20）](10-Decisions-Integrations.md#aiプランナー提案のプレイグラウンドスキーマ-v20)（2026-08-19）
- [ヘルスケア: Apple Health export の分離DB・全種raw保存（スキーマ v1）](10-Decisions-Integrations.md#ヘルスケア-apple-health-export-の分離db全種raw保存スキーマ-v1)（2026-08-24）
- [Safari の検索結果リストの隙間（inline-block ボタンのラインボックス問題）](10-Decisions-Web.md#safari-の検索結果リストの隙間inline-block-ボタンのラインボックス問題)（2026-08-26）
- [Coding Coordinator を進行役、CLI Worker を主体にする](10-Decisions-Architecture.md#coding-coordinator-を進行役cli-worker-を主体にする)（2026-09-14）
- [Direct CLI 削除・ACP 一本化（OpenCode のみ）](10-Decisions-Architecture.md#direct-cli-削除acp-一本化opencode-のみ)（2026-09-15）
- [コーディング実行のトークン使用量積算と試行単位の合算方針](10-Decisions-Architecture.md#コーディング実行のトークン使用量積算と試行単位の合算方針)（2026-09-16）
- [Scheduler Task から Job への完全改称とワンショット実行ジョブ導入](10-Decisions-Architecture.md#scheduler-task-から-job-への完全改称とワンショット実行ジョブ導入)（2026-09-17）
- [エージェント会話の送信キューはクライアント側に置く](10-Decisions-Web.md#エージェント会話の送信キューはクライアント側に置く)（2026-09-17）
- [Task Agent MVP 仕様](../docs/task-agent/specification.md)（2026-09-14）。文書群の入口は [docs/task-agent/README.md](../docs/task-agent/README.md)。判断記録は [docs/task-agent/adr/](../docs/task-agent/adr/) 配下:
  - [SQLiteをTask状態の正本とする](../docs/task-agent/adr/sqlite-as-task-state-source-of-truth.md)
  - [CLI投入・WebUI操作・Webサーバー同居worker](../docs/task-agent/adr/cli-intake-webui-hitl-resident-worker.md)
  - [承認ポリシー付きPlanを実行境界にする](../docs/task-agent/adr/approved-plan-as-execution-boundary.md)
  - [コード定義AdapterとDB管理Capabilityポリシー](../docs/task-agent/adr/capability-manifest-and-delegate-adapters.md)
  - [Coding対象解決と既存実行境界](../docs/task-agent/adr/workspace-resolution-and-coding-cli-trust-boundary.md)（主対象Projectのconfidence付き解決、単一対象の実行境界を含む）
  - [自動ロールバックを行わず、要約Eventと人間判断で復旧する](../docs/task-agent/adr/no-automatic-rollback-recovery-via-trace-and-hitl.md)
