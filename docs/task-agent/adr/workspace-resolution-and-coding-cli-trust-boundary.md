# Coding対象解決と既存実行境界

## Status

Accepted

## Context

MVPで副作用を持つTask Capabilityは `memory_propose`、既存Agent、Coding CLIである。Vault直接編集と
外部書込みは扱わないため、全Workspaceを横断する新しいロック機構はまだ不要である。

## Decision

- Coding CLIは、既存Projectの有効な `project_path` だけを対象にし、`validate_git_repo` でGit rootへ
  正規化してPlanへ保存する。
- 対象が一意でなければ既存HITLで質問し、勝手にProjectを選ばない。
- Git書込みの同時実行排他は既存Coding基盤のrepo lockに委ねる。Task共通lockは導入しない。
- Coding CLIと既存Agentの内部権限・Plan逸脱は親Taskでは技術的に保証しない。Planに指示とEventを
  残すことで緩和する。

## Consequences

- Task workerを直列化しても、手動Coding runとの競合は既存repo lockで扱われる。
- 将来Vault/外部書込みを追加する時点で、対象別の共通lockと直接書込みAdapterを設計する必要がある。

## Alternatives

- MVPから共通読取共有/書込み排他lockを作る: 現在の直接書込み範囲には過剰で不採用。
- Project候補や無効pathも対象にする: 誤作用リスクが高く不採用。
- 親側でCLIを完全sandboxする: CLI固有権限と重複し、実装負荷が大きいため不採用。
