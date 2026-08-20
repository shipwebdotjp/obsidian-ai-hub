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

## 主要な決定

- [テスト層再編プラン (Phase 0 完了)](../docs/test-reduction/plan.md)
- [E2E を重大なユーザーフローに限定する (Phase 7〜9 追加検証)](10-Decisions-Testing.md#e2e-を重大なユーザーフローに限定する-phase-7〜9-追加検証)
- [フロントエンドのツールチェーンポリシー (Vite 6 + Vitest 4)](10-Decisions-Testing.md#フロントエンドのツールチェーンポリシー-vite-6--vitest-4)
- [タスク管理 Web UI (loopback または tailnet + トークン)](10-Decisions-Web.md#タスク管理-web-ui-loopback-または-tailnet--トークン)（2026-08-15 の [Bearer 認証一元化](10-Decisions-Web.md#web-api-の-bearer-認証一元化ループバックtailnet-免除の廃止) で置換）
- [LINE通知から既存Webフォームへ誘導するHITL v1](10-Decisions-HITL.md#line通知から既存webフォームへ誘導するhitl-v1)（2026-08-15）
- [Inbox分類にカレンダー登録カテゴリとHITL承認を追加](10-Decisions-Integrations.md#inbox分類にカレンダー登録カテゴリとhitl承認を追加)（2026-08-15）
- [Inbox分類にリマインダー登録カテゴリとHITL承認を追加](10-Decisions-Integrations.md#inbox分類にリマインダー登録カテゴリとhitl承認を追加)（2026-08-15）
- [pytestプロセスからの本番シークレット遮断（conftest強制ENV=test）](10-Decisions-Testing.md#pytestプロセスからの本番シークレット遮断conftest強制envtest)（2026-08-15）
- [HITLモバイル一覧詳細のスクロール修正（列フレックス min-height 問題）](10-Decisions-Web.md#hitlモバイル一覧詳細のスクロール修正列フレックス-min-height-問題)（2026-08-16）
- [AIプランナー提案のプレイグラウンド（スキーマ v20）](10-Decisions-Integrations.md#aiプランナー提案のプレイグラウンドスキーマ-v20)（2026-08-19）
