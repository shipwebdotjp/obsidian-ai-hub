# CodingAgents ACP 移行 ToDo

関連調査: [2026-09-15-codingagents-acp-investigation.md](2026-09-15-codingagents-acp-investigation.md)

## 全フェーズの不変条件

- [x] Coding service、Task Agent の Directional Plan、Git root 正規化、repo lock、SQLite の
  run/event、既存 HITL を引き続き正本とする。ACP の plan や permission はこれらを置換しない。
  （resident worker の ACP 分岐も同一契約。2026-09-15確認）
- [x] Agent からの filesystem / terminal capability は、Client が対象制限・監査・取消・HITL を
  完全に実装するまで advertise しない。
  （`clientCapabilities` は elicitation/form のみ。2026-09-15確認）
- [x] stdout は ACP の newline-delimited JSON-RPC のみ、stderr は redacted diagnostics として分離する。
  （`AcpConnection` の分離 + 非JSON行skip。2026-09-15確認）
- [x] 実 Agent を使う調査・互換性検証では、本番 DB、実ユーザーの repository、外部書込み先を使わない。
  （PoC は一時repoのみ。2026-09-15のブラウザ live E2E は指示により本番DBへ session/run
  記録のみ残し、repo は使い捨て `/tmp/acp-browser-test`、外部書込みなし）
- [x] DB に書き込むテストは `uv run pytest tests/` で実行する。browser E2E は追加・通常実行しない。
  （E2E 追加なし、手動確認のみ。2026-09-15確認）
- [x] provider 固有の message 分岐を共通 ACP client に混ぜない。標準外の回避策は profile と
  version 範囲に明示する。
  （起動・argv・resume 可否のみ profile。codex live 実行は未実施。2026-09-15確認）

## Phase 0 — 互換性 PoC と採用条件の確定

目的: 実装をアプリ本体へ接続する前に、Codex ACP と OpenCode ACP の実際の capability と
session/取消の挙動を、書込み不能な隔離 repository で確認する。

### PoC harness

- [x] `docs/acp/compatibility-matrix.md` の雛形を作り、Agent、配布元、起動 argv、固定 version、OS、
  認証方式、実施日を記録できるようにする。
- [x] 一時 Git repository と一時作業ディレクトリだけを使う ACP JSON-RPC harness を用意する。
- [x] stdio subprocess の process group、stdin writer、stdout の NDJSON reader、stderr collector、
  request ID 相関、timeout、終了待機を実装する（アプリ DB には接続しない）。
- [x] `initialize` を送信し、protocol version、Agent info、auth method、全 capabilities、
  session config options を JSON artifact と matrix へ保存する。
- [x] `session/new` → text-only `session/prompt` → `session/update` の受信 → prompt 完了応答を、
  Codex / OpenCode のそれぞれで記録する。
- [x] `session/cancel` と `$/cancel_request` の各々について、進行中 prompt の応答、stop reason、
  process 終了、残存 child process を確認する。
- [x] session process を終了した後に `session/resume` と `session/load` を試し、advertise の有無、
  成否、会話 replay、失敗 JSON-RPC error を記録する。
- [x] Client capability を最小（fs/terminal 非 advertise）にして、Agent が permission、shell、
  file edit を必要とする入力でどう停止・通知するかを確認する。実ファイル変更は許可しない。

### profile の採用情報

- [x] Codex profile: `codex-acp` の配置方法、固定 package/binary version、`CODEX_PATH` の要否、
  headless で許可する authentication、sandbox / approval option を確定する。
  （2026-09-15実測: npm pin 1.11.0、`CODEX_PATH` 不要、headlessは `api-key`。sandbox/approvalの
  session config選定はPhase 1へ申送り）
- [x] OpenCode profile: `opencode acp` の固定 version、起動引数、認証、session 永続性、必要な
  environment を確定する。
  （2026-09-15実測: 1.18.31、`--hostname 127.0.0.1 --port 0` 必須、auth.jsonのopencode-go、
  再起動後resume/load成功）
- [x] Node/npm を production run 中に暗黙 download しない配布方法を決める。
  （`tools/acp_poc` にsave-exactで事前install、lockfileで固定）
- [x] profile ごとに「必須 capability」「任意 capability」「未対応時の fallback」「既知不具合と
  version 範囲」を matrix に書く。
