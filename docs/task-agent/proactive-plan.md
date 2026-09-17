# Task Agent プロアクティブ化 計画メモ（Phase A-C）

Status: Draft（調査・提案。実装未着手）

この文書は、Task Agent を「要求駆動の実行者」から「自発的にユーザーを助け、
支援し、成長を後押しするエージェント」へ拡張するための調査結果・設計案・
優先順位を、将来の実装時の参考資料としてまとめたものである。意思決定の正本は
[specification.md](specification.md) と [adr/](adr/)、作業事実は [TODO.md](TODO.md) に置き、
本書はロードマップと設計候補の整理に限定する。

関連: [README.md](README.md)、[CONTEXT.md](../../CONTEXT.md)、
[docs/development-quality-playbook.md](../../docs/development-quality-playbook.md)

---

## 1. 目的と位置づけ

- 目的: ユーザーの活動・目標・状況を継続的に観測し、必要なときに自ら気づき、
  提案・問いかけ・フォローアップを行い、ユーザーの成長を支援する。
- 位置づけ: 既存の要求駆動 Task（人間が依頼 → Plan → 実行）を土台として維持し、
  その上に「自発ループ」を別レイヤーとして載せる。既存の承認境界・Event 監査・
  冪等性の仕組みを再利用し、新しい常駐プロセスや自動実行を安易に増やさない。

---

## 2. 現状の評価

### 2.1 すでに強い点

- 要求駆動の実行基盤: 承認済み Directional Plan → Runtime Orchestrator の動的ループ、
  `capability_completed` Event による監査、二層 Observation（詳細/履歴要点）、
  自己修正上限、scope 逸脱時の再承認（[orchestrator.py](../../src/obsidian_ai_hub/tasks/orchestrator.py),
  [directional.py](../../src/obsidian_ai_hub/tasks/directional.py)）。
- HITL: 対象質問・カレンダー/リマインダー提案・リサーチ提案・人物候補・メモリ候補など、
  既存の承認基盤が揃っている（[hitl/](../../src/obsidian_ai_hub/hitl/)）。
- 提案の冪等性: `research_suggestion_requests` と Task ID 単位のキーで重複登録を防止
  （[research/capabilities.py](../../src/obsidian_ai_hub/research/capabilities.py)）。
- Capability の自動派生: Agent Registry のツールを Task Capability として自動公開
  （[tasks/capabilities.py](../../src/obsidian_ai_hub/tasks/capabilities.py)）。
- 既存の定期実行: `task_runner.py` + `tasks/tasks.local.yml` + Web の `/task-config` で
  cron 的スケジュールを管理（[task_runner.py](../../src/obsidian_ai_hub/task_runner.py)）。

### 2.2 自発性・成長支援のギャップ

| 領域 | 現状 | ギャップ |
| --- | --- | --- |
| トリガ | 定期実行は YAML のシェルコマンド。AI 起点は `--suggest-research-theme`（毎日23:45）1本のみ | エージェント自身が起動条件・周期・フォローを持つ仕組みが無い。`task_agent_*` にトリガ条件列も無い |
| ユーザーモデル | memory（承認済み400tok注入）、people、`projects.goal`、summaries（mood/sleep）、activity、healthcare（別DB・未接続）が断片化 | 横断スナップショットがツールとして存在しない（planner context pack は日次提案専用の内部関数） |
| 目標・習慣 | 「今日の目標」は Daily Note への一方向テキスト。`projects.goal` 以外の構造化モデル無し | goal/OKR/habit/streak/check-in のテーブル・API・ツールが無い |
| 結果追跡 | `planner_proposals` の状態、research feedback が部分的 | 助言の採否・効き目・フォローアップを記録する汎用ストアが無い |
| 割り込み制御 | LINE push は best-effort（[line_notification/](../../src/obsidian_ai_hub/line_notification/)） | 静音時間・日次予算・頻度上限・重複抑止・ミュートが無い |
| モデルハーネス | planner/runtime は JSON テキスト生成＋自前パース。role 別モデル/温度/予算は未設定 | role 別モデル、構造化 tool calling、日次トークン/コスト予算、フォールバックが無い |

### 2.3 調査で確認した制約（既存文書の事実）

- Task worker は FastAPI の lifespan 同居・単一。[post-mvp.md](post-mvp.md) の優先1は
  カレンダー/リマインダー直接書込み、優先2は外部入口と Task 通知、優先3は専用常駐 worker。
