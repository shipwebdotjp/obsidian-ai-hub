# CONTEXT.md — タスクオーケストレーション

この文書は obsidian-ai-hub のタスクオーケストレーションに関する用語と境界を定義する。
仕様は [docs/task-agent/specification.md](docs/task-agent/specification.md)、判断理由は
[docs/task-agent/adr/](docs/task-agent/adr/) を参照する。

## Bounded Context

- **Task Orchestration** — 自由文依頼をPlanへ変換し、承認ポリシーに従って既存能力へ委譲し、
  状態と結果を追跡する文脈。
- **HITL** — Taskの対象解決質問とカレンダー/リマインダー作成提案を保存・回答する汎用基盤。TaskのPlan承認自体は所有しない。
- **AI Agents / Coding Workspace** — Taskが子runを作る既存の実行文脈。Taskはそれぞれの内部会話・
  権限・出力を所有しない。
- **Coding Workspace** — Coordinator は進行・質問・最終要約だけを担い、Worker が技術的な
  実行主体（リポジトリ調査・実装・テスト・技術判断）となる二層構成。Coordinator は実装方針・
  対象ファイル・コマンドを通常時に決めない。Worker 呼び出しは Coordinator が応答本文に
  出力する `<cli_request>` タグのみで行い、ツール経由で外部CLIを起動しない。使用バックエンド
  名は Coordinator に開示しない。
- **Vault / Calendar / Reminders** — Taskが読取対象として参照し得る外部境界。Calendar / Remindersへの追加は既存提案HITL登録ツール経由のみ行い、人間の承認はHITL側で行う。Vaultへの直接書込みは `vault_write_file` Capability経由のみ行い、既定 `plan_required` のPlan一括承認を要する。

## ユビキタス言語

| 用語 | 定義 |
| --- | --- |
| **Task** | 自由文依頼一件の集約ルート。Plan、状態、Event、子run参照を所有する。 |
| **Task Agent** | Task Orchestration機能全体。CLI、Planner、Task worker、WebUIを含む。 |
| **Plan** | 目的、順序付きStep、Capability、対象、入力、副作用、完了条件を持つ実行記述。Task内で版管理される。Directional Planと旧形式の静的Planがある。 |
| **Directional Plan** | タスクの目的、実行方針、承認されたCapability範囲、制約、完了条件を表す。全ツール引数を事前確定しない。 |
| **Step** | 旧形式の静的Plan内の一つのCapability実行単位。保存済み入力と対象だけを使う。 |
| **Runtime Orchestrator** | Directional Planと過去のObservationを基に、次のActionを構造化出力する判断主体。 |
| **Action** | 次のCapability呼び出し、またはタスク完了を表す構造化された判断。 |
| **Observation** | Capability実行結果としてRuntime Orchestratorへ戻される情報。 |
| **Approval Scope** | 承認された目的、Capability、制約の境界。範囲外のActionは実行せず再承認へ回す。 |
| **Capability** | コードで定義されたAdapterと、DBで管理する有効状態・承認ポリシーの組。 |
| **Approval Policy** | `auto` または `plan_required`。Planの人間承認要否を決めるCapability設定。 |
| **Adapter** | Registry tool、AI Agent、Coding CLIの入出力をTaskのEventと結果へ正規化する層。 |
| **Child Run** | Agent AdapterまたはCoding Adapterが作る既存のAgent/Coding run。 |
| **Workspace** | Coding Stepの正規化済みGit root。将来の直接書込み対象も含み得るが、MVPでは共通lockを持たない。 |
| **HITL Question** | 対象を一意に解決できないときに既存HITLへ登録する質問。 |
| **Re-approval** | Plan外の能力・対象・副作用が必要だという自己申告後、改訂Planを承認すること。 |
| **Trace Event** | Taskの追記のみの監査記録。子run/HITLの参照と要約を持つ。 |
| **リサーチ提案コンテキスト** | 直近のノート、アクティビティ、過去テーマ・フィードバックをTask Observation上限内に圧縮した読み取り情報群。 |
| **リサーチテーマ候補登録** | `research_theme_propose` Capabilityにより最適なテーマをHITL提案候補として自動登録する操作。実行コンテキストに応じた冪等性を維持する。 |

## 不変条件

- Taskは常に一つの状態だけを持ち、終端状態から遷移しない。
- `plan_required` Capabilityを含むPlanは、人間の一括承認なしに実行しない。
- `auto` CapabilityだけのPlanは、保存後に人間の承認を待たず実行できる。
- Stepは保存済みPlanにあるCapability、対象、入力だけを使う。
- 差戻し理由は必須で、Task IDはPlan改訂を通じて不変である。
- Trace Eventは追記のみで、既知秘密値とLLM非公開思考過程を含まない。
- worker停止後のTaskは自動再実行しない。

## 外部境界

- **CLI入口** — Task投入専用であり、Task IDと詳細URLを返す。
- **WebUI** — Plan承認、差戻し、取消、結果閲覧、Capability policy設定を扱う。
- **HITL** — 対象解決質問とカレンダー/リマインダー作成提案の永続化と回答処理を扱う。
- **AI Agent** — 子runは実行時点の設定で動作する。Taskは設定を凍結しないが、
  `specialist_agent` を含むDirectional Planの承認時点指紋を記録し、実行開始時に
  差分・削除を検出したら再承認へ回す。
- **Coding ACP (OpenCode)** — 正規化済みProjectのGit root内で `opencode acp` 経由の単一トランスポートで動作する。実権限は既存ACP設定に委ねる。Direct CLI と Codex バックエンドは廃止済みで、旧セッションは読取専用である。使用モデルは `coding.acp.opencode_model`（未設定時は `opencode-go/muse-spark-1.3-contributor`）で、毎ターンの prompt 前に `session/set_model` で固定する。拒否時はターンを失敗させる。
