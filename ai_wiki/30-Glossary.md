# ドメイン用語集

## AI エージェント

利用者が作成した、システムプロンプト、LLM 設定、利用を許可する登録ツールの組である。ツール実装を任意コードとして保存せず、サーバーが持つツールレジストリの識別子だけを選択できる。

## 会話セッション

一つの AI エージェントとの継続対話。セッションは明示的に削除されるまで保持し、削除時には配下のメッセージと実行記録も削除する。

## 最終表示会話

`/agents` で最後に選択・表示対象となった会話セッション。同一ブラウザプロファイルの `localStorage` に保存し、`session_id` なしアクセス時の会話復元に使う。

## 会話復元

`/agents` を `session_id` なしで開いたときに最終表示会話を再選択する動作。有効な deep link が最優先され、保存値が無効な場合は先頭会話へフォールバックする。

## メッセージ

会話セッションに属する user / assistant の発話。ユーザー入力と、ツール利用後に確定した最終応答を保存する。応答の生成途中のトークン列は保存しない。

## ツールレジストリ

エージェントに公開できる、安全性と引数スキーマがサーバー側で定義されたツールの一覧。エージェント設定はこの一覧からツール ID を選ぶだけで、任意の関数名・URL・コードは登録できない。

## 書込み提案

カレンダーまたはリマインダーへの新規作成を求めるエージェントのツール呼び出し。直接の副作用ではなく既存の HITL Run を作成し、承認後にだけ Apple のデータを変更する。

## Agent Skills (スキル)

エージェントが参照・利用できる手順書（`SKILL.md`）、補助テキストリソース、および直結スクリプトの集まり。1次ルート（`~/.agents/skills`）および2次ルート（`agent_skills.root` / `OBSIDIAN_AI_HUB_SKILLS_DIR`）から自動発見・インデックス化され、同名 Skill は2次ルートが優先される。エージェントが `skills` ツールを選択した際、`load_skill`（手順書取得）、`read_skill_resource`（リソース読取）、`run_skill_script`（スクリプト直接実行）の3ツールに展開される。

## 任意シェル実行 (run_shell)

`agents.registry` にネイティブツールとして登録されたシェルコマンド実行機能。任意シェル実行は有効化したエージェントへアプリ権限で直接与える。エージェント編集画面で明示選択された場合のみ利用可能であり、HITL なしで実行され、`exit_code` / `stdout` / `stderr` / `timeout` を構造化 JSON で返す。

## Coding 単発CLI

`python -m obsidian_ai_hub --coding` による Coding Orchestrator の非対話・単発実行形態。位置引数（複数可）と非TTY stdin を `"\n\n"` で結合した1プロンプトを、`coding_sessions`（新規は `--project-id`、再開は `--resume-session`）へ1ターン送信し、 `coding_messages / coding_runs` に永続化する。通常は最終 orchestrator 応答のみを `stdout`、セッション・run・git_status・進捗は `stderr`、 `--json` 指定時は最終結果の単一JSON（`ok / response / session / run`）を `stdout` に出力する。

## Relation Type (関係タイプ)

2人物間の関係性の分類・方向性・表示ラベル（正方向・逆方向）を定義する台帳レコード（`person_relation_types`）。組み込み型（25件）および利用者が作成するカスタム型が存在し、一意な `slug`、`directionality` (`directed` / `symmetric`)、`forward_label` / `reverse_label` を持つ。

## Person Relation (人物間リレーション本体)

特定の2人物間で、ある Relation Type が成立しているという継続的な状態・構造の主張レコード（`person_relations`）。有向型では正方向（`subject` → `object`）、対称型では端点辞書順に正規化保存される。期間（`started_on` / `ended_on`）とメモ（`note`）を保持し、同一5要素（型・両端点・開始日・終了日）の重複は1件に統合される。

## Relation Evidence (根拠)

特定の Person Relation を登録・採用した根拠情報レコード（`person_relation_evidence`）。1つのリレーションに対して0件以上登録され、由来源種別（`source_type`）、引用文（`quote`）、参照先（`source_ref`）、補足メモ（`note`）、および観測日（`observed_at`）を保持する。

## Person Event / Action (人物イベント／アクション)

特定時点または期間に発生した単発の出来事や行為（例: 「資金を援助した」）。継続的な関係状態である Person Relation（例: 「援助関係にある」）とは区別される概念であり、v1 対象外として将来の拡張領域に位置づけられる。
