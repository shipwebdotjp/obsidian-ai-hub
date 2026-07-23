---
title: Human in the loop向けAI質問キューと人間承認インターフェース設計調査
status: researched
generated_at: 2026-07-11T09:03:08.543095+09:00
source: gpt-researcher
output_style: long
---

## テーマ
Human in the loopの、人間による確認、選択を行う部分のインターフェース設計について。AIがタスクを進めていく上で、どうしても人間に判断を仰がないといけない部分が出てくる。いろんなAIから来る質問を一元管理して質問をキューイングしておいて、それを何らかの形で人間に通知する。デスクトップの通知であったり、ウェブ版のダッシュボードであったり、あるいは電話、メールとかLINEとかでも、メッセージングアプリでも方法は問わない。で、まあ、人間がそれに返答して、構造化したものを保存しておく。質問を投げたAIはフックやポーリングなどでその返答を受信して、処理を再開、継続進めていく。そういうことを実現できる枠組みというかプロトコルってあるんだろうか。もしくは実装例があるのか、実例や関連技術を、調査したい。

## 調査結果レポート
# Human-in-the-loop判断インターフェースの設計と実装技術調査：AIからの質問を一元管理し、人間の回答でワークフローを再開する枠組み

## 要約と結論

AIエージェントが自律的にタスクを進めるほど、「この操作を実行してよいか」「どちらの案を選ぶか」「不足情報を人間に確認したい」といった判断待ちが頻発する。質問者が想定しているような、複数AIからの質問を一元的に受け取り、キュー化し、人間に通知し、構造化された回答を保存し、AI側がフック・ポーリング・シグナル等で受け取って処理を再開する仕組みは、すでに複数の形で実装されている。

ただし、2026年7月時点での私の判断は明確で、**「Human-in-the-loopのための単一の業界標準プロトコル」はまだ存在しない**。一方で、実務上はかなり収束した設計パターンがある。中心になるのは、次の4要素である。

1. **AI側の中断・再開機構**  
   durable workflow、checkpoint、hook、signal、request/responseなど。
2. **人間判断のキュー**  
   pending / approved / rejected / expired のような状態を持つ永続ストア。
3. **通知・入力インターフェース**  
   Webダッシュボード、Slack、メール、LINE、デスクトップ通知、電話などのチャネル。
4. **構造化レスポンスと監査ログ**  
   JSON Schema、承認／却下／選択肢／自由記述、実行前後の記録、idempotency key。

特に注目すべき実装技術は、Microsoft Agent Frameworkの`RequestInfoEvent`とtool approval、Workflow SDKのtyped hook、TemporalのSignals / Queries / durable execution、AWS Bedrock AgentCore周辺のHITLパターン、そしてNylasのようなファイルベースのレビューキューである。小規模な個人開発なら「SQLite + Web UI + Slack/メール通知 + polling API」でも十分実現可能だが、本番利用や長時間停止・再起動・監査が必要な用途では、TemporalやMicrosoft Agent Frameworkのような永続実行基盤を使うのが堅い。

## 問題設定：AIエージェント時代の「人間判断キュー」

質問の本質は、「AIが人間に質問するUI」ではなく、より広く言えば、**複数の自律実行主体から発生する判断要求を、人間が処理可能な形に正規化するプロトコル／基盤**である。

典型的な場面は以下である。

| 場面 | AIが止まる理由 | 人間に求める操作 |
|---|---:|---|
| メール返信 | 自動送信のリスクがある | 下書き承認・修正・却下 |
| コーディングエージェント | 実装方針・破壊的変更の確認 | プラン承認・スコープ選択 |
| IT運用 | 本番変更のリスク | 変更申請承認 |
| 財務・支払い | 権限・監査・分離職務 | 支払い承認 |
| 医療・ライフサイエンス | 規制・安全性・GxP | 専門家レビュー |
| 個人AI秘書 | 予定・人間関係・価値判断 | 選択・確認・拒否 |