- Web サーバー停止中は Task が進まない。停止時に実行中だった Task は `interrupted` になり
  自動再実行しない。
- 自動ロールバック・自動再実行はしない（[adr/no-automatic-rollback-recovery-via-trace-and-hitl.md](adr/no-automatic-rollback-recovery-via-trace-and-hitl.md)）。
- 書き込み系 Capability は既定 `plan_required`。外部書込みは HITL 経由のみ。

---

## 3. 目標像: 自発ループ（Sense → Appraise → Act → Follow-up）

```
Sense            Appraise              Act                    Follow-up
  |                |                     |                        |
cron/event/idle  重要度・新規性・      通知・check_in・        outcome 記録・
 -> 統合context   実行可能性・負担で   Task生成・目標更新     フォロー予約・
 snapshot         スコアリング         提案・限定auto         memory 書き戻し
                  policy が保留/送信を判断                       -> 次回の Sense へ
  +---------------- Proactivity Policy（同意・静音・予算・重複抑止）----------------+
```

- **要求駆動 Task（既存）** は「手足」。自発ループは「脳・習慣」として分離する。
- 送信・実行の可否は LLM ではなく **policy 層**が決める（LLM は候補とスコアを出すだけ）。
- 閉ループにする: 介入の結果（採用/却下/効き目）を記録し、次回の判断と memory に戻す。

---

## 4. 設計原則・安全境界

1. 既定は **suggest-only**（通知・提案・質問のみ）。自動実行は可逆なものに限り段階的に。
2. 外部書込みは既存 HITL/Plan 承認を必ず経由する。Task Agent から直接書かない。
3. すべての介入に **evidence（根拠）と why-now** を付ける。根拠が弱ければ沈黙する。
4. 割り込み予算（日次上限・静音時間・重要度しきい値・cooldown・mute）を最優先で尊重する。
5. 健康データは **集計のみ・opt-in**。原レコードをプロンプトへ出さない。
6. 追加の常駐デーモンは増やさない（当面はサーバー同居）。将来は post-mvp 優先3で再検討。
7. 送信・副作用の直前で policy と schema を検証し、失敗時は送信せず理由を記録する。
8. 秘密値・非公開思考過程を保存しない（既存 redaction 方針を継承）。

---

## 5. ロードマップ概要

| Phase | テーマ | 主な内容 |
| --- | --- | --- |
| A | 自発性の土台 | A1 介入ストア+政策+コーチ受信箱 / A2 統合コンテキストツール / A3 自走スケジューラ / A4 通知と問いかけ / A5 目標・習慣モデル |
| B | 自発ループと成長フィードバック | B1 朝夜ループ / B2 機会検出器 / B3 結果ループ+memory書き戻し / B4 評価ハーネス |
| C | 成長支援と限定自律 | C1 学習・成長ループ / C2 ドメイン別限定auto / C3 個人モデル統合 / C4 モデルハーネス強化 |

### 決定済みの優先順位（2026-09 時点）

- 着手範囲: **A1 + A2 のみ**を最初に実装する。
- 自律レベル: **suggest-only から開始**。書き込み・Task 生成は人間の操作で起動する。
- 実行プロセス: **当面はサーバー同居**（`make serve` 中のみ動作）。専用 launchd worker は後回し。
- 健康データ: **集計のみ opt-in** で使う。原データはプロンプトに出さない。

---

## 6. Phase A 詳細

### A1. 介入ストア・政策・コーチ受信箱（確定設計）

**趣旨**: 自発的な提案を一箇所に集約する「コーチ受信箱」。suggest-only では Web に提示し、
ユーザーが accept したときだけ Task を作る。

**DB マイグレーション v48**（[database.py](../../src/obsidian_ai_hub/database.py) の
`run_migration_v47` の次に `run_migration_v48` を連鎖追加）

- `proactive_interventions`
  - `intervention_id` (`pi_*`)
  - `title`, `summary` (why-now), `evidence_json`
  - `trigger_kind`（例: `manual`, `planner_proposal`, 将来の `stalled_project`）
  - `dedupe_key`, `importance` (1-5), `novelty`, `urgency`
  - `status` (`proposed` / `accepted` / `rejected` / `snoozed` / `muted` / `expired`)
  - `source`, `channel`（当面 `inbox` 固定）, `created_task_id`
  - `snooze_until`, `cooldown_until`, `expires_at`, `response_reason`
  - `responded_at`, `created_at`, `updated_at`
