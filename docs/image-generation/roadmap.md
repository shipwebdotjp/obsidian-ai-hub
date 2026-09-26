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

**状態: 実装済み（2026-09-26）。** 入力契約は
[ADR（media_id 正本 + 入口での自動取り込み）](../image-generation/adr/image-edit-input-contract.md) 参照。
以下は設計の記録として残す。

**目的**: 添付画像や過去に生成した画像を入力に、編集・バリエーション・部分修正を行う。

**現状/制約**
- `ImageGenerateInput` は `prompt` のみで、入力画像を受け取れない。
- 入力画像は `agent_messages.attachments_json` に base64 で保存され、
  `agents/runtime.py:_build_user_message` が LLM のマルチモーダル入力に使うだけ。
  ツール引数（JSON）は 2,000/20,000 文字で切り詰められるため、バイト列を引数に載せられない。
- `agents/store.get_message(message_id)` で添付を取得でき、trusted ctx に
  `user_message_id` が入るため、「そのターンの添付」は参照可能。
- 現行 `media/generation.py` は `client.images.generate` のみ。`client.images.edit` は未使用。

**設計方針（推奨）: `media_id` を正本にしつつ、入口で自動取り込み（事前登録は必須にしない）**

入力画像の与え方は次の3案を比較した。

| 案 | 会話（添付） | Task / Workflow | 正本/来歴 | 主な欠点 |
| --- | --- | --- | --- | --- |
| A. 添付 or パスのみ（取り込みなし） | 添付をそのまま送る | パスを読んで送る | 入力は正本化されない | 来歴/ギャラリーが不統一。パスが唯一の識別子で任意ファイル読取の面が広がる |
| B. 事前アップロード + DB 登録必須 → `media_id` 指定 | 事前アップ→ID 指定 | 事前アップ→ID 指定 | 統一 | 会話 UX が悪い。Task/Workflow に登録の往復と余分な承認が増える |
| **C. `media_id` 正本 + 入口で自動取り込み（推奨）** | ターン添付を自動取り込み | パスを渡すと内部で取り込む | 統一 | 実装がやや増える（取り込み層） |

案 C を採る。**外から見た入力は「添付」か「パス」か「既存 media_id」だが、内部では必ず
`generated_media` の行（`media_id`）に正規化してから provider へ送る。** これにより
会話の手軽さと Task/Workflow の実用性を保ちつつ、来歴・ギャラリー・重複排除が一貫する。

**入力モード（`image_edit` の args schema、いずれか1つ必須）**
- `use_current_attachment: true` — 会話用。trusted ctx の `user_message_id` の添付を採用。
- `source_path: str` — Task/Workflow 用。許可ルート配下のみ。内部で取り込む。
- `source_media_id: str` — 既存メディア（`generated` / `upload` / `import`）を再利用。
- 共通: `prompt`（必須）、`mask_media_id` / `mask_path`（任意）、`size`、`quality`、`output_format`、`count`。
- 引数に base64 を載せない（ツール結果/引数は切り詰められるため）。

**データモデル（migration v67）**
- `generated_media.source TEXT NOT NULL DEFAULT 'generated'`（`generated` / `upload` / `import`）。
- `generated_media.content_sha256 TEXT`（任意・索引）— 添付/パスの再取り込みを重複排除。
- 出力側 `metadata_json` に `{"operation":"edit","source_media_id":...}` を記録し系列を辿れるようにする。

**取り込み層（新 `media/ingest.py`）**
- `ingest_attachment(...)`（会話）、`ingest_path(...)`（Task/Workflow）、`ingest_bytes(...)`（共通）。
- パス許可ルート: `VAULT_PATH`、`IMAGE_GENERATION_OUTPUT_DIR`、任意の `image_generation.input_dir`。
  絶対パスは許可ルート内のみ、相対パスは `input_dir`（既定 Vault）基準。NUL/`..`/シンボリックリンク脱出・
  非正規ファイルを拒否（`web/services/vault.py` の containment 流用）。
- 実体検証: Pillow で形式（png/jpeg/webp）・寸法・`Image.MAX_IMAGE_PIXELS`、`max_input_bytes` 上限。
  マスクは入力画像と同寸法を検証（provider 要件）。

