# 調査結果: フロントエンドの重複と共通化候補

対象: `frontend/src`。行番号は調査時点のもの。証跡は直接検証済み（`rg` / ファイル読取）。

## 既に共通化済み（手本）

| 資産 | 用途 |
|---|---|
| `hooks/usePagination.ts` | 一覧ページング（4 箇所で使用） |
| `hooks/usePaneResize.ts` + `components/SplitHandle.tsx` | 2 ペインのドラッグリサイズ（12 ファイル） |
| `hooks/useSessionPromptDraft.ts` | 下書き保存（agents / coding） |
| `components/StructuredValue.tsx` | 構造化値レンダリング |
| `features/people/useNativeDialog.ts` | native `<dialog>` の focus/復帰 |
| `utils/date.ts` | 日付フォーマット |
| `features/task-agent/taskAgentLabels.ts` | ステータスラベル/色の唯一の集約例 |
| `components/MarkdownPreview.tsx` / `CopyMessageButton.tsx` / `InConversationQuestionCard.tsx` | チャット共有 UI |
| `features/settings/chatSendMode.ts` | 送信モード判定 |

---

## Tier 1 — 完全〜ほぼ同一コピー（低リスク・機械的）【採用: Phase 0】

### 1. Toast が 4 ファイルで完全一致
- `features/memories/MemoryPage.tsx:10-14,38,54-60,289-300`
- `features/research/ResearchPage.tsx:10-14,31,61-67,363-374`
- `features/vault-search/VaultSearchPage.tsx:8-12,48,59-65,236-247`
- `features/planner/PlannerPage.tsx:19-23,211,213-219,597-608`

`Date.now() + Math.random()` と `pointer-events-none fixed bottom-4 right-4` が全一致。
`notify` は `MemoryList` / `MemoryDetailPanel` / `ResearchList` / `ResearchDetailPanel` /
`VaultSearchDetailPanel` へ prop drilling されている。

→ `ToastProvider` + `useToast()` に集約。

### 2. research の `statusLabel` がバイト単位で一致
- `features/research/ResearchList.tsx:64-72`
- `features/research/ResearchDetailPanel.tsx:102-110`

加えて `jobStatusBadge` の色マップ（`ResearchList.tsx:74-87`）が他機能と重複。

### 3. エラー文言抽出が 28 ファイル・40 箇所以上
`e instanceof ApiError ? e.message : "…"`（例: `MemoryList.tsx:68,120,139,153`,
`MemoryDetailPanel.tsx:77,106,123,155`, `SummaryDashboardPage.tsx` 8 箇所,
`HitlPage.tsx` 4 箇所）。`err instanceof Error ? err.message : …` も people 系に多数。

→ `getApiErrorMessage(e, fallback)` / `getErrorMessage(e, fallback)`。

### 4. 改行リストのパースが 6 コピー
- `features/projects/utils.ts:1-5` `parseKeywords`
- `features/memories/MemoryEditForm.tsx:28-33` `splitList`
- `features/people/PeoplePage.tsx:557`
- `features/people/PropertyDefinitionsTab.tsx:150-153,159-162,199-202,208-211`

### 5. 送信キューが 2 モジュールでほぼ完全一致
- `features/agents/agentSendQueue.ts`（188 行）
- `features/coding/utils/codingSendQueue.ts`（174 行）

関数シグネチャが完全対応（`buildKey` / `read` / `write` / `remove` / `create` /
`enqueue` / `removeQueued` / `markError` / `clearError`）。差分は添付有無・
キー接頭辞・サイズ上限（4,000,000 vs 1,000,000）・id 接頭辞のみ。

→ `createSendQueue<TExtra>()`。

### 6. コピー状態タイマーが完全一致
- `features/agents/useAgentChat.ts:972-997`
- `features/coding/hooks/useCodingUiState.ts:61-84`

同じ 2000ms・同じガード・同じ console.error。

### 7. API のクエリ文字列が手組み
`client.ts` 内で `URLSearchParams` を 15 箇所（136, 220, 277, 353, 392, 400, 422,
454, 489, 503, 536, 546, 658, 877）、手動連結が `coding.ts:312,320`,
`peopleApi.ts:39,140`, `ProjectsPage.tsx:77-110`。スキップ意味論も
`!== undefined/null/""` と `if (v)` が混在（後者は falsy を落とす）。

→ `buildQuery(params)` / `withQuery(path, params)`。

---

## Tier 2 — 構造の共通化（中リスク・高効果）【採用: Phase 1】

### 8. 一覧＋詳細レイアウト
`usePaneResize` の分割代入と `SplitHandle`、`lg:w-[var(--pane-size)]`、
`mobileDetailOpen` 条件分岐（52 箇所）が繰り返される。

- `MemoryPage.tsx:114-119,218-288`
- `ResearchPage.tsx:262-267,306-362`
- `VaultSearchPage.tsx:116-121,163-235`
- `HitlPage.tsx:435-440,442-561`
- `ExecutionLogPage.tsx:218-223,333-411`
- `TaskAgentPage.tsx:22-27,29-63`
- `PlannerPage.tsx:344-350,445-595`（`side:"right"`）
- `summary-dashboard/BrowseTab.tsx:82-87,89-143`
- `PeoplePage.tsx:840` ほか
- `ProjectsPage.tsx:376,460-522`

