# Tailscale Funnel で LINE Webhook が公開できなかった件の調査記録

調査日: 2026-08-18  
結果: Tailscale アプリのバージョンアップで解消。設定・ACL・コードは変更不要だった。

## 1. 事象

- Tailscale Funnel（`https://m1mbp.tail744355.ts.net/`）から専用 Nginx（`127.0.0.1:8764`）を経由して LINE Webhook を公開している。
- LINE Developers の Webhook URL 検証が失敗する。
- nginx のアクセスログには何も記録されない（リクエストが届いていない）。

```text
LINE Platform
  └─ Tailscale Funnel: https://m1mbp.tail744355.ts.net/
       └─ 専用 Nginx（127.0.0.1:8764）
            └─ LINE Webhook API
```

## 2. 切り分けの結果

| 確認項目 | 結果 | 判断 |
| --- | --- | --- |
| 公開 DNS での名前解決（`dig @1.1.1.1`） | 解決する（103.84.155.x = Funnel リレー） | 問題なし |
| Tailscale IP 直接アクセス（`--resolve ...:100.73.5.87`） | 404（nginx まで到達、TLS 正常） | ローカル・証明書は正常 |
| 公開リレー IP 経由（`--resolve ...:103.84.155.153`） | `SSL_ERROR_SYSCALL` で TLS ハンドシェイク失敗 | **ここが断絶** |
| `tailscale funnel status` | `Funnel on`、proxy 設定も `AllowFunnel: true` | 設定は正常 |
| tailnet ポリシー（`nodeAttrs` の `funnel` 属性） | `tag:aihub-host` に付与済み | 問題なし |
| nginx / Webhook API のローカル動作 | 405（GET）、POST で 200 | アプリ側は正常 |

## 3. 原因

**Tailscale 1.102.1 の既知バグ。** Funnel リレー（`funnel-ingress-node`、`tag:ingress`、`UnsignedPeerAPIOnly: true`）からの接続を、peerapi が「ingress cap なし」として誤って拒否していた。ACL・nodeAttrs が正しく設定されていても発生する。

決定的なログ（macOS 統合ログ、`io.tailscale.ipn.macsys.network-extension`）:

```text
peerapi: ingress: denied; no ingress cap from [fd7a:115c:a1e0:ab12:4843:cd96:6268:d02b]:58700
```

参照 issue / PR（すべて 2026-08-04〜05 に close・merge）:

- https://github.com/tailscale/tailscale/issues/20739 （Funnel not working with Tailscale 1.102.1）
- https://github.com/tailscale/tailscale/issues/20756 （peerapi ingress denied despite CapGrant）
- https://github.com/tailscale/tailscale/pull/20745 / #20748 （allow ingress peer capability for unsigned peers）

## 4. 対応

Tailscale アプリを最新版へアップデート（修正含む）→ Funnel 設定はそのまま維持 → リレー経由の TLS が通るようになり、nginx ログに `LineBotWebhook/2.0` の 200 が記録された。

## 5. 教訓（再発時のチェック順）

1. 公開 DNS で名前解決できるか（`dig @1.1.1.1`）。できないならテールネット側の設定。
2. Tailscale IP 直接と公開リレー IP の両方で curl し、どちらが失敗するかで断絶箇所を特定。
3. ローカル・証明書・ACL が正常で、リレー経由だけ TLS が通らない場合は **Tailscale 自体の既知バグを疑い、まずアップデート**。
4. nginx にログが残らないのは「リクエストが nginx に届いていない」証拠。Funnel リレー〜tailscaled 間の断絶を疑う。
