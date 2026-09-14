# Task Agent TODO

実装作業の追跡チェックリスト。フェーズ参照は [implementation-plan.md](implementation-plan.md)、
仕様節参照は [specification.md](specification.md) を指す。

## Decision gates

実装着手前の決定事項 (implementation-plan.md §10)。

- [ ] G1: CLI コマンド名・フラグを決定する (Phase 2, spec §16.1)
- [ ] G2: テーブル名・マイグレーション番号を決定する。既存 `task_state` (v19) との名前衝突を回避する (Phase 0, spec §16.2)
- [ ] G3: Workspace ロックの実装方式 (DB テーブル vs インプロセス) を決定する (Phase 5, spec §16.3)
- [ ] G4: Capability Manifest の保存形式 (既存 `agents` テーブルとの統合方法) を決定する (Phase 3, spec §16.4)
- [ ] G5: 逸脱検知の機構 (自己申告＋監査 vs 機械照合) を決定する (Phase 5, spec §16.5)
- [ ] G6: トレースの保存閾値 (全文保存 vs 要約) を決定する (Phase 1/7, spec §16.6)
- [ ] G7: トレース保持期限 (既存 30 日ポリシーとの関係) を決定する (Phase 7, spec §16.7)
- [ ] G8: 既存 HITL の LINE 通知誘導を Task Agent で使うか決定する (Phase 4, spec §16.8)
- [ ] G9: WebUI URL のパス設計 (タスク詳細ページのルーティング) を決定する (Phase 2/4, spec §16.9)
- [ ] G10: 委譲先 CLI セッションを coding workspace のセッションとして共有するか決定する (Phase 5, spec §16.10)

## Domain and persistence

- [ ] tasks 系テーブルの DDL 素案を仕様 §17 から作成し、レビューする (Phase 0)
- [ ] 新 migration を `database.py` に追加し、`PRAGMA user_version` を進める (Phase 1)
- [ ] migration テスト: 既存 v43 からの連続適用とテーブル存在確認 (Phase 1)
- [ ] `tasks` / `task_plans` / `task_events` / `task_artifacts` / `capabilities` の永続化 API を実装する (Phase 1)
- [ ] 計画の版管理 (同一 task_id で version 加算) を実装する (Phase 1, spec §7.2)

## Task intake and worker

- [ ] タスク受付サービス (自由文＋メタデータ → task 登録 → task_id/状態/WebUI URL 返却) を実装する (Phase 1, spec §15)
- [ ] CLI 投入フラグを実装し、即時返却契約 (spec §4) を満たす (Phase 2)
- [ ] CLI 投入の空入力エラー処理を実装する (Phase 2, spec §4)
- [ ] 常駐ワーカーの claim (`queued` → `planning`) を実装する (Phase 2)
- [ ] インスタンスロックによる二重 claim 防止を確認する (Phase 2, `runs/instance.py` 流用)
- [ ] launchd / Makefile へワーカー起動を追加する (Phase 2)

## Planning and HITL

- [ ] 計画生成 (目的・手順・ツール/委譲先・対象・想定変更・完了条件) を実装する (Phase 3, spec §7.1)
- [ ] 曖昧な依頼の HITL 質問フォールバック (`planning` → `waiting_user`) を実装する (Phase 3, spec §8.1)
- [ ] `task_hitl_links` で既存 `hitl_runs` とタスクを紐付ける (Phase 4)
- [ ] WebUI 受信箱 (HITL Request 一覧、ポーリング) を実装する (Phase 4, spec §5)
- [ ] 計画承認操作 (`waiting_approval` → `ready`) を実装する (Phase 4, spec §7.2)
- [ ] 理由必須の差戻し操作 (`waiting_approval`/`waiting_reapproval` → `planning`) を実装する (Phase 4, spec §7.2)
- [ ] タスク取消操作を実装する (Phase 4, spec §9.3)
- [ ] タスク詳細画面 (状態・計画版・トレース・成果物・変更一覧) を実装する (Phase 4, spec §5)

## Workspace and locking

