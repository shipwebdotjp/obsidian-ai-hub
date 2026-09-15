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

### D2 — プロダクト判断だけを既存 HITL へ送る

- Agent が要件・仕様・優先順位・受入条件などの判断を必要とする場合、既存 Worker contract の
  `<needs_user_input>…</needs_user_input>` を一つ付けて停止する。
- Coordinator はこの報告を受け、既存の `coding.ask_user` HITL run を作る。人間の回答は永続化され、
  既存の HITL worker が次の Coordinator turn を再開する。
- Agent からの ACP `session/request_permission` や elicitation はプロダクト質問として扱わない。
  これは技術的な実行 UI のための protocol message であり、接続断を越える質問・回答には適さない。

### D3 — ACP Client が宣言する機能を最小にする

- Phase 1 の Client capability は `fs`、`terminal`、`elicitation` を advertise しない。これは
  「アプリのファイル API、アプリの terminal、接続中フォーム UI を Agent に貸さない」という意味である。
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
| プロダクト質問 | Worker の `<needs_user_input>` 報告 | `coding.ask_user` HITL checkpoint → HITL worker / 次の Coordinator turn | HITL 取消は Coding run も cancelled。回答喪失は failed | なし |
| ACP 技術許可 | `session/request_permission` と profile の事前定義 option | request/応答 → run event | option が不明なら failed。HITLにはしない | 許可された場合は Agent の repository 内操作 |
| 取消・復旧 | `session/cancel`、process exit、ACP session ID | 終端 status・diagnostics・旧/新 session ID → 監査 / 次 turn | cancel/切断時に自動 rollback しない | 既存 repository 変更は戻さない |

## Phase 1 の受入条件

- [ ] Codex / OpenCode とも、選択済み Git root で技術作業を操作ごとのアプリ承認なしに完了できる。
- [ ] Worker の `<needs_user_input>` だけが既存 `coding.ask_user` HITL を作り、回答後に Coordinator →
  Agent の順で続行できる。
- [ ] `fs` / `terminal` / `elicitation` 非advertiseでも、Agent の sandbox 内の正常な作業を妨げない。
- [ ] 予期しない ACP permission request は profile の事前定義 option で処理されるか、安全に failed となり、
  プロダクト判断 HITL と混同されない。
- [ ] cancel、切断、Codex の再作成、OpenCode の再開を contract test で確認する。

## 承認

- [x] 承認: Agent の技術的実行を Codex/OpenCode に委任し、プロダクト判断だけを既存 HITL にエスカレーションする（2026-09-15）。
