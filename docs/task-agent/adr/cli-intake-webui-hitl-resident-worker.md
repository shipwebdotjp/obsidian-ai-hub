# CLI投入・WebUI操作・Webサーバー同居worker

## Status

Accepted

## Context

TaskはCLIから素早く投入し、長時間の計画・実行は非同期で進める必要がある。既存のAgent/Coding
workerはFastAPI lifespanに同居し、既存のlaunchd HITL workerは質問回答をdispatchする専用プロセスである。

## Decision

- CLIは `--task-agent TEXT` の投入専用とし、Task IDと詳細URLを返して終了する。
- Task一覧・詳細、Plan承認、差戻し、取消は `/task-agent` のWebUIで行う。
- Task workerはFastAPIの既存worker lifespanに同居し、一度に一Taskを進める。
- Taskの対象解決質問だけは既存HITL基盤を使う。Plan承認はTask APIで直接処理する。
- `--hitl-worker` とlaunchdの構成は変更しない。Webサーバー停止中のTaskはキューに残る。

## Consequences

- 独自の常駐サービスを増やさない代わりに、Webサーバーが稼働していなければTaskは進まない。
- Task専用画面に条件付き差戻し理由を実装でき、既存HITL questionモデルを拡張しない。

## Alternatives

- 専用launchd worker: 常時実行できるが、workerの二重管理とロックが増えるため不採用。
- CLIで承認まで対話する: 長時間Task・モバイル閲覧と相性が悪く不採用。
- Plan承認も既存HITLで扱う: 差戻し理由の条件付き入力を歪めるため不採用。
