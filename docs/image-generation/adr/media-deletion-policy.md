# 生成メディアの削除ポリシー（親連動削除 + 手動削除）

## Status

Accepted (2026-09-26)

## Context

`image_generate` / `image_edit` は `generated_media` に行と出力ディレクトリのファイルを残す。
削除経路がないため不要なファイルが増え続ける。一方で、同じ画像は `content_sha256` で1行に
集約され、生成物が別の編集の `source_media_id` として再利用されることもある。親（会話 /
Task / Workflow 実行）を消しても安全に消せる単位を決める必要がある。

既存の親削除経路:

- 会話: `agents.store.delete_session`（`agent_messages` / `agent_runs` は FK CASCADE だが
  `generated_media` は FK なし）。
- Task: `tasks.store.purge_terminal_tasks`（終端 Task を既定30日でパージ）。
- Workflow: `workflow.store.delete_run`（終端 Run を削除）。
- `generated_media` は Workflow 実行 ID を持っていなかった（bridge Task の `task_id` のみ）。

## Decision

1. **正本と識別子**: 削除は `generated_media` の行を正本とし、行の `relative_path` を
   containment 済みで解決してからファイルを削除する。クライアントは `media_id` のみ指定する。
2. **親連動削除**: 会話セッション削除 / 終端 Task パージ / Workflow 実行削除に連動して、
   **その親の `source='generated'` の行とファイルだけ**を削除する。
   - 入力（`source='upload'` / `'import'`）は共有・再利用され得るため**残す**（手動削除に委ねる）。
   - 時間ベースの保持期間設定は設けない（親の既存ライフサイクルに合わせる）。
3. **Workflow 紐付け（R4）**: `generated_media.workflow_run_id` を追加（migration v68）し、
   Workflow の bridge Task から実行 ID を trusted ctx 経由で伝播して記録する。
   これにより Workflow 実行削除時にその実行の生成物を正確に消せる。
4. **手動削除**: `DELETE /api/v1/media/{media_id}` で任意の行（入力含む）とファイルを削除する。
   未知 id は 404。ギャラリー（R2）の削除 UI は後付け。
5. **失敗時（best-effort）**: 先にファイルを unlink（欠落・失敗はログして継続）し、その後に行を
   削除する。親の削除はメディア処理の失敗で止めない。クラッシュ時は行が欠落ファイルを指し
   配信が 404 になるだけで、孤児ファイルより安全側に倒す。
6. **孤児ファイル回収は今回見送り**。未参照ファイルの走査削除は命名規則・経過時間などの
   安全条件と合わせてギャラリー/保守ジョブと同時期に検討する。

## Operation-scenario contract

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 手動削除 | client の `media_id` | DB 行が正本 | 行 + ファイルを削除 | ギャラリー/UI | 未知 id は削除せず 404 | ファイル/行の削除 |
| 親連動削除 | 親 ID (`session_id`/`task_id`/`workflow_run_id`) | 親 ID | `source='generated'` の行 + ファイルのみ | 親の削除処理 | ファイル欠落/unlink 失敗はログして行削除は継続 | ファイル/行の削除 |
| 再実行 | 同一削除の再実行 | 同上 | 変化なし | 同上 | 行が無ければ何もしない (冪等) | なし |

## Alternatives

- **親に紐づく全メディアを削除**: 入力も消えて共有先のカードが壊れるため不採用。
- **参照カウント/所有者モデル**: 安全だがスキーマと全保存経路の変更が重く、単一ユーザーでは
  過剰。将来、複数親での共有が問題化したら再検討する。
- **時間ベース保持**: 実装は単純だが「親と同じタイミングで消す」方針に反し、Task の既存パージと
  二重管理になるため不採用。
- **行削除を先に行う**: クラッシュ時に孤児ファイルが残るため、ファイル先行を採用。

## Consequences

- 会話/Task/Workflow を消すと、その生成物も消える。長く残したい成果物は Vault へコピー（R6）。
- 入力（アップロード/取込）は親を消しても残る。手動削除で明示的に消す。
- 親の削除トランザクション内で行を削除するため、行削除はロールバック可能。ファイル unlink は
  ロールバックできない（best-effort）。
- 孤児ファイルは当面残り得る（回収は将来の保守処理）。
