---
sidebar_position: 2
title: ジョブのスケジュール
---

# ジョブのスケジュール

## スケジュール種別とフィールド

| `type` | 使用できるフィールド（既定値） |
| --- | --- |
| `minutely` | `second`（0） |
| `hourly` | `second`（0）、`minute`（0） |
| `daily` | `second`、`minute`、`hour`（0） |
| `weekly` | `second`、`minute`、`hour`、`weekday`（`*`、月=0） |
| `monthly` | `second`、`minute`、`hour`、`day`（1） |

フィールドの値は次の形式で書けます。

- 単一の数値: `minute: 0`
- リスト: `minute: [0, 30]`
- カンマ区切り文字列: `minute: "0,30"`
- 範囲: `hour: "8-18"`
- ステップ付き範囲: `minute: "*/15"`、`hour: "8-18/2"`
- `*`（許可される箇所）: `weekday: "*"`

## 例

毎分 0 秒（Inbox のほぼリアルタイム処理）:

```yaml
- id: merge_inbox
  enabled: true
  schedule:
    type: minutely
    second: 0
  command: uv --directory /path/to/obsidian-ai-hub run -m obsidian_ai_hub --merge-inbox
```

毎時 0 分:

```yaml
- id: hourly_example
  enabled: true
  schedule:
    type: hourly
    minute: 0
  command: echo "hello"
```

毎週月曜 8:00、15 分おき（平日 8〜18 時）:

```yaml
- id: weekday_morning
  enabled: true
  schedule:
    type: weekly
    weekday: 0
    hour: 8
    minute: 0
  command: echo "monday"
```

## コマンドの実行規則

- コマンドはシェルを介さず、`&&` で区切って `shlex` でトークン化されます。
- `cd /path && ...` で作業ディレクトリを変更できます。
- パイプ・リダイレクト・環境変数展開などのシェル演算子は解釈されません。
- 空のコマンド、空のセグメント、末尾の `&&` はエラーです。

## Workflow 対象

`command` の代わりに `workflow: {workflow_id, inputs}` を指定すると、発火時に最新の公開 Revision で Run を作成します。

- 入力は発火時の `inputs_schema` で検証されます。不整合・公開版不在では Run を作らず、当該枠を消費します（コマンド Job とは異なり再試行しません）。
- 固定入力は平文で保存されます。秘密値を含めないでください。
- 発火枠は `workflow_schedule_dispatches` に記録され、同一枠で Run は高々 1 件です。

## 実行状態

- 最終実行時刻は `jobs/last_run.json` に保存されます。
- 追加・再有効化・対象（command / workflow と入力）/スケジュール変更時は保存時刻で arming され、過去の枠を遡って実行しません。
- コマンド失敗時は `last_run` を更新せず、後続サイクルで再試行します。Workflow の発火失敗は枠を消費し、次回枠で再評価します。
- 構造化保存では `jobs.local.yml` のコメントは保持されません。

## 次に読む

- [ジョブ管理](../features/jobs.md)
- [CLI リファレンス](cli.md)
