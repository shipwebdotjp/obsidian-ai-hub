# Workspace 解決とコーディング CLI の信頼境界

## Status

Accepted

## Context

タスクの作用対象をどう決め、どう権限を与えるかを決める必要がある。
既存 AI Hub には (a) config.yml 登録の Vault、(b) projects テーブルの確定済みプロジェクト
(`project_path` は nullable、status は inquiry/active/paused/completed/cancelled)、
(c) coding backend の `validate_git_repo` (Git ルートへの正規化) がある。

また、コーディング CLI (Codex/OpenCode) は自身の設定 (`coding.cli` 等) で実権限を持ち、
親プロセスからその作用範囲を技術的に拘束する仕組みを持たない。

## Decision

- **Workspace 解決規則**:
  - Vault は `config.yml` に登録された Vault を対象とする。
  - Git リポジトリは、既存の確定済みプロジェクトのうち**有効な `project_path` を持つもの**のみ対象。
    未解決候補 (project_candidates) やパスなしプロジェクトは対象外。
    `project_path` は既存 `validate_git_repo` で Git ルートへ正規化して使う。
  - 自由文から対象を一意に特定できない場合、**勝手に選ばず WebUI の HITL で質問する**。
- **権限**: Vault と登録済み Git リポジトリに**共通権限**を適用する
  (読取・作成・編集・削除・コマンド実行)。権限の細分化は MVP ではしない。
- **コーディング CLI の信頼境界**: 実権限は CLI 固有設定を信頼し、
  **親オーケストレーターによるサンドボックス保証は MVP では行わない**。
  CLI の対象外パス作用や削除禁止を親側で技術的に保証しないことを、脅威・制約として明記する。
- 同一 Workspace への書込みは排他ロック、読取同士は並列可。ロック待ちは `waiting_lock` 状態。

## Consequences

- 委譲先 CLI が計画外のパスへ作用したり削除を行ったりする残存リスクを、ユーザーが受容する構成になる。
  緩和は CLI 固有設定 (approve モード等) と計画承認・トレース監査に委ねる。
- 対象解決の曖昧さは HITL 質問に落ちるため、誤った Workspace への自動実行は起きにくい。
- projects の status/`project_path` 運用 (確定済みかつパス設定済み) がタスク対象の品質を決める。

## Alternatives

- **親側サンドボックス (パス許可リスト・ファイルシステム監視)**: 技術的に堅牢だが、
  macOS での実装コストと CLI との干渉が大きく MVP を超える。将来課題として記録。
- **未解決候補・パスなしプロジェクトも対象にする**: 対象の信頼性が保証されず、誤作用の恐れ。不採用。
- **Workspace ごとに異なる権限レベル**: MVP では権限管理コストに見合わない。不採用。
