# Gmail 連携機能

Gmail デスクトップ OAuth 連携機能により、AI エージェントおよび Task Agent から Gmail メッセージの検索・読取およびメール下書きの作成が安全に行えます。

---

## 概要と利用前提

本機能は**個人利用・単一 Google アカウント**の統合を前提としています。

- **読み取り・下書き作成のみ:** メールの検索 (`gmail_search_messages`)、詳細読取 (`gmail_read_message`)、下書き作成 (`gmail_create_draft`) のみに対応しています。
- **送信機能なし:** 本アプリケーションにはメール送信機能（`send`）は一切実装されていません。下書きを作成した後は、人間のユーザーが Gmail 上で内容を確認し、手動で送信を行います。
- **制限事項:** メール送信、下書き更新・削除、添付ファイルダウンロード/本文展開、転送、HTMLメール作成、エイリアス切替、マルチアカウントには対応していません。

---

## セットアップと初回認証

### 1. Google Cloud Console での設定

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセスし、プロジェクトを作成（または選択）します。
2. **Gmail API** を有効化します。
3. **OAuth 同意画面**（OAuth consent screen）を設定します。
   - ユーザータイプ: 個人利用（外部テストユーザーに自身の Gmail アドレスを追加）
   - 必要なスコープ: `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/gmail.compose`
4. **認証情報（Credentials）** の作成:
   - 「認証情報を作成」 → 「OAuth クライアント ID」 を選択
   - アプリケーションの種類: **デスクトップ アプリ** (Desktop App)
   - クライアント JSON をダウンロードします。

### 2. クライアント JSON の配置

ダウンロードした JSON ファイルを以下のデフォルトパスへ配置します。

```bash
mkdir -p ~/.config/obsidian-ai-hub/gmail
cp path/to/downloaded_client_secret.json ~/.config/obsidian-ai-hub/gmail/client_secret.json
```

※ 環境変数 `GMAIL_CLIENT_SECRET_PATH` でカスタムパスを指定することも可能です。

### 3. 初回認可の実行 CLI

以下の独占コマンドを実行して、ローカルブラウザで Google アカウントの認可を行います。

```bash
uv run python -m obsidian_ai_hub --gmail-authorize
```

- ブラウザが起動し、Google アカウントのログイン・スコープ承認画面が表示されます。
- 承認が完了すると、所有者限定権限 (0600) で認証トークンが `~/.config/obsidian-ai-hub/gmail/token.json` に保存されます。
- ターミナルには認証されたメールアドレス、トークン保存パス、承認スコープのみが表示され、トークン本文やシークレットは出力されません。

---

## 提供ツール（Capabilities）

AI エージェントおよび Task Agent で以下の3つのツールが利用可能です。

| ツール ID | 承認ポリシー | 説明 | 主な入力 |
| :--- | :--- | :--- | :--- |
| `gmail_search_messages` | 自動 (auto) | Gmail メッセージの検索・一覧取得 | `query`, `label_ids`, `max_results` (1〜20) |
| `gmail_read_message` | 自動 (auto) | メッセージ詳細・本文テキスト・添付メタデータ読取 | `message_id` |
| `gmail_create_draft` | 計画確認必須 (plan_required) | 新規または返信のメール下書き作成 | `mode` (`new`/`reply`), `body_text`, `to`, `subject`, `reply_to_message_id`, `reply_all` |

### 本文および添付ファイルの取り扱い

- **本文テキスト抽出:** MIME 構造を解析し、`text/plain` を優先取得します。`text/plain` がない場合は標準ライブラリによる HTML-to-text 変換を行い、最大 20,000 文字にクランプします（超過時は `truncated: true`）。
- **添付ファイル:** 添付ファイルの本文やバイナリデータは LLM に展開されません。ファイル名、MIME タイプ、バイトサイズ等のメタデータのみが返されます。

---

## 重複防止と at-most-once 契約（receipt Capability）

メール下書き作成（`gmail_create_draft`）は Workflow および Task Agent の **receipt Capability** として管理され、外部副作用を伴うため `gmail_draft_requests` データベーステーブルにより **at-most-once (最大1回)** 動作が保証されます。

### 1. 入出力契約
- **入力契約:**
  - `body_text` および `subject` は `narrative`（自由テキスト・テンプレート出力）の流入を許可します。
  - `mode`, `to`, `cc`, `bcc`, `reply_to_message_id`, `reply_all` は `structured` 限定であり、`narrative` 値の流入は Workflow 公開時の静的検証で拒否されます。
- **出力 receipt:**
  - 出力フィールド: `status`, `request_key`, `gmail_draft_id`, `gmail_message_id`, `gmail_thread_id`, `reused_receipt`, `receipt_persisted`
  - 後続 Node・条件 Edge・pipe・テンプレートからは一切参照できません（`allowed_uses: []`）。

### 2. 決定的なリクエストキー
- **Workflow:** `gmail_draft:wf:{run_id}:{activation_id}` （retry attempt や bridge Task ID は含めない）
- **Task Agent:** `gmail_draft:task:{task_id}:{plan_id}:{step_index}` （承認済み plan の plan_id を使用）

### 3. at-most-once と needs_attention 停止規則
1. **事前保存 (`creating`):** Gmail API 呼び出し直前にステータス `creating` が永続化されます。
2. **成功時 (`created`):** Gmail から受領情報（下書き ID、メッセージ ID、スレッド ID）が返された後、ステータスを `created` に更新します。同一リクエストキーで再実行された場合は、Gmail API を再呼び出しせず保存済みの受領情報を再利用します。
3. **入力ハッシュ不一致時:** 同一 Action で入力ハッシュが変更された場合、Gmail API を呼び出さずに `needs_attention`（要対応）で停止します。
4. **不確実な失敗時 (`unknown`):** 通信障害や途中クラッシュが発生した場合、ステータスは `unknown` となり、`needs_attention` で停止して自動再試行をブロックします。
5. **DB 永続化失敗時:** Gmail API 呼び出し成功後にローカル receipt の永続化だけが失敗した場合は、取得済み ID を記録し `receipt_persisted: false` で `needs_attention` 停止します。

---

## 再認可とトラブルシューティング

- **トークン期限切れ / 権限取り消し:** 実行時ツールは自動でブラウザを開きません。トークンが無効またはスコープ不足の場合は、「`--gmail-authorize` を実行してください」というエラーが返されます。再度 CLI で `--gmail-authorize` を実行してください。
- **再認可コマンド:**
  ```bash
  uv run python -m obsidian_ai_hub --gmail-authorize
  ```