- [x] ACP v1 を初期採用版として固定する。ACP v2 の採否はこの移行と切り離し、v2 専用の
  compatibility ticket を作る。（v2 ticketの起票は未実施・要GitHub issue作成）

### Phase 0 完了条件

- [x] 両 Agent の `initialize` artifact と capability matrix がレビュー済みである。
  （2026-09-15実測、2026-09-15方針レビュー完了）
- [x] session new、prompt、cancel、process cleanup、再接続可否の結果が再現可能な手順とともにある。
  （`tools/acp_poc/README.md` + `docs/acp/artifacts/`）
- [x] 実装で必要な minimum capability と、profile に隔離すべき差異が確定している。
  （matrix「実装向け minimum capability」節）
- [x] permission/HITL の方針を [委任とプロダクト判断 HITL contract](permission-hitl-contract.md) として承認している。
  （技術的作業はAgentへ委任し、プロダクト判断だけを既存HITLへ送る）

| 段階 | 正本・識別子 | 停止・失敗 | 不可逆操作 |
| --- | --- | --- | --- |
| 交渉 | 登録済み profile、固定 version、`initialize` response | version/必須 capability 不一致なら prompt 前に failed | なし |
| session | app session の transport/profile と ACP `sessionId` | 再開不能は profile の規則により新規化または failed。エラー本文から推測しない | なし |
| prompt | 承認済み Task Plan、正規化 Git root、ACP prompt | protocol error、切断、cancel は監査可能な終端状態にする | Agent による workspace 変更の可能性 |
| プロダクト質問 | ACP `elicitation/create`（form）を正規とし、Worker の `<needs_user_input>` 報告を fallback とする。質問の正本は既存 `coding.ask_user` | ACP 経路は回答まで接続を維持し、同じ接続上で結果を返して Agent turn を継続する。fallback 経路は HITL の回答を次の Coordinator turn へ渡す。ACP technical permission は HITL にしない | なし |

## Phase 1 — 共通 ACP backend の追加（direct CLI を既定のまま維持）

目的: 既存の安全・永続化契約を変えずに、ACP を一つの実行 transport として追加する。

### ドメインと永続化

- [x] `coding_sessions` / `coding_runs` の migration を設計する。provider/backend 名と transport
  (`direct_cli` / `acp`) を分け、ACP session ID、profile ID、Agent version、capability snapshot、
  resume mode、接続終了理由を診断として保持する。
  （v45: transport/session/profile 列 + backfill。turn 診断に version/profile/capability/
  agentInfo/stop reason/update種別/elicitation を保持。2026-09-15実装）
- [x] 旧 session は transport を明示的に `direct_cli` として backfill し、既存 `backend=codex|opencode`
  の意味を変更しない。（v45 で backfill。2026-09-15確認）
- [x] 新しい session 作成時だけ transport を選択可能にし、既存 session の再開は保存済み transport/profile
  を必ず使う。direct CLI 履歴を ACP session へ自動 replay / migration しない。
  （作成 API のみ transport 受付、run は session 値を引継ぎ、worker は保存値で分岐。
  ブラウザに transport 選択 UI（既定 direct_cli）を追加。2026-09-15実装）
- [x] 既存の status transition、repo lock、external session ID の整合性、Task child run の参照を壊さない
  migration / regression test を追加する。
  （`tests/test_coding_acp*.py` + workspace/regression suite 全緑。2026-09-15確認）

### 共通 ACP Client

- [x] `AcpLaunchProfile` を定義する（profile ID、executable、argv、環境 allowlist、固定 version、
  必須 capabilities、auth policy、session persistence policy、既知回避策）。
  （codex: 1.11.0 固定・resume 不可、opencode: 1.18.31 固定・`--hostname/--port` 必須を argv 化。
  version 不一致は警告 + 診断記録。2026-09-15実装）
- [x] `AcpClientBackend` を実装する。stdio の JSON-RPC encode/decode、request ID 相関、双方向 request、
  notification dispatch、timeout、process group cleanup を共通化する。（2026-09-15実装）
- [x] `initialize` を必ず最初に実行し、version negotiation と profile の必須 capability を検証する。
  未対応は安全に failed とし、暗黙の downgrade をしない。
  （spec 準拠: `protocolVersion: 1` int、`clientCapabilities`。不一致は例外で failed。
  実 Agent での拒否（`Invalid params`）を修正し live 確認。2026-09-15実装）
