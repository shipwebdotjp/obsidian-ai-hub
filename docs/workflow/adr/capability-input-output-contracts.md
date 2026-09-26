# Capability 入出力契約の段階的厳格化

## Status

Accepted (2026-09-25)。実装は段階的に行う。

## Context

Workflow の Capability Node は、後続 Node の分岐・加工・副作用の入力になる。現在はすべての
Task Capability で入力モデルを解決して実行時検証しているが、モデルによっては未知キーを拒否せず
捨てる。出力は一部だけ schema を宣言しており、既存の宣言も参照ピッカーの候補を増やす目的が中心で、
全 Capability の成功契約にはなっていない。

すべての入出力を一律に closed schema にすると、`skills`、`custom:*`、外部検索・抽出のような
可変出力まで固定することになる。また、Capability の実行後に検出する出力不一致を副作用 Node の
失敗・再試行に直結させると、外部処理を重複させたり、成立済みの effect を未記録にしたりする。

## Decision

- **入力は原則 strict にする。** コード所有の固定 Capability は Pydantic の入力モデルで未知キーを
  拒否し、実行前に検証する。動的 dispatch は例外ではなく二段階の検証境界とする。すなわち、外側は
  選択子だけを strict に検証し、選択された Skill / plugin ツールは自身の strict な引数 schema で
  検証する。
- **すべての Capability は出力契約クラスを明示する。** クラスは次の3種とし、すべてに詳細 JSON
  Schema を強制しない。
  - `structured`: Workflow が安定したデータとして後続へ渡せる出力。参照ピッカーへ公開するフィールド
    は型と存在条件を schema で宣言する。後続の制御や副作用が依存する成功フィールドは required にする。
  - `receipt`: 書込み・提案・ジョブ登録などの結果。payload 全体ではなく、完了を識別・監査できる
    ID、status、対象などの最小限を契約にする。
  - `opaque`: plugin、Skills、外部 provider など、安定したデータフロー契約をまだ持たない出力。
    型付きフィールド参照は公開しない。実際に summary へ正規化する Adapter 以外には、synthetic な
    `summary` フォールバックも提示しない。
- **出力の strict は closed schema と同義にしない。** `structured` / `receipt` の schema は必要な
  required フィールド、型、必要なら件数・値域を検証する一方、追加フィールドは原則許容する。provider
  の加算的な変更で既存 Revision を壊さず、Workflow が依存する部分だけを契約にする。
- **出力 mismatch の失敗化は段階的に使う。** `fail_on_output_mismatch` は既定 false のまま維持し、
  まず副作用を持たない `structured` Capability で利用する。副作用 Capability は、receipt が
  effect・冪等性・不一致後の停止を正しく表現し、mismatch が自動再試行を誘発しないことを確認するまで
  strict の既定対象にしない。
