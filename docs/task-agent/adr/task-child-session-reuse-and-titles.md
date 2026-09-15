# 同一タスク内の子セッション再利用と内容記述タイトル

## Status

Accepted

## Context

`task_bde93d76a598` では Runtime Orchestrator が `coding_cli` を3回呼び出し、
各回が別Codingセッション (`... step 0/1/2`) になった。初回で実装・テスト・
コミットまで完了していたが、2回目以降は検証目的の再呼び出しだった。
調査で判明した事実:

- 完了結果の伝達自体は機能していた (`capability_completed` の observation が
  次ターンの prompt に入る)。ただし2段階の切詰め (adapter の末尾2000字 +
  prompt の履歴予算) で末尾の完了証拠 (テスト件数・コミットSHA) が落ち、
  Orchestrator が完了条件を確認できず再検証を選んだ。
- `CodingAdapter` / `AgentAdapter` は毎回 `create_session` しており、同一タスク
  でも文脈が引き継がれない。再利用の探索・記録が存在しなかった。
- タイトルは `f"Task {task_id} step {step_index}"` の固定書式で、IDの切出し
  バグはなかった (DB上の3件はいずれも完全な task_id を含む)。
  ただし内容を表さず、backend の自動タイトル生成 (`_should_update_coding_title`)
  は placeholder 以外を上書きしないため、生成もされなかった。

## Decision

- 同一タスク内の追加委譲は、同一対象 (coding: project_id+backend / agent:
  agent_id) の既存セッションを原則再利用する。新規作成は `fresh_session=true`
  の明示要求、既存セッションの不存在・対象不一致・実行中 (busy) の場合のみ。
- 再利用の探索は当該タスク自身の `child_run_started` イベントだけを逆順走査し、
  `session_id` を記録する (旧イベントは `child_run_id` 経由で解決)。他タスクの
  セッションは参照しない。DB schema 変更はしない。
- 新規セッションのタイトルは作業内容由来の30字以内
  (`inputs.task` → step title → plan purpose の順、空のときのみ旧書式) とする。
- 旧 `Task <id> step <n>` 書式は内容を持たないため、backend 自動生成による
  上書き対象に加える (placeholder・空と同等扱い)。内容由来・ユーザー指定の
  タイトルは引き続き保護する。
- Observation の prompt 表示は両端保持の予算方式に変え、完了証拠が
  欠落しないようにする (最新: 先頭500字+末尾1500字、過去: 先頭200字+末尾600字、
  履歴全体の総予算60000字、超過時は最古の action から1行サマリーへ圧縮し
  最新は常に保護)。Adapter の `tail_text` は末尾2000字に拡大。完了判断自体は
  LLM に残し、同一内容の再検証を避ける旨を system prompt に一行追加する
  (独立検証の禁止ではなく抑制)。

## Consequences

- 検証目的の追呼しは同一セッションの次runとして実行され、文脈再構築が不要に
  なる。at-least-once の重複実行可能性は変わらない (既存契約どおり)。
- `coding_cli` / `specialist_agent` の入力 schema に `fresh_session` (既定false)
  が増える。Planner 向け schema 表示にも現れる。
- 旧書式タイトルの既存セッションは、次回 backend 実行時に自動生成で置換され
  得る。ユーザー指定タイトルへの影響はない。

## Alternatives

- 新規セッション時に placeholder を入れて backend 自動生成に完全委譲: 実行
  完了まで内容不明のまま残り、生成失敗時は placeholder が残留するため不採用。
  ただし旧書式の上書き許可により、生成経路自体は温存した。
- 同一Capability連続呼び出しのハード禁止: 実装→修正のような正当な多段作業を
  壊すため不採用。prompt 指導に留める。
- Task↔session の対応表を新設: schema 変更が要るため不採用。既存イベントの
  拡張 (`session_id` / `session_reused` 追加) で足りる。
