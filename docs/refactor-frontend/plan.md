# 実装計画: Phase 0 / Phase 1

[調査結果](investigation.md) から採用した範囲。重複解消を優先し、巨大ファイルの
分割とチャット基盤・認証 fetch の統合は見送る。

## 検証

- `cd frontend && npx tsc -b`
- `cd frontend && npx vitest run`
- 影響画面を手動確認（E2E は追加しない。`frontend/AGENTS.md` / `AGENTS.md`）

各バッチで上記を実行し、既存 55 テストを維持する。ワーディング検査は追加しない。

---

## Phase 0 — クイックウィン

| # | 内容 | 主な変更 |
|---|---|---|
| 0-1 | エラー文言ヘルパ | 新 `utils/error.ts`（`getApiErrorMessage` / `getErrorMessage`）。約 40 箇所を置換 |
| 0-2 | Toast 共通化 | 新 `components/Toast.tsx`（`useToasts` / `ToastStack`）。4 ページ移行。`notify` prop は既存テスト維持のため段階的に撤去 |
| 0-3 | research ラベル統合 | 新 `features/research/researchLabels.ts`。完全一致 2 箇所を統合 |
| 0-4 | リスト文字列 | 新 `utils/list.ts`（`parseMultilineList`）。6 コピーを統合 |
| 0-5 | 送信キュー汎用化 | 新 `features/chat/sendQueue/createSendQueue.ts`。agent/coding を薄い生成に |
| 0-6 | コピー状態 | 新 `hooks/useCopyMessage.ts`。2 箇所を統合 |
| 0-7 | クエリビルダ | `client.ts` に `buildQuery` / `withQuery`。15+4 箇所を置換 |

## Phase 1 — レイアウト・データ

| # | 内容 | 主な変更 |
|---|---|---|
| 1-1 | MasterDetail | 新 `components/MasterDetailLayout.tsx`（内部に戻るバー）。主要 3 ページ移行 |
| 1-2 | fetch 共通化 | 新 `hooks/useListResource.ts` / `useDetailResource.ts`。競合ガードを統一 |
| 1-3 | モーダル/フォーム | 新 `components/ModalShell.tsx` + `components/form/FormField.tsx`。people/projects/jobs 移行 |
| 1-4 | ステータスバッジ | 新 `utils/statusBadge.ts`。hitl/research/execution-logs/job-state を統合 |
| 1-5 | チャート | 新 `components/charts/`。SVG 出力と a11y を厳密比較 |
| 1-6 | 小物 | `hooks/useDebouncedValue.ts`、`JobPage` を `usePagination`/`PaginationBar` へ |

## 見送り（将来）

- チャット/SSE 基盤の一本化（`useRunStream` / `ToolCallCard` 等）
- 認証付き fetch の統合
- 型の単一ソース化、巨大ファイル分割

## 実装順序

Phase 0 を 0-1 から順に実施し、各バッチで検証。Phase 1 は 1-1, 1-2 を優先。

## 実装状況

検証: `npx tsc -b` / `npx vitest run`（全バッチ後に実施、519 tests pass）。

### Phase 0 — 完了

| # | 成果物 | 移行 |
|---|---|---|
| 0-1 | `utils/error.ts` | 32 ファイル・約 90 箇所 |
| 0-2 | `components/Toast.tsx`（`useToasts` / `ToastStack`） | Memory / Research / VaultSearch / Planner |
| 0-3 | `features/research/researchLabels.ts` | ResearchList / ResearchDetailPanel（完全一致を統合） |
| 0-4 | `utils/list.ts`（`splitList`） | Projects / MemoryEditForm / PeoplePage / PropertyDefinitionsTab |
| 0-5 | `features/chat/sendQueue/core.ts` | agent / coding の送信キュー |
| 0-6 | `hooks/useCopyMessage.ts` | useAgentChat / useCodingUiState |
| 0-7 | `api/client.ts` の `buildQuery` / `withQuery`（単体テスト追加） | client / coding / peopleApi / ProjectsPage |

補足: Toast は `notify` prop の撤去までは行わず、状態と DOM の重複解消に留めた
（既存テストが通知文言を検査するため、prop 撤去は別途）。

### Phase 1 — 一部完了

| # | 成果物 | 移行 | 状況 |
|---|---|---|---|
| 1-1 | `components/MasterDetailLayout.tsx` | Memory / Research / VaultSearch | 主要パターンのみ。他は下記「見送り」 |
| 1-2 | `hooks/useListResource.ts` | MemoryList / ResearchList | 詳細取得フックは未着手 |
| 1-3 | `components/Modal.tsx` | AgentModals（3 モーダル） | CodingModals・native dialog は未移行 |
| 1-6 | `hooks/useDebouncedValue.ts` | MemoryPage / ResearchPage | 完了 |

### Phase 1 — 見送り（理由）

- **1-1 の残り**: ExecutionLog は `md` ブレークポイント、Hitl / TaskAgent / People /
  Projects は背景色・`paneRef` の所有位置・カード枠が異なる。Agents / Coding は
  サイドバー側が `paneRef` を保持し折りたたみ可能。Planner は `side: "right"` かつ
  選択時のみ詳細を表示。これらを 1 コンポーネントに寄せると props が増え、CSS の
  正規化で目視確認できない視覚差分を生むため、共通化は主要 3 ページに限定した。
- **1-2 の詳細取得**: `useDetailResource` は読み込み時のページ固有リセット
  （編集中フラグ・関連取得など）が多く、行動を変えずに抽象化するには各ページの
  再設計が必要。次段で実施する。
- **1-4**: ドメインごとにステータス集合と配色（`bg-*-100` と `bg-*-50 border-*`）が
  異なり、統合すると表示が変わるため見送り。
- **1-5**: 手書き SVG のフレーム・軸・凡例は 3 ファイルで、視覚的等価性を目視で
  検証できないため見送り。

### Phase 0 で得られた効果

- チャット送信キューの実装（約 190 行 × 2）を共有コア化。
- エラー文言抽出・トースト・クエリ構築・リストパースの重複を除去。
- マスター/ディテール 3 ページから `usePaneResize` 配線と戻るバーを除去。

