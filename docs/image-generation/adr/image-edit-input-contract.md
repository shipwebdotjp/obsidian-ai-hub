# 画像編集の入力契約（media_id 正本 + 入口での自動取り込み）

## Status

Accepted (2026-09-26)

## Context

`image_generate` に続いて画像編集（image-to-image）を追加する。会話には画像添付があり
（`agent_messages.attachments_json` に base64、`agents/runtime.py:_build_user_message` が LLM 入力に使う）、
Task / Workflow はファイルパスや既存メディアを入力にしたい。入力画像の与え方には次の3案があった
（比較は [ロードマップ R1](../../../docs/image-generation/roadmap.md)）。

- A. 添付/パスをそのまま provider へ送る（入力が正本化されず、任意ファイル読取の面が広がる）。
- B. 事前アップロード + DB 登録を必須にし `media_id` だけを受け取る（会話 UX が悪く、Task/Workflow に余分な往復）。
- C. `media_id` を正本にしつつ、入口（添付 / パス）で自動取り込みする。

ツール引数は JSON で 2,000/20,000 文字に切り詰められるため、base64 を引数に載せられない。
provider の `images.edit` は生バイト列を必要とする。ファイル削除が必要で、行だけでは入力を
参照できない。

## Decision

1. **正本と識別子**: 編集の入力・出力はすべて `generated_media` の `media_id` で扱う。
   入力は `source`（`upload` = 会話添付 / `import` = パス取込 / `generated` = 生成物）で区別し、
   `content_sha256` で再取り込みを重複排除する（migration v67。単一ライタ前提の best-effort で、
   厳密な一意性が必要になれば UNIQUE 制約と競合処理を追加する）。
2. **入力モード（`ImageEditInput` の単一正本、いずれか1つ必須）**:
   - `use_current_attachment=true`（会話）: trusted ctx の `user_message_id` →
     `agents/store.get_message` の画像添付を採用。
   - `source_path`（Task/Workflow）: 許可ルート配下のみ。相対パスは
     `image_generation.input_dir`（既定 Vault）基準、絶対パスは許可ルート内に限定。
   - `source_media_id`: 既存メディアを再利用。
   - 任意の `mask_media_id` / `mask_path`。`prompt` は必須。base64 は引数に載せない。
3. **取り込み層（`media/ingest.py`）**: 上記を必ず `generated_media` の行に正規化してから
   `media/generation.py:edit_images` を呼ぶ。許可ルートは `VAULT_PATH` /
   `IMAGE_GENERATION_OUTPUT_DIR` / `IMAGE_GENERATION_INPUT_DIR`。`..`・NUL・シンボリックリンク脱出・
   非正規ファイル・サイズ超過を拒否し、Pillow で形式（PNG/JPEG/WebP）・寸法・
   `Image.MAX_IMAGE_PIXELS` を検証する。
4. **出力**: `image_generate` と共通の保存・失敗補償（DB 失敗時にファイル削除）を使い、
   `metadata_json` に `{"operation":"edit","source_media_id":...}` を記録する。
   provider 失敗時は出力行を作らない（取り込んだ入力は再利用のため残す）。
5. **ポリシー**: Task Capability の既定承認は `plan_required`（外部送信 + 書込み + パス読取）。

## Operation-scenario contract

| 段階 | 入力と正本 | 機械可読な識別子 | 永続化 | 次に読む主体 | 停止・失敗時 | 不可逆操作 |
| --- | --- | --- | --- | --- | --- | --- |
| 入力検証 | 添付(base64) / `source_path` / `source_media_id` | 内容 SHA-256 / `media_id` | なし | 本サービス | 形式・寸法・サイズ不正、許可ルート外、source 複数指定は provider 前に停止 | なし |
| 取込 | 検証済みバイト列 | サーバー生成 `media_id` | 出力ディレクトリ + `generated_media` 行 (source=upload/import) | image_edit / ギャラリー | 同一 SHA-256 が既存なら再書込みしない | アプリ外ファイル書込み |
| 編集 | 取込済み入力 + prompt | `media_id` | provider 応答はメモリ | 保存 | provider 失敗は出力を作らない | 外部APIへ1回送信 |
| 保存 | 出力バイト列 | `media_id` | 出力ファイル + `generated_media` 行 (source=generated) | serving route / UI | DB 失敗時はファイル削除 | アプリ外ファイル書込み |
| 参照 | クライアントの `media_id` | DB 行が正本 | なし | browser | 未知 id / containment 失敗は 404 | なし |

## Alternatives

- **A（パス/添付をそのまま送る）**: 実装は軽いが、来歴・ギャラリーが不統一になり、パスが唯一の
  識別子として任意ファイル読取の面が広がる。
- **B（事前登録必須）**: 正本は統一できるが、会話 UX が悪く、Task/Workflow に登録の往復と
  余分な承認が増える。事前登録の自動化（案 C）で B の利点だけを残せる。
- **別テーブル `uploaded_media` を新設**: `generated_media` を type で一般化する方が
  配信・ギャラリー・削除を1経路にできるため不採用。

## Consequences

- 会話の添付・Task/Workflow のパス入力もギャラリーに載り、削除（R3）は親連動で扱える。
- 添付は会話履歴（LLM 再送用）と出力ディレクトリの双方に保持され、`content_sha256` で
  再取り込みの重複を抑える。
- 相対パスは `input_dir`（既定 Vault）基準。`input_dir` を増やすと許可ルートも増えるため、
  設定変更は読取可能範囲の変更として扱う。
- 画像の実体再エンコード・EXIF 除去・モデレーション分類は未実装（[R9](../../../docs/image-generation/roadmap.md)）。
