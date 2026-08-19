# アーキテクチャ・運用の決定記録

## バックアップ失敗の実行ログ記録

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-02 |
| カテゴリ | バックアップ・実行ログ |
| 決定内容 | backup は rsync の失敗を `sys.exit()` で終了せず、同期元・同期先・終了コード・標準エラーを含む `BackupError` を送出し、CLI 実行ログを `failed` として完了させる |

### 結論に至った経緯

`SystemExit` は通常の `Exception` 捕捉を通らないため、CLI ラッパーの `finally` による `[END]` 出力だけが残り、`command_runs` が `running` のままになる。rsync の標準エラーも破棄されていたため、Web UI の実行ログだけでは失敗理由を確認できなかった。失敗した同期をすべて実行後に詳細を集約した例外として送出し、既存の例外ログ記録経路で保存する。

## 共有SQLiteの所有者はdatabase.py、長期記憶はmemoryパッケージ

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-20 |
| カテゴリ | アーキテクチャ・分割 |
| 決定内容 | 共有SQLiteの接続・マイグレーションは `obsidian_ai_hub.database` に集約し、長期記憶は `obsidian_ai_hub.memory` パッケージに分割する。`obsidian_ai_hub.memory` は公開APIのファサードとして維持する |

### 結論に至った経緯

旧 `memory.py`（約2,600行）は、長期記憶のライフサイクルに加えて、memories / research_themes / activity_logs / summaries / people など全ドメインが共有するSQLiteの初期化と v1–v8 マイグレーションを抱えていた。これにより、

- summary / activity / research / people_sync が `from obsidian_ai_hub.memory import get_db_connection` に依存し、メモリ機能に間接的に引きずられる
- LLMクライアントなどの重い依存が、SQLiteだけを利用するドメインにも伝播する
- ファイルが肥大化し、見通しと保守性が悪化している

という問題があった。LLM呼び出しを含むメモリ機能と、純粋なDB基盤を分離する必要がある。

### 構造

- `obsidian_ai_hub.database` — SQLite接続、テスト環境の本番DBガード、v1–v8 マイグレーション、スキーマ所有者。
- `obsidian_ai_hub.utils.embeddings` — 遅延初期化されるSBERT埋め込みと `cosine_similarity`。研究ドメインからも直接利用される。
- `obsidian_ai_hub.memory` パッケージ:
  - `models` — カラム定数、ID/時刻生成、安定性検証、シリアライザ、マージヘルパ、EDITABLE_FIELDS。
  - `store` — memories / events のCRUD、`log_memory_event`、`_prune_dedup_suggestions`。
  - `dedup` — 完全一致 / ベクトル類似 / LLM による重複候補評価。
  - `extraction` — 週範囲算出、ソース抽出、LLM抽出、保存。
  - `review` — 承認 / 却下 / 編集 / 一括 / resolve / 削除のライフサイクル。
  - `context` — 有効期限判定、expired 遷移、`compile_context`。
  - `projection` — `approved.md` と copilot profile Markdown の生成。
  - `__init__.py` — 公開APIのファサード。再エクスポートのみで、テストやCLI、Webからの `from obsidian_ai_hub import memory` を維持する。

### 互換性

- 既存の import パス `from obsidian_ai_hub import memory` および `from obsidian_ai_hub.memory import symbol` は維持される。
- テストの monkeypatch 対象 (`obsidian_ai_hub.memory.llm_client`、`obsidian_ai_hub.memory.generate_memory_id` 等) は、ファサード経由の解決に変更することで互換性を保つ。
- DBスキーマ・マイグレーション内容はバイト等価で、既存の本番DBはそのまま v8 までマイグレーションされる。
- テストでは `test_memory_db_path` フィクスチャと `OBSIDIAN_AI_HUB_TESTING=1` による本番DB保護を引き続き利用する。

### トレードオフ

- ファサードを維持するため、 `obsidian_ai_hub.memory` の責務が依然として広範に見える。実装はサブパッケージに閉じているため、コードの見た目は改善している。
- 依存方向は `models → stdlib`、`store → database + models`、`dedup / extraction / review / context / projection → 上位層` となり、循環importは存在しない。
- `projection` だけは `approved.md` の書き出しをトリガするため `review` と `context` から逆参照される。import-time の循環を避けるため、`projection.project_approved_memories` の呼び出しはローカル import で行う。

## プロジェクト追跡機能の導入と設計

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-20 |
| カテゴリ | プロジェクト管理 |
| 決定内容 | ゴール・終了状態を持つ「プロジェクト」の1マスタ一元管理、数値ID化、日次でのLLMによる候補抽出・自動照合、週次・月次でのリンクの和集合による継承を導入する |

