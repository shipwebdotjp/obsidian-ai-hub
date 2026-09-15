# CodingAgents の ACP 対応に関する調査

調査日: 2026-09-15

## 結論

**汎用 ACP Client アダプタを一つ追加し、Codex / OpenCode の既存の直接 CLI
アダプタは移行期間だけ残す。検証済みの切替後に直接 CLI アダプタを削除する**、という
段階的な方針を推奨する。

ここでいう「CLI を残す」は、Codex や OpenCode の実行バイナリをなくさない、という意味では
ない。ACP の標準的なローカル transport 自体が、Client が Agent サーバーを subprocess として
起動し、stdio で通信する方式である。削除候補は、現在の
`CodexCliBackend` / `OpenCodeCliBackend` が個別の CLI 引数・JSON 出力・エラー文言を解釈している
**直接 CLI プロトコル**である。

最終形は「ACP が共通層、エージェントごとの差は launch profile と capability に閉じる」。
ただし ACP は全機能と運用上の意味を同一化するものではない。各 Agent の capability negotiation
と実装上の差異を扱う profile は必要であり、「方言がない」という前提で一気に旧実装を削除するのは
危険である。

## 調査対象と前提

このレポートの CodingAgents は、`src/obsidian_ai_hub/coding/` の Coding Workspace と、
それを子 run として起動する Task Agent の `coding_cli` Capability を指す。現在は次を持つ。

| 領域 | 現在の実装・契約 |
| --- | --- |
| 実行 | `CodingBackend.execute()` の同期的な一往復。`CodexCliBackend` は `codex exec --json` / `resume`、`OpenCodeCliBackend` は OpenCode 固有の CLI を実行する。 |
| セッション | アプリの `coding_sessions` と外部の `external_session_id` を対応付ける。外部セッション消失は一度だけ新規化して継続する。 |
| 会話制御 | アプリ内 Coordinator が `<cli_request>` を発行し、Worker の結果を次ターンの観測として返す。Worker は技術的な実行主体である。 |
| 安全・耐久性 | Git root 正規化、リポジトリ単位 lock、取消、HITL の質問、SQLite run/event 監査、Task の承認済み Plan を維持する。 |
| 表示 | アプリの SSE は `worker_start` / `worker_done` と Coordinator の tool event を中心に構成される。 |

したがって ACP 化はモデルや Task の実行境界を置換する案件ではなく、主に「Worker と話す
transport・イベント取得・セッション再開」を置換する案件である。

## ACP で得られるもの、得られないもの

ACP は Editor/Client と Coding Agent の通信を標準化する JSON-RPC 2.0 プロトコルである。標準的な
ローカル構成では Client が Agent を subprocess 起動し、UTF-8 の newline-delimited JSON-RPC を
stdin/stdout で送受信する。従って本アプリは ACP **Client** を実装することになる。

基本フローは `initialize`（版・capability の交渉）、`session/new` または対応時の
`session/load` / `session/resume`、`session/prompt`、`session/update` の逐次通知、完了応答、
`session/cancel` である。通知にはメッセージ、tool call、plan、usage などを載せられる。
`session/load` / `resume` は Agent が advertise した場合だけ呼べる。従って ACP は、現行の
`external_session_id` を使った会話継続に近い標準面を提供するが、全 Agent に再開を保証するものではない。

Client が提供するファイルシステム、terminal、elicitation、permission 応答も capability として
明示する。未 advertise の capability は未対応として扱わなければならない。これは安全側に有用だが、
本アプリの HITL・永続化・取消に接続する実装責務は残る。

## Codex / OpenCode の現状

公式 ACP の Agent 一覧と Registry は Codex と OpenCode の両方を掲載している。

- Codex は `@agentclientprotocol/codex-acp` という独立した stdio ACP server である。これは Codex
  App Server を起動して ACP request を Codex 操作へ、Codex event を ACP event へ変換するアダプタであり、
  Codex CLI 自体のネイティブ ACP endpoint ではない。認証、model / reasoning / approval / sandbox 設定、
  tool・plan・差分等のイベントを提供すると説明されている。