**各面のフロー**
- 会話: ターン送信時に添付を `generated_media(source='upload')` へ取り込み、当該ターンの
  media_id をコンテキストに1行注入する。LLM は `use_current_attachment` か media_id で編集を呼べる。
  会話履歴の base64 は LLM 再送用に残す（重複は `content_sha256` で抑制）。
- Task: Runtime Orchestrator が履歴から詳細入力を実行時生成するため、
  ユーザー発話中のパスを `source_path` に、または先行アクションの観測にある media_id を
  `source_media_id` に入れて1ステップで実行できる（登録往復は不要）。
- Workflow: 参照は配列添字に対応（`nodes.<id>.output.images[0].media_id`）。
  `run.inputs.media_id` / 前段 Node 出力 / `source_path` のいずれかを入力にする。

**共通化**
- `media/generation.py` に `edit_images(...)`（`client.images.edit`）。provider 呼び出し・書込み・
  参照返却は `image_generate` と共通関数へ集約。`image_generate` / `image_edit` は同一の書込み・
  失敗補償（DB 失敗時にファイル削除）を共有する。
- Capability 既定は `plan_required`。`_OUTPUT_SCHEMAS` に入力/出力契約を追加。
- 取り込んだ入力メディアは失敗時も残す（ギャラリー/再試行で再利用）。出力は provider 失敗時に作らない。

**スコープ（R1 MVP）**
- 会話: 添付の自動取り込み + `use_current_attachment` / `source_media_id`。
- Task/Workflow: `source_path` / `source_media_id`。
- **新しいアップロード UI は作らない**（手元の新規ファイルを Task/Workflow へ入れる導線は
  R2 のメディアピッカー/共有アップロードで対応する）。

**影響範囲**: `media/generation.py`, `media/ingest.py`(新), `media/store.py`, `agents/registry.py`,
`database.py`（migration v67）, `tasks/capability_schemas.py`, `web/routes/agents.py`（添付取込）,
`web/services/vault.py`（containment 再利用）, `utils/config.py`, frontend（添付を入力候補に）。

**リスク/不可逆性**: 外部送信 + ファイル書込み（+ パス読取）。**ゲート: 要**
（操作シナリオ契約: 入力検証→取込→1回送信→保存、失敗時に外部送信しない、パス脱出拒否の fake provider 縦断テスト）。

**未決**: 添付の保持期間（R3 と連動）、`image_generate` と `image_edit` を1ツールに統合するか、
`input_dir` を追加するか Vault/出力先だけで足りるか、編集の入力に ratio/fidelity 相当のパラメータを足すか。
実装時は本項を ADR 化する（入力契約に代替案と横断影響があるため）。

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

**追加: メディアピッカーと共有アップロード（Task/Workflow から画像を選ぶ）**

Task / Workflow から編集入力に使う画像の与え方について:

- **R1 MVP では専用のアップロード UI を作らない。** 次の順で既存資産を使って入力できる:
  1. **ギャラリー / メディアピッカーで選ぶ**（`media_id`）。生成済み・会話でアップロード済みの
     画像はこれで再利用できる。ピッカーは共有コンポーネントとして作る。
  2. **`source_path`**（Vault / 出力ディレクトリ内の既存ファイル）。
- それでも「手元の新規ファイルを Task/Workflow に使いたい」頻度が高いなら、**汎用のメディア
  アップロード**を後から足す（Task/Workflow 専用にはしない）:
  - `POST /api/v1/media/uploads`（multipart）→ `media/ingest.py` で取り込み → `media_id` を返す。
  - 同じメディアピッカーに「アップロード」を付ける。ギャラリーにも載る。
  - Workflow の入力フォームは `InputsSchemaForm` に `format: media`（UI ウィジェットヒント）を足し、
    Task 作成フォームも同ピッカーを使う。既存の `x-ui` ウィジェット機構（`capability_schemas._FIELD_WIDGETS`）
    と同じ考え方で拡張する。
- 順序: **R2 のギャラリー/ピッカーを先に**作り、必要になったらアップロードを追加する。

**影響範囲**: `media/store.py`（list クエリ）, `media/ingest.py`（アップロード時）,
`web/routes/media.py`, `web/api.py`, frontend `features/media/`（一覧 + ピッカー）,
`features/task-agent`（作成フォーム）, `features/workflows/InputsSchemaForm`, `Web UI マップ`。

