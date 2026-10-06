# Multi-Vault v1 実装計画

## Phase 1 — 設定と起動基盤

1. Vault Registry のモデル、設定読み込み、primary Vault 解決を追加する。
2. 旧単数 Vault 設定を削除し、main 専用の設定を `primary_vault` へ移す。
3. 起動時設定検証と LaunchAgent 用の起動状態／失敗理由を実装し、`make status-web` を診断入口にする。
4. `ENV=test` と opcheck が3つの一時 Vault を使うよう更新する。
5. 多数モジュールに影響する理由、破壊的な設定切替、AI access 境界を Architecture ADR に記録する。

完了条件: 有効な Registry で Web が起動し、無効な Registry では Web が起動せず `make status-web` だけで設定理由を確認できる。

## Phase 2 — 共通 Vault 操作と索引

1. Registry を唯一の入口として、安全なファイル解決・列挙・読取り・書込みを Vault ID 対応に置き換える。
2. 検索インデックス、専用スレッド所有、同期、再構築を Vault 単位に分離する。
3. `--sync-vault`／`--rebuild-vault` の全 Vault・個別 Vault 契約を導入し、パス変更による索引無効化を実装する。
4. 既存の日次、Inbox、人物、リサーチ、ダッシュボード、Copilot プロファイルなどを primary Vault 解決経由へ移す。

完了条件: main / blog / ai を互いに混在させずに同期・検索・読取り・書込みでき、main 専用フローの出力先が変わらない。

## Phase 3 — Agent、Task、Workflow

1. Agent 設定・API・CLI・SQLite に `default_vault_ids` を追加し、既存値を main へ migration する。
2. Agent の Vault ツール、Run 信頼済み文脈、ツール履歴、`@` 文脈参照を Vault ID 対応にする。
3. `ai_access` を全 AI 経路で副作用直前に強制する。通常 Agent の blog / ai 書込みは直接実行し、main 汎用書込みは拒否する。
4. Task Agent／Workflow の schema と Capability adapter を Vault ID 対応にし、既存 `plan_required` を維持する。

完了条件: Agent の既定検索、単発の追加 Vault 検索、別 Vault ファイル添付、blog / ai への直接書込み、main への拒否が一貫して動く。

## Phase 4 — Web UI、CLI、運用文書

1. Vault 検索を全 Vault 既定の横断検索へ、ファイルエクスプローラーを Vault 選択式へ更新する。
2. Agent 編集画面に既定 Vault 選択を追加し、検索結果・添付チップ・ツール結果に Vault 表示を加える。
3. CLI、API 型、ユーザーガイドを破壊的な新契約へ更新する。README に詳細を重複させない。
4. 実運用では `make restart`、`make status-web`、隔離 opcheck を使って確認する。実 Vault へ書込み確認を行う場合は `__opcheck_` 接頭辞を使い、依存物を含めて削除・不在確認する。

完了条件: UI と CLI のすべての Vault 操作が Vault ID を曖昧にせず表示・実行でき、設定方法と障害診断方法がユーザーガイドで分かる。

## 検証方針

- Registry: ID、root、入れ子、AI access、起動状態の失敗表示。
- Migration: 既存 Agent の main 既定化、既存 context ref の main 補完、既存 DB データ保持。
- 索引: Vault 分離、全件／個別同期、部分失敗、パス変更後の rebuild 必須。
- 認可: `none` / `read` / `write`、main の汎用 AI 書込み拒否、対象固定 main フロー維持。
- Agent: 既定対象、単発追加、Vault をまたぐ context ref、ツール履歴、書込み直後の直接参照。
- Task／Workflow: 承認ポリシー維持と Vault ID schema。
- 不可逆書込み: fake／一時 Vault を用いた縦断テストで、入力検証から原子的書込み、記録、競合停止、同期遅延まで確認する。
