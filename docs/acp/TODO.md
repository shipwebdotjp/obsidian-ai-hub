# CodingAgents ACP 移行 ToDo

関連調査: [2026-09-15-codingagents-acp-investigation.md](2026-09-15-codingagents-acp-investigation.md)

## 全フェーズの不変条件

- [ ] Coding service、Task Agent の Directional Plan、Git root 正規化、repo lock、SQLite の
  run/event、既存 HITL を引き続き正本とする。ACP の plan や permission はこれらを置換しない。
- [ ] Agent からの filesystem / terminal capability は、Client が対象制限・監査・取消・HITL を
  完全に実装するまで advertise しない。
- [ ] stdout は ACP の newline-delimited JSON-RPC のみ、stderr は redacted diagnostics として分離する。
- [ ] 実 Agent を使う調査・互換性検証では、本番 DB、実ユーザーの repository、外部書込み先を使わない。
- [ ] DB に書き込むテストは `uv run pytest tests/` で実行する。browser E2E は追加・通常実行しない。
- [ ] provider 固有の message 分岐を共通 ACP client に混ぜない。標準外の回避策は profile と
  version 範囲に明示する。

## Phase 0 — 互換性 PoC と採用条件の確定

目的: 実装をアプリ本体へ接続する前に、Codex ACP と OpenCode ACP の実際の capability と
session/取消の挙動を、書込み不能な隔離 repository で確認する。

### PoC harness

- [ ] `docs/acp/compatibility-matrix.md` の雛形を作り、Agent、配布元、起動 argv、固定 version、OS、
  認証方式、実施日を記録できるようにする。
- [ ] 一時 Git repository と一時作業ディレクトリだけを使う ACP JSON-RPC harness を用意する。
- [ ] stdio subprocess の process group、stdin writer、stdout の NDJSON reader、stderr collector、
  request ID 相関、timeout、終了待機を実装する（アプリ DB には接続しない）。
- [ ] `initialize` を送信し、protocol version、Agent info、auth method、全 capabilities、
  session config options を JSON artifact と matrix へ保存する。
- [ ] `session/new` → text-only `session/prompt` → `session/update` の受信 → prompt 完了応答を、
  Codex / OpenCode のそれぞれで記録する。
- [ ] `session/cancel` と `$/cancel_request` の各々について、進行中 prompt の応答、stop reason、
  process 終了、残存 child process を確認する。
- [ ] session process を終了した後に `session/resume` と `session/load` を試し、advertise の有無、
  成否、会話 replay、失敗 JSON-RPC error を記録する。
- [ ] Client capability を最小（fs/terminal 非 advertise）にして、Agent が permission、shell、
  file edit を必要とする入力でどう停止・通知するかを確認する。実ファイル変更は許可しない。

### profile の採用情報

- [ ] Codex profile: `codex-acp` の配置方法、固定 package/binary version、`CODEX_PATH` の要否、
  headless で許可する authentication、sandbox / approval option を確定する。
- [ ] OpenCode profile: `opencode acp` の固定 version、起動引数、認証、session 永続性、必要な
  environment を確定する。
- [ ] Node/npm を production run 中に暗黙 download しない配布方法を決める。
- [ ] profile ごとに「必須 capability」「任意 capability」「未対応時の fallback」「既知不具合と
  version 範囲」を matrix に書く。
- [ ] ACP v1 を初期採用版として固定する。ACP v2 の採否はこの移行と切り離し、v2 専用の
  compatibility ticket を作る。

### Phase 0 完了条件

- [ ] 両 Agent の `initialize` artifact と capability matrix がレビュー済みである。
- [ ] session new、prompt、cancel、process cleanup、再接続可否の結果が再現可能な手順とともにある。
- [ ] 実装で必要な minimum capability と、profile に隔離すべき差異が確定している。
- [ ] permission/HITL の方針を次の operation-scenario contract として承認している。

| 段階 | 正本・識別子 | 停止・失敗 | 不可逆操作 |
| --- | --- | --- | --- |
| 交渉 | 登録済み profile、固定 version、`initialize` response | version/必須 capability 不一致なら prompt 前に failed | なし |
| session | app session の transport/profile と ACP `sessionId` | 再開不能は profile の規則により新規化または failed。エラー本文から推測しない | なし |
| prompt | 承認済み Task Plan、正規化 Git root、ACP prompt | protocol error、切断、cancel は監査可能な終端状態にする | Agent による workspace 変更の可能性 |
| permission | ACP request、Task policy、HITL run ID | policy 外は deny/stop。接続が失われた未回答 request は実行しない | 許可後の Agent 操作 |

