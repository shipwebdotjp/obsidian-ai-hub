# Task Agent Post-MVP 検討項目

この文書はMVPで意図的に実装しない事項の一覧である。実装の確約や優先順位ではない。
MVPの範囲は [specification.md](specification.md) を正とする。

## 次期実装の選定記録（2026-09-14）

- **調査したMVP除外候補**: Vault直接書込み、カレンダー/リマインダー直接書込み、
  任意shell・Skills・カスタムプラグイン、共通Workspace lock、複数Task workerと並列実行、
  Task固有の実行時間・呼出し数・コスト上限、Task固有の自動リトライ、
  親側の計画逸脱検出・sandbox、自動ロールバック、専用launchd Task worker、
  Capability完全CRUD、Agent設定のPlanスナップショット、Capability別の高度な承認ポリシー、
  Artifact/Delegation/HITL linkの専用テーブル、保持期間とアーカイブ、依頼本文の暗号化、
  通知と外部入口（Inbox・定期実行・LINE/Push）。
- **選定した機能（1つのみ）**: Agent設定のPlanスナップショット（最小形:
  承認時点の指紋記録と実行開始時の差分検出・再承認回し。設定の完全凍結はしない）。
- **選定根拠**:
  - ユーザー価値: 仕様書が「承認後にAgentのsystem promptや有効toolが変われば挙動も
    変わり得る。このリスクは個人利用の運用として受容する」と明記していた承認境界の
    既知の穴を塞ぐ。承認した内容と異なる設定で子runが動ることを防げる。
  - 実装コスト: DB migration不要（`plan_json` 内の任意キー追加のみ）、外部書込みなし、
    実行開始時の比較と既存 `waiting_reapproval` 経路の再利用だけの小変更。
  - 設計整合性: 承認済みPlanを実行境界にするADRと、無効化Capabilityの実行前停止という
    既存 precedent（`_ensure_capabilities_enabled`）に沿う。委譲対象allowlistと同様に
    Planへ承認範囲を記録する。
  - リスク: 可逆的で副作用なし。スナップショットのない旧Plan・委譲なしPlanは従来通り
    通過するため回帰が小さい。Vault/外部書込み・shell公開・並列worker・自動ロールバック
    といった不可逆・競合・復旧責任を伴う候補は今回見送った。

## 書込みCapability

- **Vault直接書込み** — ノートの作成・編集・削除をTask Capabilityとして追加する。
  パス制約、変更一覧、取消時の途中状態、共通Workspace lockを合わせて設計する。
- **カレンダー/リマインダー直接書込み** — Taskの一括Plan承認を唯一の承認として、既存の
  提案HITLを経由せずに書き込むAdapterを追加する。外部API失敗時の結果表示も必要になる。
- **任意shell、Skills、カスタムプラグイン** — Task Capabilityとして公開するかを個別に検討する。
  公開する場合は、固定allowlist、入力検証、redaction、対象範囲、取消の契約を追加する。

## 実行制御と安全性

- **共通Workspace lock** — Vault/外部書込みを追加する段階で、読取共有・書込み排他、待機状態、
  lock解放時の再開を導入する。MVPのGit書込みは既存Codingのrepo lockを使う。
- **複数Task workerと並列実行** — まず単一workerの実運用を観測し、並列化が必要になった時点で
  claim、lock、子run待機の競合制御を拡張する。
- **Task固有の実行時間・呼出し数・コスト上限** — MVPでは取消に依存する。追加する場合は、
  子runの既存上限との優先順位と、超過時の停止/再承認UXを定める。
- **Task固有の自動リトライ** — Adapterごとの安全な再試行条件、冪等性、外部副作用の重複防止を
  定義できる場合にのみ追加する。
- **親側の計画逸脱検出・sandbox** — 現在はAgent/Coding CLIの自己申告を使う。ファイル監視、
  パスallowlist、Planとの差分照合を導入するなら、CLI固有権限との責任分界を再設計する。
- **自動ロールバック** — Vault、Git、外部APIを横断して安全に戻す方式が必要になるため、
  変更スナップショットと復旧責任を含めて別途検討する。

## 運用と設定

- **専用launchd Task worker** — Webサーバー停止中もTaskを進めたくなった場合に追加する。
  FastAPI同居workerとの二重実行を防ぐinstance ownershipが前提となる。
- **Capability完全CRUD** — 現在の設定UIは `enabled` と `approval_policy` のみである。
  DBからAdapter、入力仕様、説明を任意作成する機能は、コード定義との整合検証を設計してから行う。
- **Agent設定のPlanスナップショット** — 現在は実行時の最新Agent設定を使う。承認後の設定変更を
  実行境界から除外したくなった時点で、system prompt、tool設定、委譲先をPlanへ固定する。
  （2026-09-14に最小形を実装: `specialist_agent` を含むDirectional Planは承認時点の
  Agent設定指紋（`agent_config_snapshot`）をPlanへ記録し、実行開始時に差分・削除を検出したら
  `waiting_reapproval` へ回す。実行中の子runへの設定固定や実行中ループでの再検出は将来課題。）
- **Capability別の高度な承認ポリシー** — `auto` / `plan_required` 以外の、削除だけ追加承認、
  時間帯制限、対象別policyなどは、実際の利用パターンが出てから検討する。

## 保存・観測性

- **Artifact/Delegation/HITL linkの専用テーブル** — MVPではEvent内の要約とID参照で辿る。
  成果物横断検索や分析が必要になった場合に正規化テーブルを追加する。
- **保持期間とアーカイブ** — terminal Taskは30日で削除する。長期監査が必要になった場合は、
  保存対象、redaction、アーカイブ先、削除ポリシーを改めて決める。
- **依頼本文の暗号化** — 既知秘密値のredactionと「未知の秘密を入力しない」運用を置き換える場合に、
  鍵管理、ローテーション、復旧方法を含めて導入する。
- **通知と外部入口** — Inbox・定期実行・LINE/Push通知は、Task受付サービスの契約を保ったまま
  追加できる。通知失敗がTask本体を失敗させない方針を先に定める。
