# ACP の委任とプロダクト判断 HITL contract

対象: ACP 移行 Phase 1「アプリへの接続」。
根拠: [compatibility-matrix.md](compatibility-matrix.md) の Phase 0 PoC。
この文書の承認により、[TODO.md](TODO.md) の Phase 0 は完了し、Phase 1 に着手できる。

## 一文でいうと

**選択済みの Git repository 内で何を調べ、どう実装・テストするかは Codex/OpenCode に任せる。**
仕様・優先順位・受入条件など、人間のプロダクト判断が必要になったときだけ、既存の
Coordinator が HITL にエスカレーションする。

ACP はこの分担を変えない。ACP は「アプリと Coding Agent が会話する配線」であり、
Agent の技術的な作業をアプリが操作ごとに承認する仕組みではない。

## 決定

### D1 — Coding Agent へ委任する範囲

- Coding session 作成時に正規化した Git root を、Agent の作業対象とする。
- その repository 内の調査、ファイル変更、shell 実行、テスト実行、技術的な実装判断は、
  Codex/OpenCode の profile が選んだ sandbox / approval 設定に委任する。アプリは操作ごとの
  Plan 照合、allow/deny、HITL を行わない。
- repository 外へのアクセス制限、認証情報の供給、利用可能な model / sandbox / approval の選択は
  profile の責務として維持する。これは「各操作を承認する」ものではなく、session を開始するときの
  実行環境の境界である。

### D2 — プロダクト判断は elicitation を正規経路とし既存 HITL へ送る

- ACP Worker が要件・仕様・優先順位・受入条件などのプロダクト判断を必要とする場合、
  正規経路は ACP `elicitation/create`（`form` のみ）である。
- Client は `elicitation/create` を受けたら、既存の `coding.ask_user` と同じ永続 HITL run /
  Web UI / 回答検証に登録する。`coding.ask_user` は質問の正本のまま残す。
- 回答まで ACP subprocess と接続を維持し、回答後は同じ接続上で `accept` と構造化回答を返して
  Agent turn を継続する。次の Coordinator turn は作らない。
- `cancel`・期限切れ・アプリ再起動・接続断のときは許可せず `cancel` / 失敗として停止する。
  再起動後に古い elicitation へ回答を返そうとはしない（Codex ACP は再接続 resume が実測で
  失敗しているため）。
- 既存 Worker contract の `<needs_user_input>…</needs_user_input>` → Coordinator →
  `coding.ask_user` → 次の Coordinator turn の経路は、direct CLI 用および ACP 非対応 Agent の
  移行期 fallback として残す。
- ACP `session/request_permission` はプロダクト質問として扱わない。これは技術的な実行許可の
  protocol message であり、D3 の事前定義 option か failed 停止で処理する。

### D3 — ACP Client が宣言する機能を最小にする

- Phase 1 の Client capability は `fs`、`terminal`、`elicitation/url` を advertise しない。これは
  「アプリのファイル API、アプリの terminal、外部 URL を開く接続中 UI を Agent に貸さない」
  という意味である。`elicitation/form` のみ advertise する。
- 非advertiseは Agent 自身の sandbox 内の shell / filesystem 操作を禁止しない。Phase 0 でも両 Agent は
  それぞれ自前 sandbox で `rg` / `find` / `ls` を実行した。
- 通常の実行は profile の approval 設定で Agent が止まらないように構成する。予期しない
  `session/request_permission` を受信した場合は、request と選択した応答を run event に記録し、
  profile が「選択済み Git root 内の委任作業」として事前定義した option があればそれを選ぶ。
  そうでなければ failed に停止する。HITL へ変換しない。

### D4 — 接続・取消・復旧

- `session/cancel` を唯一の turn 取消手段とする。`$/cancel_request` には依存しない。
- OpenCode は Phase 0 実測どおり再起動後の resume/load を使用できる。Codex ACP は同条件で resume/load が
  失敗するため、新規 session を作り、理由と旧/新 ACP session ID を run event に残す。
