# Task Agent 文書群

Task Agent は、AI Hub と人間の間で依頼を理解・分解・中継する単一のタスクオーケストレーターである。
CLI から自由文プロンプトを投入すると、常駐ワーカーが非同期に計画を作り、WebUI の HITL
(Human-in-the-Loop) で計画承認・質問回答・差戻し・取消を行い、Obsidian Vault と登録済み
Git リポジトリへ委譲実行する。MVP の優先順位は、実タスクの完遂品質より状態遷移・HITL・監査・
停止と再開の完全性にある。

## 文書一覧

| 文書 | 役割 |
| --- | --- |
| [CONTEXT.md](../../CONTEXT.md) | 用語・ドメインモデル・不変条件（リポジトリルートのドメインモデル文書） |
| [specification.md](specification.md) | 確定済みの外部契約と振る舞い（MVP 仕様） |
| [implementation-plan.md](implementation-plan.md) | 実装順序、依存関係、検証戦略 |
| [TODO.md](TODO.md) | 未完了作業の追跡チェックリスト |
| [adr/sqlite-as-task-state-source-of-truth.md](adr/sqlite-as-task-state-source-of-truth.md) | SQLite をタスク状態の正本とする |
| [adr/cli-intake-webui-hitl-resident-worker.md](adr/cli-intake-webui-hitl-resident-worker.md) | CLI 投入専用 + WebUI HITL + 常駐ワーカー |
| [adr/approved-plan-as-execution-boundary.md](adr/approved-plan-as-execution-boundary.md) | 承認済み計画を実行境界にする |
| [adr/capability-manifest-and-delegate-adapters.md](adr/capability-manifest-and-delegate-adapters.md) | Capability Manifest + 委譲先固有 Adapter |
| [adr/workspace-resolution-and-coding-cli-trust-boundary.md](adr/workspace-resolution-and-coding-cli-trust-boundary.md) | Workspace 解決とコーディング CLI の信頼境界 |
| [adr/no-automatic-rollback-recovery-via-trace-and-hitl.md](adr/no-automatic-rollback-recovery-via-trace-and-hitl.md) | 自動ロールバックを行わず、構造化トレースと HITL で復旧する |

## 文書ごとの責務

- **CONTEXT.md** — ユビキタス言語、Bounded Context、集約・エンティティ・値オブジェクト、不変条件、
  外部境界を定義する。実装詳細・仕様・手順は含まない。
- **specification.md** — 確定済みの外部契約 (CLI 投入、WebUI、状態遷移) と振る舞いを定義する。
  実装方法や順序は含まない。未決事項は仕様書 §16 に列挙する。
- **implementation-plan.md** — 仕様を実リポジトリ構成へ落とす実装順序・依存関係・検証戦略を定める。
  仕様を上書きしない。未決事項は decision gate として扱い、勝手に確定しない。
- **TODO.md** — 未完了作業の追跡。実装事実が確定したら更新する。
- **ADR** — 独立して変更され得る重要な設計判断を Context / Decision / Consequences / Alternatives
  付きで記録する。

## 文書更新時の同期規則

1. **状態識別子・用語・リンクを文書間で一致させる。** 状態キーは specification.md §13 を正とし、
   CONTEXT.md・ADR・図・TODO はそれを参照する。識別子を変える場合は specification.md の変更が先。
2. **仕様変更と設計判断変更を混同しない。** 振る舞いの変更は specification.md を更新し、
   それに伴い判断そのものが変わる場合のみ該当 ADR を更新する (ADR の Status を見直す)。
3. **完了した TODO を実装事実として仕様へ無条件に移さない。** TODO が完了しても、
   それが外部契約の確定を意味するとは限らない。仕様への反映は specification.md の編集として
   明示的に行う。
4. ADR の必須見出し (`Status / Context / Decision / Consequences / Alternatives`) と
   Status 値は移動・編集で変えない。