## Phase 1 — 共通 ACP backend の追加（direct CLI を既定のまま維持）

目的: 既存の安全・永続化契約を変えずに、ACP を一つの実行 transport として追加する。

### ドメインと永続化

- [ ] `coding_sessions` / `coding_runs` の migration を設計する。provider/backend 名と transport
  (`direct_cli` / `acp`) を分け、ACP session ID、profile ID、Agent version、capability snapshot、
  resume mode、接続終了理由を診断として保持する。
- [ ] 旧 session は transport を明示的に `direct_cli` として backfill し、既存 `backend=codex|opencode`
  の意味を変更しない。
- [ ] 新しい session 作成時だけ transport を選択可能にし、既存 session の再開は保存済み transport/profile
  を必ず使う。direct CLI 履歴を ACP session へ自動 replay / migration しない。
- [ ] 既存の status transition、repo lock、external session ID の整合性、Task child run の参照を壊さない
  migration / regression test を追加する。

### 共通 ACP Client

- [ ] `AcpLaunchProfile` を定義する（profile ID、executable、argv、環境 allowlist、固定 version、
  必須 capabilities、auth policy、session persistence policy、既知回避策）。
- [ ] `AcpClientBackend` を実装する。stdio の JSON-RPC encode/decode、request ID 相関、双方向 request、
  notification dispatch、timeout、process group cleanup を共通化する。
- [ ] `initialize` を必ず最初に実行し、version negotiation と profile の必須 capability を検証する。
  未対応は安全に failed とし、暗黙の downgrade をしない。
- [ ] session 新規作成、再開、prompt、完了 stop reason、cancel、close を共通 lifecycle として実装する。
- [ ] ACP `session/update` を内部の typed event envelope に正規化する。message、tool call、plan、usage、
  unknown update、JSON-RPC error、process exit を区別する。
- [ ] 接続断・Agent session 不在時の振る舞いを profile の session persistence policy で決定する。
  一度だけの新規化が許される場合も、理由・旧/新 session ID を event に保存する。
- [ ] Python ACP SDK を採用する場合は、SDK が担う schema/connection と、自前で持つ subprocess /
  persistence / SSE の責務を設計書に明記する。採用しない場合は同等の schema validation を用意する。

### アプリへの接続

- [ ] `coding/service.py` で `worker_start` / `worker_done` の既存 SSE 契約を維持し、ACP 由来の詳細を
  追加 event として流す。既存 consumer を壊す rename / semantic change をしない。
- [ ] ACP Agent の message / tool / plan / usage を coding run event に保存する。機密値と過大な raw payload
  は redact・上限化する。
- [ ] 既存の Coordinator `<cli_request>` → Worker → 観測 → Coordinator のループは維持し、Worker の一回の
  呼出しだけを ACP `session/prompt` に差し替える。
- [ ] `session/request_permission` の応答器を実装する。Task の承認済み範囲内の allow/deny を機械的に
  決め、範囲外・持続的な質問は deny/stop と既存 HITL 作成へ接続する。
- [ ] ACP elicitation を初期リリースで advertise するかを明示的に決める。advertise する場合は、
  HITL run と verified user/connection の紐付け、cancel、restart を縦断実装する。
- [ ] Client fs/terminal は非 advertise のままにする。将来の提供は別 ADR と operation-scenario contract を
  必須にする。
- [ ] Codex / OpenCode の profile を追加し、固有の起動・認証・config だけを profile に置く。

### Phase 1 のテストとレビュー

- [ ] ACP test double と一時 Git repository による isolated backend integration test を作る。
- [ ] 正常系: initialize → new → prompt → update → end、イベント永続化、SSE、git status を確認する。
- [ ] 異常系: unsupported version/capability、malformed JSON-RPC、Agent error、stdout 汚染、process crash、
  timeout、cancel、close を確認する。
- [ ] 状態系: restart 後の interrupted 化、resume 可/不可、session ID 不在、再作成、旧 direct CLI session
  の継続を確認する。
- [ ] 権限系: policy 外 permission、HITL 待機、回答前の切断、cancel、重複回答が副作用なしで停止することを
  確認する。
- [ ] Task Agent からの coding child run で、Plan allowlist、repo lock、child cancel、event link が保たれる
  結合テストを追加する。