- 接続断、process crash、protocol error のときは Coding run を `failed` または `interrupted` にする。
  既に Agent が行った repository 変更の自動 rollback はしない。

## 操作シナリオ contract

| 段階 | 入力と正本 | 永続化 / 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- |
| session 開始 | project の正規化 Git root、選択 profile | profile/version/capability/ACP session ID → coding session/run | 必須 capability 不足・起動失敗は prompt 前に failed | なし |
| 技術作業 | Agent prompt、profile の sandbox/approval | ACP progress → run event / SSE | Agent 自身の失敗は worker output と終端 status を保存 | repository 内の変更・コマンド実行 |
| プロダクト質問 | ACP `elicitation/create`（form）と Worker の `<needs_user_input>` 報告（fallback） | `coding.ask_user` HITL checkpoint → 待機中の ACP リクエストへの応答（ACP 経路）または HITL worker / 次の Coordinator turn（fallback 経路） | HITL 取消・期限切れ・切断・再起動は Coding run も cancelled / failed。古い elicitation へは回答しない | なし |
| ACP 技術許可 | `session/request_permission` と profile の事前定義 option | request/応答 → run event | option が不明なら failed。HITLにはしない | 許可された場合は Agent の repository 内操作 |
| 取消・復旧 | `session/cancel`、process exit、ACP session ID | 終端 status・diagnostics・旧/新 session ID → 監査 / 次 turn | cancel/切断時に自動 rollback しない | 既存 repository 変更は戻さない |

## 待受・再開の機械可読契約（実装正本: `coding/acp_elicitation.py`）

- 識別子: `hitl_run_id`（HITL run）、elicitation 要求 ID（Agent の JSON-RPC `id`）、
  `connection_token`（turn ごとの uuid）。表示用 `message`・`label` を内部 ID として
  再利用しない。choice value は安定 ID、content 変換時に元の enum メンバ型へ戻す。
- 待受行 `acp_elicitation_waits`（migration v46）の状態: `waiting` → `consumed`
 （回答を同一接続へ返した）または `stale`（cancel・期限切れ・切断・再起動）。
  waiter thread が heartbeat を更新し、`handle_coding_ask_user` は heartbeat 新鮮度と
  要求 ID 一致で live/stale を判定する（プロセスまたぎ対応、in-process 状態に依存しない）。
- 回答検証は副作用（接続への応答）より前。必須欠落・型変換失敗は ValueError とし、
  turn を failed にする（schemaless な応答を作らない）。enum の自由入力は Agent が
  再検証する前提で通過させる。
- 重複回答は HITL の once-only 制約と wait 行の単一消費で安全に停止する。

## Phase 1 の受入条件

- [ ] Codex / OpenCode とも、選択済み Git root で技術作業を操作ごとのアプリ承認なしに完了できる。
- [ ] ACP 経路の `elicitation/create`（form）または fallback 経路の Worker `<needs_user_input>` が
  既存 `coding.ask_user` HITL を作る。ACP 経路は回答後に同一 ACP 接続で Agent turn を継続し、
  fallback 経路は回答後に Coordinator → Agent の順で続行できる。
- [ ] `fs` / `terminal` / `elicitation/url` 非advertise（`elicitation/form` のみ advertise）でも、
  Agent の sandbox 内の正常な作業を妨げない。
- [ ] 予期しない ACP permission request は profile の事前定義 option で処理されるか、安全に failed となり、
  プロダクト判断 HITL と混同されない。
- [ ] cancel、切断、Codex の再作成、OpenCode の再開を contract test で確認する。

## 承認

- [x] 承認: Agent の技術的実行を Codex/OpenCode に委任し、プロダクト判断だけを既存 HITL にエスカレーションする（2026-09-15）。
- [ ] 再承認: ACP worker のプロダクト判断は `elicitation/create`（form）を正規経路とし、`coding.ask_user`
  を正本・UIとして同一 ACP 接続で応答する改訂（`<needs_user_input>` は fallback）。
