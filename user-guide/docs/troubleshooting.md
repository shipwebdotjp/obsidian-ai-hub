---
sidebar_position: 2
title: トラブルシューティング
---

# トラブルシューティング

## サーバーが起動しない

- **`OBSIDIAN_AI_HUB_API_TOKEN` が空** — 空だとサーバーは起動に失敗します。`.env` に設定してください。
- **ポートが使用中** — `--serve-port` で別ポートにするか、`lsof -ti :8765 | xargs kill` で解放します（LaunchAgent 登録後は `make restart-web` が行います）。
- **フロントエンドが未ビルド（`503`）** — `make build-web` を実行して `frontend/dist` を生成します。

## ブラウザで「接続エラー」になる

ヘルスチェック `GET /health` に到達できていません。
サーバーが起動しているか、ホスト / ポートが一致しているかを確認し、**再読み込み** します。

## トークン関連

- **入力しても弾かれる** — `.env` の `OBSIDIAN_AI_HUB_API_TOKEN` と完全に一致しているか確認します（大文字小文字・空白）。
- **401 が返る** — トークンが失効・変更されています。**設定** 画面で再入力してください。
- **ジョブ管理で 403** — アクセス制限画面が表示された場合、トークン認証とネットワーク（localhost または tailnet）を確認します。
- **設定の保存に失敗** — トークンが無効です。**設定** 画面の入力を確認してください。

## ジョブが実行されない

- **`tasks/` が残っている** — runner は起動を拒否します。`uv run -m obsidian_ai_hub.job_runner --migrate-tasks-to-jobs` で移行してください。
- **設定 YAML が壊れている** — 破損した `jobs.local.yml` は空として扱われず、明示的にエラーになります。内容を修正してください。
- **arming のため遡って実行されない** — 追加・再有効化・コマンド/スケジュール変更時は保存時刻で arming されます。次の該当枠を待つか、`last_run` を確認してください。
- **失敗が繰り返される** — 失敗時は `last_run` が更新されず、後続サイクルで再試行されます。コマンドとログを確認します。
- **常駐 HITL ワーカーと二重** — 常駐ワーカー稼働中は `hitl_dispatch` を定期ジョブにしないでください。

## Task / ワークフローが進まない

- **Web サーバーが停止していると進みません。** Task はキューに残り、Run も実行されません。
- `interrupted` の Task は **再計画**、`interrupted` の Run は **再開** で戻します。
- ワークフローの承認待ち・HITL 待ち・attention 待ちは、それぞれの画面で処理します（[Run・承認・復旧](workflow/runs.md)）。

## ワークフローの検証・実行エラー

[制約とトラブルシューティング](workflow/limits.md) を参照してください。
とくに「実行には公開が必要」「公開済み Revision は編集不可」はよくあるつまずきです。

## リサーチのコードベース調査が使えない

`project` モードは有効な Git リポジトリのプロジェクトのみ選べます。
**プロジェクト管理** でプロジェクトを登録・確認してください。

## ENV=test で外部サービスにつながらない

テストモードでは LLM・LINE・カレンダー・Web 検索などが既定でブロックされます。
必要な場合のみ `.env.test` に `ALLOW_EXTERNAL_IN_TEST=1` を設定してください。

## Apple 連携のエラー

プランナー画面に「Apple連携でエラーが発生しました」と表示される場合、
`APPLE_CALENDAR_NAME` の設定、カレンダー / リマインダーへのアクセス権限を確認してください。

## 旧 URL が 404 になる

- Web UI: `/tasks` → `/jobs` へ移動しました。
- API: `/api/v1/task-config` → `/api/v1/scheduler-jobs`（recurring: `recurring-jobs`、one-shot: `one-shot-jobs`）へ移動しました。旧 URL は 404 を返します。

## 参考

- [運用](operations.md)
- [ワークフローの制約](workflow/limits.md)
- [CLI リファレンス](reference/cli.md)
