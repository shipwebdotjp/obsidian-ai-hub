# GoalをProjectから分離し、コーチ履歴を時系列で保持する

## Status

Accepted

## Context

長期目標コーチは、仕事や作業対象を表す既存Projectとは異なり、人生上の方向性・学び・
あり方も扱う。ユーザーは、現在のFocusだけでなく、何を選び、どう調整し、何を学んだかを
後から振り返れることを求める。

## Decision

- Long-term Coach は Goal、Focus、Weekly Reflection を所有する独立した集約とし、
  `projects.goal` を再利用・移行しない。
- Focus は一つの Goal に属する。Goal ごとに現在扱う Focus は一つとし、選択、継続、
  縮小、変更、休止は時系列で残す。
- Weekly Reflection は、その週にユーザー自身が記録した取り組み、難しさ、気づき、
  Focus Decision を保持する。Goal と Focus の現在の表現を後から編集しても、
  過去の選択と振り返りを Coach Thread から失わせない。
- Reflection 本文（取り組み、難しさ、気づき、次週の範囲）は作成後も自由に変更・更新可能とする。
  ただし、選択された週・Focus・決定種別（continue / narrow / change / pause）・切替先 Focus は
  保存後に変更不可とし、その時点の Focus 選択・決定イベント（Coach Thread Event）と表示名スナップショットを
  不変の時系列履歴として保持する。
- Phase 1 は手動の Web 内週次 Reflection に限定し、Project/Task/活動履歴からの推測、
  Scheduler、外部通知を使わない。

## Consequences

- SQLite migration と Coach 専用の API/UI が必要になる。
- 将来 Project と関連付ける場合も、Coach が Project を所有せず任意参照として追加する。
- Phase 2 以降の Experiment は Focus に結び付けられるが、Phase 1 の履歴モデルを
  置き換えない。

## Alternatives

- `projects.goal` を Goal として使う: 作業対象と長期のあり方が混ざり、Project の状態遷移や
  要約連携にコーチの意味を持ち込むため不採用。
- 現在の Goal/Focus だけを保存する: Focus の変更理由や学びを失い、長期的な振り返りを
  支えられないため不採用。
