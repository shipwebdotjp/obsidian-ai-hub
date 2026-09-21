---
sidebar_position: 6
title: Run・承認・復旧
---

# Run・承認・復旧

## Run を作成する

Run は **`published` Revision からのみ** 作成できます。
エディタの **実行入力** に値を入れて **実行** を押すか、API の
`POST /api/v1/workflows/revisions/:revision_id/runs` を使います。

入力は Revision の `inputs_schema` で検証されます。

## 承認

次のいずれかを含む Run は、作成時に `waiting_approval` になります。

- 承認ポリシーが `plan_required` の Capability Node
- **Agent Node**（Agent を含む Run は常に承認が必要）

Run 詳細（`/workflows/runs/:runId`）で **承認** を押すと `queued` になり、実行が始まります。
`auto` Capability だけの Run は承認なしで実行されます。

:::warning[Agent の権限は実行時点の設定です]
Agent Node は実行時点の最新の Agent 設定（system prompt・model・許可ツール）で動きます。
承認 UI は「現在および将来の Agent 権限で実行される」ことを前提として扱ってください。
開始時の設定指紋は `workflow_events` に記録されます。
:::

## Run 詳細の見方

| セクション | 内容 |
| --- | --- |
| ヘッダー | Run ID と状態。状態に応じた操作ボタン。 |
| 概要 | 作成日時、結果要約、エラー要約、実行入力の JSON。 |
| グラフ | 実行時スナップショットの読み取り専用グラフ。Node ごとの状態表示と実行回数。 |
| Node | 選択中 Node の `status` / `attempt` / 出力（またはエラー）。未選択時は全 Node。 |
| Events | 追記のみの監査イベント一覧。 |

### グラフ表示とノード選択

- グラフは Run 作成時の `graph_snapshot` を使った読み取り専用表示です。ドラッグや編集はできません。
- 各 Node の状態は、その Node の最新 Activation の最後の `attempt` から決まります（retry や Loop 反復を含みます）。
- 1 つの Node が複数回実行された場合（Loop・再実行）は実行回数を表示します。
- Node をクリックすると、その Node だけの Activation・`attempt`・出力／エラー履歴に絞って表示します。完全な Node ID は選択詳細に表示されます。「選択を解除」で全 Node の履歴に戻ります。
- 条件分岐で通過した Edge は記録されないため、Edge は定義どおりに表示し、通過状態の強調はしません。
- スナップショットを持たない旧 Run ではグラフを表示せず、従来どおり全 Node の履歴を表示します。

進捗は SSE（`GET /api/v1/workflows/runs/:run_id/stream`）で自動更新されます。
切断時は last-event-id により差分から再開し、完了・待機状態に達するとストリームは閉じます。

## 状態に応じた操作

| Run 状態 | 操作 |
| --- | --- |
| `waiting_approval` | **承認** |
| `interrupted` | **再開** |
| 非終端 | **取消** |
| `waiting_attention` | **採用して続行** / **再実行** / **失敗として処理** |
| 終端（`completed` / `incomplete` / `failed` / `cancelled`） | **再実行**（Rerun） |

### 取消（キャンセル）

- `queued` / `waiting_approval` / `waiting_hitl` / `waiting_attention` なら即時に `cancelled`。
- `running` なら `cancelling` を経て協調的に `cancelled` へ。
- **実施済みの副作用は巻き戻しません**（自動ロールバックは行いません）。

### 中断と再開

- Web サーバー（worker）停止時、その instance が所有する `running` / `cancelling` Run は `interrupted` になります。
- `waiting_approval` / `waiting_hitl` / `waiting_attention` は維持されます。
- `interrupted` は自動再実行されません。**再開** で `queued` に戻します。
- 完了済み Node は Activation 単位で重複実行されません。

### HITL 待ち

- `hitl_wait` Capability は HITL へ質問を登録し、Node を `waiting_hitl`、Run を `waiting_hitl` にします。
- worker の claim は解放されます。回答は既存の **確認待ち**（`/hitl`）画面で行います。
- 回答後、回答値が型付き出力として返り、Node は `succeeded` になります。

### needs_attention（非冪等 Node の中断）

Agent / Coding などの非冪等 Node が外部操作中に中断すると、自動再開せず次の状態になります。

- Node: `needs_attention`
- Run: `waiting_attention`

人間は次のいずれかを選びます。

1. **採用して続行** — 子 Run が実際に成功済みで、出力 schema と Effect を再検証できる場合のみ有効。
2. **再実行** — 新しい Activation として再実行する。重複副作用の可能性がある。
3. **失敗として処理** — error Edge があればそこへ進み、なければ Run を `failed` にする。

### 再実行（Rerun）

終端 Run は、その `graph_snapshot` と `inputs` を引き継いだ新しい Run として再実行できます。

- 元 Revision が `superseded` でも、スナップショットを複製するため再実行できます。
- **再実行** を押すと入力フォームが開きます。入力は上書きでき、`inputs_schema` で検証されます。省略時は元 Run の入力をコピーします。
- 承認要否はスナップショットの Node 集合から再判定されます。
- 新しい Run は `source_run_id` で元 Run を参照し、`run_rerun_created` イベントが記録されます。
- 非終端 Run は再実行できません（`409`）。

## 保持期間と機密情報

- 終端 Run とその Node・Activation・Event は **30 日後** に削除されます。非終端 Run は削除されません。
- 入力・出力・エラーは既知の設定済み秘密値を redact して保存します。
- **Run 入力に API キーなどの秘密値を入れないでください。** 資格情報は Capability 側で実行時に注入されます。

## worker の動作

Workflow worker は Web サーバーの FastAPI lifespan に同居します。
**Web サーバー停止中は新しい Run の実行が進みません。** 再起動後に **再開** してください。

## 次に読む

- [テンプレート](templates.md)
- [制約とトラブルシューティング](limits.md)