### 結論に至った経緯

1. **プロジェクト概念の定義と境界:**
   - 「プロジェクト」は仕事・個人の境界を超え、同一マスタで一元管理される。inquiry (検討中・未着手)・active (進行中)・paused (保留中)・completed (完了)・cancelled (中止) の状態遷移を持ち、タグは持たない。
   - LLMがプロジェクト候補を自動抽出する際、単発の雑務や継続習慣、一般的な関心領域と明確に区別し、「ゴールまたは終了状態を持つ取り組み」に限定する。

2. **数値自動採番IDと既存リンク移行:**
   - `projects.project_id` および `project_candidates.candidate_id` は SQLite の `INTEGER PRIMARY KEY` による自動採番を採用（AUTOINCREMENT は付与しない）。
   - マイグレーション（スキーマバージョン 9）で、以前の未使用な文字列IDベース of `projects` / `summary_projects` は DROP & RE-CREATE して再構築した。
   - 候補（candidate）を「新規正式プロジェクトとして承認」または「既存プロジェクトへ紐付け」する際は、過去に紐付いていた全要約リンク（`summary_project_candidates`）を正式プロジェクト（`summary_projects`）へ自動移管し、元の候補リンクは削除し、候補は `resolved`（解決済みアーカイブ）状態へと更新する。

3. **却下済み候補の重複抑止:**
   - 候補を却下（`rejected`）すると、対象候補に紐付いていた `summary_project_candidates` のリンクはすべて削除される（過去のサマリーにも表示しない）。
   - 却下された候補レコードはDB内に `status = 'rejected'` として保持され、日次のLLM要約抽出で同じ正規化名を持つ候補が検出されても、サーバー側で保存せず無視（スキップ）する。
   - 「却下候補の再開」を行うと、ステータスは `unresolved` に戻りインボックスに復帰する。

4. **週次・月次での Union 継承（LLM非介在）:**
   - 週次サマリーはLLMによる再判定を行わず、該当週に属する日次サマリが持つ `summary_projects`（正式プロジェクト）および `summary_project_candidates`（未解決候補）を収集し、和集合（Union）をとって継承保存する。
   - 月次サマリーも同様に、該当月を覆う週次サマリのプロジェクト・候補リンクを和集合で継承する。
   - すでに解決・却下された候補リンクは、自動的に除外または正式プロジェクトのリンクへと変換される。

## Web サーバー環境変数の OBSIDIAN_AI_HUB_ プレフィックス統一

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-12 |
| カテゴリ | 環境変数・命名 |
| 決定内容 | Web サーバー関連の環境変数は「メモリレビュー専用」ではなくアプリ全体に影響するため、`MEMORY_REVIEW_*` を `OBSIDIAN_AI_HUB_*` に改名する。 |

### 結論に至った経緯

`MEMORY_REVIEW_API_TOKEN` は Web API 全体の認証、`MEMORY_REVIEW_HOST` / `PORT` / `CORS_ORIGINS` は Web サーバー全体のバインド・CORS 設定であり、メモリレビュー機能に限定されない。実態に合わせたプレフィックスへ統一した。

### 変更対象（env var → 新名称）

- `MEMORY_REVIEW_API_TOKEN` → `OBSIDIAN_AI_HUB_API_TOKEN`
- `MEMORY_REVIEW_ALLOW_TAILNET_TASKS` → `OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS`
- `MEMORY_REVIEW_HOST` → `OBSIDIAN_AI_HUB_HOST`
- `MEMORY_REVIEW_PORT` → `OBSIDIAN_AI_HUB_PORT`
- `MEMORY_REVIEW_CORS_ORIGINS` → `OBSIDIAN_AI_HUB_CORS_ORIGINS`
- `MEMORY_REVIEW_FRONTEND_DIST` → `OBSIDIAN_AI_HUB_FRONTEND_DIST`

既存のテスト隔離変数（`OBSIDIAN_AI_HUB_TESTING` 等）と命名が揃い、`.env` および launchd plist は旧名に依存していないため設定変更は不要。

## 実行・LLMログ基盤と30日保持期限の導入

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-21 |
| カテゴリ | 実行ログ・LLMログ |
| 決定内容 | CLIの全アクションとLLMコールの履歴を共有SQLiteのスキーマバージョン10（`command_runs`, `llm_call_logs`）に保存し、30日経過レコードを書き込み時に自動クリーンアップする。 |

### 結論に至った経緯

1. **実行・LLMコールの透明性と診断性:**
   - システム運用中のCLIアクションの実行ステータス（開始、成功、失敗、例外情報）および、各タスクが呼び出すLLM呼び出し（プロンプト、応答、温度、消費トークン、finish reason）を正確に記録・可視化し、Web UIでトラブルシューティングを行えるようにする。

