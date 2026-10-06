# Multi-Vault v1 ToDo

## 設計・記録

- [x] `ai_wiki/10-Decisions-Architecture.md` に multi-vault の ADR を追加する。
- [ ] AI 書込みの操作シナリオ契約と、main の対象固定内部フロー一覧を実装時に照合する。

## Registry と設定

- [x] `VaultDescriptor`、Vault ID、AI access、primary Vault の中央モデルを作る。
- [x] `config.yml` の `vaults` と `primary_vault` を読み込む。
- [x] `VAULT_PATH`、旧 `vault:`、単数索引設定を削除する。
- [x] 起動時に root 存在・非重複・非入れ子・primary 一意性を検証する。
- [x] 起動状態と失敗理由を保存し、`make status-web` に表示する。
- [x] test と opcheck の3 Vault 一時設定を作る。

## Vault 操作と索引

- [x] Vault ID 対応の安全なファイル read/list/write service を作る。
- [x] 人間、通常 Agent、Task／Workflow、内部 primary フローの信頼済み操作文脈を分ける。
- [x] 全単数 `VAULT_PATH` 参照を Registry または primary Vault 解決へ置き換える。
- [x] Vault 単位の索引保存先、検索 executor、索引 identity を作る。
- [x] `--sync-vault`／`--rebuild-vault` に反復可能な `--vault` 指定を加える。
- [x] path 変更時の検索無効化と明示 rebuild を実装する。

## API・Agent・実行器

- [x] Vault 一覧、Vault ID 付き検索、読取り、列挙 API を追加し、旧契約を削除する。
- [x] Agent の `default_vault_ids` migration、API、CLI を追加する（編集 UI は Phase 4 で対応）。
- [x] `vault_search` の既定＋単発 `additional_vault_ids` を実装する。
- [x] `vault_read_file`／`vault_write_file`、Task schema、Workflow schema を Vault ID 必須にする。
- [x] context ref を `{vault_id, path}` に移行する。
- [x] AI access と main 汎用書込み拒否を副作用直前で検証する。
- [x] blog / ai の通常 Agent 書込みを無承認、Task／Workflow 書込みを plan-required のまま保つ。

## UI・文書・確認

- [ ] Vault 検索の全 Vault 既定フィルターと Vault 表示を実装する。
- [ ] ファイルエクスプローラーに main 初期値の Vault セレクターを追加する。
- [ ] Agent の既定 Vault 選択と、Vault をまたぐ `@` 参照ピッカーを実装する。
- [ ] 設定、Vault 検索、Agent、CLI、運用、トラブルシューティングの user guide を更新する。
- [ ] Registry、migration、索引、認可、Agent、Task／Workflow、不可逆書込みのテストを追加・監査する。
- [ ] 隔離 opcheck と、後片付け済みの実運用確認を行う。
