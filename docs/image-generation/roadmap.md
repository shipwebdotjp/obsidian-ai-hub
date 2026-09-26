# 画像生成・生成メディア ロードマップ

現行版（`image_generate`）で意図的に見送った機能と、今後追加するとよい機能を
実装可能な粒度で整理する。項目は独立して着手でき、優先度は案である。
不可逆操作（外部送信・アプリ外書込み・削除・認可変更）を含む項目は
[不可逆変更の設計・実装品質ガイド](../development-quality-playbook.md) の対象であり、
各項目に「ゲート」欄で要否を示す。

- 対象読者: 実装者・運用者
- 位置づけ: 生きた計画（実装のたびに更新する。完了した項目は履歴として残さず削除してよい）
- 現行版の利用者向け説明: [画像生成](../../user-guide/docs/features/image-generation.md)
- 決定記録: [画像生成 Capability（generated_media・スキーマ v66）](../../ai_wiki/10-Decisions-Integrations.md#画像生成-capabilitygenerated_mediaスキーマ-v66)

## 現行版のスコープ（実装済み）

| 領域 | 実装 |
| --- | --- |
| ツール | `image_generate`（テキスト→画像）。Agent Registry builtin。Agent / Task / Workflow へ自動派生 |
| 保存 | `media/generation.py`（OpenAI Images API）+ `media/store.py`（原子的書込み + `generated_media` 行） |
| 正本/識別子 | `generated_media.media_id`（サーバー生成）。パスはクライアント非依存 |
| 配信 | `GET /api/v1/media/{media_id}` と `/download`（Bearer 認証、containment 再検証） |
| UI | Agent チャット / Task 詳細 / Workflow 実行の各ツール結果・イベント・Node 出力にインライン表示 + ダウンロード |
| 設定 | `image_generation.{output_dir,model,default_size,default_quality,max_count,timeout_seconds}` + 環境変数 |
| ポリシー | Task Capability の既定承認は `plan_required` |

### 既知の制約（現行版）

- テキストからの生成のみ。入力画像を使う編集・バリエーションは不可。
- 生成物を一覧・検索・削除する UI / API がない（保存先を直接見るしかない）。
- 入力画像の添付は会話の LLM 入力としてのみ使われ、ツールから参照できない。
- `generated_media` は Workflow 実行との紐付け列を持たない（Task の `task_id` までは記録）。
- 画像生成 API 呼び出しは実行ログ・トークン/コスト集計の対象外。
- モデル既定は `gpt-image-2.5-sunburst`。`gpt-image-2.5` は存在せず、`512x512` はモデル最小未満。

---

## R1. 画像編集（image-to-image / バリエーション / マスク）— P0

**目的**: 添付画像や過去に生成した画像を入力に、編集・バリエーション・部分修正を行う。

**現状/制約**
- `ImageGenerateInput` は `prompt` のみで、入力画像を受け取れない。
- 入力画像は `agent_messages.attachments_json` に base64 で保存され、
  `agents/runtime.py:_build_user_message` が LLM のマルチモーダル入力に使うだけ。
  ツール引数（JSON）は 2,000/20,000 文字で切り詰められるため、バイト列を引数に載せられない。
- `agents/store.get_message(message_id)` で添付を取得でき、trusted ctx に
  `user_message_id` が入るため、「そのターンの添付」は参照可能。
- 現行 `media/generation.py` は `client.images.generate` のみ。`client.images.edit` は未使用。

**設計案**
- `generated_media` に `source TEXT NOT NULL DEFAULT 'generated'`（`generated` / `upload`）を追加し、
  ユーザー添付も「メディア」として取り込む（migration。既存行は `generated`）。
  - 取り込みタイミングは送信時（`start_queued_run`）または編集ツール実行時の遅延取り込み。
  - 添付の重複排除は内容ハッシュ `content_sha256` を任意列で持つと再取込を避けられる。
- 新ツール `image_edit`（args schema 単一正本）:
  - `prompt`（必須）、`source_media_id`（`upload`/`generated` いずれか）
  - または `use_current_attachment: bool`（trusted ctx の `user_message_id` 添付を自動採用）
  - `mask_media_id`（任意、透過マスク）、`size`、`quality`、`output_format`、`count`
- `media/generation.py` に `edit_images(...)` を追加（`client.images.edit`）。
  provider 呼び出し・書込み・参照返却は `image_generate` と共通化する。
- Capability 既定は `plan_required`（外部送信 + 書込み）。`_OUTPUT_SCHEMAS` に出力契約を追加。

**影響範囲**: `media/generation.py`, `media/store.py`, `agents/registry.py`,
`database.py`（migration, `source`）, `tasks/capability_schemas.py`,
`web/routes/agents.py`（添付取込）, frontend（添付を入力候補として選べる UI）。

**リスク/不可逆性**: 外部送信 + ファイル書込み。**ゲート: 要**（編集の操作シナリオ契約、fake provider 縦断テスト）。

**未決**: 添付を `generated_media` に取り込むか（テーブル名は generated のままか）、
添付の保持期間、`image_edit` と `image_generate` を1ツールに統合するか。

---

## R2. メディアギャラリー（一覧・検索・詳細）— P0

**目的**: 生成物（将来は添付・音声・動画も）を Web UI で一覧・検索・閲覧・ダウンロードする。

**現状/制約**: 一覧 API / 画面がない。`generated_media` の読み出しは `media_id` 単体のみ
（`media/store.py:get_generated_media`）。

**設計案**
- 読み出し API:
  - `GET /api/v1/media?media_type=&source=&session_id=&task_id=&q=&limit=&cursor=`
    逆方向キーセット（`created_at DESC, media_id`）でページング。既存の
    [会話履歴のページング方針](../../ai_wiki/10-Decisions-Web.md) に合わせる。
  - `GET /api/v1/media/{id}` は既存（バイナリ）。詳細メタは別途
    `GET /api/v1/media/{id}/info`（prompt / model / size / 作成元）を追加。
- 画面: `frontend/src/constants/routes.ts` / `App.tsx` / `Sidebar.tsx` に `/media` を追加。
  グリッド + 遅延読込 + 詳細モーダル + ダウンロード + フィルタ + 作成元へのリンク。
  カードは既存 `GeneratedMediaCard` / `Website` と揃える。
- DB: `generated_media(created_at)`, `(session_id)` は既存。`media_type`/`source`/`task_id` の
  索引を必要に応じて追加。

**影響範囲**: `media/store.py`（list クエリ）, `web/routes/media.py`, `web/api.py`,
frontend `features/media/`（一覧ページ）、`Web UI マップ`。

**リスク/不可逆性**: 読取のみ（P0 範囲）。**ゲート: 不要**（一覧・詳細まで）。

---

## R3. メディアの削除・保持期間・孤児回収 — P0（削除は不可逆）

**目的**: 不要なメディアとファイルを削除し、孤児ファイルを回収する。

**現状/制約**
- 削除経路がない。`store.save_generated_image` は「ファイル→DB 行」順のため、
  DB 失敗時はファイルを消すが、クラッシュ時は孤児ファイルが残り得る（行は欠落ファイルを指さない）。
- 削除は不可逆（アプリ外ファイル + DB 行）。

**設計案**
- `DELETE /api/v1/media/{id}`: DB 行を削除し、containment 済みパスのファイルを削除。
  行が無い / ファイルが無い場合も冪等に成功相当とする。UI は確認ダイアログ + 論理削除ではなく物理削除。
- 保持期間: `image_generation.retention_days`（既定は無期限 or 90 日）を設定。
  Scheduler Job（[jobs](../../user-guide/docs/features/jobs.md)）で期限超過を削除。
- 孤児回収: 出力ディレクトリを走査し、`generated_media.relative_path` に存在しないファイル
  （`.part` 一時ファイル、`output_dir` 直下の管理外ファイルは除外）で一定期間経過したものを削除。
  逆に、行があるがファイルが無い場合は行を残しつつ監査ログに記録（勝手に消さない）。
- 削除・保持の実行主体と記録: `__opcheck_` と同様に識別子をログへ。人間が復旧できる材料を残す。

**影響範囲**: `media/store.py`, `web/routes/media.py`, `scheduler_jobs`（新規ジョブ）, frontend（削除 UI）,
`database.py`（監査が必要なら列追加）。

**リスク/不可逆性**: 削除は不可逆。**ゲート: 要**（削除の操作シナリオ契約、失敗/部分削除時の挙動、
保持設定の既定値決定）。

---

## R4. 作成元（Agent 会話 / Task / Workflow）との紐付け — P1

**目的**: どの会話・Task・Workflow 実行が生成したかを記録し、生成元から辿れるようにする。

**現状/制約**
- `session_id` / `run_id` / `task_id` は記録するが、Workflow 実行 ID は
  bridge Task のコンテキストに載らず、`workflow_run_id` は常に NULL になるため現行版では削除した。
- Workflow の capability 実行は `workflow/runners.py:_run_capability` が
  bridge Task（`origin='workflow'`）を作って Task アダプタ経由で実行する。

**設計案**
- bridge Task コンテキストに Workflow 実行 ID を載せる（`_task_context` へ伝播）か、
  汎用の `origin_kind` / `origin_id`（`agent` / `task` / `workflow` + ID）を導入する。
- ギャラリー詳細からセッション / Task / Workflow 実行ページへリンク。
- 会話メッセージに `media_id` 参照を保持する場合（R5）は、どのメッセージ由来かを併記。

**影響範囲**: `workflow/runners.py`, `tasks/adapters/registry_tools.py`, `media/store.py`,
`database.py`（列）, frontend（リンク）。

**リスク/不可逆性**: なし（メタデータ追加）。**ゲート: 不要**。

---

## R5. アシスタント応答への画像埋め込みと Markdown 連携 — P2

**目的**: 生成画像を会話本文・Markdown ノートへ自然に埋め込めるようにする。

**現状/制約**
- `<img src="/api/v1/media/{id}">` は Bearer ヘッダーを載せられず 401 になる。
  現行 UI は認証付き fetch + オブジェクト URL でカード表示する。
- `components/MarkdownPreview.tsx` は `img` レンダラを持たず、`data:` URL は既定で除去される。

**設計案**
- `MarkdownPreview` に認証対応の `img` コンポーネントを追加し、
  `![alt](/api/v1/media/<id>)` を `GeneratedMediaCard` 相当で描画する
  （共有フックで Blob を取得。全 Markdown 利用箇所に影響する点に注意）。
- アシスタントの最終応答に画像カードが既出でも、本文参照と二重表示にならないよう調整。
- Vault ノートへ画像を置く場合は Vault 内相対パスで `![[...]]` / Markdown 埋め込み（R6）。

**影響範囲**: `components/MarkdownPreview.tsx`, `features/media/*`, Agents/Coding/Research の表示。

**リスク/不可逆性**: なし（表示）。**ゲート: 不要**。共有 Markdown への影響は回帰確認必須。

---

## R6. Vault 連携（メディア保存 / ノート挿入）— P1

**目的**: 生成画像を Vault 内に置き、デイリーノート等から Obsidian でそのまま閲覧・埋め込みできるようにする。
（現行は `output_dir` を Vault サブフォルダにすれば閲覧は可能。以下はより統合された体験。）

**現状/制約**
- `vault_write_file` は UTF-8 テキスト専用でバイナリを扱えない。
- Vault に画像を大量に置くと Vault index / 同期 / バックアップが重くなる（利用者も懸念）。

**設計案**
- 設定 `image_generation.vault_subdir`（例 `media/generated`）を追加し、
  生成時に Vault 配下へも配置する「Vault モード」を選べるようにする。
- 新 Capability `media_to_vault`（`media_id` + `vault_subdir` + `insert_into_note?`）:
  - containment 検証済みのコピー（原子的置換）。既存ファイル上書きは `overwrite` 明示。
  - 任意で対象ノート末尾に `![[...]]` を追記（テキスト書込み、既存の `write_vault_file` 経路を再利用）。
  - 不可逆（Vault 書込み）なので `plan_required`。既存の vault 書込み契約に合わせる。
- 「コピー」ではなく「`output_dir` を Vault 内に設定」を推奨既定にする選択肢も残す。

**影響範囲**: `media/store.py`, `agents/registry.py`（新ツール）, `web/services/vault.py`（バイナリコピー）,
`config.py`, user guide。

**リスク/不可逆性**: Vault への不可逆書込み。**ゲート: 要**（vault 書込みの操作シナリオ契約に準拠）。

---

## R7. プロバイダ / モデル拡張とコスト統制 — P1

**目的**: モデル選択と支出を安全に制御する。

**現状/制約**
- 既定モデルは設定で1つ。呼び出しごとのモデル指定は不可。
- コスト/使用量の集計・上限がない（外部 API は従量課金）。

**設計案**
- 許可モデル allowlist `image_generation.allowed_models` と、呼び出しごとの
  `model` 上書き（allowlist 外は拒否）。`quality`/`size` のモデル別許容値も検証。
- provider 抽象化（OpenAI 直・OpenAI 互換 `base_url`・将来の別ベンダ）。`media/generation.py` に
  クライアントファクトリを集約（既にテスト用注入済み）。
- 予算ガード: 日次/月次の枚数・概算コスト上限、上限超過時は外部呼び出し前に明示失敗。
  使用量は `generated_media.metadata_json` と実行ログ（R8）に記録。
- レート制限・同時実行数の制御（過負荷/連打対策）。

**影響範囲**: `media/generation.py`, `config.py`, `agents/registry.py`,
`utils/execution_logger.py`, `database.py`（必要なら集計列）。

**リスク/不可逆性**: 外部送信。**ゲート: 要**（コスト上限は「送信前に止める」契約）。

---

## R8. 可観測性（実行ログ / メトリクス）— P1

**目的**: 画像 API 呼び出しを LLM 呼び出しと同様に記録し、障害調査とコスト把握に使う。

**現状/制約**
- `utils/execution_logger` は LLM 呼び出し（`start_llm_call` / `succeed_llm_call` / `fail_llm_call`）のみ。
  画像生成は記録されない。

**設計案**
- `media/generation.py` の provider 呼び出しを実行ログに記録（provider / model / size / quality /
  count / 所要時間 / 成否 / エラー種別）。既存の実行ログ画面で確認可能にする。
- 集計（日次枚数、失敗率、平均レイテンシ）をダッシュボード/ヘルスに任意表示。

**影響範囲**: `utils/execution_logger.py`, `database.py`（ひな型）, `media/generation.py`,
`features/execution-logs`。

**リスク/不可逆性**: なし（記録）。**ゲート: 不要**。

---

## R9. 入力検証・エラー処理・モデレーション強化 — P1

**目的**: 異常系と悪性入力に対して安全かつ分かりやすく振る舞う。

**現状/制約**
- provider エラーは `openai` の例外がそのまま `except Exception`（sanitize）へ落ちる。
- URL フォールバックは scheme allowlist + redirect 拒否 + サイズ上限まで実装済み（R10 で更に強化）。
- 保存画像の実体検証（Pillow）やメタデータ除去は未実施、デコンプレッションボム対策も未設定。

**設計案**
- provider エラーの分類とメッセージ化: コンテンツポリシー違反、レート制限（429）、
  5xx / タイムアウトは指数バックオフで限定リトライ、認証/パラメータ不正は即失敗。
- 実体検証: `PIL.Image.open` で形式・寸法・`Image.MAX_IMAGE_PIXELS` を確認し、
  EXIF 除去・サムネイル生成は再エンコードで行う（信頼できないメタデータを保存しない）。
- 取り込むアップロード（R1）には MIME/サイズ/枚数上限と、必要なら内容スキャン。

**影響範囲**: `media/generation.py`, `media/store.py`, `agents/registry.py`。

**リスク/不可逆性**: 外部送信/書込み。**ゲート: 要**（失敗時の副作用なしを契約に含める）。

---

## R10. 画像以外のメディア（音声・動画）— P2

**目的**: 同じ保存・配信・表示の仕組みで他メディアを扱う。

**現状/制約**: テーブルは `media_type` を持ち `type=image` のみ運用。カードは画像前提の分岐あり
（非画像はファイル名表示のみ）。

**設計案**
- `media_type` を `image` / `audio` / `video` に一般化。配信は `Content-Type` と
  `Content-Range`（動画の Range 対応）を検討。
- フロントは `GeneratedMediaCard` を種別ごとのプレーヤ/埋め込みに拡張。ギャラリー（R2）は種別フィルタ。
- 生成ツール（音声 TTS、動画）は別 Capability として追加（同じ `generated_media` を利用）。

**影響範囲**: `media/*`, `web/routes/media.py`, frontend `features/media/*`。

**リスク/不可逆性**: 書込み/外部送信の新ツール次第。**ゲート: ツール追加時に要**。

---

## R11. CLI / 運用ツール — P2

**目的**: 端末から直接生成・確認できるようにする。

**設計案**
- `src/obsidian_ai_hub/` に薄い CLI ラッパ（`--image-generate "prompt"` / `--image-list` / `--image-delete`）。
  アプリロジックは `media/` に置き、CLI は薄く保つ（[AGENTS.md](../../AGENTS.md) の構成規約）。
- 隔離サンドボックス（`make opcheck-serve`）で実データを壊さず確認できるようにする。

**影響範囲**: `main.py`（引数）, `media/*`。

**リスク/不可逆性**: 削除系は不可逆。**ゲート: 削除コマンドで要**。

---

## R12. プリセット・スケジュール生成 — P2

**目的**: よく使う画風/構図を再利用し、定期的に生成する。

**設計案**
- 画風プリセット（prompt テンプレート）を `agent_prompt_templates` と同様の仕組みで管理。
- Scheduler Job から `image_generate` を定期実行（例: 日次の挿絵）。
  生成物はギャラリーで確認、必要なら Vault/ノートへ（R6）。
- `quality`/`size` を安価側に固定したプリセットを既定にし、コストを予測可能にする（R7 と連動）。

**影響範囲**: `scheduler_jobs`, `agents/registry.py`, frontend 設定/ジョブ画面。

**リスク/不可逆性**: 外部送信（定期課金）。**ゲート: 要**（予算上限と停止条件）。

---

## R13. テスト・運用の拡充 — 継続

- Gallery / 編集 / 削除の縦断テスト（fake provider、隔離 DB）。
- 削除・保持・孤児回収の失敗系（部分削除、ファイル欠落、権限エラー）。
- frontend: ギャラリー・カード・フィルタの unit テスト（文言は検証しない）。
- 操作確認は `make opcheck-serve` の隔離サンドボックスを第一選択とし、
  `__opcheck_` 命名で後片付けする（[testing.md](../testing.md)）。

---

## 優先順位（案）

| 優先 | 項目 | 種別 | ゲート |
| --- | --- | --- | --- |
| P0 | R1 画像編集 | 外部送信 + 書込み | 要 |
| P0 | R2 ギャラリー（一覧・詳細） | 読取 | 不要 |
| P0 | R3 削除・保持・孤児回収 | 削除（不可逆） | 要 |
| P1 | R4 作成元の紐付け | メタデータ | 不要 |
| P1 | R6 Vault 連携 | Vault 書込み（不可逆） | 要 |
| P1 | R7 モデル拡張・コスト統制 | 外部送信 | 要 |
| P1 | R8 可観測性 | 記録 | 不要 |
| P1 | R9 検証・エラー・モデレーション | 外部送信/書込み | 要 |
| P2 | R5 応答への埋め込み | 表示 | 不要 |
| P2 | R10 画像以外のメディア | ツール次第 | ツール時 |
| P2 | R11 CLI | ツール次第 | 削除時 |
| P2 | R12 プリセット・定期生成 | 外部送信 | 要 |

推奨着手順: **R2 → R1 → R3**（閲覧できる → 編集できる → 片付けられる）。
R2 は読取のみでリスクが低く、R1/R3 の確認にも必要な土台になる。

## 未決事項（実装前に決める）

- ユーザー添付を `generated_media` に取り込むか（`source` 列の追加とテーブル名の妥当性）。
- 保持期間の既定（無期限 / N 日）と、削除を物理か論理（猶予つき）か。
- 画像ファイルを Vault に置く既定にするか（Vault 肥大化とのトレードオフ）。
- 画像 API 呼び出しの実行ログを既存テーブルに載せるか、専用テーブルにするか。
- コスト上限の単位（枚数 / 概算金額）と、上限超過時の停止範囲（全体 / エージェント単位）。
- 認可: 現状は単一ユーザー前提。複数主体を許す場合のメディア所有権。
