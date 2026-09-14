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
  既定policyは読取・検索系のみ `auto`、それ以外(`run_shell`、Skills、
  `custom:*` プラグイン、新規builtinを含む)は `plan_required` とする。
- 次のtoolだけはコード固定の除外セットとしてTask Capabilityにしない:
  `ask_user`(会話内専用)、`agent_delegate`(`specialist_agent` と重複し親Agent
  run文脈が前提)、`calendar_create_proposal` / `reminder_create_proposal`
  (既存提案HITLとの二重承認になるため。spec §1の決定を継承)。
- DB側の `enabled` / `approval_policy` は起動時同期でも上書き保護する
  (migration v44 seedと同一規則)。

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
