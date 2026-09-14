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
| [specification.md](specification.md) | 確定済みの外部契約と振る舞い |
| [implementation-plan.md](implementation-plan.md) | 実装順序、既存基盤との接続、検証 |
| [TODO.md](TODO.md) | 未完了作業の追跡 |
| [post-mvp.md](post-mvp.md) | MVP後に再検討する機能・運用項目 |
| [adr/](adr/) | 変更コストが高い設計判断 |

## 設計上の要点

- CLI の入口は `python -m obsidian_ai_hub --task-agent "依頼"`。Task ID、状態、
  詳細URLを返して終了する。
- WebUI は `/task-agent/:id` にTask一覧・詳細を置き、既存の定期タスク設定 `/tasks` と
  分ける。
- Task worker は FastAPI の既存 worker lifespan に同居する。Webサーバー停止中は新規の
  計画・実行を行わない。
- Capability のAdapter定義はコードで固定し、DBと設定UIでは有効/無効と承認ポリシーだけを
  管理する。任意shell、Skills、プラグインはMVPのTask Capabilityではない。
- 外部書込み（カレンダー、リマインダー）とVault直接編集はMVP外。既存の提案HITLをTaskの
  実行経路で呼ばないため、二重承認は生じない。

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
2. 振る舞いは仕様書、判断理由はADR、実装順序は実装計画、作業事実はTODOに記す。
3. 承認ポリシー、Capability登録、実行境界を変更する際は、対応するADRと `CONTEXT.md` を
   同時に更新する。