- `proactive_intervention_events`（追記のみの監査。Task Event と同型の最小列）
- `proactive_policy`
  - `domain` (`global` / `schedule` / `learning` / `health` / `projects` / `inbox` / `research`)
  - `mode` (`off` / `suggest`。`approve` / `auto` は将来用に予約)
  - `min_importance`, `daily_cap`, `quiet_start`, `quiet_end`, `cooldown_hours`,
    `health_opt_in`, `updated_at`
  - 初期 seed: global のみ `mode=suggest, min_importance=3, daily_cap=3, health_opt_in=0`
- `proactive_suppressions`（`dedupe_key`, `reason`, `until`。`until IS NULL` は無期限 mute）
- インデックス: `(status, created_at)`, `(dedupe_key, cooldown_until)`

**新モジュール `src/obsidian_ai_hub/proactive/`**

- `store.py`: CRUD と状態遷移、Event 追記
- `policy.py`: `evaluate(intervention) -> allowed | suppressed(reason)`。
  `off` / dedupe・cooldown / mute / `daily_cap` / `min_importance` / 静音時間を判定する。
  **送信可否は LLM に決めさせない。**
- `dedupe.py`: 正規化トピック + 対象 ID の sha256 で `dedupe_key` を決定的に生成
  （[planner/store.py](../../src/obsidian_ai_hub/planner/store.py) の fingerprint 方式を踏襲）
- `service.py`
  - `create_intervention(...)`: policy → 重複 → 日次上限の順に検証し、通れば `proposed` で保存
  - `respond(action)`: `accept` は `tasks.intake.submit_request` で Task を 1 件作成し
    `created_task_id` を保存。**同一 intervention の再 accept は Task を増やさない**。
    `reject` / `snooze` / `mute` は状態と抑止のみ更新

**API / Web**（[web/api.py](../../src/obsidian_ai_hub/web/api.py) にルータ登録）

- `GET /api/v1/proactive/interventions`（status/limit 絞り込み）
- `POST /api/v1/proactive/interventions`（手動/内部生成。テスト・seed・UI の「気づきを追加」）
- `POST /api/v1/proactive/interventions/{id}/respond`
  （`accept|reject|snooze|mute` + `reason` / `snooze_hours`）
- `GET /api/v1/proactive/policy` / `PUT /api/v1/proactive/policy/{domain}`
- フロント `/coach`: 介入カード（title / why-now / evidence / importance / status）、
  accept → Task 詳細へ深リンク、reject/snooze/mute、政策設定（mode・日次上限・静音・health opt-in）。
  既存デザイン規約に従い、フロント単体テストのみ（ブラウザ E2E は追加しない）。

**小さな producer 橋渡し（推奨・分離可能）**

- [planner/suggest.py](../../src/obsidian_ai_hub/planner/suggest.py) が新しい
  `planner_proposals` を保存したとき、同一 fingerprint で `trigger_kind='planner_proposal'`
  の介入も作る。Phase B の検出器が入る前でもコーチ受信箱に実データが入る。

### A2. 統合コンテキストツール（読取専用・auto）

**趣旨**: 断片化したユーザー情報を 1 回で読めるようにし、Phase B の判断材料を揃える。

- `src/obsidian_ai_hub/proactive/context.py`（既存 builder を再実装せず再利用）
  - `user_context_snapshot`: principal 人物、approved memory、active projects（goal 付き）、
    直近 day/week 要約（mood/sleep_hours）、activity 7-30 日、予定/リマインダー 7 日、
    未処理 HITL、queued/running Task、research テーマ。セクション別に予算で切詰め
    （[tasks/observation.py](../../src/obsidian_ai_hub/tasks/observation.py) の budget 方式を流用）。
  - `summary_search`: `summaries` + `summary_items`（mood/sleep 含む）を期間・query で検索。
  - `health_daily_metrics`: `proactive_policy.health_opt_in=0` なら `{"enabled": false}`。
    有効時も [healthcare/queries.py](../../src/obsidian_ai_hub/healthcare/queries.py) の
    日次集計のみ（睡眠・運動・HRV 等）。原レコードは返さない。
- `agents/registry.py` に `input_model` 付きで 3 ツール追加。読取専用なので
  [tasks/capabilities.py](../../src/obsidian_ai_hub/tasks/capabilities.py) の
  `AUTO_POLICY_TOOL_IDS` に追加し、Task Capability へ自動露出させる。
- `compact_schema_text` が解決できることをテストする。

### A3. 自走スケジューラ