2. **30日間の保持期限とクリーンアップ:**
   - LLMの入出力には個人メモや機密情報を含み得るため、長期間の肥大化を防ぎセキュリティ境界を守る観点から、保持期間は開始時刻から30日とする。
   - 新規ログの書き込み（開始、成功、失敗時）トリガーでクリーンアップを自動実行し、外部キー制約（ON DELETE CASCADE）と整合するよう、先にLLMログを削除し、その後にコマンドログを削除する。

3. **安全な伝播と不完全な応答の厳格化:**
    - `ContextVar` を用いて、スレッド・非同期の境界をまたいで親 `run_id` を伝播する。CLI外からのLLM呼び出しは親なしの独立したLLMログとして記録される。
    - 日次要約を含む要約機能において、LLMの不完全な応答（閉じフェンスがない、切り捨てられた不完全なJSONなど）は自動修復・部分的な保存を一切行わず、明確なエラー（ValueError）として例外を上位に伝播させ、コマンド全体を失敗として記録する。

## アクティビティログへの既存プロジェクト紐付け

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-07-22 |
| カテゴリ | アクティビティログ・プロジェクト管理 |
| 決定内容 | 新規アクティビティログを記録する際、LLMによる分類と同時に既存プロジェクトへの紐付け（0件または1件）を行う。 |

### 結論に至った経緯

アクティビティログと進行中のプロジェクトを関連付けることで、どのプロジェクトにどれだけの時間が使われているかをダッシュボード等で可視化・追跡できるようにする。

### 実装・紐付け基準

1. **紐付け基準と優先度:**
   - 画面情報（前面アプリ名、ウィンドウタイトル）およびOCRテキストに**直接的かつ明確な根拠**がある場合のみ、既存プロジェクト（最大1件）に紐付ける。
   - 曖昧な場合や該当するものがない場合は必ず `null`（未紐付け）とする。**「誤紐付けより未紐付けを優先」**する。
   - この紐付けはLLMが推定した補助メタデータであり、正確な工数・進捗・プロジェクト実績の厳密な記録ではない。
2. **対象プロジェクト:**
   - LLMに提示する既存プロジェクトは、ステータスが `inquiry`, `active`, `paused` のプロジェクトのみとする。
   - 完了・中止済みのプロジェクト、未解決プロジェクト候補、新規候補は紐付け対象外とする。
3. **境界条件と遡及制限:**
   - 新規アクティビティログの記録時のみ自動紐付けを適用し、新規プロジェクト候補の自動作成や過去の既存ログの一括遡及分類・補完は行わない。

## Web サービス層の分割リファクタリング

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-01 |
| カテゴリ | アーキテクチャ・構成 |
| 決定内容 | 2,719行に肥大化した `src/obsidian_ai_hub/web/service.py` を、機能ドメイン単位のサブパッケージ `web/services/` に分割する。`web/service.py` は公開APIのファサード（再エクスポートのみ）として維持し、`api.py`・テスト・`summary/project_utils.py` の既存 import を変更せず互換性を保証する。 |

### 構造

- `services/memory.py` — 長期記憶（list/get/review/update/resolve/delete 等）。
- `services/research.py` — リサーチテーマ（list/get/run/rerun）。
- `services/vault.py` — Vault 検索・ファイル読み取り。
- `services/dashboard.py` — ダッシュボード（home/browse/day/stats）と集計ヘルパ。
- `services/projects.py` — プロジェクト・プロジェクト候補。`ProjectConflictError` を所有。
- `services/people.py` — 人物 CRUD・別名編集。人物系コンフリクト例外（`AliasConflictError` 等）を所有。
- `services/people_candidates.py` — 人物候補（list/detail/assign/resolve/promote）。
- `services/people_merge.py` — 人物統合（verify/preview/merge）と重複候補検出。
- `services/people_sync.py` — Vault 同期とレポート。
- `services/summary.py` — サマリ編集オプション・詳細更新/削除。
- `services/task_config.py` — タスク設定（get/update/preview）。`TaskConfigConflictError` を所有。
- `services/execution_logs.py` — 実行ログ・LLM コール詳細。
- `services/hitl.py` — HITL 実行一覧・回答・キャンセル。

### 結論に至った経緯

`service.py` は API ルーター `api.py` からモジュール全体を `service.X` として参照され、テストも `service.X`・パッチ（`obsidian_ai_hub.web.service.<func>`）・直接 import で同一モジュールに依存している。memory パッケージ分割で確立済みの「公開APIのファサードを維持する」パターンを踏襲し、`service.py` を再エクスポート専用にすることで、`api.py`・テスト・`summary/project_utils.py` を一切変更せずに分割できる。ロジックは一切変更せず純粋な移動・抽出のみとする。People 領域はさらに candidate / merge / sync で機能分割し、単一モジュールの肥大化（約1,150行）を回避する。

