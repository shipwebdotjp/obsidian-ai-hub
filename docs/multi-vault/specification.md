# Multi-Vault v1 仕様

## 目的

個人運用の main Vault を既定として維持しながら、Hugo ブログ用 Vault と AI の協働・作業用 Vault を、検索・読取り・書込みの対象として扱う。

AI が自由に作る作業ノートと、ユーザーについて確定した長期知識は分ける。後者の正本は既存の承認・失効・検索を持つ長期メモリであり、AI Vault の内容を自動注入しない。

## Vault Registry

`config/config.yml` に絶対パスを直接記載する。`.env` に Vault パスは置かない。

```yaml
vaults:
  main:
    path: /Users/you/Documents/Obsidian
    display_name: Personal
    role: primary
    ai_access: read
  blog:
    path: /Users/you/Documents/Blog
    display_name: Blog
    ai_access: write
  ai:
    path: /Users/you/Documents/AI-Workspace
    display_name: AI Workspace
    ai_access: write

primary_vault:
  inbox: inbox
  daily: daily
  template: template
  knowledge: copilot/knowledge
  research: research
  webclip: webclip
  people: people
```

- `main` は必須であり、唯一の `role: primary` である。
- Vault ID は安定した小文字 ID とし、表示名やパスを識別子に使わない。
- 各ルートは既存のディレクトリで、重複・入れ子を許可しない。
- `ai_access` は `none` / `read` / `write` のいずれかである。
- 旧 `VAULT_PATH`、旧 `vault:`、単数 Vault の索引設定と、Vault ID を持たない公開 API・CLI・ツール契約は廃止する。互換レイヤーは設けない。
- `primary_vault` は Inbox、daily、people、research など main 専用の既存業務規約だけに適用する。blog と ai に同じフォルダ構造を要求しない。

Web 起動時に Registry を検証する。不正な設定は Web 起動を失敗させ、起動状態に短いエラー要約を保存する。再起動前の preflight は v1 には含めない。`make status-web` は LaunchAgent の状態に加えて `starting` / `ready` / `failed` と最後のエラーを表示する。

## 読取り・書込みの境界

人間が Web UI、CLI、Obsidian、Finder を通じて操作する場合は Vault の AI access に制限されない。AI が LLM ツールを通じて操作する場合だけ、サーバー側で次を強制する。

| `ai_access` | AI 検索・読取り | AI 書込み |
| --- | --- | --- |
| `none` | 不可 | 不可 |
| `read` | 可 | 不可 |
| `write` | 可 | 可 |

- `main` への汎用 Agent の書込みは常に拒否する。
- Inbox、日次処理、人物、リサーチ公開など、コードで対象を primary Vault に固定した既存フローは維持する。
- `blog` と `ai` は、`vault_write_file` を持つ通常の Agent が無承認で書き込める。上書きには従来どおり `overwrite=true` を明示する。
- Task Agent と Workflow の `vault_write_file` は既存の `plan_required` を維持する。Plan 承認後でも main への汎用書込みは拒否する。
- LLM の自由文やクライアントから渡された actor 表示で権限を判定しない。人間向け経路、通常 Agent、Task／Workflow、対象固定の内部フローをサーバー内部の信頼済み実行文脈として区別する。

## 検索、ファイル参照、Agent

すべてのファイル参照は `{vault_id, relative_path}` を使う。

- 人間向け Vault 検索は全 Vault を既定に横断検索し、Vault ID で絞り込める。検索結果には Vault ID、表示名、相対パスを返す。
- ファイルエクスプローラーは Vault を一件選んで閲覧し、初期選択は main とする。
- Agent は SQLite に `default_vault_ids` を持つ。対象を省略した `vault_search` はこの範囲を検索する。
- ユーザーが自然言語で別 Vault を求めた場合、LLM はそのツール呼出しだけ `additional_vault_ids` を渡せる。これは既定範囲へ加算され、Run や Session には保存しない。
- `vault_read_file` と `vault_write_file` は `vault_id` を必須にする。明示 ID の呼出しは、その一回の操作だけに適用される。
- `@` 文脈参照は `{kind: "vault_file", vault_id, path}` として保存する。他 Vault の一ファイル添付は、その Vault 全体を Agent の検索対象に加えない。
- Agent の既定 Vault は検索上の既定値であり、厳密な認可上限ではない。認可上限は Vault の `ai_access` である。

既存 DB の Agent は `default_vault_ids: ["main"]` に、既存の単数 Vault 文脈参照は `vault_id: "main"` に migration する。会話履歴や長期メモリは保持する。

## 索引と同期

Vault ごとに Markdown の意味・キーワード・ハイブリッド検索索引を独立して保持する。共通の埋め込みモデル設定と索引基準ディレクトリを使い、保存先は `<storage_dir>/<vault_id>/` から導出する。

- `--sync-vault` は対象未指定なら全 Vault を ID 順に同期する。`--vault <id>` は個別同期に使う。
- `--rebuild-vault` も同じ対象指定を持つ。
- 全 Vault 処理は、一 Vault の失敗後も残りを試み、失敗 ID を報告して最後に非ゼロ終了する。
- AI 書込み直後は `{vault_id, relative_path}` を返し、同じ会話では直接読取りできる。意味検索への反映は毎時同期または手動同期まで待つ。
- Vault ID の `path` を変更した場合、その ID の既存索引は無効化する。`--rebuild-vault --vault <id>` が成功するまで検索に使わない。
- Registry から削除された Vault や無効化された旧索引を自動削除しない。清掃は将来の明示操作とする。

## v1 の非対象

- Hugo の frontmatter 検証、slug・下書き管理、画像管理、ビルド、公開。
- Vault の UI 管理、動的な追加・削除、AI access の UI 編集。
- Agent ごと／フォルダごとの ACL。
- 書込みごとの HITL 承認、AI 書込み直後の索引同期、AI Vault 内容の長期メモリへの自動昇格。

## AI 書込みの操作シナリオ契約

| 段階 | 入力と正本 | 識別子 | 永続化・次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- |
| ツール入力 | `vault_id`、Vault 相対パス、本文、`overwrite` | Registry Vault ID | Tool schema で正規化。Agent runtime | 未知 ID・read/none・main 汎用書込み・不正パスは書込前に失敗 | なし |
| 対象解決 | Registry とパス安全検証 | `{vault_id, relative_path}` | なし。書込み service | ルート外、symlink escape、既存ファイル競合は停止 | なし |
| 原子的書込み | UTF-8 本文 | 同上 | Vault ファイル。Agent Run tool trace | I/O 失敗は部分書込みを残さず失敗 | 新規作成または置換 |
| 結果 | `vault_id`、相対パス、bytes、overwrite 結果 | 同上 | Run のツール履歴。次の Agent 呼出し | 索引未同期は書込み失敗にしない | なし |
| 同期 | Registry Vault の索引 | Vault ID | 独立索引。同期 CLI／検索 service | 失敗時はその Vault を検索不可。ファイル正本は維持 | 派生索引の更新 |
