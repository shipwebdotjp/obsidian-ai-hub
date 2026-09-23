# Workflow 型付き日時式 (`$expr`)

## Status

Accepted (実装済み)。正本仕様は [../specification.md](../specification.md) §3.6。

## Context

Workflow の入力は型付き参照と固定リテラルのみで、実行時点の日時を扱う手段が無かった。
「今週の月曜〜日曜を `calendar_read` に渡す」のような定番フローが書けず、Scheduler の
固定入力も日付を静的にしか表現できない。既存の型付き参照 `$ref` の意味は変えず、
値の位置に日時式を足す必要がある。

## Decision

- **専用タグ `$expr` を導入**し、`$ref` を使える値の位置でだけ解釈する。通常の文字列や
  `$ref` の意味は変えない（後方互換）。
- **形式は Elasticsearch / Grafana 風のコンパクト列**とし、`kind: "date_math"` /
  `version: 1` で名前空間を固定する。Splunk 互換は対象外（区切り記号・週の意味が異なる）。
- **言語仕様は実装ライブラリから独立**させる。評価器は Python 標準ライブラリの
  `zoneinfo` / `calendar` で実装し、Pendulum などの追加依存は導入しない。compact 式の
  パーサと週・時分秒の floor は自作が必要で、委譲できる範囲が小さいため。
- **基準時刻は Run ごとに一度固定**する。手動 Run は作成時刻、定期 Scheduler は発火枠、
  one-shot は `run_at_utc`（無ければ作成時刻）、Rerun は新規作成時刻。resume・retry・
  attention 再実行は保存済み時刻を再利用する。`workflow_runs.reference_time`（UTC ISO 8601）
  に永続化し、`run.context.reference_time` 参照と `now` anchor の両方の基準にする。
- **Run 入力の式**も許可する。anchor は `now` または `run.context.reference_time` に限定し、
  Node 出力・Loop 状態は参照させない（循環と評価順序の複雑化を避けるため）。
- **JSON Schema `format: "date"` / `"date-time"`** を追加し、anchor と `result` の型検証に使う。
  型検証は schema が既知の位置では公開時、Capability 入力など未知の位置では実行直前に行う。

## Alternatives

- **Pendulum を追加して委譲する**: 月末クランプと DST 正規化は楽になるが、compact 式の
  パース・floor・週開始の式単位指定は結局自作になり、依存と lockfile 更新に見合わない。不採用。
- **構造化された演算配列 (`[{op, unit, amount}]`)**: 検証は楽だが、ES/Grafana 風の既存慣習と
  可読性を優先し、compact 文字列を採用。
- **`config.<alias>` 参照を同時に導入する**: 非秘密設定の allowlist・レジストリ・Editor API を
  伴う独立した変更であり、日時式の動機と直交する。別変更として分離。不採用（本 ADR の範囲外）。
- **基準時刻を都度 `datetime.now()` にする**: 再開・retry で結果が変わり再現性が壊れる。
  固定を採用。
- **Run 入力を式の対象外にする**: Scheduler の固定入力で相対日付を表現できないため不採用。

## Consequences

- 公開済み Revision に `$expr` が埋め込まれるため、言語意味の変更は後方互換性の問題になる。
  `kind` / `version` で将来拡張の余地を残す。
- Run 入力の `$expr` は `inputs_json` にそのまま保存され、実行時に基準時刻で解決される。
  Agent 出力など保存済みの値は式として解釈しない（`allow_expressions` は Run 入力のみ）。
- `$expr` 内の anchor `$ref` は既存の参照 remap（Revision 複製・import・Template）で
  自動的に書き換わる。
- `format` の追加で schema サブセット・検証・Editor の 3 箇所を同期させる必要がある。