- **成功・業務エラーの共通 envelope は今回導入しない。** business failure の分岐、retry 意味論を
  全 Adapter / plugin にまたがって統一する必要が生じた時点で、別 ADR として設計する。
  ただし strict（`fail_on_output_mismatch: true`）の Node では、registry tool が失敗を表す
  事実上の共通形であるトップレベル `error` キーを契約違反として Node を失敗させる。これは
  共通 envelope の導入ではなく strict 時の最小規則であり、`error` の分類・再試行・分岐は
  引き続き対象外とする
  ([amendment](workflow-graph-and-agent-node.md#amendment-capability-node-の-strict-出力))。

## Consequences

- Workflow の静的補完と実行時検証は、実際に安全に利用できるデータフローに限定される。`calendar_read` /
  `reminders_read` を先例に、後続 Node が実際に参照する read/search Capability から `structured`
  schema を拡充する。
- 既存の output schema を増やすだけでは不十分である。Capability ごとにクラスを棚卸しし、入力の
  未知キー拒否、公開する出力フィールド、strict を有効にできる実行条件を確認する。
- `opaque` Capability の出力を Workflow の型付きデータフローで使う必要がある場合は、対象 Adapter
  に正規化層と `structured` schema を追加してから公開する。任意 JSON を参照可能にして迂回しない。
- 新規・変更した Capability 契約には、入力の未知キー拒否、成功出力の schema 適合、read-only
  `structured` Node の mismatch が後続へ流れないことを、それぞれの境界で検証する。

## Considered options

- **全 Capability の全 payload を直ちに closed schema にする**: 型付き参照とドリフト検知は最大化
  できるが、外部・plugin 出力の追随コストと後方互換性のリスクが大きく、副作用後の mismatch にも
  不適切であるため採用しない。
- **必要時だけ個別 schema を足す**: 初期コストは低いが、入力の黙殺、存在しない summary 候補、
  データフローで信頼できる出力範囲の不明確さを残すため採用しない。
- **直ちに共通の success/error envelope を導入する**: 業務エラーの分岐には有効だが、Adapter、
  plugin、effect、retry の意味論を同時に移行する横断変更になるため、需要が明確になるまで分離する。

## Amendment (P1 契約台帳と参照境界 + 限定 P2)

Status: Accepted (2026-09-26)。Phase 1 を全面採用し、Phase 2 は高利用・読み取り系
（`vault_read_file` / `calendar_read` / `reminders_read` /
`research_context_snapshot` / `hitl_wait`）に限定して採用する。Phase 3
（副作用 Capability の receipt 解放）は保留する。

### 決定

- **Capability ごとのコード正本を導入する。** 全組込み Capability と
  workflow-only Capability を `structured` / `receipt` / `opaque` に必ず分類する
  （`tasks/capability_schemas.py` の ledger + `workflow/capabilities.py` の
  workflow-only 分）。動的 plugin（`custom:*`、明示的な契約登録のないもの）と
  `skills` は `opaque` とする。
- **参照ポリシーは `structured = strict_fields`、`receipt` / `opaque` =
  `forbidden` とする。** `receipt` の schema は監査・表示用に公開するが、P3 までは
  後続 Node・条件・pipe・テンプレートから参照できない。
- **既存公開 Revision に互換モードを設けない。** 保存・公開・実行の全経路で
  opaque／未検証出力への参照を拒否し、違反のある既存公開 Revision は手動で
  後継 draft を作成・公開してから supersede する。自動変換・自動 publish はしない。
- **静的検証で次を拒否する**（Capability / Agent / LLM / Loop 入力、Edge 条件、
  値パイプライン、`$expr` anchor、Text Template 入力の全経路）。
  - opaque／receipt の `nodes.<id>.output...` 参照
  - 出力全体（`nodes.<id>.output`）への参照
  - 未宣言フィールド、未宣言ネスト、欠落し得る必須でない経路
  - `fail_on_output_mismatch: true` でない structured Node の出力参照
- **`fail_on_output_mismatch: true` は structured の読み取り系と `hitl_wait` に
  だけ許可する。** 書込み・外部操作・receipt での指定は検証エラーにする。
- **P2 の strict 対象を最初に次の 5 つとする。**
  - `vault_read_file`: `relative_path` と `content` を required にする。
  - `calendar_read`: `events` を required にし、各 event の `title` / `start` /
    `end` / `all_day` / `source` を正規化して required にする。Apple と
    recurring の取得状態を `apple_status` / `recurring_status` で明示する。
  - `reminders_read`: `reminders` を required にし、各 reminder の `title` /
    `due` / `source` を正規化して required にする。取得状態も同様に明示する。
  - `research_context_snapshot`: 現行 5 トップレベル値を required にし、下位の
    未契約データは展開しない（ネスト参照は未宣言として拒否）。
  - `hitl_wait.answer`: 人間入力境界で文字列へ正規化・検証する。
- **strict は closed schema 化ではない。** 必要な required field と型・完全性だけを
  保証し、追加フィールドは許可する。部分結果は lenient 実行では観測可能なまま残すが、
  strict Node では契約違反として失敗させ、後続の判断・副作用へ流さない。
- **strict + retry の併用警告は効果的 Capability に限定する。** 読み取り系の
  retry に副作用の重複はないため警告しない。
- **opaque に synthetic summary schema を返さない。** `ui_output_schema` は
  opaque で `null` を返し、参照ピッカーは不適格な候補を表示しない。新規の P2
  Node はエディタで strict を既定オンにする（既存 config の既定値は変更しない）。

### 操作シナリオ契約（不可逆操作: なし — 本 amendment は参照境界の閉鎖であり、
外部書込み・削除・認可変更を含まない）

| 段階 | 入力・識別子 | 停止規則 |
| --- | --- | --- |
| 公開 | revision の Node config と参照 | 契約違反は検証エラーで公開不可 |
| 実行 | strict Node の出力 object | `error` キー・required 欠落・型違い・null・取得不完全は Node 失敗、後続なし |
| 移行 | 公開 Revision の監査 | 違反参照 0 件を確認してから後継へ supersede |

### 残余リスク

- 既存公開 Revision の違反参照は公開時の再検証でのみ検出される。切替前後の
  read-only 契約監査で検出し、手動移行する。
- `periodic_note_read`、人物・Project・検索・Skills・Agent / Coding / Research
  出力は、P2 後の監査結果と利用実績に基づく次の structured 候補とする。

## Related

- [Workflow Graph / Agent Node ADR](workflow-graph-and-agent-node.md#amendment-capability-node-の-strict-出力)
- [ガイド型フォーム ADR](workflow-editor-guided-forms.md#amendment-p1-targetフィールドウィジェット出力スキーマ)
- [Workflow v2 ロードマップ](../v2_roadmap.md)
