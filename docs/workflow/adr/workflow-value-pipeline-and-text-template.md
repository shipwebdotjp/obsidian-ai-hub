# Workflow 値パイプラインと Text Template Node

## Status

Accepted (実装済み)。正本仕様は [../specification.md](../specification.md) §3.7 / §3.8。

## Context

型付き参照 `$ref` は値をそのまま渡すだけで、参照先の配列から一部を取り出したり、文字列を
整形したりできなかった。また複数値から文章（メール本文・レポート・プロンプト）を組み立てる
手段が無く、各 Capability / Agent に前処理を押し付けるか、Agent に丸投げするしかなかった。
`$expr` で日時は作れるが、文章化は対象外である。

## Decision

- **値パイプライン `pipe`**: `{"$ref": ..., "pipe": [...]}` として `$ref` の値位置に限定して
  導入する。演算子は `upper` / `lower` / `truncate` / `slice` / `replace` / `pluck` / `join` /
  `default` に限定し、args のキー・型・範囲を公開時に、入力値の型を実行時に検証する。pipe は
  任意の JSON 型を返しうる（`slice`/`pluck` は配列）。
- **`$ref` の意味は変えない**: `is_reference` は厳密な `{"$ref": str}` のまま維持し、
  `reference_path` / `reference_pipe` を併設する。`$expr.anchor` は bare `$ref` のみ許可する。
- **`text_template` Node**: `inputs` と Jinja2 `template` から `output.text`（string）を生成
  する純粋 Node。`SandboxedEnvironment`（loader なし・独自 global なし・StrictUndefined・
  autoescape なし）で描画し、テンプレート 16 KiB / 出力 64 KiB を上限とする。公開時に構文と
  `inputs` に無い変数を検証し、実行時も StrictUndefined で失敗させる。
- **失敗は Node 単位**: 参照・pipe・日時式の解決失敗とテンプレート描画失敗は、対象 Node を
  `failed` にし、error Edge があればそこへ進める（外部呼出前）。既存の未解決 `$ref` も
  この経路に寄せた。Loop の `input_mapping` / `continuation_condition` の解決失敗は Run レベルの
  ままとする（値位置として pipe は書けるが失敗粒度は粗い）。
- **依存**: Jinja2 を直接依存として追加する（transitive には既に存在）。
- **承認境界は不変**: `text_template` は effects も外部副作用も持たず、`requires_approval` の
  対象外とする（Agent / `plan_required` Capability の判定は変えない）。

## Alternatives

- **参照ごとの加工を Capability 側に持たせる**: 各 Adapter に前処理を足すと、加工ロジックが
  ドメインサービスへ散らばり、Workflow のデータフローが読めなくなる。不採用。
- **文字列テンプレート展開を `$ref` 内に埋め込む**: 型が失われ、参照と加工の境界が曖昧に
  なる。JSON 構造を保つ `pipe` を採用。
- **pipe を `$expr` にも付ける**: 日時式の出力整形は `text_template.inputs` で足り、`$expr`
  の評価器と言語を複雑にしないため見送り。
- **Jinja2 を通常 Environment で動かす**: テンプレート作成者は信頼済みだが、Agent 出力を
  変数に取るため sandbox を維持する。組み込み global（`range` 等）は残し、出力上限で
  DoS を緩和する。
- **別のテンプレート言語（Mustache 等）**: 条件・ループ・フィルターの表現力と実績で Jinja2
  を採用。

## Consequences

- 公開済み Revision に `pipe` と `template` が埋め込まれるため、演算子意味・テンプレート言語の
  変更は後方互換の問題になる。`op` 名と上限で拡張余地を残す。
- `pipe` の静的検証は args の形までで、途中の型整合は実行時検証のみ。誤りは Node 失敗として
  表面化する。
- `text_template` の出力は schema の無い string 固定。構造化出力が必要になった場合は別途
  `output_schema` を持つ Node 種別として再設計する。
- `calendar_read` / `reminders_read` の出力 schema に event/reminder のフィールドを追加し、
  参照ピッカーと `pluck` が guided になった。

## Addendum: `filter` / `sort` / `unique`（追補）

予定・リマインダーの取得結果から「必要なものだけ」を決定的に後続へ渡す需要に対し、`pipe` に
`filter` / `sort` / `unique` を加算的に追加した（`op` 名と上限で拡張余地を残した当初方針の
範囲内で、既存 Revision の意味は変えない）。

- `filter` は単一述語 `{key, op, value}`（`op` 既定 `eq`）に限定する。`as:"date"` で比較系
  `op` を時系列比較にでき、パース不能は Node 失敗。対象 `key` の無い要素は除外する
  （`pluck` の失敗方針とは意図的に分ける）。
- `sort` は安定ソート・`null` 末尾。要素型が混在する場合は決定性のため失敗とする。
- `unique` は最初の出現を保持し、`key` 省略時は JSON 正規化で同一性を判定する。
- 静的検証に、参照先の宣言型と先頭演算子の入力型（文字列 / 配列）の突き合わせを追加した。
  pipe 途中の型推論は行わず、不透明な位置は実行時検証のままとする。
- 複合条件（AND/OR）、`sort` の `as:"date"`、`map` / regex / JSONPath は将来候補とする
  （[../v2_roadmap.md](../v2_roadmap.md) §2）。
