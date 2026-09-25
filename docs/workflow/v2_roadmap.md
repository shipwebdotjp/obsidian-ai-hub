# Workflow v2 ロードマップ（拡張余地）

この文書は、実装済みの **`$expr`（型付き日時式）**、**値パイプライン `pipe`**、**`text_template`
Node** で意図的に採用しなかった拡張余地と、Workflow 全体の残バックログを将来候補として
整理する。個別の契約は [specification.md](specification.md) を正本とする。

分類の目安:

- **土台の拡張**: 既存の言語・検証・API を広げるが、後方互換を保ちやすい。
- **再設計が要る**: 出力契約・Node 種別・データモデルを変えるため ADR が必要。
- **運用課題**: 仕様ではなく監視・通知・履歴の不足。

## 1. `$expr`（日時式）の拡張余地

- **`config.<alias>`（非秘密の環境設定参照）** — 前回の変更で意図的に分離した。明示 allowlist・
  参照レジストリ・Run 作成時の固定・Editor への型/説明提供が必要。土台の拡張だが
  セキュリティ境界を伴う。
- **`kind` の追加** — v1 は `date_math` のみ。算術・文字列・条件式を増やす余地は `kind` と
  `version` で確保済み。増やす場合は評価器と検証を別モジュールに分ける。
- **出力フォーマット** — `result` は `date` / `datetime` 固定。`YYYY/MM/DD` などの任意書式や
  ロケール表記は未対応。増やすとパース・検証・Editor が広がる。
- **`$expr` への `pipe` 適用** — 現状は禁止し、日付整形は `text_template.inputs` 経由。式結果を
  その場で `truncate` したい需要が出たら、`pipe` 適用対象を広げる。
- **期間・差分** — `now` と別時刻の差（日数・営業日）や、期間型の生成は未対応。
- **既定タイムゾーン・週開始の Workflow / アカウント設定** — 現状は式ごとの指定と全体既定
  `Asia/Tokyo` / `monday`。設定画面からの既定上書き余地。
- **公開時の範囲検査** — 過大な `math` は実行時 `OverflowError` を `ValueError` 化して失敗する
  （規模の上限は未検証）。公開時に上限を弾くと実行前検証が強くなる。
- **条件 `value` / `from_path` への式** — 現状は値位置のみ。条件式に日時比較を持ち込む余地。

## 2. 値パイプライン `pipe` の拡張余地

- **演算子の追加** — regex 抽出/置換、JSONPath、`map`、`split`、`flatten`、数値・日付の
  フォーマット、`json_parse`/`json_stringify`、`filter` の複合条件（AND/OR）など。
- **静的型推論** — 現状は args を公開時、参照先の宣言型と先頭演算子の入力型（文字列/配列）を
  公開時に、値型を実行時に検証。pipe 途中の型を推論して後続演算子まで公開時に弾く余地。
- **`sort` の日付比較** — `filter` は `as:"date"` を持つが `sort` は辞書順のみ。時系列ソートの
  `as` 追加余地。
- **`$expr` への適用** — §1 と同じ。
- **パイプラインの再利用・ネスト** — 名前付きマクロや、配列要素内の `$ref`+`pipe`。現状は
  値位置に限定し、args への `$ref`/`$expr` ネストは禁止。
- **`config.<alias>` / Run 入力値への適用** — 設定値や手列入力の正規化に使う余地。
- **失敗の粒度** — Loop `input_mapping` / `continuation_condition` の解決失敗は現状 Run レベル。
  Node 粒度に寄せると error Edge が使える。
- **Editor プレビュー** — 実データでの演算結果プレビュー、演算子のドラッグ並べ替え。

## 3. `text_template` の拡張余地

- **構造化出力** — 現状は `output.text`（string）固定。`output_schema` を持つ別 Node 種別に
  すれば、テンプレートで JSON を組み立てて型付きで後続へ渡せる。再設計が要る。
- **テンプレート部品化** — `include` / `import` / macros と loader。現状は loader なしの
  単一本文。共有部品を持たせると revision 間の依存管理が必要になる。
- **sandbox 強化** — 組み込み global（`range` 等）を残している。ループ/コスト上限や
  `range` 除去は、表現力とのトレードオフで判断する。
- **上限の設定化** — 16 KiB / 64 KiB は固定。Workflow 単位で調整できる余地。
- **テンプレート環境オプション** — `trim_blocks` / `lstrip_blocks`、独自フィルター、
  autoescape（HTML/Markdown 出力時）。
- **変数の型宣言** — `inputs` は値のみ。変数ごとの schema を宣言して Editor 補完と検証を
  強くする。
- **Editor プレビュー（実装済み）** — サンプル値での描画プレビューと、変数名・入れ子フィールド
  の補完を実装した（`POST /workflows/text-template/preview` と `TextTemplateEditor` /
  `TextTemplatePreview`）。残る余地はサンプル値の保存と補完対象の拡張（多重 for 等）。
- **通知本文テンプレートへの再利用** — 完了通知 outbox と組み合わせ、本文をこの Node で
  組む設計。

## 4. その他の Workflow バックログ（今回の3機能の範囲外）

- **完了・失敗・承認待ち・HITL の通知 outbox** — Scheduler と組み合わせて無人運用を成立
  させるための運用課題。LINE / Push に Run への深いリンクを付ける。
- **Run 履歴の一覧・絞り込み・Activity 連携** — 監査と復旧のため、状態・期間・Revision・
  再実行元で追えるようにする。運用課題。
- **Agent Node の構造化出力の堅牢化** — JSON 不適合時の限定修復再試行、失敗表示の改善。
- **Loop ネスト / 並列 fork / AND join** — 制御構造の再設計。安全境界と検証が重くなる。
- **Agent Node ごとの prompt / model / tool 上書き** — 承認境界を含む ADR が必要。
- **複雑な JSON Schema（`$ref` / `oneOf` / 再帰）** — 検証器と Editor の再設計。
- **任意コード Node** — v1 では追加しない。追加時は別 ADR と不可逆操作の品質ゲートが必須。
- **Workflow ごとの同時実行数制御・承認待ち Run の抑止/自動失効** — 運用ポリシー。
- **[Capability 入出力契約の段階的厳格化](adr/capability-input-output-contracts.md)** — 全 Capability
  の入力は strict 化し、出力は `structured` / `receipt` / `opaque` を明示する。`calendar_read` /
  `reminders_read` を先例に、後続 Node が実際に参照する読み取り系から schema を拡充する。副作用
  Capability の strict 出力失敗化は、receipt・effect・再試行の契約が揃うまで既定にしない。
- **スターターテンプレートの JSON ファイル化と UI インポート** — User Template の code 定義版。

## 優先順位の目安

1. 運用課題（通知 outbox、Run 履歴） — 無人運用の価値を直接高める。
2. 土台の拡張（`config.<alias>`、`$expr` / `pipe` の演算子追加、Capability 入出力契約の段階的厳格化）
   — 既存契約を壊さずに表現力を足せる。
3. 再設計（`text_template` の構造化出力、Loop ネスト、複雑な JSON Schema） — ADR と
   検証・Editor の作り直しを伴うため、需要が明確になってから。
