---
sidebar_position: 4
title: 通知基盤
---

# 通知基盤 (Web Push / LINE)

Obsidian AI Hub では、要対応イベントおよび処理失敗イベントをリアルタイムに認知するための通知基盤を備えています。

## チャネルと対応イベント

- **初期チャネル**: Web Push（ブラウザ標準）および LINE（LINE Messaging API）
- **対象カテゴリ**:
  - **要対応 (action_required)**: HITL確認、Task承認・再承認待ち、Workflow承認・attention待ち、Agent/Coding質問（ask_user）、Planner提案
  - **失敗系 (failure)**: failed、interrupted、Taskのincomplete
- **対象外**: 開始・成功・キャンセルイベントは通知されません。

## 環境設定 (`.env`)

Web Push および LINE 送信に必要な環境変数を指定します。

```env
# Web Push VAPID 鍵設定
WEB_PUSH_VAPID_PUBLIC_KEY=your_vapid_public_key
WEB_PUSH_VAPID_PRIVATE_KEY=your_vapid_private_key
WEB_PUSH_VAPID_SUBJECT=mailto:admin@example.com

# LINE 通知設定（LINE Messaging API）
LINE_MESSAGING_TOKEN=your_line_channel_access_token
LINE_TARGET_ID=your_line_user_id

# 外部リンクの基底 URL（通知の深いリンクに使用）
OBSIDIAN_AI_HUB_WEB_URL=https://aihub.example.com
```

## VAPID 鍵の生成

`WEB_PUSH_VAPID_PUBLIC_KEY` と `WEB_PUSH_VAPID_PRIVATE_KEY` はペアで新規生成します。どちらか一方だけの設定や、公開鍵と秘密鍵の組み合わせ違いでは購読に失敗します。

リポジトリの venv を使って生成できます（npm 不要）:

```bash
uv run python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); from py_vapid.utils import b64urlencode; from cryptography.hazmat.primitives import serialization; priv=int(v.private_key.private_numbers().private_value).to_bytes(32,'big'); pub=v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint); print('PUBLIC='+str(b64urlencode(pub))); print('PRIVATE='+str(b64urlencode(priv)))"
```

または定番の `web-push` コマンドでも生成できます:

```bash
npx --yes web-push generate-vapid-keys
```

出力された公開鍵を `WEB_PUSH_VAPID_PUBLIC_KEY`、秘密鍵を `WEB_PUSH_VAPID_PRIVATE_KEY` に設定します。`WEB_PUSH_VAPID_SUBJECT` は Push サービス側に表示される連絡先で、`mailto:` か `https:` の URL を指定します。

設定後は Web サーバーを再起動し、公開鍵が配信されていることを確認します:

```bash
make restart-web
curl -H "Authorization: Bearer $OBSIDIAN_AI_HUB_API_TOKEN" \
  http://127.0.0.1:8765/api/v1/notifications/vapid-public-key
```

## 設定画面での有効化手順

すべての通知チャネルは初期状態で **オフ** になっています。

1. **設定画面** (`/settings`) へアクセスします。
2. **Web Push 通知**:
   - 「この端末でWeb Pushを購読」ボタンをクリックします。
   - ブラウザの通知許可ダイアログで「許可」を選択します。
   - 「要対応通知」および「失敗系通知」のチェックボックスで配信カテゴリを選択します。
3. **LINE 通知**:
   - 「LINE通知 有効化」のスイッチをオンにします。
   - 「要対応通知」および「失敗系通知」のチェックボックスで配信カテゴリを選択します。

## 深いリンク遷移

通知をクリックすると、該当する画面へ直接遷移します（例: `/hitl?run_id=...` / `/task-agent/:id` / `/workflows/runs/:id` / `/agents?session_id=...` / `/coding?session_id=...` / `/planner`）。
通知 URL に Bearer トークンや秘密情報は含まれません。未認証の場合はログイン／トークン入力画面へ誘導されます。

## トラブルシューティング

- ブラウザの許可ダイアログで「許可」を選んだのに購読ボタンが失敗表示になる場合は、まず `vapid-public-key` の応答を確認します。`vapid_public_key` が空文字なら `.env` の VAPID 鍵が未設定か、設定後の再起動漏れです。鍵を設定して `make restart-web` で再起動し、ボタンを押し直してください。
- 鍵を後から変更すると既存の購読は無効になるため、各端末で購読し直してください。
