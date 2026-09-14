# Task Agent 実装プラン

Status: Draft (implementation plan, not started)

## 1. 実装方針

Task Agentは新規 `tasks/` サブパッケージに置くが、Agent/CodingのLLM実行ループ、子runの
キュー、HITL質問、FastAPI worker lifespanを再実装しない。TaskはPlanと親子参照を所有し、
既存runを実行器として扱う。

初期MVPで作らないものは、共通Workspace lock、専用launchd worker、Capability完全CRUD、
Artifact/Delegation/HITL linkテーブル、Vault/外部書込みAdapter、Task固有の上限・リトライである。

## 2. 実装順序

### Phase 1: 文書・永続化・状態機械

- `CONTEXT.md` とTask Agent仕様・ADRをこの決定済みモデルへ同期する。
- `database.py` にv44 migrationを追加し、`task_agent_tasks`、`task_agent_plans`、
  `task_agent_events`、`task_agent_capabilities` と必要なTask/Plan/Event索引を作る。
- コード定義のCapability catalogを作り、migrationで初期DB設定をidempotentにseedする。
- `tasks/store.py` にTask作成、Plan版管理、追記Event、原子的claim、状態遷移、30日purgeを実装する。
- `tasks/redaction.py` を既存の設定済み秘密値に接続し、永続化前にTask入力・要約をredactする。

### Phase 2: PlannerとTask worker

- `tasks/planning.py` に、構造化PlanまたはHITL質問を返すPlannerを実装する。モデル設定は既存の
  Agent provider/modelを既定として使い、新しいモデル設定UIは作らない。
- Plannerに有効Capability、登録済みAgent、妥当なProject/Git rootだけを渡し、未解決時は
  既存HITL questionを登録する。
- `tasks/worker.py` に単一Task workerを実装し、`queued → planning` と
  `ready → running` のclaim、auto実行、Plan待機、子run監視を担わせる。
- `runs/manager.py` にTask workerの起動、停止、Task recovery、30日purgeを追加する。
  launchdや `--hitl-worker` の役割は変更しない。

### Phase 3: Capability Adapter

- `tasks/adapters/registry_tools.py` はコードの固定allowlistだけを既存Registryから解決して、
  保存済み入力で呼び出す。
- `tasks/adapters/agent.py` は指定Agentの新規session/runを既存serviceでキューし、終端結果を
  Task Eventへ要約する。Agent設定は実行時に読み直す。
- `tasks/adapters/coding.py` はPlanのProject/Git root/backendで新規Coding session/runを作る。
  既存Coding workerのrepo lockと取消機構を使う。
- Agent/CodingへのStep指示にPlan外作業を止める構造化再承認要求を含め、受信時は改訂Planを作って
  `waiting_reapproval` にする。自己申告されない逸脱を親で検出しようとはしない。

### Phase 4: API、CLI、WebUI

- `web/routes/task_agent.py` と対応serviceに仕様のTask/Capability APIを実装し、既存API routerへ
  登録する。
- `main.py` に `--task-agent TEXT` を追加し、他の実行フラグと併用不可にする。root直下は薄い
  CLIラッパーに留める。
- `/task-agent` 一覧、`/task-agent/:id` 詳細、Capability設定画面をReactに追加する。
  既存HITLの質問回答UI/APIを再利用し、Plan承認・差戻しはTask詳細から直接行う。
- Task workerが使うHITL resume handlerをcomposition rootへ登録する。

### Phase 5: 保守・検証

- terminal Taskを30日でcascade削除するpurgeをstartup maintenanceに接続する。
- README/運用説明に、Webサーバー停止中はTaskが進まないこと、子runの既存制限、依頼本文へ
  未知の秘密を含めないことを記載する。

## 3. 重要な実装規則

- Plan作成時にCapability key、入力、対象、承認ポリシーを保存する。実行時に入力や対象を
  LLMで作り直さない。
- Capabilityのpolicy変更後も既存Planの承認要否は変えないが、disabledは実行開始を阻止する。
- Taskが直接書込みを扱わない間は共通lockを導入しない。Task workerは直列で、Git書込みの
  排他はCoding基盤の既存repo lockに委ねる。
- Plan承認を既存HITL questionに無理に変換しない。条件付きの差戻し理由をTask APIで検証する。
- DBを書くテストは `uv run pytest tests/` 経由で実行し、本番DBを使わない。

## 4. 検証計画

- v43からv44へのmigration、seedの冪等性、FK/cascade、30日purge。
- 状態機械の全許可・代表禁止遷移、Plan版の増分、理由なし差戻しの拒否。
- auto-only Plan、承認必須Plan、disabled Capability、HITL質問からの再キュー。
- Agent/Coding子run生成、Task Event参照、取消伝播、サーバー停止時の `interrupted`、
  自動再実行なし。
- allowlist外のCapability、shell、Skills、plugin、外部書込み提案の拒否とredaction。
- CLI即時返却、Task API結合、Task詳細・Capability設定のフロントエンド単体テスト。
  ブラウザE2Eは追加・実行しない。
