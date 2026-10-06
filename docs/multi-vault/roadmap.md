# Multi-Vault ロードマップ

## v1 後の前提

v1 は用途を問わない Markdown Vault 基盤である。blog は Hugo リポジトリ内の Markdown を AI が読取り・書込み・検索できるだけであり、Hugo 固有の操作は行わない。AI Vault は自由な作業ノートの場所であり、ユーザー知識の正本ではない。

## v2 — Hugo authoring

- Hugo の content root、section、archetype を Vault 設定として明示する。
- frontmatter の schema 検証、slug・date・draft の編集補助を加える。
- 記事候補、本文、関連ノート、レビュー状態を扱うブログ用 Agent を作る。
- 画像・static assets の参照と生成物の配置を安全なパス契約で扱う。
- Hugo build を隔離して実行し、診断結果を表示する。公開・デプロイは build と別の明示承認境界にする。

## v2 — AI Workspace の成熟

- 作業ノートの種類、来歴、関連 Task／Agent Run を扱う軽量なメタデータを追加する。
- AI Vault のノートを、ユーザーが選んだものだけ長期メモリ候補や main Vault の成果物へ昇格できるようにする。
- 生成物の保持・アーカイブ・明示削除を設計する。自動削除は導入しない。
- Agent の作業結果から、参照した Vault とファイルを辿れる表示を改善する。

## v2 — 運用と権限の拡張

- Vault の追加・無効化、索引清掃、索引再構築を安全に支援する管理画面または専用 CLI を検討する。
- Vault ごとの同期頻度、書込み後の増分同期、索引状態・サイズ・最終同期時刻を可視化する。
- 実際の必要性が生じた場合だけ、Agent ごと・フォルダごとの許可範囲を追加する。v1 の `ai_access` を後方の上限として維持する。
- main 以外の用途別 Vault を、対象固定の業務フローに昇格する場合は個別に operation-scenario contract と ADR を作る。
