# 子runのHITL待ちとTask待機の連携

## Status

Accepted

## Context

子 Coding/Agent run は ask_user で `waiting_user` になり、HITL 回答後に再開
できる（`coding.ask_user` / `agents.ask_user` ハンドラが `queued` へ戻す）。
Task Adapter は子 run を `wait_for_child_run` でポーリングするが、以下が
未整備だった:

- `waiting_user` も実行タイムアウト (30分) の対象で、回答待ちが長いと Task
  が `failed` になる一方、子 run は生き残り、回答後に誰も見ない孤児 run が
  完走する。
- Task キャンセル時の子 cancel 要求は `cancelling` にするだけだが、
  `waiting_user` の run には稼働中スレッドがなく、誰も `cancelled` へ遷移
  させない。Adapter は終端を待ち続け、結局タイムアウトする。
- 子 run の質問待ちが Task 側に記録されず、Task 詳細画面から HITL へ辿れない。

## Decision

- `wait_for_child_run` に `waiting_statuses` を導入し、`waiting_user` の間は
  実行タイムアウトの期限を更新し続ける（回答待ちは免除）。回答後の実行には
  改めて全予算が付く。Task の `cancelling` 検出は従来どおり毎 poll 行う。
- 初回の waiting 検出で `on_first_wait` を一度だけ呼び、Adapter が Task に
  `hitl_question_asked` イベント（`child_run_id` + `hitl_run_id`）を追記する。
  Task 詳細 UI は同イベント型を汎用描画（HITL リンク＋回答カード）できるため、
  フロント変更は不要。
- Task キャンセル時の子 cancel は、子 cancel 要求に加えてリンク先 HITL run
  を `hitl.service.cancel_run` で取り消す。HITL 側が checkpoint の
  domain/run_id で子 run を `cancelled` へ同期する実装済み経路を使う。
  回答済み後の再キュー拒否ガード（既存）と合わせ、cancel が回答で上書き
  されることはない。

## Consequences

- 回答待ちは無期限になる（Task キャンセルでのみ中断）。サーバー再起動時の
  `interrupted` 化の既存挙動は変わらない。
- `hitl_question_asked` は従来の対象解決質問と同一型を使う。Task 詳細の質問
  カードは最新の同型イベントを拾うため、子 run の質問にも回答 UI が出る。
- cancel 経路が子 run を1回余分に読む（HITL リンク取得）。既存テストの状態
  キューを1件増やして対応。

## Alternatives

- waiting 専用の長い固定タイムアウト（例: 24時間）: 期限自体は残るため不採用。
  回答待ちは人間の応答時間に依存し、期限の正当化ができない。
- 子 run の `user_question` を Task worker が別スレッドで監視: 直列 worker の
  設計と衝突するため不採用。poll ループ内の検出で足りる。
- HITL run への Task 側リンク表を新設: 既存イベント拡張で足りるため不採用。