### 検証

- `uv run pytest tests/` を全通過させる。
- lint 設定は存在しないため、テストにより回帰がないことを担保する。

## 決定記録を領域別ファイルへ分割する

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-15 |
| カテゴリ | ドキュメント・意思決定記録 |
| 決定内容 | 汎用の `10-Decisions.md` へ決定を追記し続けず、アーキテクチャ・運用、Web・フロントエンド、HITL、外部連携、テスト・開発環境、人物同定・人物管理の領域別記録に追加する。`00-Index.md` を入口とし、旧 `10-Decisions.md` は既存アンカーを維持する互換案内とする。 |

### 結論に至った経緯

旧 `10-Decisions.md` は約45件・1,000行超となり、関連する判断を探すために全体を横断する必要があった。すでに人物同定には独立した決定記録が存在しており、同じ責務別の整理を他領域にも適用できる。

決定本文を見出し単位で移動し、索引から各領域へ到達できるようにすることで、日常の参照と追記を小さな文書に限定する。一方、過去の文書やブックマークからの `10-Decisions.md` の見出しリンクを壊さないため、旧ファイルには同じ見出しを残して移転先を案内する。

### 運用ルール

- 新しい決定は `00-Index.md` を参照し、主な変更対象の領域の決定記録へ追加する。
- 複数領域にまたがる場合も本文は1か所だけに置き、他の領域や索引からリンクする。
- 新たな領域別記録が必要になった場合は、先に `00-Index.md` とこの運用ルールを更新する。

## Inboxの準リアルタイム処理をHITLから分離したまま既存task runnerで毎分バッチ化

| 項目 | 内容 |
|------|------|
| 決定日 | 2026-08-19 |
| カテゴリ | アーキテクチャ・運用 / Inbox処理 |
| 決定内容 | `merge_inbox` を `minutely` / `second: 0` に変更し、既存の LaunchAgent（`StartInterval: 60`）と `task_runner` の `fcntl` 単一実行ロックで毎分起動する。常駐worker・watchdog・FSEvents・launchd `WatchPaths` は導入しない。通常ファイルは `mtime` から5秒未満なら次回実行へ回し、iCloudオフロード済みファイルは既存のダウンロード要求と最大60秒待機を維持する。マージ・転記・分類が成功した場合のみ元ファイルを削除する。WhisperモデルはそのCLIプロセス内のみでロードし、終了時に解放する。HITL worker への統合せず、`10-Decisions-HITL.md` は変更しない。 |

### 結論に至った経緯

- **launchd `WatchPaths` を主トリガーにしない**: Appleのlaunchd資料（Creating Launch Daemons and Agents）に明記されている通り、`WatchPaths` はイベント欠落や不整合状態を許容する。Inbox処理を主トリガーにするには信頼性が不足するため、60秒間隔の `StartInterval` で毎分の `task_runner` 起動に乗せる。
- **常駐worker・FSEvents を追加しない**: HITL worker は `KeepAlive` 常駐で応答責務を持ち、Inbox処理は冪等なバッチで十分準リアルタイム化できる。別workerを追加するとプロセス管理・依存・リソースが二重化し、HITLの責務境界を越える。
- **既存 LaunchAgent と `task_runner` の単一実行ロックで十分**: `jp.shipweb.obsidian-ai-hub.plist` は `StartInterval: 60` で `task_runner` を起動済み。`task_runner.main()` は `RUNNER_LOCK_FILE` を `fcntl.LOCK_EX | LOCK_NB` で取得するため、長時間の音声転記中でも重複起動は抑止される。
- **5秒猶予は mtime 基準の単一stat**: per-minute バッチが保存と同時刻で走った場合の軽い安全策として、`mtime + 5 > now` のとき処理・削除せず次回へ回す。待機や二重statは行わない。逐次書き込みの厳密検出は目的としない。
- **削除は成功時のみ**: `os.remove` への置き換えにより、`is_icloud_offloaded` 待機失敗・読込失敗・転記失敗・マージ例外では元ファイルを残し、次回実行で再試行できるようにする。メモ分類フォールバックは成功として扱う（daily noteへ追記された=成功）。
- **HITL分離**: calendar / reminder 分岐は HITL 承認runを登録するが、これは `10-Decisions-HITL.md` の既存責務であり、本決定のスコープ外。Inbox処理の起動方式のみを変更する。
