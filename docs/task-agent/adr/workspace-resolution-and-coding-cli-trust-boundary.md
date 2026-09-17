# Coding対象解決と既存実行境界

## Status

Accepted

## Context

MVPで副作用を持つTask Capabilityは `memory_propose`、既存Agent、Coding CLIである。Vault直接編集と
外部書込みは扱わないため、全Workspaceを横断する新しいロック機構はまだ不要である。

## Decision

- Coding CLIは、既存Projectの有効な `project_path` だけを対象にし、`validate_git_repo` でGit rootへ
  正規化してPlanへ保存する。
- 対象が一意でなければ既存HITLで質問し、勝手にProjectを選ばない。
- Git書込みの同時実行排他は既存Coding基盤のrepo lockに委ねる。Task共通lockは導入しない。
- Coding CLIと既存Agentの内部権限・Plan逸脱は親Taskでは技術的に保証しない。
- `coding_cli` の子Coding Coordinatorへは解決済みの作業本文 (`inputs.task` または Plan目的) のみを渡し、Task Agent内部構造や逸脱申告プロトコル (`<deviation_request>`) は渡さない。
- `coding_cli` 内部の作業範囲や追加作業の必要性を親が強制・検出せず、通常のCoding結果報告に委ねる。想定外の作業が発生した場合も自動再計画・再承認 (`waiting_reapproval`) は行わず、利用者がCoding結果を確認して必要に応じて新しいTaskとして依頼する運用上の制約とする。
- `specialist_agent` の逸脱申告契約 (`<deviation_request>`) は従来通り維持し、`coding_cli` とは非対称な契約として扱う。

## Amendment: 主対象Projectのconfidence付き解決（Directional Plan v3）

- Taskは「主対象Project 1件」または「一般Task」に分類する。複数repoにまたがる作業は別Taskに分け、
  主対象は常に1件とする。分類は非Coding Taskにも記録するが、実行先制限として使うのは `coding_cli` のみとする。
- PlannerはPlan生成と対象選定を1回のLLM呼出しで同時に行う。Planner contextには各有効Projectの
  名前・キーワード・Git rootに加え、最新3件のCoding sessionの題名と最新user依頼を渡す（各断片redact済み、
  1件300文字・Projectあたり800文字・全体12,000文字で打ち切る）。worker応答や実行ログ全体は渡さない。
- Planner出力の `project_resolution`（kind / project_id / 表示名スナップショット / confidence 0..1 /
  短い根拠 / source）はv3 Planの必須要素とする。`confidence` は統計的確率ではなく、人間への
  質問へ分岐するための判断スコアである。
- 推定scoreが0.75（`TARGET_CONFIDENCE_THRESHOLD`）未満ならPlanは保存せず、全有効Projectと
  「一般Task」を残した既存HITL質問（内部値 `project:<整数ID>` / `general`）へ回す。
  質問文には推定上位候補のscore・根拠を記載する。
- HITL回答またはPlan画面の変更は正規化済みIDを `target_resolution_selected` Eventとして保存し、
  以後の再計画で強制入力にする（人間指定はconfidenceを持たない）。
- Projectを選んだv3 Planの `allowed_project_ids` はそのIDだけにし、Runtimeは範囲外の
  `coding_cli` 実行を拒否する（既存のallowlist検証）。一般TaskのPlanに `coding_cli` は含めない。
- 承認待ちPlan（`waiting_approval` / `waiting_reapproval`）では対象を選び直せる。変更時は現行pending Planを
  `superseded` にし、Taskを `queued` に戻して人間指定を前提に新Planを作る。
- 対象Projectが承認後に削除・Git root不正になった場合、Coding実行前に止めて `waiting_reapproval` にする
  （外部実行なし）。Plan画面から対象を選び直せる。

## Consequences

- Task workerを直列化しても、手動Coding runとの競合は既存repo lockで扱われる。
- 将来Vault/外部書込みを追加する時点で、対象別の共通lockと直接書込みAdapterを設計する必要がある。

## Alternatives

- MVPから共通読取共有/書込み排他lockを作る: 現在の直接書込み範囲には過剰で不採用。
- Project候補や無効pathも対象にする: 誤作用リスクが高く不採用。
- 親側でCLIを完全sandboxする: CLI固有権限と重複し、実装負荷が大きいため不採用。
