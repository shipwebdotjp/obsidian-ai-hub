# Workflow エディタのガイド型フォーム（自前スキーマフォーム）

## Status

Accepted (2026-09-22)。Phase 0〜4 と P0 フォローアップ（スキーマ作成フォーム・
検証ジャンプ・参照ピッカー改善）を実装済み。Capability 出力スキーマの宣言は対象外。

## Context

Workflow エディタの作成障壁は、Capability / Agent の入力、Agent の出力 Schema、
Loop 設定、型付き参照がすべて生 JSON 編集中心であることにある
（[v2_roadmap.md](../v2_roadmap.md) の優先順位 3）。実行入力フォーム
(`InputsSchemaForm.tsx`) もトップレベルのみで、ネストした `inputs_schema` に追従できない。

一方、扱うスキーマは意図的に小さい。

- `inputs_schema` / `output_schema` / `state_schema` は v1 サブセット
  （`object` / `properties` / `required`、primitive、`enum`、配列、
  `additionalProperties`。`$ref` / `oneOf` / `anyOf` / `allOf` / 再帰は検証で拒否）。
- Capability 入力は `tasks/capability_schemas.py` の Pydantic モデルが単一正本で、
  形は平坦（`Optional` は `anyOf:[X, null]`、`Literal` は `enum`、`Dict` は
  `additionalProperties`）。ネストモデルは現状なし。

このため「スキーマから値を入力する」汎用フォームライブラリ（RJSF 等）が解くのは
一層だけで、実際の障壁である **スキーマ作成・リテラル/参照トグル・型付き参照ピッカー・
自由形式 object 編集** はいずれもアプリ固有で自作になる。

## Decision

- **JSON Schema フォームは自前実装する。** 外部フォームライブラリは導入しない。
  v1 サブセットと Pydantic 由来スキーマを1つの正規化表現に畳み、単一のレンダラで扱う。
- **正規化はバックエンドを正本にする。** `tasks/capability_schemas.ui_input_schema()` が
  `anyOf:[X,null]`→`nullable`、`$defs`/`$ref` のインライン解決、`default`/`enum`/
  `description`/制約の抽出を行い、`GET /api/v1/workflows/capabilities` の
  `inputs_schema` として返す。`hitl_wait` は `workflow/capabilities.py` の
  `WORKFLOW_ONLY_INPUT_SCHEMA` に固定スキーマを持つ。未知の形は
  `{"x-unsupported": true}` とし、フロントは生 JSON にフォールバックする。
- **型付き参照は型付き候補ツリーとして一元化する。** `run.inputs.*`、
  `nodes.<id>.output.*`、`loop.state|input|iteration` をスコープ別に列挙し、
  Agent は `output_schema`、Loop / Loop Result は `state_schema`、
  Capability は出力型未宣言のため `.output` 全体のみ、という情報を持つ。
  Edge 条件と Loop 継続条件は同じ候補源を共有する。
- **Capability 出力スキーマは宣言しない。** Adapter 出力は
  `parse_json_object(result.summary)` か `{"summary": ...}` で型が無いため、
  ピッカーは opaque のまま扱う（コード宣言は別 ADR の対象）。
- **Agent Node の `inputs` は自由形式の構造化エディタで編集する。**
  契約上スキーマレスであるため、key/value 行（ネスト可）と各値の
  リテラル/参照トグル、`task`/`context` などのサジェストのみ提供し、
  バックエンドの契約は変更しない。
- 対象スコープは「主要な痛みを深く」: 参照ピッカー、Capability 入力フォーム、
  ネスト対応の値フォーム、Loop 入出力 mapping。

## Alternatives

- **RJSF（`@rjsf/core`）を導入する**: 「スキーマから値を入力する」一層は解けるが、
  スキーマ作成 UI・リテラル/参照トグル（JSON Schema で表現不可）・参照ピッカー・
  自由形式エディタは結局自作になる。依存とテーマ、ajv が増える割に得るものが薄い。
  v1 のサブセットと現行フロントの薄い依存方針に照らして不採用。
- **フルスクラッチのスキーマ作成 UI を同時に作る**: 差し替えコストは高いが、
  v1 ではサブセットが小さいため後続フェーズで追加できる。今回は対象外。
- **Capability 出力スキーマをコードで宣言する**: 参照ピッカーの精度は上がるが、
  全 Adapter の出力契約を定義・検証する横断変更になる。UX 改善とは分離して別途検討。

## Consequences

**利点**

- 作成障壁の大半（入力・出力・Loop・参照）をスキーマ単一正本から生成でき、
  タイポや型不一致が実行前に見える。
- 外部依存を増やさず、Tailwind・日本語ラベル・テスト容易性を維持できる。
- 正規化の正本がバックエンドにあるため、Capability 追加時に UI 変更が不要。

**不利益・コスト**

- 正規化スキーマとレンダラを自前で保守する。Pydantic が新しい形を出した場合は
  `x-unsupported` フォールバックに落ちる。
- 生 JSON フォールバックを残すため、UI は二系統（フォーム/JSON）を持つ。

**リスク**

- スキーマ作成が生 JSON のままなので、参照ピッカーの恩恵は
  `output_schema` / `state_schema` を書けることを前提とする。
  出力 Schema の作成障壁が残る場合は最小のスキーマビルダーを前倒しする。

## Amendment (P0 フォローアップ)

Status: Accepted (2026-09-22)。当初「対象外」としていたスキーマ作成 UI を実装した。

- `SchemaAuthoringForm` / `schemaModel.ts` を追加し、`inputs_schema` /
  `output_schema` / `state_schema` を v1 サブセットのプロパティ行（型・必須・説明・
  `enum`・入れ子 `object`・配列 `items`）で編集できるようにした。生 JSON トグルと
  サブセット検証（バックエンドの `validate_schema_subset` をミラー）を併設する。
- 検証結果（ローカル／サーバー）の行をクリックすると該当 Node / Edge の source Node を
  選択してスクロールする。
- 参照ピッカーを既定折りたたみにし、自由入力が参照形式でない場合の警告、配列 `[0]` 例、
  パスのコピーを追加した。

## 対象外

- Capability 出力スキーマのコード宣言（参照ピッカーは opaque のまま）
- 定義の import / export、ユーザー管理テンプレート、複雑な JSON Schema

## 関連文書

- [../specification.md](../specification.md) §6・§9・§15・§18
- [v2_roadmap.md](../v2_roadmap.md)
- [workflow-graph-and-agent-node.md](workflow-graph-and-agent-node.md)
- [../../../src/obsidian_ai_hub/tasks/capability_schemas.py](../../../src/obsidian_ai_hub/tasks/capability_schemas.py)
