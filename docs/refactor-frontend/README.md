# フロントエンド リファクタリング

`frontend/src`（非テスト 約 35,000 行 / 15 機能ディレクトリ / 55 テスト）の重複と
共通化候補を調査し、段階的に解消するための記録。

- [調査結果](investigation.md) — 重複箇所の一覧と証跡
- [実装計画](plan.md) — 採用した Phase 0 / Phase 1 のバッチと移行順

## 背景

コード量が増え、同等のロジック（一覧＋詳細レイアウト、fetch、トースト、
send キュー、チャット基盤など）が機能ごとにコピーされている。機能追加・
不具合修正のたびに複数箇所を同期する必要があり見通しが悪い。

## 方針

- 重複解消を優先し、巨大ファイルの分割は後回しにする。
- 既存の共通化済み資産（`usePagination`, `usePaneResize`, `useSessionPromptDraft`,
  `StructuredValue`, `useNativeDialog`, `utils/date.ts`, `taskAgentLabels.ts`）を
  手本に、同じ配置規約（`src/components`, `src/hooks`, `src/utils`）で抽出する。
- 挙動を変えない。既存テストは原則無変更で通す。ワーディングを検査する
  テストは追加しない（`frontend/AGENTS.md`・`AGENTS.md` に従う）。

## 対象範囲

- 採用: Phase 0（クイックウィン）／ Phase 1（レイアウト・データ共通化）
- 見送り: チャット/SSE 基盤の一本化、認証 fetch 統合、型整理、巨大ファイル分割
  （将来 Phase 2 / Phase 3。詳細は [investigation.md](investigation.md)）
