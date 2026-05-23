#!/usr/bin/env python3
# ObsidianのInboxにあるファイルをマージしてDailyNoteに追加するスクリプト
# 2025/04/24

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import whisper

from obsidian_ai_hub.handler import add_research_theme
from obsidian_ai_hub.utils import config, extracter, llm_client

logger = logging.getLogger(__name__)

# 処理対象の拡張子
MARKDOWN_EXTENSIONS = {".md"}
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav"}

@dataclass(frozen=True)
class InboxClassification:
    category: str

def is_icloud_offloaded(file_path: Path) -> bool:
    """
    iCloud Driveでオンラインのままのファイルかどうかを確認。
    ファイルを直接開いてみて、エラーが出ればダウンロードが必要。
    """
    try:
        # ファイルサイズが極端に小さいかチェック（0バイトなど）
        stat = file_path.stat()
        if stat.st_size == 0:
            return True
            
        # ファイルを読み込みモードで開いて、OSにダウンロードを強制させる
        with open(file_path, 'rb') as f:
            # 先頭1バイトだけ読んでみる（実際の読み込み）
            f.read(1)
        return False
    except (OSError, IOError):
        # ファイルが開けなければダウンロード中かオンデマンドファイル
        return True


def wait_for_icloud_download(file_path: Path, timeout: int = 60) -> bool:
    """
    iCloudファイルがダウンロード完了するまで待機。
    """
    import time

    start = time.time()
    while time.time() - start < timeout:
        if not is_icloud_offloaded(file_path):
            return True
        time.sleep(0.5)
    return False


def _build_classification_prompt(content: str) -> str:
    return f"""
あなたは Obsidian の Inbox 内容を分類するアシスタントです。

次の2択で分類してください。
- research: 「リサーチしてほしい」「調べたい」「検討したい」といった意図が内容から読み取れる
- memo: 上記以外

ルール:
- 出力は JSON だけにしてください
- 余計な説明、前置き、コードフェンスは禁止です

出力形式:
{{"category":"research"}} または {{"category":"memo"}}

--- Inbox content ---
{content}
--- end ---
""".strip()


def _extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in LLM response")

    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON is not an object")
    return payload


def parse_classification_response(text: str) -> InboxClassification:
    payload = _extract_json_object(text)
    category = str(payload.get("category", "")).strip().lower()

    if category == "research":
        return InboxClassification(category="research")

    if category == "memo":
        return InboxClassification(category="memo")

    raise ValueError(f"Unknown classification category: {category}")


def classify_inbox_content(content: str) -> InboxClassification:
    prompt = _build_classification_prompt(content)
    try:
        response = llm_client.generate_llm_response(
            provider="openai",
            model=config.RESEARCH_PROMPT_MODEL,
            prompt=prompt,
            temperature=0.0,
            max_tokens=256,
        ).strip()
        return parse_classification_response(response)
    except Exception:
        logger.exception("LLM classification failed, falling back to memo")
        return InboxClassification(category="memo")


def merge_content_into_daily_note(
    content: str,
    daily_file: Path,
    hour_str: str,
) -> str:
    location = extracter.get_frontmatter_value(content, "location")
    if location:
        subheader = "## 📍今日の移動"
        location_name = location
        location_map = config.LOCATION_MAP
        for key, value in location_map.items():
            if key in location:
                location_name = value
                break
        content_to_merge = f"- {hour_str} {location_name}"
        extracter.append_to_subheader_file(daily_file.as_posix(), subheader, [content_to_merge])
        return "location"

    classification = classify_inbox_content(content)
    if classification.category == "research":
        add_research_theme.append_research_theme(content)

    subheader = "## 📝メモ"
    content_to_merge = f"- {hour_str} [{classification.category}] {content}"
    extracter.append_to_subheader_file(daily_file.as_posix(), subheader, [content_to_merge])
    return classification.category