**リスク/不可逆性**: 読取のみ（P0 範囲）。**ゲート: 不要**（一覧・詳細まで）。
アップロード追加時は外部ファイル取込みのため入力検証契約（R1 の ingest を共用）に従う。

---

## R3. メディアの削除・親連動削除・孤児回収 — P0（削除は不可逆）

**目的**: 不要なメディアとファイルを削除し、孤児ファイルを回収する。

**現状/制約**
- 削除経路がない。`store.save_generated_image` は「ファイル→DB 行」順のため、
  DB 失敗時はファイルを消すが、クラッシュ時は孤児ファイルが残り得る（行は欠落ファイルを指さない）。
- 削除は不可逆（アプリ外ファイル + DB 行）。

**決定: 保持期間の設定は当面追加しない（親と同時に削除する）**

- 時間ベースの `retention_days` は設けない。メディアは所有する親（会話 / Task / Workflow 実行）の
  既存削除と同じタイミングで削除する。
- 既存の削除経路にフックする:
  - 会話: `agents/store.delete_session`（セッション削除時に `session_id` 一致のメディアを削除）。
  - Task: `tasks/store.purge_terminal_tasks`（終端 Task の既存 30 日パージに `task_id` 一致を連動）。
  - Workflow: `workflow/store.delete_run`（実行削除時にその実行のメディアを削除）。
- ファイル削除が必要なため DB の FK CASCADE だけでは足りない。共通ヘルパ
  `media/store.py: delete_media_for_parent(kind, id)`（行検索 → containment 済みパスを unlink → 行削除、
  冪等・ファイル欠落や権限エラーでも行削除は継続しログ記録）を各削除経路から呼ぶ。
- 紐付いていないメディア（親が先に消えた、CLI 単体、R4 前の Workflow 実行など）は残り得る。
  まずはギャラリーからの手動削除（下記）で対応し、自動回収は必要になったら追加する。

**設計案（手動削除・孤児回収）**
- `DELETE /api/v1/media/{id}`: DB 行を削除し、containment 済みパスのファイルを削除。
  行が無い / ファイルが無い場合も冪等に成功相当とする。UI は確認ダイアログ + 物理削除。
- 孤児回収（任意・後回し可）: 出力ディレクトリを走査し、`generated_media.relative_path` に存在しない
  ファイル（`.part` 一時ファイルや管理外は除外）で一定期間経過したものを削除。逆に、行があるが
  ファイルが無い場合は行を残しつつ監査ログに記録（勝手に消さない）。
- 削除の実行主体と記録: `__opcheck_` と同様に識別子をログへ。人間が復旧できる材料を残す。

**影響範囲**: `media/store.py`（`delete_media_for_parent` / 手動削除）, `agents/store.py`,
`tasks/store.py`, `workflow/store.py`（削除フック）, `web/routes/media.py`, frontend（削除 UI）。

**リスク/不可逆性**: 削除は不可逆。**ゲート: 要**（削除の操作シナリオ契約、部分削除/ファイル欠落時の挙動）。
Workflow 実行単位の削除は R4（`workflow_run_id` の記録）完了まで正確に行えない点に注意。

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
| P0 | R3 削除・親連動削除・孤児回収 | 削除（不可逆） | 要 |
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

## 決定済み

- **入力画像の与え方**: `media_id` を正本にし、入口（添付 / `source_path`）で自動取り込み（R1）。
- **保持期間**: 設定を追加せず、親（会話 / Task / Workflow 実行）の既存削除と同時に削除する（R3）。
- **Task/Workflow 用の新規アップロード UI**: R1 MVP では作らない。R2 のメディアピッカーで
  既存メディアを選び、必要なら汎用アップロードを後から追加する。

## 未決事項（実装前に決める）

- `image_generation.input_dir` を新設するか、Vault と出力ディレクトリの許可ルートだけで足りるか。
- メディアピッカー/共有アップロードを R2 と同時に入れるか、R1 完了後に分けるか。
- 画像ファイルを Vault に置く既定にするか（Vault 肥大化とのトレードオフ）。
- 画像 API 呼び出しの実行ログを既存テーブルに載せるか、専用テーブルにするか。
- コスト上限の単位（枚数 / 概算金額）と、上限超過時の停止範囲（全体 / エージェント単位）。
- 認可: 現状は単一ユーザー前提。複数主体を許す場合のメディア所有権。
