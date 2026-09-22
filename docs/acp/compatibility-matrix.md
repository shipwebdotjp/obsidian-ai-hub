# ACP Compatibility Matrix (Phase 0 PoC)

この表は 2026-09-15 の PoC 実測結果（固定 version・capability・session/cancel 挙動）の記録である。
移行の判断と未実装の残課題は
`ai_wiki/10-Decisions-Architecture.md`「CodingAgents は共通 ACP Client へ段階移行する」を正とする。

方針承認: [ACP の委任とプロダクト判断 HITL contract](permission-hitl-contract.md)。技術的作業は
Agent/profile に委任し、プロダクト判断だけを既存 Coordinator → HITL 経路へ送る。

ACP v1 を初期採用版として固定。v2 は別 ticket（本移行と切り離し）。PoC の raw artifact は
`docs/acp/artifacts/` に残す。

## 環境

| 項目 | 値 |
| --- | --- |
| OS | Darwin (arm64) |
| node | v24.13.0 |
| npm | 11.6.2 |
| Python | 3.12.12 |
| 実施日 | 2026-09-15 |
| 作業ディレクトリ | 一時 Git repository + 一時 cwd のみ（本番DB・実ユーザrepo不使用） |
| Client capability | Phase 0 PoC 時は最小（`clientCapabilities: {}` — fs/terminal/elicitation 非advertise）。Phase 1 以降は `elicitation/form` のみ advertise し、fs/terminal/`elicitation/url` は非advertise のまま |

## Agent 一覧

| Agent | 配布元 | 起動 argv | 固定 version | 認証方式 |
| --- | --- | --- | --- | --- |
| Codex | npm `@agentclientprotocol/codex-acp`（`tools/acp_poc/node_modules` にpin導入、save-exact） | `node <repo>/tools/acp_poc/node_modules/@agentclientprotocol/codex-acp/dist/index.js` | 1.11.0 | `api-key`（検証用 `OPENAI_API_KEY`。`~/.codex/auth.json` にも同種資格あり）。`_auth/status_update` で `kind: api-key` を確認 |
| OpenCode | mise `opencode` binary | `opencode acp --hostname 127.0.0.1 --port 0` | 1.18.31 | `~/.local/share/opencode/auth.json` の `opencode-go` entry（使用model `opencode/big-pickle`）。検証用 `OPENCODE_GO_API_KEY` をフォールバックとして用意 |

- `CODEX_PATH`: 不要を確認。環境変数未設定でも `codex-acp` は PATH 上の `codex`（0.153.0）で動作した。
- `--help` / `--version` は `codex-acp` に存在しない（stdio待機でhangする）。versionは `node_modules/.../package.json` + `initialize` の `agentInfo` で確認する。
- Node/npm の暗黙 download は production run では行わない。PoC では上記 pin 版を事前 install したもののみ使う。

## initialize 結果

| 項目 | Codex (1.11.0) | OpenCode (1.18.31) |
| --- | --- | --- |
| protocol version | 1 | 1 |
| agent info | `@agentclientprotocol/codex-acp` 1.11.0 | `OpenCode` 1.18.31 |
| auth method | `api-key`（openai provider）、`chat-gpt` | `opencode-login`（terminal）1件 |
| agent capabilities | `loadSession: true`、`promptCapabilities: {embeddedContext, image}`、`sessionCapabilities: {resume, list, close, delete, fork, additionalDirectories, subagents}`、`mcpCapabilities: {http}`、`auth: {logout}`、custom `_meta`（steering/goal/jetbrains） | `loadSession: true`、`promptCapabilities: {embeddedContext, image}`、`sessionCapabilities: {close, fork, list, resume}`、`mcpCapabilities: {http, sse}` |
| session config options | `session/new` 応答に `models.availableModels` を含む | `session/new` 応答に `configOptions`（model select等）を含む |
| artifact | `artifacts/codex-1.11.0-2026-09-15/initialize-run.json` | `artifacts/opencode-1.18.31-2026-09-15/initialize-run.json` |

## session / prompt / cancel

| 項目 | Codex | OpenCode |
| --- | --- | --- |
| `session/new` | 成功（sessionId発行）。`models` 付き | 成功（`ses_`形式sessionId）。`configOptions` 付き |
| text-only `session/prompt` → `session/update` → 完了応答 | `end_turn`。updates: `agent_message_chunk`/`session_info_update`/`usage_update`/`available_commands_update` | `end_turn`。updates: `agent_message_chunk`/`agent_thought_chunk`/`usage_update`/`available_commands_update` |
| `session/cancel` | `stopReason: cancelled`。process終了・残存childなし | `stopReason: cancelled`。process終了・残存childなし |
| `$/cancel_request`（`{"id": prompt_id}`） | turnは継続し `end_turn`。cancel効果なし（実測） | turnは継続し `end_turn`。cancel効果なし（実測） |
| process終了後の `session/resume` | advertiseあり（`sessionCapabilities.resume`）だが**失敗**: `-32603 no rollout found for thread id` | advertiseあり。**成功**（`configOptions` 付きresult） |
| process終了後の `session/load` | advertiseあり（`loadSession: true`）だが**失敗**: 同上 `-32603` | advertiseあり。**成功** |
| 最小Client capability時のpermission/shell/file-edit要求 | `session/request_permission` なし。Agent自身のsandboxで `rg`/`find` を実行（tool_call `execute`）。repo無変更 | `session/request_permission` なし。Agent自身のsandboxで `ls -la` を実行（tool_call `execute`）。repo無変更 |

