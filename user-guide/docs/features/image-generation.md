---
sidebar_position: 4
title: 画像生成
---

# 画像生成

`image_generate` は、テキストプロンプトから画像を生成して保存するツールです。
**AIエージェント** の会話、**Task Agent**、**ワークフロー**の Capability Node から
同じツールとして利用できます。生成した画像は実行画面にインライン表示され、
その場でダウンロードできます。

## 有効にする

- **AIエージェント**: エージェント編集の「利用するツール」で **画像生成** を選びます。
- **Task Agent / ワークフロー**: Capability として自動的に追加されます。既定の承認
  ポリシーは `plan_required`（計画承認が必要）です。Capability 設定画面で
  `enabled` と承認ポリシーを変更できます。
- API キーは `OPENAI_API_KEY` を使用します。

## 保存先の設定

画像は `config/config.yml` の `image_generation.output_dir` に保存されます。既定は
Vault の外（`~/.config/obsidian-ai-hub/media`）です。Vault のサブフォルダを指定すると、
Obsidian からも画像を閲覧できます（Vault が重くなる場合は外のままにしてください）。

```yaml
image_generation:
  output_dir: /path/to/your/obsidian-ai-hub/media
  model: gpt-image-2.5-sunburst
  default_size: 1024x1024
  default_quality: low
  max_count: 4
  timeout_seconds: 180
```

`.env` で上書きできます。

- `IMAGE_GENERATION_OUTPUT_DIR` — 保存先ディレクトリ
- `IMAGE_GENERATION_MODEL` — 使用する画像モデル
- `IMAGE_GENERATION_DEFAULT_SIZE` / `IMAGE_GENERATION_DEFAULT_QUALITY`
- `IMAGE_GENERATION_MAX_COUNT`

## ツールの入力

| 入力 | 既定 | 説明 |
| --- | --- | --- |
| `prompt` | 必須 | 生成したい画像の説明。被写体・画風・構図・雰囲気を具体的に書きます。 |
| `size` | `1024x1024` | 出力サイズ。`1024x1024`（最小） / `1536x1024`（横） / `1024x1536`（縦） / `auto`。 |
| `quality` | `low` | 描画品質。`low` / `medium` / `high` / `auto`。 |
| `output_format` | `png` | `png` / `jpeg` / `webp`。 |
| `count` | `1` | 生成枚数（1〜`max_count`）。 |
| `background` | 未指定 | `opaque` / `transparent` / `auto`（モデルが対応する場合）。 |

既定は低品質・最小サイズです。品質やサイズを上げるとコストと生成時間が増えます。

:::note[モデル名と最小サイズ]
OpenAI 側には `gpt-image-2.5` というエイリアスは存在せず、`gpt-image-2.5-sunburst` /
`gpt-image-2.5-flare` などのバリアント名が必要です。環境に合わせて
`image_generation.model` を設定してください。また `512x512` は最小ピクセル数を下回るため
受け付けられず、指定できる最小サイズは `1024x1024` です。
:::

## 結果の表示とダウンロード

ツールは画像そのものではなく、`media_id` を含む参照を返します。

- エージェントの「ツール呼び出し」、Task Agent の Action 履歴 / 実行Event、ワークフローの
  Node 出力に、画像と **ダウンロード** ボタンが表示されます。
- 画像は認証付きの `GET /api/v1/media/{media_id}` で配信されます。ブラウザは
  トークン付きで取得し、オブジェクト URL として表示します。

## 安全と再実行

- パスはサーバーが生成し、保存先ルートの外へは書き込めません（絶対パス・`..`・
  シンボリックリンクによる脱出を拒否）。
- ファイルを書き込んだ後に DB 記録に失敗した場合は、書き込んだファイルを削除して
  中途半端な状態を残しません。
- 1回の呼び出しは新しい `media_id` を1つ以上作ります。同じプロンプトの再実行は
  既存の画像を上書きせず、別の画像として保存されます。

## 次に読む

- [AIエージェント](agents.md)
- [Task Agent](task-agent.md)
- [ワークフロー](../workflow/index.md)
