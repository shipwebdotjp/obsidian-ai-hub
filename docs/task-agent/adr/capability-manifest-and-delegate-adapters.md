# コード定義AdapterとDB管理Capabilityポリシー

## Status

Accepted

## Context

Taskは既存Registry tool、AI Agent、Coding CLIを使い分ける。任意の実行器をDBから作れるように
すると、入力検証、redaction、取消、監査の保証を失う。一方で個人利用では、能力ごとの有効化と
承認要否をUIから素早く変えたい。

## Decision

- Adapter key、入力検証、説明、allowlistはコードで固定する。
- `task_agent_capabilities` をDBの正本とし、`enabled` と `approval_policy` をWebUIで更新できる。
- `specialist_agent` と `coding_cli` は汎用Adapterであり、Planが対象Agent/Projectを固定する。
- Agentは実行時の最新設定を使う。TaskはAgent設定をスナップショットしない。

## Amendment (Capability自動同期)

Status: Accepted (当初の「初期カタログから除外」判断を改訂する)。

- Agent Registry (`agents.registry.TOOL_DEFINITIONS`) をCapabilityの正本とし、
  `tasks/capabilities.py` が起動時に自動派生する。Registryに新規builtin toolを
  追加すれば、Task Capabilityとしても自動公開される(入力スキーマは
  `tasks/capability_schemas.py` が `args_schema` から自動導出するため追加作業なし)。
- 自動派生の安全境界は「提示しない」から「提示するがPlan承認必須」へ移行する。
  既定policyは読取・検索系と提案HITL登録のみ `auto`、それ以外(`run_shell`、
  Skills、`custom:*` プラグイン、新規builtinを含む)は `plan_required` とする。
- 次のtoolだけはコード固定の除外セットとしてTask Capabilityにしない:
  `ask_user`(会話内専用)、`agent_delegate`(`specialist_agent` と重複し親Agent
  run文脈が前提)。

## Amendment (提案HITL登録のTask Capability化)

Status: Accepted (当初の「提案HITLは除外」判断を改訂する)。

- `calendar_create_proposal` / `reminder_create_proposal` をTask Capabilityに含める。
  直接書込みはせず、既存ツール経由で提案HITL登録のみ行うため、二重承認にはならない:
  `auto` 時のPlan確認は不要とし、人間の承認は既存提案HITL側で行う。
- 既存バリデーション・権限制御・ツール境界・安全制約は維持し、HITL登録処理の迂回はしない。
- `plan_required` 時の承認フローは従来どおり維持する。
- DB側の `enabled` / `approval_policy` は起動時同期でも上書き保護する
  (migration v44 seedと同一規則)。

## Amendment (リサーチ基盤への接続)

Status: Accepted (2026-09-14)。

- `research_agent` Capabilityを追加する。既存リサーチ基盤
  (`research.runner`: テーマ/job DB、バックグラウンドjob実行、Vault公開) を
  新Adapterから再利用し、リサーチのパイプライン自体は複製しない。
- Vaultへのレポート新規作成は不可逆な書込みのため、既定policyは `plan_required`。
- practitioner対象(委譲対象ID)は不要で、入力は `theme` 必須の
  `ResearchAgentInputs` (Pydantic単一正本) とする。
- research jobには協調的キャンセルがない。タスク取消時はjobの終端
  (succeeded/failed) を待ってから取消を伝播し、started後のjobは完走
  (Vault公開を含む) し得る。この仕様は specification.md の操作シナリオ契約に記録する。

## Amendment (Vault直接書込みのTask Capability化)

Status: Accepted (2026-09-14)。

- `vault_write_file` をTask Capabilityに含める。実装はAgent Registryの
  builtin tool (`agents.registry.vault_write_file` /
  `web.services.vault.write_vault_file`) を正本とし、Task側の手動登録は
  不要 (自動派生)。入力スキーマは `args_schema` (`VaultWriteFileInput`)
  から自動導出する。
- Vaultへの書込みは不可逆操作のため、既定policyは `plan_required` とする。
  `auto` への緩和は本ADRの改訂を要する。
- 上書きは `overwrite=true` の明示指定が必須 (既定 `false` では競合停止)。
  パスはVault相対のみを受け付け、絶対パス・`..`・解決先がVault外となる
  シンボリックリンク経由の書込みを拒否する。書込みは一時ファイル+置換に
  よる原子書込みとする。
- 操作シナリオ契約は `web/services/vault.py` の `write_vault_file`
  docstring を正本とし、縦断テストは `tests/test_vault_write_file.py`
  (Registry tool 実行 + Task Adapter 実行) とする。

## Amendment (画像生成のTask Capability化)

Status: Accepted (2026-09-26)。

- `image_generate` をTask Capabilityに含める (Agent Registry builtin toolから自動派生)。
  入力schemaは `args_schema` (`ImageGenerateInput`) から自動導出し、出力contractは
  `capability_schemas._OUTPUT_SCHEMAS` に宣言する。
- 外部画像API呼び出しとアプリ外ファイル書込みを伴うため、既定policyは `plan_required`。
  `auto` への緩和は本ADRの改訂を要する。
- 生成物は設定ディレクトリ配下へ原子的に書き込み、`generated_media` 行を正本として
  `media_id` で配信する。クライアントはパスを指定しない。
- 操作シナリオ契約は `media/store.py` のdocstringを正本とし、縦断テストは
  `tests/test_image_generate.py` (fake provider + 配信 + 失敗補償 + Task Adapter実行)。

## Consequences (当初)

- 追加Capabilityにはコードとテストが必要だが、危険な能力が設定だけで公開されない。
- Agent編集が承認後の実行挙動を変え得る。これは個人利用の既知リスクである。

## Consequences (自動同期の追加分)

- 新builtin toolの追加はRegistryの1箇所で済み、Task側の手動登録は不要になる。
- 危険側の能力も一覧に現れるが、`plan_required` 既定と `enabled` 切替で制御する。
  除外セットの取りこぼしはコードレビューで担保する。

## Alternatives

- 完全なCapability CRUD: 柔軟だがAdapterとの整合検証・管理画面が重く不採用。
- コードだけでpolicyも固定: 実装は軽いが、個人運用での調整性を失うため不採用。
- 既存Registryを全公開: shellやpluginまでTaskから実行可能になるため当初は不採用。
  自動同期への移行に伴い、`plan_required` 既定+最小除外セットの条件付きで採用へ変更。
