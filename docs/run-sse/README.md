# Run 実行の接続分離と再接続可能 SSE

ブラウザ接続から独立して Agent / Coding の run を実行し、SSE で購読・再接続する仕組み。
実装は完了しており、判断理由は
`ai_wiki/10-Decisions-Web.md`「ブラウザ接続から分離したRun実行と再接続可能SSE」を正とする。

## 契約の要点

- run 開始と購読を分離する。開始 API は `202` と run を返し、`Idempotency-Key` の再送を受理する。
- `GET .../runs/{run_id}/events` は `Last-Event-ID` 以降を昇順 replay し、heartbeat を送り、終端で close する。
- イベントは永続行と同じ payload を `id:` 付きで送る。`text_append` は 250ms / 約4KB で集約する。
- 単一 active run 制約を session 単位で持つ。非終端 run がある session の削除は拒否する。
- アプリプロセス存続中の exclusive lock と `instance_id` による claim を行い、shutdown で自インスタンスの
  非終端 run のみ `interrupted` 化する。再起動後に自動再実行はしない。
- cancel は run 単位の状態遷移へ接続する。subscriber の切断は run を変更しない。
- フロントは `sessionStorage` に最終適用イベント ID のみをキャッシュし、`text_append.delta` を
  append-only で復元する。

## 未実装・保留

- OS 強制終了後に残った CLI 子プロセスの検出・終了。追加する場合も PID / process group の所有性確認
  なしに kill しない。

## 検証

`tests/test_run_sse_*.py`（store / agent api / coding api / worker）と
frontend の `runSse.test.ts` 系で、切断・再購読・冪等性・startup/shutdown・取消を検証する。