- OpenCode は現行ソースで `opencode acp` を「ACP server を開始する」コマンドとして実装している。
  内部 HTTP server を起動し、`@agentclientprotocol/sdk` の Agent-side connection に stdio の NDJSON
  stream を接続している。少なくとも transport は標準 ACP である。

これは共通 Client 化に十分な根拠だが、同じ feature set の根拠ではない。Codex は ACP adapter を一枚
追加で挟む一方、OpenCode は native command であり、認証手順、再開、permission、構成 option、通知粒度、
エラーの正確な意味は起動ごとに `initialize` の応答を記録して検証する必要がある。

## 選択肢の比較

| 選択肢 | 評価 | 判断 |
| --- | --- | --- |
| A. 現行の Codex/OpenCode 直接 CLI を残したまま、各々に ACP 版を追加 | 既存利用は守れるが、実行契約・テスト・設定・障害対応が provider × transport で増える。ACP の共通化効果を失う。 | 不採用。短期の互換 fallback としてのみ許容。 |
| B. ACP Client アダプタを一つ実装し、provider ごとの差を profile 化。直接 CLI は段階移行中だけ残す | 通信、JSON-RPC 相関、capability 交渉、session lifecycle、cancel、イベント正規化を一箇所にできる。差異も隠蔽せず検証可能。 | **採用**。 |
| C. 直ちに ACP のみへ切替え、直接 CLI を即削除 | コードは早く減るが、既存の session resume / 自動新規化 / HITL / cancellation の未検証差分で、実運用の会話・書込み run を壊しうる。Codex 側は外部 adapter 依存も新たに増える。 | 今は不採用。B の受入条件を満たした後の最終段階として採用。 |

## 推奨アーキテクチャ

```text
Coding service / Task coding capability / SQLite run  （既存の正本・安全境界）
                         |
                   CodingAgentBackend
                         |
              AcpClientBackend  （共通）
              - stdio JSON-RPC connection
              - initialize / capability negotiation
              - session lifecycle / cancel
              - ACP update -> 内部標準 event
                         |
        +----------------+----------------+
        |                                 |
 Codex ACP launch profile          OpenCode ACP launch profile
 codex-acp -> Codex App Server     opencode acp
```

### 共通アダプタの責務

1. session ごとに Agent process と双方向 JSON-RPC connection を保持する（または Agent が再開を
   advertise する場合だけ安全に再接続する）。stdout は ACP message 専用、stderr は診断ログとして
   分離する。
2. `initialize` の protocol version、Agent info、全 capability、auth method、session config option を
   永続化可能な診断情報として取得する。対応していない機能は呼ばない。
3. 新規時の `session/new`、再開時の `session/resume` / `session/load`、入力の `session/prompt`、
   `session/update`、完了 stop reason、`session/cancel` を内部の `CodingBackendResult` と進捗 event に
   正規化する。
4. ACP の tool call / plan / message / usage を、現在の Web SSE と run event に loss-aware に写像する。
   現在の `worker_start` / `worker_done` は残し、詳細は追加 event にする。既存 API consumer を壊さない。
5. transport 切断、JSON-RPC error、Agent stop reason、process exit を区別し、外部 session の再作成は
   capability と provider profile が許す場合に一度だけ行う。現在のようにエラー本文の文字列検索で
   「session not found」を推測しない。

### profile に残す責務

profile は「ACP 方言を本体に混ぜる」ためではなく、標準化されない起動・運用差を明示する薄い宣言層にする。