- `task_schedules`（`prompt`, `cadence`, `next_run_at`, `idempotency_key`, `source`, `enabled`）
- サーバー lifespan 内の軽量 tick（新しい常駐デーモンは増やさない）
- `task_create` capability（冪等キー・source 付き）でエージェント自身がフォロー Task を積む
- 既存 23:45 の `--suggest-research-theme` をこのテーブルへ移行
- 専用 launchd worker（post-mvp 優先3）は必要になった段階で再検討

### A4. 通知と問いかけ

- `notify_user`（policy チェック・予算消費・delivery ログ・深リンク）
- `check_in`（既存 HITL `ask_user` 方式の先回り質問）
- 通知の outbox / 再送は「通知漏れが運用上問題になった段階」で追加（post-mvp 優先2）
- チャネルはまず LINE + Web。静音時間・日次予算を実送信前に必ず適用

### A5. 目標・習慣モデル

- `goals`（why / metric / target / project_id / source）+ `goal_progress`
- `goal_list` / `goal_get` / `goal_propose` / `goal_update_proposal`、`habit_propose`
- `make_today_target` の「今日の目標」を構造化し、完了チェックを読めるようにする
- activity / summaries と goal を紐付け、進捗を自動集計する基盤

---

## 7. Phase B 詳細

### B1. 朝夜ループ（Task として生成）

- 朝: `user_context_snapshot` → 検出器 → スコアリング → 予算内で通知/check-in/提案
- 夜: 振り返り収集（構造化セルフレポート）→ 翌日の材料
- ハードコード cron ではなくタスクテンプレート（A3）から生成する

### B2. 機会検出器（決定的ルール + LLM 判定の二段）

- プロジェクト停滞、目標ドリフト、習慣未達、睡眠負債/過労（health opt-in）、
  予定過密/衝突、Inbox 滞留、HITL 放置、リサーチ/読書のフォロー期限、間隔反復の復習期限
- 各検出器は候補（evidence + スコア）を出し、policy が送信を決める

### B3. 結果ループ

- 介入への accept/reject/snooze、follow-up Task、`reflection` プロンプトで
  memory 候補へ自動書き戻し（人間承認は既存 memory レビューを流用）

### B4. 評価ハーネス

- fake clock / fake tool での golden シナリオ（予算順守・静音・重複なし・弱証拠で沈黙）
- 過去データの replay。指標: 介入数/日、accept 率、snooze/mute 率、follow-through、目標進捗

---

## 8. Phase C 詳細

- C1 学習・成長ループ: 目標 → Vault からスキル/知識マップ → 練習計画・間隔反復・進捗レポート
- C2 ドメイン別限定 auto: 可逆・記録・undo 付き。外部書込みは HITL 経由のまま
- C3 個人モデル統合: `copilot/core/*.md`（values 等）のバージョン管理・差分検知・全エージェント注入
- C4 モデルハーネス強化: role 別モデル（安価な triage/検出と強力な coach）、
  role 別 temperature / max_tokens、日次トークン・コスト予算の強制、
  planner/runtime の構造化 tool calling 化とフォールバック

---

## 9. 具体設計の補足

### 9.1 プロンプト案

- Proactive persona（コーチ人格）: 最後の一歩を 1 つ、証拠を添える、罪悪感で動かさない。
  既存 `copilot/core/{values,response_style,decision_policy,risk_tolerance}.md` を再利用。
- Appraise プロンプト: `importance / novelty / actionability / urgency / user_burden /
  confidence` を JSON スコアで出力。送信判断は policy。
- Anti-spam プロンプト: 具体証拠が無ければ提案しない、cooldown 内は再提案しない、
  why-now と evidence を必ず添付する。
- Reflection プロンプト: 何を提案し、ユーザーがどう応じ、何を学んだかを構造化し memory 候補へ。

### 9.2 モデルハーネス案

- role 別設定キー: `PROACTIVE_TRIAGE_PROVIDER/MODEL`（検出・選別、安価）、
  `PROACTIVE_COACH_PROVIDER/MODEL`（コーチング、強力）、`TASK_PLANNER_*`。
- role 別 temperature / max_tokens。既存の固定 0.7 / 4096 を role で上書き可能に。
- 日次予算は `llm_call_logs` を集計し hard stop。Task 単位の予算（post-mvp 優先4）と整合。
- planner/runtime の構造化 tool calling 化は信頼性よりも保守コストの改善として後段。

### 9.3 安全・割り込み設計

