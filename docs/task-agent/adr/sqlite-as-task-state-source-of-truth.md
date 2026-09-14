# SQLiteをTask状態の正本とする

## Status

Accepted

## Context

TaskはCLI投入、承認待ち、子run待ち、停止復旧を跨ぐため、プロセス外の状態正本が必要である。
既存AI HubはSQLite migration、WAL、単一worker instance lockを用いてAgent/Coding/HITLを管理している。

## Decision

- Taskの正本は既存SQLiteの `task_agent_tasks`、`task_agent_plans`、`task_agent_events` とする。
- Capability policyは同じDBの `task_agent_capabilities` に置く。
- migrationは `database.py` のv44として追加し、既存 `task_state` と名前を混同しない。
- Eventは追記のみ、状態遷移とworker claimはDBで検証する。

## Consequences

- 既存DBのバックアップ・テスト分離・instance lockを利用できる。
- Taskは子runの詳細を複製せず、ID参照と要約Eventを持つ。

## Alternatives

- プロセス内メモリ: 停止復旧・承認待ちを保持できず不採用。
- 別DB/キュー: 個人ローカル用途には運用負荷が過大で不採用。
- Artifact/Delegation等の専用テーブル群: 子runとEventで追跡できるMVPには過剰なため不採用。
