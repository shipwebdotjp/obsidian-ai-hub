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
  # 相対 source_path（画像編集の入力）を解決する基準。既定は Vault。
  # input_dir: /path/to/your/input-images
  model: gpt-image-2.5-sunburst
  default_size: 1024x1024
  default_quality: low
  max_count: 4
  max_input_bytes: 8388608
  # AIエージェント / Task Agent からの呼び出しでは quality を llm_quality に固定する
  lock_llm_quality: true
  llm_quality: low
  timeout_seconds: 180
```

`.env` で上書きできます。

- `IMAGE_GENERATION_OUTPUT_DIR` — 保存先ディレクトリ
- `IMAGE_GENERATION_INPUT_DIR` — 画像編集の相対パス入力の基準ディレクトリ
- `IMAGE_GENERATION_MODEL` — 使用する画像モデル
- `IMAGE_GENERATION_DEFAULT_SIZE` / `IMAGE_GENERATION_DEFAULT_QUALITY`
- `IMAGE_GENERATION_MAX_COUNT` / `IMAGE_GENERATION_MAX_INPUT_BYTES`
- `IMAGE_GENERATION_LOCK_LLM_QUALITY` / `IMAGE_GENERATION_LLM_QUALITY`

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

## LLM による品質の上書きを制限する

AIエージェントや Task Agent の会話では、LLM がツールの引数を決めるため、指定しないと
`quality: high` を選びがちです。`image_generation.lock_llm_quality: true`（既定）のとき、
**LLM 主導の呼び出しでは `quality` を無視**し、`image_generation.llm_quality`（既定 `low`）
に固定します。

- 対象: AIエージェントの会話、Task Agent（詳細入力を実行時に LLM が生成するため）。
- 対象外: ワークフローの Capability Node や、`media_id` などを明示指定する直接呼び出し
  （人間が設計した明示入力のため制限しません）。
- LLM に選ばせたい場合は `lock_llm_quality: false` にします。

## 画像を編集する（`image_edit`）

既存の画像を、プロンプトで編集・加工するツールです。生成と同じく Agent / Task /
ワークフローから利用でき、既定の承認ポリシーは `plan_required` です。

入力画像は次のいずれか1つで指定します。

| 入力モード | 使い方 | 説明 |
| --- | --- | --- |
| `use_current_attachment` | 会話 | そのターンでユーザーが添付した画像を編集します。 |
| `source_path` | Task / ワークフロー | サーバーが読める画像パス。相対パスは `input_dir`（既定 Vault）基準、絶対パスは許可ルート（Vault / 出力先 / `input_dir`）内に限ります。 |
| `source_media_id` | すべて | 生成済み・アップロード済み・取り込み済みの `media_id` を指定します。 |

- 共通の任意入力: `mask_media_id` / `mask_path`（編集する領域を指定するマスク画像）、
  `size`、`quality`、`output_format`、`input_fidelity`、`background`、`count`。
- 取り込んだ入力画像もメディアとして保存され、`media_id` で再利用できます。同じ内容の画像は
  重複して保存されません（内容ハッシュで判定）。
- 生成物には由来（どの `media_id` を編集したか）が記録されます。

## 結果の表示とダウンロード

ツールは画像そのものではなく、`media_id` を含む参照を返します。

- エージェントの「ツール呼び出し」、Task Agent の Action 履歴 / 実行Event、ワークフローの
  Node 出力に、画像と **ダウンロード** ボタンが表示されます。
- 画像は認証付きの `GET /api/v1/media/{media_id}` で配信されます。ブラウザは
  トークン付きで取得し、オブジェクト URL として表示します。

## 削除とライフサイクル

生成物は親（会話 / Task / Workflow 実行）の削除に連動して削除されます。

- **会話**: セッションを削除すると、そのセッションで生成した画像の行とファイルが削除されます。
- **Task**: 終端タスクの既存パージ（既定30日）に連動して削除されます。
- **ワークフロー**: 実行（Run）を削除すると、その Run が生成した画像が削除されます。
- 対象は**生成物（`source='generated'`）のみ**です。会話の添付やパス取込などの**入力**は
  共有・再利用され得るため残ります。
- 手動削除は `DELETE /api/v1/media/{media_id}`（API）で行えます。ギャラリー（今後追加）の
  削除 UI はこれを使う予定です。
- 長く残したい成果物は Vault へコピーしてください（今後追加予定）。クラッシュ由来の
  孤児ファイルの自動回収は今後の対応です。

## 安全と再実行

- 保存パスはサーバーが生成し、保存先ルートの外へは書き込めません（絶対パス・`..`・
  シンボリックリンクによる脱出を拒否）。
- 画像編集の `source_path` / `mask_path` は許可ルート（Vault / 出力先 / `input_dir`）内の
  通常ファイルだけを読みます。入力は PNG / JPEG / WebP に限り、寸法・サイズ上限を検証します。
- ファイルを書き込んだ後に DB 記録に失敗した場合は、書き込んだファイルを削除して
  中途半端な状態を残しません。
- 1回の呼び出しは新しい `media_id` を1つ以上作ります。同じプロンプトの再実行は
  既存の画像を上書きせず、別の画像として保存されます。

## 次に読む

- [AIエージェント](agents.md)
- [Task Agent](task-agent.md)
- [ワークフロー](../workflow/index.md)