| 項目 | profile で扱う内容 |
| --- | --- |
| 起動 | executable、argv、必要最小限の環境変数、起動前 health/version check。Codex は `codex-acp`、OpenCode は `opencode acp`。 |
| 認証 | 非対話サーバーで許可する auth method、ブラウザー認証を提供しない設定、必要 secret の供給元。 |
| 初期設定 | 対応が確認された sandbox / approval / model 等だけを session config として選ぶ。未対応 option を静かに送らない。 |
| 永続性 | `load` / `resume` の capability、Agent process と session ID の寿命、再作成可否。 |
| 既知の非互換 | capability だけでは表せない upstream 不具合は、version 範囲・回避策・終了条件を記録する。 |

profile にプロトコル message の分岐ロジックを置かない。標準 ACP の decode / encode は常に一実装とし、
非標準拡張は `_meta` または `_` prefix の公式規約に従い、明示的 opt-in がある時だけ有効化する。

## 現行設計と衝突する重要点

### 1. Permission と HITL は同じものではない

ACP の `session/request_permission` は、Agent が処理中に Client へ送る同期的な許可要求である。一方、
本アプリの HITL は SQLite に質問を永続化し、worker 停止後にも回答・取消・再開できる耐久的な状態機械である。

ACP request をそのまま「UI に許可ダイアログを出し、その接続で待つ」実装にすると、Web server restart や
切断時に回答先を失う。MVP では以下を明確に選ぶ必要がある。

- 選択済み Git root 内の技術的な調査・実装・テストは Coding Agent に委任し、アプリが操作ごとに
  allow / deny や HITL を挟まない。
- 要件・仕様・優先順位などのプロダクト判断だけを、既存 Worker の `<needs_user_input>` 報告から
  Coordinator と durable な HITL run へ送る。ACP Agent の technical permission / elicitation はこの
  プロダクト質問経路に混ぜない。
- `fs` / `terminal` / `elicitation` capability は初期リリースで advertise しない。これはアプリのサービスを
  Agent に貸さない宣言であって、Agent 自身の sandbox 内操作を禁止するものではない。

この分離は、既存 ADR の「親 Task は Coding Agent 内部の権限・Plan逸脱を技術的に保証しない」という境界も
変えない。ACP は可視性と permission point を増やすが、Agent 自身が持つ filesystem/terminal 権限を
自動的に sandbox 化するわけではない。

### 2. 現在の Coordinator ループとの関係

ACP Agent は plan・tool call・途中 message を直接送れるが、既存 Coordinator を同時に残すと、
「Coordinator が `<cli_request>` を出す二段階」と「ACP Agent が独自に計画・質問する二段階」が併存する。
初期移行では前者を維持する。つまり Worker の一回の実行を ACP `session/prompt` に差し替え、既存の
Coordinator、Task Plan、repo lock、SQLite status は正本のままとする。

ACP の plan/tool event を表示・監査に使うことと、Task の Directional Plan の承認を ACP plan に委譲する
ことは別案件である。後者は authorization boundary を変えるため、今回の transport 移行に含めない。

### 3. セッション再開とプロセス寿命

現行は turn ごとに CLI を起動して外部 ID を渡す。ACP では process を session 中に保持できるが、サーバー
再起動で失われる。逆に process を turn ごとに起動するなら、各 Agent が `session/load` または
`session/resume` を実際に advertise・成功する必要がある。ACP 仕様上これは capability 依存である。

よって「session process をどこまで保持するか」は PoC の実測後に決める。少なくとも、`external_session_id`
を ACP session ID に機械的に読み替えるだけでは不十分で、Agent version、capabilities、resume mode、最後の
接続終了理由を diagnostics に残すべきである。

## 段階的な移行計画

### Phase 0: 互換性 PoC（書込み不可の検証用 repository）

Codex ACP と OpenCode ACP に対し、共通 JSON-RPC harness で次を記録する。実ユーザーの project や本番 DB
には書き込まない。

1. `initialize` 結果（version、capabilities、auth、agent info）。
2. 新規 session、短い `session/prompt`、message/tool/plan notification、完了 stop reason。
3. cancel 中の response / process 終了、timeout、stderr と stdout の分離。
4. session を閉じてからの `resume` / `load`、不可能時の明確な失敗。
5. file edit / shell / permission request と、Client capability を最小にした時の振る舞い。