- [ ] operation-scenario contract、不可逆操作、identity/schema boundary、失敗/停止規則を背景に含めて
  `ocr review` を実行し、出力はファイルへ保存して読む。

### Phase 1 完了条件

- [ ] direct CLI を既定にしたまま、Codex / OpenCode の ACP profile を選択して隔離環境で end-to-end に
  実行できる。
- [ ] 既存 coding / Task Agent の focused regression suite が通る。
- [ ] permission/HITL、cancel、restart、session lifecycle の contract test がある。
- [ ] UI は追加 event を安全に無視または表示でき、既存画面を手動確認済みである。

## Phase 2 — shadow 検証と opt-in 運用

目的: 実 Agent の差異と運用上の故障を観測しながら、ACP を利用者が選べる transport にする。

- [ ] 書込み対象を持たない acceptance repository と固定 prompt suite を整備する。
- [ ] direct CLI / ACP を同一 suite で比較する。生成文の一致は判定しない。
- [ ] 次を provider/profile/version 別に記録する: session 継続、期待ファイル変更、git status、tool/plan
  event、cancel、HITL stop/restart、終端 status、resource cleanup、エラー診断。
- [ ] Codex ACP と OpenCode ACP の upgrade compatibility suite を実行し、version pin を更新する手順を定める。
- [ ] Web UI と Task Agent で ACP を明示 opt-in にする。利用者に profile、version、再開可否、既知の
  制限を表示する。
- [ ] telemetry は個人の prompt / source を保存せず、profile/version/capability hash、状態、失敗分類、
  duration、cleanup 成否に限定する。
- [ ] production での新規 ACP session と旧 direct CLI session の同時利用、repo lock 競合、取消を
  手動確認する（実データを破壊しない範囲）。
- [ ] fatal failure、permission/HITL 不整合、孤児 process、run の非終端残留に対する rollback は
  「既定 transport を direct CLI のままに戻す」こととし、実施済み workspace 変更を自動 rollback しない。

### Phase 2 完了条件

- [ ] 両 profile の acceptance matrix が満たされ、未対応 capability は UI / docs に明記されている。
- [ ] opt-in 利用時に、cancel、restart、permission/HITL、repo lock の未解決重大障害がない。
- [ ] 旧 direct CLI session を壊さず、ACP failure が session/run 監査で追跡できる。
- [ ] ACP を新規 session の既定にする判断を、実測結果とともにレビューできる。

## Phase 3 — ACP の既定化と direct CLI 廃止

目的: ACP を唯一の Coding Agent transport とし、個別 CLI 出力 parser の保守を終える。

- [ ] 新規 Coding session の既定 transport を ACP に変更する。既存 direct CLI session の読取り・再開を
  いつまで保証するか、support window とユーザー通知を定める。
- [ ] Phase 2 の受入結果に基づき、Codex/OpenCode profile の必須 version・upgrade test・障害対応手順を
  リリース運用へ組み込む。
- [ ] support window 終了後、未終端でない direct CLI session の transport を archival 状態にする。
  会話履歴は削除しない。
- [ ] `CodexCliBackend`、`OpenCodeCliBackend`、CLI 固有 JSON parser、エラー文言による session 判定、
  OpenCode export 専用タイトル同期、および不要な config/test を削除する。
- [ ] 削除後、Codex / OpenCode profile、new/resume/prompt/cancel/permission/HITL/Task child run の
  contract suite を実行する。
- [ ] `ocr review` に本 ToDo の operation scenario を渡して実行し、direct CLI の dead path や
  authorization boundary の回帰を人間が確認する。
- [ ] affected Web screens を手動確認し、migration / removal の release note を残す。

### Phase 3 完了条件

- [ ] 新規 run はすべて ACP transport を使い、direct CLI 実装への実行経路がない。
- [ ] 旧 session の保持・閲覧・終了方針を満たし、意図しない DB / 会話履歴削除がない。
- [ ] cancel、restart、permission/HITL、Task の承認範囲、repo lock の縦断シナリオが通る。
- [ ] Codex/OpenCode に加え、第三の ACP-compatible Agent を profile 追加だけで PoC 接続できる。

## 将来候補（本移行の完了条件ではない）

- [ ] ACP v2 への移行評価。
- [ ] Client filesystem / terminal capability を Git root 制限・監査・HITL と一体で提供する設計。
- [ ] ACP の native subagent / background task / per-turn file-change report を UI に公開する設計。
- [ ] Coordinator を残すか、ACP Agent を Coding Workspace の直接主体にするかの product / authorization
  model 再設計。
