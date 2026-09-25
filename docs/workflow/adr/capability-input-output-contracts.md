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

## Related

- [Workflow Graph / Agent Node ADR](workflow-graph-and-agent-node.md#amendment-capability-node-の-strict-出力)
- [ガイド型フォーム ADR](workflow-editor-guided-forms.md#amendment-p1-targetフィールドウィジェット出力スキーマ)
- [Workflow v2 ロードマップ](../v2_roadmap.md)