成果物は provider ごとの capability matrix と、採用する version の固定・アップグレード試験条件である。

### Phase 1: 共通 ACP backend を追加（direct CLI はデフォルトのまま）

- `CodingBackend` を非同期 lifecycle を表現できる内部 interface に拡張し、`AcpClientBackend` と
  `AcpLaunchProfile` を追加する。Python SDK は Pydantic model、async base class、JSON-RPC plumbing を
  提供しており、採用候補である。ただし、subprocess lifecycle、SQLite、SSE 正規化はアプリ側の責務とする。
- DB / API の既存 `backend` 名（`codex` / `opencode`）を急に意味変更しない。移行中は transport
  (`direct_cli` / `acp`) と profile/version/ACP session diagnostics を追加し、旧 session は必ず旧 transport
  で再開する。
- 実装の初期 Client capability は必要最小限とし、permission と elicitation の挙動を明示的にテストする。
  workspace file/terminal を Client 経由で提供するのは別 phase とする。

### Phase 2: shadow 検証後に opt-in

- 同一の受入用 repository / prompt suite で direct CLI と ACP の結果を比較する。文章一致ではなく、
  session 継続、期待ファイル変更、git status、取消、HITL停止、run の終端状態、イベント監査を判定する。
- UI と Task Agent に ACP を opt-in で提供し、運用上の失敗を provider/profile/version 別に観測する。
- 既存 session は移行しない。direct CLI session の会話履歴を ACP session へ再生しない限り、会話の意味や
  tool 状態を失うためである。旧 session は read-only として閲覧可能にし、必要なら新規 ACP session を作る。

### Phase 3: ACP を既定化し、direct CLI を廃止

次の受入条件を両 profile で満たしてから、**新規 session の既定を ACP に変更**する。

- 新規・継続・Agent/session 不在時の stop が、仕様化した状態遷移で成功する。
- cancel、server restart、process crash で run が `running` のまま残らず、診断情報を保つ。
- permission / HITL に対する allow、deny、cancel、再開が操作シナリオどおりである。
- repo lock、Git root、Task の Plan 承認・対象 allowlist は ACP 経由でも迂回されない。
- Codex ACP / OpenCode の固定した互換 version と upgrade test がある。

既存の direct CLI session が終端または明示移行済みであり、support window を過ぎたら、
`CodexCliBackend`、`OpenCodeCliBackend`、CLI 固有 JSON parser、文字列による session-not-found 判定、
OpenCode export 専用のタイトル同期を削除する。エージェント executable を削除するわけではない。

## 実装時の operation-scenario contract

ACP 導入はコードを書き込ませ得る authorization boundary に関わる。実装開始時にはプロジェクトの
不可逆変更品質ゲートに従い、少なくとも次の縦断 scenario を仕様・テストの正本にする。

| 段階 | 正本・入力 | 永続化 / 次の主体 | 停止・失敗 | 不可逆操作 |
| --- | --- | --- | --- | --- |
| 起動・交渉 | 登録済み profile、固定 argv、`initialize` response | profile/version/capability diagnostics → run event | 非対応 version / 必須 capability 欠落は prompt 前に failed | なし |
| session 解決 | coding session の transport/profile と ACP session ID | session diagnostics → Coding service | resume 非対応・ID不在は契約に従い新規化または failed。推測しない | なし |
| prompt 実行 | 承認済み Task Plan、Git root、ACP prompt | ACP updates → SSE / run event | protocol error・切断・cancel は終端状態へ一意に遷移 | Agent が workspace を変更し得る |
| permission / 質問 | ACP request、Task policy、HITL run | allow/deny と HITL link → event | policy外は deny/stop。接続切断時に未回答を実行しない | 許可後の Agent 操作 |
| 完了・復旧 | stop reason、git status、process exit | run status / diagnostics | 完了 event 前の失敗は `failed` / `interrupted`。自動 rollback はしない | 既存変更は戻さない |

