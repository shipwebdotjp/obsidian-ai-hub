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
- 初期カタログから `run_shell`、Skills、custom plugin、外部書込み提案を除外する。
- Agentは実行時の最新設定を使う。TaskはAgent設定をスナップショットしない。

## Consequences

- 追加Capabilityにはコードとテストが必要だが、危険な能力が設定だけで公開されない。
- Agent編集が承認後の実行挙動を変え得る。これは個人利用の既知リスクである。

## Alternatives

- 完全なCapability CRUD: 柔軟だがAdapterとの整合検証・管理画面が重く不採用。
- コードだけでpolicyも固定: 実装は軽いが、個人運用での調整性を失うため不採用。
- 既存Registryを全公開: shellやpluginまでTaskから実行可能になるため不採用。