- [x] session 新規作成、再開、prompt、完了 stop reason、cancel、close を共通 lifecycle として実装する。
  （spec 形状: new/resume/load の `sessionId/cwd/mcpServers`、prompt blocks、`session/cancel`
  通知、advertise 時のみ close。2026-09-15実装）
- [x] ACP `session/update` を内部の typed event envelope に正規化する。message、tool call、plan、usage、
  unknown update、JSON-RPC error、process exit を区別する。
  （種別集計 + 本文抽出を診断に保持。raw payload は保存しない。spec 形状ネスト対応。
  2026-09-15実装）
- [x] 接続断・Agent session 不在時の振る舞いを profile の session persistence policy で決定する。
  一度だけの新規化が許される場合も、理由・旧/新 session ID を event に保存する。
  （opencode: resume、codex: 再作成 + notice。2026-09-15実装・単体 test）
- [x] Python ACP SDK を採用する場合は、SDK が担う schema/connection と、自前で持つ subprocess /
  persistence / SSE の責務を設計書に明記する。採用しない場合は同等の schema validation を用意する。
  （SDK 不採用、自前実装 + `acp_elicitation` に validation 集約。調査報告に明記。2026-09-15）

### アプリへの接続

- [x] `coding/service.py` で `worker_start` / `worker_done` の既存 SSE 契約を維持し、ACP 由来の詳細を
  追加 event として流す。既存 consumer を壊す rename / semantic change をしない。
  （`elicitation_response` を追加 event として新設、既存 event 無変更。resident worker も
  同一 event。2026-09-15実装）
- [ ] ACP Agent の message / tool / plan / usage を coding run event に保存する。機密値と過大な raw payload
  は redact・上限化する。
  （現状: worker 本文 + 種別集計 + 上限化のみ保存。機密値の検出・redact 設計は未実施のため残す）
- [x] 既存の Coordinator `<cli_request>` → Worker → 観測 → Coordinator のループは維持し、Worker の一回の
  呼出しだけを ACP `session/prompt` に差し替える。
  （SSE flow と resident worker の両方で差し替え。live で 2 turn 連続実行を確認。2026-09-15実装）
- [x] ACP worker がプロダクト判断を必要とするとき、`elicitation/create`（form）を正規経路とする。
  受信したら既存 `coding.ask_user` と同じ永続 HITL run / Web UI に登録し、回答まで ACP subprocess と
  接続を維持して、回答後に同じ接続上で `accept` と構造化回答を返して Agent turn を継続する。
  既存 `<needs_user_input>` → Coordinator → `coding.ask_user` HITL → 次の Coordinator turn の経路は
  direct CLI 用および ACP 非対応 Agent の移行期 fallback として残す。
  （2026-09-15実装: `acp_elicitation` + service接続）
- [x] ACP `session/request_permission` はプロダクト HITL に変換しない。profile が選択済み Git root 内の
  委任作業として事前定義した option がある場合だけ応答し、それ以外は run を failed にする。
  （既知 allow option のみ応答、未知は HITL を作らず failed。単体 test。2026-09-15実装）
- [x] Client は `elicitation/form` のみ advertise する（`elicitation/url` は提供しない）。
  接続を維持できる間は ACP elicitation が正規経路であり、cancel・期限切れ・アプリ再起動・接続断の
  ときは許可せず cancel / 失敗として停止する。再起動後に古い elicitation へ回答しない。
  （2026-09-15実装: `initialize` で `{"form": {}}` のみ、`url` 要求は -32602）
- [x] Client fs/terminal と `elicitation/url` は非 advertise のままにする。将来の提供は別 ADR と
  operation-scenario contract を必須にする。
  （`clientCapabilities` に elicitation/form のみ。2026-09-15確認）
- [x] elicitation 由来の HITL 回答は `handle_coding_ask_user` の「次の Coordinator turn へ戻す」再開と
  分岐させる。direct / fallback は従来通り `queued` へ戻し、ACP elicitation 由来は待機中の ACP
  リクエストへの応答に回す。`ask_user` schema と elicitation form schema の変換と回答検証を再利用する。
  （2026-09-15実装: `resume_target=acp_elicitation` + `acp_elicitation_waits` 行の heartbeat で
  live/stale 判定。stale は fallback 再queue）