def main():
    if not config.INBOX_PATH.exists():
        logger.error("config.INBOX_PATH not found")
        return

    # 現在の日付時刻を出力
    # now = datetime.now()
    # print(f"Current time: {now}")

    # Inbox ディレクトリ内のファイルを処理
    for inbox_file in config.INBOX_PATH.iterdir():
        if not inbox_file.is_file():
            continue

        ext = inbox_file.suffix.lower()
        if ext not in MARKDOWN_EXTENSIONS and ext not in AUDIO_EXTENSIONS:
            continue

        # iCloud Driveでオンラインのままのファイルはダウンロード
        if is_icloud_offloaded(inbox_file):
            logger.info("Downloading (iCloud online-only): %s", inbox_file.name)
            try:
                # subprocess.run(
                #     ["xattr", "-d", "com.apple.quarantine", inbox_file.as_posix()],
                #     check=True,
                # )
                subprocess.run(
                    [
                        "ditto",
                        "-rsrc",
                        inbox_file.as_posix(),
                        inbox_file.with_suffix(inbox_file.suffix + ".tmp"),
                    ],
                    check=True,
                )
                inbox_file.unlink()
                inbox_file.with_suffix(inbox_file.suffix + ".tmp").rename(inbox_file)
                if not wait_for_icloud_download(inbox_file):
                    logger.warning("Timeout waiting for iCloud download: %s", inbox_file.name)
                    continue
            except (subprocess.CalledProcessError, FileNotFoundError, OSError):
                logger.exception("Failed to download iCloud file: %s", inbox_file.name)
                continue
        else:
            logger.info("Processing local file: %s", inbox_file.name)

        logger.info("Processing inbox file: %s", inbox_file.name)

        # ファイルの作成日時を取得（macOS対応）
        try:
            stat_info = inbox_file.stat()
            # Birth time（作成日時）を取得
            dt = datetime.fromtimestamp(stat_info.st_birthtime)
        except (AttributeError, OSError):
            # st_birthtimeが存在しない場合は変更日時を使用
            stat_info = inbox_file.stat()
            dt = datetime.fromtimestamp(stat_info.st_mtime)

        # 09:00以前なら前日に調整
        if dt.hour < 9:
            dt = dt - timedelta(days=1)

        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        day_str = dt.strftime("%Y-%m-%d")
        hour_str = dt.strftime("%H:%M")

        # Daily ノートのパスを決定し、必要ならディレクトリを作成
        daily_dir = config.DAILY_PATH / year / month
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_file = daily_dir / f"{day_str}.md"

        # Daily note が存在しない場合はテンプレートから作成
        if not daily_file.exists():
            logger.info("Creating new daily note from template")
            try:
                template_content = config.TEMPLATE_PATH.read_text(encoding="utf-8")
            except Exception:
                logger.exception("Error reading template")
                continue
            daily_file.write_text(template_content, encoding="utf-8")

        # ファイル内容を読み込み
        if ext in MARKDOWN_EXTENSIONS:
            try:
                content = inbox_file.read_text(encoding="utf-8")
            except Exception:
                logger.exception("Error reading inbox file")
                continue
        elif ext in AUDIO_EXTENSIONS:
            try:
                # 一時ファイルにコピーしてから処理（iCloud/ファイルロック問題の回避）
                logger.info("Transcribing audio file: %s", inbox_file.name)
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                with open(inbox_file, 'rb') as src, open(tmp_path, 'wb') as dst:
                    dst.write(src.read())

                model = whisper.load_model("medium")  # または"medium", "small"
                result = model.transcribe(tmp_path.as_posix(), language="ja")
                raw_content = result["text"]
                prompt = f"""
                あなたは音声文字起こし補正専門エディタです。
                以下はWhisperで文字起こしした日本語テキストです。
                意味を変更してはいけません。
                推測で内容を追加してはいけません。
                削除も禁止です。
                誤認識・誤変換のみ修正してください。

                ---ここから---
                {raw_content}
                ---ここまで---
                """
                response = llm_client.generate_llm_response(
                    provider=config.INBOX_AUDIO_CORRECTION_PROVIDER,
                    model=config.INBOX_AUDIO_CORRECTION_MODEL,
                    prompt=prompt,
                ).strip()
                content = response
                if not content:
                    content = raw_content
            except Exception:
                logger.exception("Error transcribing audio file")
                if "tmp_path" in locals():
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except:
                        pass
                continue

        # 一時ファイルのクリーンアップ（オーディオ処理用）
        if ext in AUDIO_EXTENSIONS and "tmp_path" in locals():
            try:
                tmp_path.unlink(missing_ok=True)
            except:
                pass

        branch = merge_content_into_daily_note(content, daily_file, hour_str)
        logger.info("Routed inbox content as: %s", branch)
        if branch == "location":
            logger.info("Merged content into daily note")
        elif branch == "research":
            logger.info("Added research content from inbox: %s", inbox_file.name)
        else:
            logger.info("Merged content into daily note")

        # 本番では削除するが、動作確認中はコメントアウト
        os.remove(inbox_file)
        # print(f"  Removed inbox file: {inbox_file.name}")


if __name__ == "__main__":
    main()