StackAIの記事は、この種のHITL設計の最重要原則として、AIが「提案」し、人間の承認後に「コミット」するという分離を挙げている。つまり、AIは構造化されたアクション案を保存し、人間に提示し、承認後にのみ実行する。この「propose / commit」の分離は、意図せぬ副作用を避け、承認の意味を明確にし、監査可能性を高めるための実務上の中核パターンである ([StackAI, n.d.](https://www.stackai.com/insights/human-in-the-loop-ai-agents-how-to-design-approval-workflows-for-safe-and-scalable-automation))。

この考え方は、質問者の関心である「AIが人間に判断を仰ぐ部分のインターフェース設計」と非常に近い。単に通知を送るだけでなく、AIの提案内容、判断理由、リスク、選択肢、回答形式、回答後の実行内容を明示する必要がある。

## 現時点で標準プロトコルはあるのか

### 結論：単一標準はないが、実装パターンは収束している

「HITL質問管理プロトコル」と呼べるような、Slack・メール・Web UI・各AIエージェントが共通で話す標準仕様は、少なくとも提供資料の範囲では確認できない。MCP、webhook、workflow signal、tool approval、approval queueなど、関連する部品は存在するが、それらを横断する単一プロトコルはまだ形成途上である。

ただし、各フレームワークは似た構造に向かっている。

| 系統 | 中断方法 | 再開方法 | 人間UIとの接続 |
|---|---|---|---|
| Microsoft Agent Framework | `RequestInfoEvent` / `RequestPort` | responseを渡してresume | tool approvalや独自リクエスト |
| Workflow SDK | `defineHook()`でhookをawait | APIからhook resume | Web UI / webhook |
| Temporal | WorkflowがSignal待ち | Signalで決定を注入 | 任意のUI・通知基盤 |
| AWS AgentCore系 | 承認が必要な操作でHITL | 承認後にtool実行 | centralized / tool-specific / async / real-time |
| 軽量自作 | DBやファイルにpending保存 | polling / webhook | Slack・メール・Webなど |

つまり、現実的には「プロトコルを探す」というより、**共通のHITLリクエスト形式を自分で定義し、既存のdurable workflowや通知基盤に載せる**のが最も実装可能性が高い。

## Microsoft Agent Framework：Request / ResponseとしてのHITL

Microsoft Agent Framework Workflowsでは、HITLはworkflow内のrequest / response機構として扱われる。executorが外部システム、たとえば人間オペレーターにリクエストを送り、回答を待ってからworkflowを進める設計である。カスタムexecutorと`WorkflowBuilder`では`RequestPort`パターンを使い、agent orchestrationではtool approvalが同じHITL request / response機構で実現される ([Microsoft, n.d.](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop))。

特に重要なのは、tool approval時にworkflowが停止し、`RequestInfoEvent`を発行する点である。イベントのpayloadには、C#やGoでは`ToolApprovalRequestContent`、Pythonでは`type == "function_approval_request"`の`Content`が含まれる。これは、AIエージェントが「このtool callを実行してよいか」と人間に確認するための標準的なイベント表現に近い ([Microsoft, n.d.](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop))。

さらに、Microsoft Agent Frameworkではcheckpointとの統合も重要である。checkpoint作成時にはpending requestもcheckpoint stateとして保存され、復元時には未回答のrequestが再び`RequestInfoEvent`としてemitされる。つまり、プロセスが落ちたり再起動したりしても、人間への質問が消えない。これは、質問者が求める「質問をキューイングして保存し、AIが再開する」要件に直結している ([Microsoft, n.d.](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop))。

この仕組みは、Microsoft Agent Framework内で閉じるならかなり理想に近い。ただし、複数フレームワークのAIや外部サービスを横断して一元管理したい場合は、`RequestInfoEvent`をそのまま全体標準にするのではなく、後述するような独自の`HumanRequest`スキーマに変換するアダプタを作るのが現実的である。

## Workflow SDK：typed hookで人間入力を待つ

Workflow SDKのHuman-in-the-Loop機能も、質問者の構想に非常に近い。`defineHook()`で型付きhookを定義し、workflow内で`await hook`する。hookが呼ばれると、tool call IDをtokenとしてhook instanceが作成され、workflowは人間の入力を待つ。その間、compute resourcesは消費されない。UIはpending tool callと入力データ、たとえばフライト詳細や価格などを表示し、人間がAPI endpointからdecisionを送るとhookがresumeされる ([Workflow SDK, n.d.](https://workflow-sdk.dev/docs/ai/human-in-the-loop))。

ここで重要なのは、HITLが「チャット画面上の一時停止」ではなく、**型付きの外部イベント待ち**として扱われていることだ。これにより、数分だけでなく数日後の人間入力にも耐えられる。さらに、code deploymentをまたいでも安定して再開できると説明されている ([Workflow SDK, n.d.](https://workflow-sdk.dev/docs/ai/human-in-the-loop))。

このモデルは、質問者の目的に対してかなり直球である。AI側はhookをawaitし、外部のWeb UIや通知システムはhook tokenに紐づいた判断画面を出し、回答APIがhookをresumeする。プロトコルというより、実装フレームワークとして有力である。

## Temporal：長時間待機・SLA・監査に強い承認ワークフロー基盤

Temporalは、AI専用ではないが、HITL承認ワークフローに非常に適したdurable execution基盤である。Temporalのブログでは、文書承認プロセスの問題として、依頼が未回答のまま放置される、期限が過ぎても何も起きない、再起動で文脈が失われる、監査証跡が不完全になる、といった典型的失敗が挙げられている。その解決として、決定をdurablyに待ち、SLAを自動で強制し、schedulerなしでescalationし、インフラが落ちても全アクションが記録される承認システムを構築する方法が示されている ([Temporal, 2026](https://temporal.io/blog/human-in-the-loop-approvals))。

TemporalでHITLを実装する場合、基本構成は以下になる。

| Temporal概念 | HITLでの役割 |
|---|---|
| Workflow | AIタスク全体、または承認待ちプロセス |
| Activity | 通知送信、レポート生成、外部API実行 |
| Signal | 人間の承認・却下・選択を注入 |
| Query | 現在の承認状態をUIから読む |
| Timer | SLA、期限、リマインダー、エスカレーション |
| Task Queue | Workerへの実行ルーティング |

Temporalの強みは、人間が数時間・数日・数週間後に返答するようなケースでも、workflow stateを保持し続けられる点である。質問者が考える「AIが処理を中断し、人間の回答で再開する」仕組みを、分散システムとして堅牢に構築するなら、Temporalは最有力候補の一つである。

ただし、Temporalは汎用基盤であり、HITL用UIやAI request schemaが最初から完成しているわけではない。Webダッシュボード、通知チャネル、回答フォーム、権限管理は自分で作る必要がある。

## AWS AgentCoreとMCP周辺：承認ロジックをtool定義側に置く考え方

AWSのHealthcare and Life Sciences向け記事では、AIエージェントにおけるHITLパターンとして、centralized、tool-specific、asynchronous、real-timeという複数の承認方式が整理されている。医療・ライフサイエンスではGxPなどの規制要件やデータの機微性があり、特定の処理に人間の監督が必要になるため、HITL構成が不可欠だと説明されている ([AWS, n.d.](https://aws.amazon.com/blogs/machine-learning/human-in-the-loop-constructs-for-agentic-workflows-in-healthcare-and-life-sciences))。

特に興味深いのは、承認ロジックをMCP serverのtool definitions内に閉じ込めるアプローチである。この場合、agent自身はどのtoolに承認が必要かを知らなくてもよい。tool定義側で承認要件を追加・変更できるため、agentの推論ロジックからapproval policyを分離できる ([AWS, n.d.](https://aws.amazon.com/blogs/machine-learning/human-in-the-loop-constructs-for-agentic-workflows-in-healthcare-and-life-sciences))。

これは非常に重要な設計思想である。複数AIが同じtool群を使う場合、各AIに「この操作は人間承認が必要」と個別実装するのではなく、tool gatewayやMCP server側で承認ポリシーを一元管理する方が安全である。質問者の構想に当てはめるなら、AIからの質問を一元管理するだけでなく、**承認が必要な操作を検出するゲートウェイ**を設けるとよい。

## 実装例：NylasのHITLメールエージェント

NylasのHuman-in-the-loop Email Agentは、軽量だが実装イメージが非常に分かりやすい。流れは、未読メールを`nylas email list --unread --json`で取得し、Python agentがLLMに分類と返信下書きを依頼し、下書きをJSONファイルとしてreview queueに保存し、人間がapprove / rejectし、承認済みだけを送信するというものだ ([Nylas, n.d.](https://cli.nylas.com/guides/build-human-in-loop-email-agent))。

Nylasの例では、review queueが`pending/*.json`として実装される。人間が確認した後、ファイルを`approved/`または`rejected/`へ移動する。dispatch scriptは`approved/`ディレクトリを走査して送信し、送信後は`sent/`へアーカイブする。記事では、20件のバッチについてfetchからapproved-sendまでの総ループ時間が、人間のレビュー時間を除き2分未満、承認済み下書き10件のdispatchが8秒未満と説明されている ([Nylas, n.d.](https://cli.nylas.com/guides/build-human-in-loop-email-agent))。

この例の価値は、必ずしもNylas CLIそのものではない。重要なのは、**HITLは最初から大規模基盤でなくても、pending / approved / rejected / sentという状態遷移だけで実用化できる**という点である。個人開発やObsidian連携、ローカルAIエージェントの確認キューであれば、このファイルベース方式やSQLite方式は十分現実的である。

また、Nylasの記事は、レビューUIをターミナルプロンプトからSlack通知やWeb UIへ置き換えられると述べている。agentは承認がどのUIで行われたかを知らなくてよく、ファイルが適切なディレクトリへ移動されればよい、という疎結合設計である ([Nylas, n.d.](https://cli.nylas.com/guides/build-human-in-loop-email-agent))。

## 通知インターフェース：Slack、メール、Webhook、Web UI

質問者が挙げたように、人間への通知手段はデスクトップ通知、Webダッシュボード、電話、メール、LINE、メッセージングアプリなど多様でよい。設計上は、通知チャネルをHITL requestの本体から分離するのが望ましい。

Slack連携の実装例として、Aembitの記事はSlack Incoming Webhooksを使い、AI agentのタスク完了通知を送る方法を示している。具体的には、Slack appでIncoming Webhookを作成し、Python側から`requests.post(WEBHOOK_URL, json={"blocks": formatted_message})`で通知を送る。セキュリティ上はWebhook URLを秘密情報として扱うことが最重要とされている ([Aembit, 2026](https://aembit.io/blog/how-to-connect-custom-ai-agents-with-slack))。

HITLに応用する場合、Slack通知には以下を含めるとよい。

- 質問タイトル
- AI名・workflow名
- 優先度
- 期限
- 提案アクション
- リスク説明
- 「承認」「却下」「詳細を見る」ボタンまたはURL
- 回答フォームへの署名付きリンク

ただし、SlackやLINEのようなチャットUIだけに依存すると、判断履歴や構造化データが散らばりやすい。そのため、実務的には**中央のHITLサーバーを正とし、Slackやメールは通知・簡易入力チャネルとして扱う**のがよい。

## Zoom sampleから見る本番実装上の落とし穴

Zoomのhuman-in-the-loop workplace agent sampleは、HITL実装の具体例であると同時に、本番化時の注意点を示している。GitHub上の説明では、Zoom webhookは3秒以内に200 ACKを返す必要があるため、実際の処理をwebhook handler内でfire-and-forgetにすると、プロセスが落ちた場合に処理が失われ、retryやdead-letterもないと指摘されている。推奨策は、SQS、Cloud Tasks、BullMQなどの実キューにイベントを投入し、retry、DLQ、idempotencyを備えたworkerで処理することである ([Zoom, n.d.](https://github.com/zoom/human-in-the-loop-workplace-agent-sample))。

また、Zoom webhookはtimeout時に再送されるため、`x-zm-trackingid`やpayload hashを使ってdedupする必要があるとされている。これはHITL全般に当てはまる。人間の承認ボタンが二重送信されたり、通知webhookが再送されたりすると、支払い・メール送信・本番変更が二重実行される危険がある。したがって、idempotency keyは必須である ([Zoom, n.d.](https://github.com/zoom/human-in-the-loop-workplace-agent-sample))。

この点は、質問者の構想を本番レベルにする際に重要である。単に「AIがpollingして回答を受け取る」だけでなく、回答そのもの、通知、実行アクションすべてに冪等性を持たせる必要がある。

## 設計すべき共通データモデル

複数AIからの質問を一元管理するには、内部的に次のような`HumanRequest`スキーマを定義するとよい。

```json
{
  "request_id": "hrq_123",
  "source_agent": "coding-agent-1",
  "workflow_id": "wf_456",
  "run_id": "run_789",
  "checkpoint_id": "ckpt_001",
  "request_type": "approval",
  "title": "本番DBのマイグレーションを実行してよいですか",
  "prompt": "usersテーブルにindexを追加します。実行してよいですか。",
  "context": {
    "diff_url": "https://example.com/diff",
    "risk_level": "medium",
    "estimated_impact": "read query performance improved; lock risk low"
  },
  "options": [
    {"id": "approve", "label": "承認"},
    {"id": "reject", "label": "却下"},
    {"id": "modify", "label": "条件付き承認"}
  ],
  "response_schema": {
    "type": "object",
    "properties": {
      "decision": {"enum": ["approve", "reject", "modify"]},
      "comment": {"type": "string"}
    },
    "required": ["decision"]
  },
  "priority": "high",
  "deadline_at": "2026-07-11T12:00:00Z",
  "status": "pending",
  "created_at": "2026-07-11T08:47:00Z",
  "idempotency_key": "toolcall_abc123"
}
```

このモデルのポイントは、AIへの返答を自然文だけにしないことだ。人間はUI上で自然に操作してよいが、保存される回答は構造化されている必要がある。

回答側は次のようになる。

```json
{
  "request_id": "hrq_123",
  "responder": "user_001",
  "decision": "approve",
  "comment": "低トラフィック時間帯に実行してください",
  "conditions": {
    "execute_after": "2026-07-11T15:00:00Z"
  },
  "responded_at": "2026-07-11T09:02:00Z"
}
```

このようにしておけば、AI側はhook resume、polling、webhook callback、Temporal signalなど、どの方式でも同じ構造を受け取れる。

## 推奨状態機械

HITL requestは、最低限以下の状態を持つべきである。

| 状態 | 意味 |
|---|---|
| `created` | AIが判断要求を生成した |
| `queued` | 中央キューに登録された |
| `notified` | 人間へ通知済み |
| `viewed` | 人間が詳細を開いた |
| `answered` | 回答済み |
| `approved` | 承認済み |
| `rejected` | 却下済み |
| `expired` | 期限切れ |
| `escalated` | 他者・別チャネルへエスカレーション |
| `delivered` | AI側へ回答送信済み |
| `resumed` | workflow再開確認済み |
| `archived` | 監査用に保存済み |

StackAIが推奨するように、AIの推論継続と実行コミットを明示的な状態遷移で分離することが、controlled autonomyの中心である ([StackAI, n.d.](https://www.stackai.com/insights/human-in-the-loop-ai-agents-how-to-design-approval-workflows-for-safe-and-scalable-automation))。

## UI設計：人間が判断しやすいインターフェース

HITLのUIで最も避けるべきなのは、「承認しますか？」だけを表示することである。人間が責任ある判断をするには、最低限以下が必要である。

### 判断カードに表示すべき情報

| 項目 | 内容 |
|---|---|
| 誰から | AI名、workflow名、tool名 |
| 何をしたいか | proposed action |
| なぜ必要か | AIの理由・根拠 |
| 影響範囲 | 対象データ、送信先、本番環境か |
| リスク | 失敗時の影響、取り消し可否 |
| 選択肢 | approve / reject / edit / ask follow-up |
| 期限 | SLA、期限切れ時の挙動 |
| 監査情報 | request_id、作成時刻、関連ログ |
| 実行プレビュー | 承認後に実行されるAPI callやメール本文 |

### 人間の負荷を下げる機能

- 優先度順のinbox
- AI別・プロジェクト別フィルタ
- 一括承認は低リスクだけに限定
- 高リスク操作は二段階確認
- 期限切れ・未読のリマインダー
- モバイル対応
- 自然文コメントを構造化フィールドへ変換
- 承認後の実行結果表示
- 「このAIから同種の質問を次回も同じ条件で許可」などのpolicy化

ここで重要なのは、人間を単なるボタン押し係にしないことである。HITLは安全性を高めるための仕組みだが、UIが悪いと確認疲れが起き、すべて承認するだけの形骸化したプロセスになる。

## 実装アーキテクチャ案

質問者の目的に対して、実用的なアーキテクチャは以下である。

```text
AI Agent / Workflow
   |
   | 1. HumanRequest作成
   v
HITL Gateway API
   |
   | 2. DBにpending保存
   v
Human Decision Queue
   |
   | 3. 通知
   +--> Slack / LINE / Email / Desktop / Phone
   |
   | 4. Web Dashboardで回答
   v
Structured Response Store
   |
   | 5. AIへ返却
   +--> webhook callback
   +--> polling API
   +--> Temporal Signal
   +--> Workflow SDK hook resume
   +--> Microsoft response resume
```

小規模な最小構成なら以下でよい。

| 部品 | 推奨 |
|---|---|
| DB | SQLiteまたはPostgreSQL |
| API | FastAPI / Node.js |
| UI | Next.js / SvelteKit |
| 通知 | Slack webhook、メール、LINE Notify相当のAPI |
| AI再開 | polling APIまたはwebhook |
| 認証 | magic link、OAuth、署名付きURL |
| ログ | JSONL + DB監査テーブル |

本格構成なら以下になる。

| 要件 | 推奨 |
|---|---|
| 長期実行 | Temporal / Workflow SDK / Microsoft Agent Framework |
| 再起動耐性 | checkpoint / durable execution |
| 承認ポリシー | tool gateway / MCP server側 |
| 監査 | immutable audit log |
| 通知信頼性 | queue + worker + retry + DLQ |
| 冪等性 | idempotency key必須 |
| 権限 | RBAC / approval delegation |
| 高リスク | multi-party approval |

## 関連OSS・エコシステム

GitHub Topicsの`hitl`には、2026年7月時点の提供情報で185件のpublic repositoriesがあり、Pythonが83件、TypeScriptが39件とされている。これは、HITLが研究概念ではなく、実装領域として広がっていることを示す。ただし、個別repositoryの成熟度はばらつくため、採用時にはstar数だけでなく、更新頻度、license、security policy、workflow durabilityの有無を確認すべきである ([GitHub, n.d.](https://github.com/topics/hitl?o=desc&s=updated))。

また、Mnexa-AIのe2aは、AI agents向けのauthenticated email gatewayとして、SPF/DKIM verified inbound、HMAC-signed delivery、webhook + WebSocket fan-out、CLI + SDKsを掲げている。メールをHITL通知・回答チャネルとして使う場合、こうした署名付き配送やwebhook fan-outは関連技術として注目できる ([Mnexa-AI, n.d.](https://github.com/Mnexa-AI/e2a))。

AxmeAIのaxmeは、「agents, services, and humans coordinate as equals」と説明され、human-in-the-loop approvals、multi-agent orchestration、agent crash recoveryなどを掲げている。成熟度は確認が必要だが、HITLを「人間もagent coordination protocolの参加者」として扱う方向性は、質問者の構想に近い ([AxmeAI, n.d.](https://github.com/AxmeAI/axme))。

## 私の具体的見解：まず作るべきは「Human Request Broker」である

本調査に基づく私の具体的意見は、次の通りである。

**複数AIからの質問を一元管理したいなら、まず「Human Request Broker」を作るべきであり、最初から特定フレームワークに閉じない方がよい。**

理由は3つある。

第一に、Microsoft Agent Framework、Workflow SDK、Temporalなどはそれぞれ強力だが、全AIが同じ基盤上で動くとは限らない。Codex系、Jules系、ローカルagent、クラウドagent、メールagentなどが混在するなら、共通化すべきはworkflow engineではなく、`HumanRequest`と`HumanResponse`のスキーマである。

第二に、通知チャネルは変わりやすい。今日Slack、明日LINE、将来電話やデスクトップ通知にしたくなる可能性がある。したがって、AIは「Slackに聞く」のではなく、「HITL Gatewayにrequestを登録する」だけにするべきである。

第三に、人間の判断履歴は資産になる。どのAIがどんな質問をし、人間がどう答え、その結果どうなったかを保存すれば、後から承認ポリシーの自動化、AIの改善、リスク分析、自己判断傾向の可視化に使える。

個人開発として始めるなら、以下の順序が現実的である。

1. `requests`テーブルと`responses`テーブルを作る。
2. AIが`POST /human-requests`で質問を登録できるようにする。
3. Web dashboardでpending一覧を表示する。
4. 回答をJSONとして保存する。
5. AIは`GET /human-requests/{id}`をpollingする。
6. Slackまたはメール通知を追加する。
7. webhook callbackまたはWorkflow SDK / Temporal / Microsoft連携を追加する。
8. idempotency、期限、監査ログ、権限管理を追加する。

最初のプロトタイプではpollingで十分である。高度化したら、Temporal SignalやWorkflow SDK hook resumeへ置き換えればよい。

## まとめ

Human-in-the-loopの判断インターフェースは、2026年時点で単一の標準プロトコルにまとまってはいない。しかし、主要フレームワークや実装例を見ると、設計原則は明確に収束している。

最重要ポイントは、AIに直接人間UIを持たせるのではなく、**AI → Human Request Broker → 通知／ダッシュボード → Structured Response → AI再開**という疎結合構成にすることである。Microsoft Agent Frameworkはrequest / responseとcheckpoint、Workflow SDKはtyped hook、Temporalはdurable signals、AWS系はtool approval policy、Nylasはシンプルなreview queueの実例を提供している。これらを組み合わせれば、質問者が構想する「いろんなAIから来る質問を一元管理し、人間が答え、AIが再開する」仕組みは十分に実現可能である。

実装上の最小単位は、標準プロトコルを待つことではなく、`HumanRequest`と`HumanResponse`のスキーマ、状態機械、通知アダプタ、再開APIを定義することである。これを小さく作れば、個人用AIダッシュボードにも、将来的な本番HITL基盤にも発展させられる。

## References

Aembit. (2026, May). *How to connect custom AI agents with Slack*. Aembit. [url website](https://aembit.io/blog/how-to-connect-custom-ai-agents-with-slack)

Amazon Web Services. (n.d.). *Human-in-the-loop constructs for agentic workflows in healthcare and life sciences*. AWS Machine Learning Blog. [url website](https://aws.amazon.com/blogs/machine-learning/human-in-the-loop-constructs-for-agentic-workflows-in-healthcare-and-life-sciences)

AxmeAI. (n.d.). *Axme: Durable execution where agents, services, and humans coordinate as equals*. GitHub. [url website](https://github.com/AxmeAI/axme)

GitHub. (n.d.). *hitl · GitHub Topics*. GitHub. [url website](https://github.com/topics/hitl?o=desc&s=updated)

Microsoft. (n.d.). *Microsoft Agent Framework Workflows - Human-in-the-loop (HITL)*. Microsoft Learn. [url website](https://learn.microsoft.com/en-us/agent-framework/workflows/human-in-the-loop)

Mnexa-AI. (n.d.). *e2a: Authenticated email gateway for AI agents*. GitHub. [url website](https://github.com/Mnexa-AI/e2a)

Nylas. (n.d.). *Build a Human-in-the-Loop Email Agent*. Nylas CLI. [url website](https://cli.nylas.com/guides/build-human-in-loop-email-agent)

StackAI. (n.d.). *Human-in-the-Loop AI Agents: How to design approval workflows for safe and scalable automation*. StackAI. [url website](https://www.stackai.com/insights/human-in-the-loop-ai-agents-how-to-design-approval-workflows-for-safe-and-scalable-automation)

Temporal. (2026, May 21). *Reliable document approvals with human-in-the-loop workflows*. Temporal. [url website](https://temporal.io/blog/human-in-the-loop-approvals)

Workflow SDK. (n.d.). *Human-in-the-Loop*. Workflow SDK Documentation. [url website](https://workflow-sdk.dev/docs/ai/human-in-the-loop)

Zoom. (n.d.). *human-in-the-loop-workplace-agent-sample*. GitHub. [url website](https://github.com/zoom/human-in-the-loop-workplace-agent-sample)