- ドメイン別モード: `off` / `suggest-only` / `approve-each` / `bounded-auto`。既定は suggest-only。
- 静音時間・日次割り込み予算（重要度別）・dedupe キーの cooldown・ワンタップ mute/snooze。
- 全メッセージに evidence + why-now + 却下手段。自動実行は可逆なもののみ、外部書込みは不可。
- 健康データは opt-in・集計のみ。kill switch と「なぜ来たか」透明化ページ。

### 9.4 操作シナリオ契約（A1 の accept → Task 作成）

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 介入生成 | `InterventionCreate` + policy | `intervention_id`, `dedupe_key` | `proactive_interventions(proposed)` | WebUI/API | off/重複/日次上限/mute/静音は保存しない（副作用なし） | なし |
| accept | `intervention_id` + prompt 本文 | `created_task_id` | `status=accepted`, `created_task_id` | Task worker | 2 回目 accept は Task を増やさない | Task 作成（内部） |
| reject/snooze/mute | `intervention_id` | `status` / `snooze_until` / suppressions | 状態・抑止のみ | 次回の生成 | — | なし |

---

## 10. 実装順と検証手順（A1 + A2）

境界から閉じる順に進める。

1. v48 migration と `proactive/store.py` + policy/dedupe
2. `proactive/service.py` の accept → Task（ここで縦断テストを先に通す）
3. API + 認証 + フロント `/coach`
4. `proactive/context.py` + registry ツール 3 種 + capability policy
5. planner bridge（任意）→ ドキュメント → OCR / 実機確認

**テスト**

- `tests/test_proactive_store.py`: off/静音/日次上限/min_importance/cooldown/mute、
  dedupe 安定性、遷移、accept 1 回だけ Task 作成（再 accept で増えない）
- `tests/test_proactive_api.py`: 作成 → respond、バリデーション、政策更新、認証
- `tests/test_proactive_context_tools.py`: snapshot に要約・活動・未処理 HITL が入る、
  `summary_search` の期間/query、health opt-out/opt-in（healthcare はクエリ層モック）
- `tests/test_agents_registry.py` 拡張: 3 ツール登録と schema 解決
- Frontend: `/coach` の単体テスト（fetch モック）。ブラウザ E2E は追加しない

**ドキュメント**

- [specification.md](specification.md): Capability 行・操作シナリオ
- 新規 ADR `adr/proactive-interventions-and-policy.md`: 介入ストアを
  `planner_proposals` と分ける理由、suggest-only 既定、サーバー同居、健康 opt-in、
  自動実行しない方針
- [CONTEXT.md](../../CONTEXT.md): 用語「介入 / 自発性ポリシー / コーチ受信箱」
- [ai_wiki/00-Index.md](../../ai_wiki/00-Index.md): ADR へのリンク

**完了時**

- `uv run pytest tests/`
- OCR レビュー（操作シナリオ・識別子・停止条件を背景に渡す。出力はファイルへ保存して読む）
- 実 DB で API/UI から介入作成 → accept → Task 1 件を確認
- `make serve` でサーバー再起動

---

## 11. 未決事項・確認したい点

1. planner bridge（`planner_proposals` → 介入）を A1 に含めるか、独立させるか。
2. フロントの URL 名（`/coach` か `/task-agent` 配下に置くか）とナビ位置。
3. policy の初期値（`daily_cap=3`, `min_importance=3`, `cooldown_hours`）の妥当性。
4. 「今日の目標」の構造化方法（Daily Note の frontmatter か新テーブルか）。
5. 将来の通知チャネル（LINE / Push / Web）の優先順位。
6. 日次トークン・コスト予算の初期上限と、超過時の挙動（停止 / 降格 / 通知のみ）。

---

## 12. 関連文書

- [post-mvp.md](post-mvp.md) — 外部入口、Task 通知、専用 worker、実行予算の位置づけ
- [specification.md](specification.md) — Capability、承認ポリシー、操作シナリオ
- [adr/directional-plan-and-runtime-orchestrator.md](adr/directional-plan-and-runtime-orchestrator.md) — 動的ループ
- [adr/no-automatic-rollback-recovery-via-trace-and-hitl.md](adr/no-automatic-rollback-recovery-via-trace-and-hitl.md) — 自動復旧しない方針
- [docs/development-quality-playbook.md](../../docs/development-quality-playbook.md) — 不可逆変更の設計・検証
- [docs/testing.md](../../docs/testing.md) — テスト隔離と安全