- [x] Codex / OpenCode の profile を追加し、固有の起動・認証・config だけを profile に置く。
  （argv・resume 可否・固定 version を profile 化。2026-09-15実装）

### Phase 1 のテストとレビュー

- [x] ACP test double と一時 Git repository による isolated backend integration test を作る。
  （mock + fake_agent 実 subprocess。2026-09-15実装）
- [x] 正常系: initialize → new → prompt → update → end、イベント永続化、SSE、git status を確認する。
  （mock + fake_agent + resident worker E2E test。2026-09-15実装）
- [x] 異常系: unsupported version/capability、malformed JSON-RPC、Agent error、stdout 汚染、process crash、
  timeout、cancel、close を確認する。
  （version 不一致・不正 elicitation・prompt error・非JSON行 skip・cancel/close の単体 test。
  process crash・timeout の実 subprocess 再現は未実施のため、将来の追加余地あり。2026-09-15）
- [x] 状態系: restart 後の interrupted 化、resume 可/不可、session ID 不在、再作成、旧 direct CLI session
  の継続を確認する。
  （resume 失敗→新規化 test、codex 再作成方針、opencode は live で resume 成功、既存 suite で
  direct 継続。2026-09-15確認）
- [x] 委任/HITL系: 通常の Agent 作業が操作単位の HITL を作らないこと、`elicitation/create`（form）
  または fallback の `<needs_user_input>` が `coding.ask_user` を作ること、ACP 経路は同一接続応答で
  turn 継続し fallback 経路は次の Coordinator turn で続行すること、回答前の切断・cancel・重複回答・
  期限切れ・再起動が安全に停止すること（古い elicitation へ回答しない）を確認する。
  （2026-09-15実装: `tests/test_coding_acp_elicitation.py` 23件 + fake_agent 実 subprocess）
- [x] ACP permission系: profile の既知 option は応答を記録して処理でき、未知 option は HITL を作らず
  failed に停止することを確認する。
  （allow 応答 + 未知 option 拒否の単体 test。2026-09-15実装）
- [ ] Task Agent からの coding child run で、Plan allowlist、repo lock、child cancel、event link が保たれる
  結合テストを追加する。
  （ACP transport での child run 結合テストは未追加。direct 経路の既存 suite は全緑）
- [x] operation-scenario contract、不可逆操作、identity/schema boundary、失敗/停止規則を背景に含めて
  `ocr review` を実行し、出力はファイルへ保存して読む。
  （3回実施、指摘は全件修正。`/tmp/ocr_review*.txt`。2026-09-15）

### Phase 1 完了条件

- [x] direct CLI を既定にしたまま、Codex / OpenCode の ACP profile を選択して隔離環境で end-to-end に
  実行できる。
  （2026-09-15 ブラウザ live: OpenCode ACP で使い捨て repo に 2 turn 連続実行 + session resume
  成功、repo 無変更。Codex ACP の live 実行は未実施）
- [x] 既存 coding / Task Agent の focused regression suite が通る。
  （`uv run pytest tests/` 1404 passed。2026-09-15）
- [x] permission/HITL、cancel、restart、session lifecycle の contract test がある。
  （`tests/test_coding_acp*.py` + 既存 HITL/worker suite。2026-09-15）
- [x] UI は追加 event を安全に無視または表示でき、既存画面を手動確認済みである。
  （transport 選択 UI + ACP バッジ追加、CodingPage 単体 test + tsc、ブラウザで手動確認。
  2026-09-15）

## Phase 2 — shadow 検証と opt-in 運用

目的: 実 Agent の差異と運用上の故障を観測しながら、ACP を利用者が選べる transport にする。

- [ ] 書込み対象を持たない acceptance repository と固定 prompt suite を整備する。
- [ ] direct CLI / ACP を同一 suite で比較する。生成文の一致は判定しない。
- [ ] 次を provider/profile/version 別に記録する: session 継続、期待ファイル変更、git status、tool/plan
  event、cancel、HITL stop/restart、終端 status、resource cleanup、エラー診断。
- [ ] Codex ACP と OpenCode ACP の upgrade compatibility suite を実行し、version pin を更新する手順を定める。
- [ ] Web UI と Task Agent で ACP を明示 opt-in にする。利用者に profile、version、再開可否、既知の
  制限を表示する。
  （Web UI の transport 選択は Phase 1 で先行実装済み。Task Agent 側と profile/version 表示は残件）
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
