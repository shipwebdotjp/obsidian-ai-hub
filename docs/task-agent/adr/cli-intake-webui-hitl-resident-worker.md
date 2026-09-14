# CLI 投入専用 + WebUI HITL + 常駐ワーカー

## Status

Accepted

## Context

タスクの入口と人間の関与点をどこに置くかを決める必要がある。既存 AI Hub には
(a) CLI コマンド群、(b) FastAPI + React の WebUI、(c) launchd 常駐 HITL ワーカー、
(d) LINE 通知から Web フォームへの誘導 (HITL v1) がある。

タスクは長時間実行かつ承認待ちを含むため、CLI を対話的に block させる設計は
実用に合わない。一方で入口の簡便さ (自由文を貼り付けるだけ) は価値が高い。

## Decision

- **CLI は投入専用**とする。自由文を受け取り、task_id・受付状態・WebUI URL を返して終了する。
- 確認・承認・差戻し・取消は**すべて WebUI の HITL**で行う。WebUI はポーリングで受信箱を確認する。
- 実行は AI Hub 内の**常駐ワーカー**が非同期に行う。
- MVP で認証・役割管理は実装しない (単一ローカルユーザー前提)。WebUI の露出は既存 Web の方針
  (loopback または tailnet + トークン) に従う。
- 外部通知 (LINE 等) は MVP 外。既存 HITL v1 の LINE 誘導を Task Agent には使わない。

## Consequences

- 投入から承認までの往復に WebUI を開く必要があり、モバイルからの気軽さは MVP では妥協する。
- 常駐ワーカーが単一障害点になる。停止時はタスクが `interrupted` になり、自動再実行しない
  ([ADR: 自動ロールバックを行わない](no-automatic-rollback-recovery-via-trace-and-hitl.md))。
- 将来の Inbox 投入・定期実行入口は、CLI と同じ受付サービスを利用して追加できる。

## Alternatives

- **CLI 対話型 (投入後に承認も CLI で)**: 長時間 block し、複数タスク並行と相性が悪い。不採用。
- **CLI だけで完結 (WebUI なし)**: 計画・トレース・差戻し理由の閲覧 UX を CLI で作り直すコストが高い。不採用。
- **リアルタイム通知 (Webhook/Push)**: MVP の完全性優先方針に対し付加価値が小さく、外部依存を増やす。不採用。