この scenario を満たす isolated end-to-end backend test を、実 Agent には依存しない ACP test double と
一時 Git repository で追加する。実 Agent との compatibility suite は別途、明示的に隔離された検証環境で
実行する。

## リスクと対応

| リスク | 対応 |
| --- | --- |
| ACP v2 は draft で、v1 と lifecycle が異なる | 最初は stable な v1 に固定し、v2 は adapter interface を保った別 compatibility project とする。v2 を「最新だから」と同時導入しない。 |
| 標準 protocol でも Agent 実装の capability / bug が異なる | capability matrix、profile、version pin、実 Agent compatibility test を持つ。capability 未広告は未対応と扱う。 |
| `codex-acp` は追加 npm package / Codex dependency を含む | profile ごとに executable と version を固定し、起動失敗を configuration error として表面化する。Node/npm の暗黙 download を本番 run で行わない。 |
| 長時間接続の孤児 process・再起動 | process group ownership、heartbeat、cancel/close、startup 時の interrupted 化を設計・テストする。 |
| Agent の豊富な event を無理に既存 SSE へ完全変換して表示を壊す | 安定した内部 event envelope を追加し、未知の ACP update は raw redacted diagnostics として記録する。既存イベントは互換維持する。 |

## この調査で確定しない事項

- 各採用バージョンの Codex ACP / OpenCode ACP が、実際の認証形態とサーバー再起動後の session resume を
  満たすかは、ローカル設定に依存するため PoC で確認が必要である。
- ACP Agent に Client filesystem / terminal を委譲するか、Agent 自身の workspace 権限を使わせるかは、
  authorization boundary の設計判断である。今回の調査では前者を advertise しない安全側を出発点とする。
- Coordinator を将来なくして ACP Agent を直接 Coding Workspace の主体にするかは、transport 変更ではなく
  product / authorization model の再設計である。

## 参照資料

- [ACP Introduction](https://agentclientprotocol.com/get-started/introduction) — ACP の目的、local stdio / remote の位置付け。
- [ACP v1 Overview](https://agentclientprotocol.com/protocol/v1/overview) — JSON-RPC、Client/Agent の責務、capability と session の基本 flow。
- [ACP v1 Initialization](https://agentclientprotocol.com/protocol/v1/initialization) — version negotiation と capability 未広告時の扱い。
- [ACP v1 Session Setup](https://agentclientprotocol.com/protocol/v1/session-setup) — `new`、`load`、`resume` と capability 要件。
- [ACP v1 Prompt Turn](https://agentclientprotocol.com/protocol/v1/prompt-turn) — prompt/update/stop reason、tool/plan/usage 通知。
- [ACP v1 Elicitation](https://agentclientprotocol.com/protocol/v1/elicitation) — structured user input と Client 接続・identity への紐付け要件。
- [ACP v1 Cancellation](https://agentclientprotocol.com/protocol/v1/cancellation) および [Transports](https://agentclientprotocol.com/protocol/v1/transports) — cancel と stdio の message 境界。
- [ACP Registry](https://agentclientprotocol.com/get-started/registry) — Codex / OpenCode の掲載状況。
- [codex-acp README](https://github.com/agentclientprotocol/codex-acp) — Codex ACP adapter の構成、提供 feature、導入方法。
- [OpenCode `acp` command source](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/cli/cmd/acp.ts) — OpenCode の ACP server 起動と stdio NDJSON 接続。
- [ACP Python SDK](https://agentclientprotocol.com/libraries/python) — Pydantic models、async base classes、JSON-RPC plumbing。
- [ACP v2 Overview](https://agentclientprotocol.com/protocol/v2/overview) — v2 が v1 と異なる lifecycle を持つことの確認用（採用対象ではない）。