`usePaneResize` 利用ファイルは 12（hooks 自身と SplitHandle を除く）。

### 9. モバイル戻るバー
`aria-label="一覧に戻る"` が 11 ファイル（`MemoryPage`, `ResearchPage`,
`VaultSearchPage`, `HitlPage`, `ExecutionLogPage`, `summary-dashboard/DetailPanel`,
`people/PeopleListTab`, `people/CandidateTab`, `projects/CandidateDetail`,
`projects/ProjectDetail`, `task-agent/TaskAgentDetailPanel`）。

### 10. 一覧/詳細の fetch（競合ガードが 3 種混在）
- AbortController: `MemoryList.tsx:35-80`, `ResearchList.tsx:28-62`,
  `VaultSearchList.tsx:23-64`, `ExecutionLogPage.tsx:71-134`, `HitlPage.tsx:180-227`
- インクリメント ref: `TaskAgentListPage.tsx:47-84`, `SummaryDashboardPage.tsx:107-165`,
  `TaskAgentDetailPanel.tsx:312-364`
- `cancelled` boolean: `PlannerPage.tsx:205-258`, `components/Sidebar.tsx:29-41`

`TaskAgentListPage` は abort が無く、アンマウント後 setState の潜在バグ。

詳細取得は「初回のみ全画面ローディング・行切替では直前内容維持」が
`MemoryDetailPanel.tsx:32-33,162-170`, `ResearchDetailPanel.tsx`, 
`TaskAgentDetailPanel.tsx:455-473` に重複。

### 11. モーダルシェル / labeled input
native `<dialog>` のクラス文字列と header/footer が people 系 9 ファイル・
`ProjectFormModal.tsx`・`JobPage.tsx` で反復。overlay 方式も混在。

### 12. ステータスラベル/色マップ
`HitlPage.tsx:380-402`, `ResearchList.tsx:74-87`, `ExecutionLogPage.tsx:198-216`,
`JobStatePage.tsx:44-55`。パレット
`succeeded→emerald / failed→rose / running→blue / pending→yellow` が反復。

### 13. チャートの軸/スケール/凡例/sr-only 表
外部ライブラリなし（`package.json` は react / react-dom / react-router /
react-markdown / remark-gfm / lucide-react のみ）。手書き SVG。
- `features/summary-dashboard/charts.tsx`（429 行）
- `features/healthcare/charts.tsx`
- `features/healthcare/HealthcareScatterChart.tsx`

フレーム定数・Y グリッド・X 軸ラベル・`formatTick`・sr-only 表が重複。

---

## Tier 3 — チャット基盤の一本化（最大の重複・高リスク）【見送り: Phase 2】

`agents` と `coding` は実質コピー。

| 機能 | 証跡 |
|---|---|
| run ストリーム状態機械 | `useAgentChat.ts:131-1112` vs `useCodingRunStream.ts:169-1001`（〜400-500 行重複） |
| ツールコール `<details>` カード 5 コピー | `CodingMessageList.tsx:70-158,279-331,350-402` / `AgentMessageList.tsx:115-175,304-370` |
| 送信待ち表示 | `AgentMessageList.tsx:399-453` vs `CodingMessageList.tsx:767-809` |
| HITL 待機 submit/cancel（ほぼバイト一致） | `useAgentSessions.ts:214-261` vs `useCodingSessionDetail.ts:145-193` |
| スラッシュ候補/パレット/キーボード | `AgentChatInput.tsx:121-167` / `CodingChatInput.tsx:54-89` |
| サイドバー描画/フォーカストラップ/自動スクロール | `AgentSidebar` vs `CodingSidebar`, `useAgentsUiState` vs `useCodingUiState` |
| 画像/プロンプト下書きの保存機構 | `useAgentImageDraft.ts` vs `useSessionPromptDraft.ts` |

共有 UI（`runSse.ts`, `MarkdownPreview`, `InConversationQuestionCard` 等）は
既に一部抽出済み。中核の状態機械が二重実装。

## Tier 4 — データ層・型（高リスク/広範囲）【見送り: Phase 3】

- 認証付き fetch の再実装: `startAgentRun` `client.ts:780-815`,
  `startCodingRun` `coding.ts:401-435`, `runSse.ts:111-141`（401/token に直結、最高リスク）
- 型重複: `SlashInvocation`（`coding.ts:168-171` ＝ `types.ts:898-901`）、
  `Project`（`api/types.ts:248-264` vs `projects/types.ts:11-28`）、
  `AssociatedSummary`（`projects/types.ts:30-36` vs `people/types.ts:21-27`）
- `any` 多用: `MarkdownPreview.tsx` 36 箇所（局所的）、`people/types.ts:362-396`、
  `catch (e: any)` が 40 箇所以上
- 巨大ファイル: `HitlPage`1262 / `PeoplePage`1127 / `JobPage`1110 /
  `TaskAgentDetailPanel`920 / `useAgentChat`1112 / `useCodingRunStream`1001

---

## 優先度まとめ

| 優先 | 項目 | リスク |
|---|---|---|
| 1 | Toast / エラー文言 / statusLabel / リスト / キュー / コピー / クエリ | 低 |
| 2 | MasterDetailLayout / fetch フック | 中 |
| 3 | ModalShell / statusBadge / チャート | 中 |
| 4 | チャット基盤 / 認証 fetch / 型整理 / ファイル分割 | 高 |
