 # 汎用・複数質問対応HITL基盤MVP

  ## 概要

  SQLiteを正本にした内部Pythonエージェント向けHITL基盤を作る。Runは複数の質問セットを順に持て、各セットの必須質問が回答済みになった時だけ再開可能にする。最初の実利用は自動生成されたリサーチ提案で、手動指定のリサーチや記憶管理は変更しない。

  ## コア基盤と永続化

  - hitl サブパッケージを追加し、以下の汎用操作を提供する。
      - Runと質問セットの原子的な登録／中断
      - 質問回答、Run取消、回答済みRunのclaimと再開
      - checkpoint更新と、登録済みhandlerへの回答マップの受け渡し

  - DBをv13へ移行する。
      - hitl_runs: run_id、agent_name、handler_key、Runのtitle/description、status、opaqueなcheckpoint_json、active_question_set_id、lease/claim情報、試行回数、エラー、日時。
      - hitl_questions: question_id、run_id、question_set_id、Run内で一意のquestion_key、sequence、required、title/prompt、汎用context_json、options_json、answer_json、status、expires_at、日時。
      - 制約は (run_id, question_set_id, question_key) を一意にし、Run : N Questionかつ同じRunの複数回中断を許容する。

  - checkpointはHITL基盤ではJSON blobとしてのみ扱う。handler名はRun列で管理し、checkpointの意味・入力・副作用記録は各機能側が所有する。
  - 回答は {option_id, comment?} を質問行へ一度だけ保存する。option_idは質問の選択肢に存在する値のみ許可する。
  - 質問セットを登録するとRunはwaiting_for_humanになる。必須質問がすべて回答済みになるとready_to_resumeへ遷移する。
      - 任意質問は再開を妨げず、dispatcherがRunをclaimする際に未回答分をskippedとして確定する。
      - 取消はRun単位のみ。Runをcancelledにし、active setの待機質問をすべてcancelledにする。質問単位の取消UI/APIは作らない。

  - Run状態は waiting_for_human → ready_to_resume → running → completed とし、failed / cancelled を持つ。handlerが次の質問セットを登録して再中断した場合、dispatcherは完了にせず新しい待機状態を維持する。
  - expires_at はnullableで保存するが、期限切れ処理・通知・Webhook・Outbox・外部エージェント用HTTP作成APIはMVP外とする。notify_atなど、意味が未確定な列は追加しない。

  ## 再開と依存方向

  - CLIに --hitl-dispatch を追加し、ready_to_resumeのRunを原子的にclaimしてhandlerを実行する。既存タスクスケジューラのプリセットにも追加し、手動または定期実行できるようにする。
  - lease切れのrunning Runを回収し、プロセス終了後にも再開できるようにする。handlerはcheckpoint内の処理済み記録を確認して再実行可能にする。
  - handlerは answers_by_question_key とcheckpointを受け取り、完了または次の質問セットへの中断を返す内部契約とする。
  - HITLコアはresearch等の機能モジュールをimportしない。各機能が自身のhandlerを登録し、アプリケーションのcomposition rootが登録を組み立てる。一方向の「機能 → HITL」依存を維持する。
  - Run・質問セット・回答の登録は、必要に応じて呼び出し側のDB接続を受け取れるようにし、ドメイン状態とHITL待機状態を単一トランザクションで確定する。

  ## リサーチへの最初の適用

  - --suggest-research-theme の自動提案だけをHITL対象にする。
      - 重複でない候補テーマの作成、research.run_approved_suggestion Run、承認／却下質問セットを同一トランザクションで登録する。
      - 承認時はテーマをapprovedにし、checkpointへjob IDを保存して調査を実行、成功結果をVaultへ保存してRunを完了する。
      - 却下時はテーマをrejectedにし、調査jobを作らずRunを完了する。

  - CLIでの明示テーマ追加、Webの新規リサーチ、--research-agent、既存の再実行は従来どおり即時開始し、成功時はVaultへ自動保存してapprovedにする。
  - research_jobsには出力先と公開完了を記録する列を追加する。job ID由来の決定的な出力先を使い、dispatcher回収時も二重のVault出力を作らない。
  - 既存のリサーチ候補の直接「承認／却下」UIと対応APIを廃止し、自動提案の回答はHITL質問キューに一本化する。

  ## API・Web UI・検証

  - 読み書きAPIは GET /api/v1/hitl/runs、Run詳細、質問回答、Run取消を追加する。Run／質問の外部作成APIは追加しない。
  - Reactに独立した「確認待ち」画面を追加する。
      - Run単位の説明と、質問セット内の設問を順番に表示する。
      - リサーチ固有の項目を持たず、title/prompt/options/contextを汎用描画する。
      - 各設問は選択肢必須・コメント任意とし、Run取消とリサーチ画面からの導線を提供する。

  - DB移行、質問セットの原子登録、必須／任意質問、取消、回答競合、次の質問セットへの再中断、lease回収をテストする。
  - リサーチの承認・却下・失敗回復・出力冪等性、自動提案だけが質問化されること、手動経路が即時実行されることをテストする。
  - API認可、Reactの質問セット回答導線、E2Eの主要フローを追加し、uv run pytest tests/ と make test-e2e を実行する。
  - 設計判断を ai_wiki/10-Decisions.md に記録する。

  ## 前提

  - 回答は選択肢＋任意コメントのみで、自由記述をLLMが解釈して制御する方式は採らない。
  - 回答履歴の改訂、質問単位の取消、期限切れの自動解決、通知・外部連携は後続段階で追加する。