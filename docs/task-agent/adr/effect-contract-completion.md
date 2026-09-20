# 完了を効果契約から導出する

## Status

Accepted

## Context

Directional Plan の実行は、次のActionをLLMが構造化出力する動的ループで行われていた。
完了はLLMが `finish` を発話したときだけ成立し、`max_actions` は無限ループ防止の
上限として定義されていた。しかし `finish` と予算枯渇が完了判定に二重化していたため、
必須Capabilityを実行して目標を達成したにもかかわらず、LLMが枠内で `finish` を選ばない
（例: 最後の1枠を重複した `research_theme_propose` に使う）と `failed` になっていた。

実行器は「目標達成」と「資源枯渇」を区別できず、`completion_criteria` は自然言語の
プロンプト表示のみで実行時に評価されていなかった。新しい形状のタスクごとに
プロンプト規約と専用述語（`_required_proposal_pending` や「提案とfinishの2枠を残す」）を
足す必要があり、対症療法が増え続ける構造だった。

## Decision

- Capabilityは、成功時に成立させる**検査可能な効果**をコードで宣言する
  (`CapabilityDefinition.satisfied_effects`)。読取・検索Capabilityは効果を持たない。
- Planは効果集合を明示しない。承認済みPlanに含まれる効果的Capabilityの効果を
  **必須効果**としてコードから導出する (`get_required_effects`)。PlannerとPlanスキーマは
  変更しない。
- Adapterは `StepResult.satisfied_effects` で実際に成立した効果を報告し、
  Orchestratorは `capability_completed` Event に保存する。再開時はEventから復元する。
- 受理述語は `必須効果 ⊆ 成立効果`。成立した時点で `finish` や残予算を待たずに
  `completed` とする。要約は観測から合成する。
- 必須効果が未達のままの `finish` は完了にせず自己修正させる (既存の上限つき)。
- 予算枯渇は、必須効果が未達なら `incomplete`（失敗ではない）として終端する。
  必須効果を持たないオープンなタスクも、予算枯渇は `incomplete` とする。
- `incomplete` をTaskの終端状態に追加する。

この決定は、仕様の「専用の自動完了・Action強制の例外は追加しない」という旧方針を
明示的に置き換える。

## Consequences

- 「達成済みなのに失敗」は構造的に発生しない。効果が成立すれば自動で完了する。
- 予算は純粋なバックストップに戻り、枯渇は「未完了」として正直に記録される。
- 完了をLLMの自己申告に依存しないため、プロンプト規約と形状別述語の追加が不要になる。
- 効果のないオープンなタスクは従来どおり `finish` で完了する。検証不能な目標は
  `incomplete` またはLLMの `finish` に委ねられ、機械検証の範囲外であることが明確になる。
- 効果述語は必要条件であり、成果の品質判断は依然としてLLMの `finish` と人間に残る。
- `incomplete` はPhase 1では新規Taskでの再試行とし、自動リトライはしない。

## Alternatives

- 予算枯渇を `failed` のままにする: 誤分類が残るため不採用。
- Planに `required_effects` を明示させる: LLMの指定漏れで検証が弱くなり、例外処理が
  増えるため不採用。義務はコード所有とする。
- 効果ごとの検査器をコードで都度用意する（タスク形状ごとの述語）: 未知タスクに対応できず、
  対症療法が増えるため不採用。効果はCapabilityに紐づけて合成する。