- [ ] Workspace 解決規則 (Vault / 有効 `project_path` の確定済み Project) を実装する (Phase 3, spec §8.1)
- [ ] `validate_git_repo` による Git ルート正規化を解決に組み込む (Phase 3, spec §8.1)
- [ ] 未解決候補・パスなし Project を対象外にするテストを書く (Phase 3, spec §8.1)
- [ ] Workspace ロック (書込み排他・読取共有) を実装する (Phase 5, spec §8.2)
- [ ] `waiting_lock` 状態への遷移と解放後の `running` 遷移を実装する (Phase 5, spec §13.1)

## Capability and delegation

- [ ] Capability Manifest モデル (名前・説明・入力仕様・必要権限・アダプター種別・リトライ方針) を実装する (Phase 3, spec §12)
- [ ] Vault Adapter (検索・読取・作成・編集・削除) を実装する (Phase 5, spec §12)
- [ ] specialist_agent Adapter (既存 `agents/` 基盤の呼出しと結果正規化) を実装する (Phase 5, spec §12)
- [ ] coding_cli Adapter (既存 `coding/backend.py` の呼出しと結果正規化) を実装する (Phase 5, spec §12)
- [ ] 委譲記録 (`task_delegations`: 委譲先・入力要約・結果要約) を実装する (Phase 5, spec §14)
- [ ] Manifest 宣言範囲内でのみの自動リトライを実装する (Phase 5, spec §9.1)

## Execution and cancellation

- [ ] 実行ループ (LLM ツール呼出し + 永続状態機械) を実装する (Phase 5, spec §11)
- [ ] 逸脱検出時の停止と改訂計画・再承認 (`waiting_reapproval`) を実装する (Phase 5, spec §7.3)
- [ ] 協調的取消 (新ステップ開始禁止・実行中ツールへの中止要求・途中変更のトレース記録) を実装する (Phase 6, spec §9.3)
- [ ] startup/shutdown recovery による `interrupted` 化を実装する (Phase 6, spec §9.2)
- [ ] 再起動後の自動再実行が発生しないことを確認する (Phase 6, spec §9.2)
- [ ] 失敗時の実施済み変更・未実施手順・復旧案の記録を実装する (Phase 6, spec §9.4)

## Trace and security

- [ ] Trace Event の追記 API と redact フックを実装する (Phase 1, spec §14)
- [ ] 秘密値が DB・プロンプト・トレースに現れないことをテストする (Phase 7, spec §10)
- [ ] Vault・ツール出力中の命令文が命令源として扱われない注入耐性テストを書く (Phase 7, spec §10)
- [ ] LLM の非公開思考過程を保存しないことをトレース実装で確認する (Phase 7, spec §14)

## WebUI

- [ ] タスク詳細ページのルーティングを実装する (Phase 4, spec §16.9)
- [ ] 受信箱・詳細画面のフロントエンド単体テストを追加する (Phase 4)
- [ ] タスク系 Web API の結合テスト (回答・承認・差戻し・取消の遷移) を追加する (Phase 4)

## Tests and verification

- [ ] 全 30 許可遷移のパラメータ化テストを実装する (Phase 1, spec §13.1)
- [ ] 代表禁止遷移 (終端からの遷移、`queued→running`、`interrupted→running`、`waiting_approval→running`) の拒否テストを書く (Phase 1, spec §13.3)
- [ ] 同一 Workspace 排他・異なる Workspace 並列の並行テストを書く (Phase 5, spec §8.2)
- [ ] ワーカー停止シミュレーションで `interrupted` 化と非自動再実行を確認する (Phase 6, spec §9.2)
- [ ] CLI→WebUI 往復の E2E シナリオ (6 本) を手動確認する (Phase 7, implementation-plan §7)

## Documentation and operations

- [ ] README / Makefile へワーカー運用手順を追記する (Phase 7)
- [ ] decision gates の決定結果を仕様書 §16 へ反映する (Phase 0)
- [ ] 受入基準 (spec §18) の 10 項目を順に確認し、結果を記録する (Phase 7)

## Post-MVP

- [ ] Inbox 投入入口を受付サービスへ接続する (spec §15)
- [ ] 定期実行入口を受付サービスへ接続する (spec §15)
- [ ] 実行上限 (ステップ数・時間・コスト) の導入を検討する (spec §11 の将来課題)
- [ ] 承認時スナップショットと実行時状態の一致保証を検討する (spec §7.4 の将来課題)
- [ ] 親側サンドボックス (パス許可リスト等) を検討する (ADR: Workspace 解決とコーディング CLI の信頼境界 の将来課題)