全runで `repoClean=True`（前後 `git status` 一致）、process group終了・orphanなし、
secret値のartifact混入なし（自動検査済み）を確認。

## profile 別 capability 要件

| profile | 必須 capability | 任意 capability | 未対応時の fallback | 既知不具合と version 範囲 |
| --- | --- | --- | --- | --- |
| codex-acp | protocol v1、`session/new`、`session/prompt`（text）、`session/update` 受信、`session/cancel` | `loadSession`、`sessionCapabilities.resume`（再開は不可のためPhase 1では不使用）、`additionalDirectories`、`subagents`、`mcp http` | resume/load失敗時は新規session化＋理由・旧/新IDをevent保存（エラー本文推測をしない）。`$/cancel_request` には依存しない | 再起動後のresume/loadはadvertiseがあっても `-32603 no rollout found` で失敗（1.11.0実測）。`_auth/status_update` 等の `_` prefix custom通知が来る（1.11.0実測、specのextensibility範囲内として受容・未知updateはredacted保存） |
| opencode-acp | protocol v1、`session/new`、`session/prompt`（text）、`session/update` 受信、`session/cancel` | `loadSession`、`sessionCapabilities.resume`（再起動後も成功することを確認）、`mcp http/sse`、`prompt embeddedContext/image` | resume失敗時はcodex同様に新規化＋記録。`$/cancel_request` には依存しない | (1) 引数なし `opencode acp` は `ServeError` で即死する（1.18.31実測）。`--hostname 127.0.0.1 --port 0` の明示が必須 → profile argvに固定。(2) stdoutに `[..] WARN .. mDNS enabled but hostname is loopback` の非JSON行が混入する（1.18.31実測）。Clientはstdout汚染を検出・記録できること |

## session/request_permission の実測形状（OpenCode 1.18.31）

Phase 0/1 の artifact では permission request は 0 件（`agentRequestCount: 0`）で、
Client 側の事前定義 option 判定は未検証だった。2026-09-22 のリサーチ project モード実運用で
OpenCode 1.18.31 が実際に `session/request_permission` を発行することを確認した。

- request の option は spec 形状（`optionId` / `name` / `kind`）。実測例:
  `[{"optionId": "once", "kind": "allow_once"}, {"optionId": "always", "kind": "allow_always"}, {"optionId": "reject", "kind": "reject_once"}]`
- Client は spec 形状 `{"outcome": {"outcome": "selected", "optionId": ...}}`（許可・明示拒否）
  または `{"outcome": {"outcome": "cancelled"}}` を返す必要がある。旧実装の
  `{"outcome": "allow", ...}` と `option_id`/`outcome` 前提の判定は spec と一致せず、
  permission request で turn が failed していた。
- 選択方針は最小権限（`allow_once` 優先、次に `allow_always`）。詳細は
  [permission-hitl-contract.md](permission-hitl-contract.md) D3 を正とする。

## 実装向け minimum capability（共通）

- `initialize` のprotocol v1合意＋必須capability検証（不一致はprompt前にfailed、暗黙downgradeなし）
- text-only `session/prompt`、`session/update` のtyped正規化（message/tool/plan/usage/unknownの区別）
- `session/cancel` による `cancelled` 終端（`$/cancel_request` は取消手段として使わない）
- process group所有＋終了待機＋orphan検査
- プロダクト質問は `elicitation/form` のみ advertise し、`elicitation/create` を既存 `coding.ask_user` HITL に登録して同一 ACP 接続で応答する（Phase 0 PoC では未観測のため Phase 1 で検証する）
- 再開可否はprofileのpersistence policyで決定（opencode: resume可、codex: 再作成）。`session not found`系の文字列推測をしない

## 再現手順

`tools/acp_poc/README.md` を参照。artifact は `docs/acp/artifacts/<agent>-<version>-<date>/` に保存する。
stderr は redacted diagnostics のみ保存し、秘密値は記録しない。

## Phase 1 live 検証メモ（2026-09-15、ブラウザ経由）

- OpenCode 1.18.31 の ACP profile をブラウザの transport 選択（opt-in）から使い捨て Git
  repository で 2 turn 連続実行。`initialize` → `session/new` → `session/prompt` →
  `session/update` → `end_turn`、2 turn 目は同一 ACP session の resume で継続し、
  `git status` clean のまま完了。spec 形状（`protocolVersion` int、
  `clientCapabilities`、`sessionId/cwd/mcpServers`、prompt blocks）への修正が前提だった。
- Codex ACP の live 実行は未実施（profile のみ実装、resume 不可方針）。
