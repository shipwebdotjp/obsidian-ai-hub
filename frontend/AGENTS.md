# AGENTS.md

このファイルは frontend ディレクトリ内で作業する際のデザイン規約を示します。

## カラーパレット

### アクションカラー

| 用途 | クラス |
|------|--------|
| 主要アクション（新規作成・検索・保存など） | `bg-blue-600 text-white hover:bg-blue-700` |
| 承認 / 両方保持 | `bg-emerald-600 text-white` |
| 却下 | `bg-rose-600 text-white` |
| 削除（一括） | `bg-rose-900 text-white` |
| 削除（単体） | `bg-rose-800 text-white` |
| マージ | `bg-blue-600 text-white` |
| 置換 (supersede) | `bg-purple-600 text-white` |
| 既存を候補で更新 | `bg-amber-600 text-white` |
| 汎用（編集・キャンセルなど） | `bg-slate-900 text-white` |
| disabled 状態 | 共通で `disabled:opacity-50` |

### リスト行の選択状態

- **選択行（詳細表示中）**: `bg-slate-200 border-l-4 border-slate-800` + `data-selected="true"` 属性
- **チェックボックス選択**: `bg-slate-100`
- **ホバー**: `hover:bg-slate-50`

選択行とチェックボックス選択が重なる場合は選択行の表示を優先する。

### 背景・レイアウト

- ページ全体: `bg-slate-50`
- カード・パネル: `bg-white`
- ヘッダー境界: `border-b border-slate-200`
- リスト区切り: `divide-y divide-slate-100`

## カーソル

- 操作可能な要素（ボタン、チェックボックス、セレクト、クリック可能な行）には `cursor-pointer` を付与する
- 無効状態の要素は `cursor-not-allowed` を優先する
- テキスト入力（input[type=text], textarea）はデフォルトのテキストカーソルを維持する

## ボタンサイジング

| コンテキスト | クラス |
|-------------|--------|
| ヘッダー・ツールバー | `px-3 py-1 text-sm` |
| ページ内アクション | `px-3 py-1.5 text-xs` |
| 行内クイックアクション | `px-2 py-0.5 text-xs` |
| 大きめのボタン | `px-4 py-2` |

## 角丸

- 全体で `rounded` を基本とする

## 日付フォーマット

共有ユーティリティ `src/utils/date.ts` を使用する。

- `formatYmdWithDow(ymd: string): string` — YYYY-MM-DD → `YYYY/MM/DD(曜)`
- `formatDateTime(isoString: string): string` — ISO 8601 → `YYYY/MM/DD(曜) HH:mm`（ブラウザのローカルタイムゾーン）
- 不正な値・未設定値は空文字を返し、呼び出し側で非表示とする

## 選択状態の伝播

- 詳細パネルを開いている行の ID を一覧コンポーネントへ prop で渡し、視覚的な選択表示を行う
- フィルター変更・削除・詳細クローズ時に選択表示を解除する
- 詳細パネルの通常ロード完了では一覧を再取得しない（データ変更操作のみ再取得）

## コンポーネントのマウント・更新

- 行切替時に詳細パネルを `key` で強制再マウントしない
- ロード時はローディング表示を出し、切替中は直前の内容を維持する

## データ属性（E2E テスト用）

- 行要素: `data-testid="memory-row"`
- 選択状態: `data-selected="true"` / `data-selected="false"`
- フィルター: `aria-label="ステータスフィルター"` など
