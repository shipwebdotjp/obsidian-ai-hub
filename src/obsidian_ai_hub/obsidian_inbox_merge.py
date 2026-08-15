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
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import whisper

from obsidian_ai_hub.handler import add_research_theme, web_extract
from obsidian_ai_hub.utils import (
    config,
    extracter,
    llm_client,
    prompt,
    webclip,
    youtube,
)

logger = logging.getLogger(__name__)

# 処理対象の拡張子
MARKDOWN_EXTENSIONS = {".md"}
AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav"}


def extract_urls(text: str) -> list[str]:
    """
    Extract and deduplicate URLs from text with light normalization.
    """
    # Regex to find URLs
    url_pattern = re.compile(r"https?://[^\s)\]]+")
    found_urls = url_pattern.findall(text)

    normalized_urls = []
    seen = set()
    for url in found_urls:
        # Light normalization: strip trailing punctuation
        normalized = url.rstrip(".,;)]")
        if normalized not in seen:
            normalized_urls.append(normalized)
            seen.add(normalized)

    return normalized_urls


def infer_title(url: str, raw_content: str) -> str:
    """
    Infer a title from raw content or fall back to URL-derived label.
    """
    if raw_content:
        # Look for the first non-empty line
        for line in raw_content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("http"):
                # Limit title length
                if len(stripped) > 100:
                    return stripped[:97] + "..."
                return stripped

    # Fallback to URL-derived label
    parsed = urlparse(url)
    domain = parsed.netloc
    path = parsed.path.rstrip("/")
    if path:
        return f"{domain}{path}"
    return domain


def generate_web_summary(raw_content: str) -> str:
    """
    Generate a concise summary of the web content using LLM.
    """
    if not raw_content:
        return ""

    try:
        rendered_prompt = prompt.render_prompt(
            config.INBOX_WEB_SUMMARY_PROMPT_PATH, {"raw_content": raw_content}
        )
        response = llm_client.generate_llm_response(
            provider=config.INBOX_WEB_SUMMARY_PROVIDER,
            model=config.INBOX_WEB_SUMMARY_MODEL,
            prompt=rendered_prompt,
            temperature=0.3,
            max_tokens=4096,
        ).strip()
        # 改行
        response = response.replace("\n", "\n  ")
        return response
    except Exception:
        logger.exception("Failed to generate web summary")
        return ""


def process_web_clips(urls: list[str], daily_file: Path, hour_str: str) -> None:
    """
    Process a list of URLs, extract content, summarize as a webclip, and append to daily note.
    """
    if not urls:
        return

    # Determine clipped_at_str using system local timezone
    if re.match(r"^\d{4}-\d{2}-\d{2}$", daily_file.stem):
        try:
            local_dt = datetime.strptime(
                f"{daily_file.stem} {hour_str}", "%Y-%m-%d %H:%M"
            )
            clipped_at_str = local_dt.astimezone().isoformat()
        except Exception:
            clipped_at_str = datetime.now().astimezone().isoformat()
    else:
        clipped_at_str = datetime.now().astimezone().isoformat()

    all_entries = []
    extracted: dict[str, dict] = {}

    youtube_urls = [url for url in urls if youtube.is_youtube_url(url)]
    regular_urls = [url for url in urls if url not in youtube_urls]

    for url in youtube_urls:
        try:
            video = youtube.extract_youtube_content(url)
            extracted[url] = {
                "raw_content": video.transcript,
                "title": video.title,
                "content_type": "youtube",
                "extra_frontmatter": {
                    "video_id": video.video_id,
                    "transcript_source": video.transcript_source,
                },
                "published_at": video.published_at,
            }
        except Exception:
            logger.exception("Failed to process YouTube URL: %s", url)
            extracted[url] = {
                "raw_content": None,
                "title": None,
                "content_type": "youtube",
                "extra_frontmatter": {
                    "video_id": youtube.extract_video_id(url),
                    "transcript_source": "unavailable",
                },
                "published_at": None,
            }

    # Chunk URLs into batches of 20
    for i in range(0, len(regular_urls), 20):
        batch = regular_urls[i : i + 20]
        results = []
        try:
            results_json = web_extract.web_extract.invoke({"urls": batch})
            results = json.loads(results_json).get("results", [])
        except Exception:
            logger.exception("Failed to invoke web_extract")
            results = []

        result_map = {}
        if isinstance(results, list):
            for r in results:
                if isinstance(r, dict) and r.get("url"):
                    result_map[r["url"]] = r

        for url in batch:
            extracted[url] = result_map.get(url) or {}

    for url in urls:
        result = extracted.get(url) or {}
        entry = webclip.process_single_webclip(
            url=url,
            raw_content=result.get("raw_content"),
            extracted_title=result.get("title"),
            hour_str=hour_str,
            daily_file=daily_file,
            clipped_at_str=clipped_at_str,
            content_type=result.get("content_type"),
            extra_frontmatter=result.get("extra_frontmatter"),
            deterministic_published_at=result.get("published_at"),
        )
        all_entries.append(entry)

    if all_entries:
        extracter.append_to_subheader_file(
            daily_file.as_posix(), "## 📝メモ", all_entries
        )


@dataclass(frozen=True)
class InboxClassification:
    category: str
    calendar_event: dict | None = None
    reminder: dict | None = None


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
        with open(file_path, "rb") as f:
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


def _parse_effective_dt(daily_file: Path, hour_str: str) -> datetime:
    if re.match(r"^\d{4}-\d{2}-\d{2}$", daily_file.stem):
        try:
            return datetime.strptime(
                f"{daily_file.stem} {hour_str}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            pass
    return datetime.now()


def _build_classification_prompt(
    content: str, effective_dt: datetime | None = None
) -> str:
    if effective_dt is None:
        effective_dt = datetime.now()
    return prompt.render_prompt(
        config.INBOX_CLASSIFICATION_PROMPT_PATH,
        {
            "content": content,
            "today": effective_dt.strftime("%Y-%m-%d"),
            "created_at": effective_dt.strftime("%Y-%m-%d %H:%M"),
        },
    )


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

    if category == "calendar":
        event = payload.get("calendar_event")
        if not isinstance(event, dict) or not event.get("title") or not event.get(
            "start_time"
        ):
            raise ValueError(
                "calendar category requires calendar_event with title and start_time"
            )
        _validate_calendar_event_times(event)
        return InboxClassification(category="calendar", calendar_event=event)

    if category == "reminder":
        reminder = payload.get("reminder")
        if not isinstance(reminder, dict) or not str(reminder.get("title") or "").strip():
            raise ValueError(
                "reminder category requires reminder with a non-empty title"
            )
        _validate_reminder_due_date(reminder)
        return InboxClassification(category="reminder", reminder=reminder)

    raise ValueError(f"Unknown classification category: {category}")


def _validate_calendar_event_times(event: dict) -> None:
    """
    Validate that start_time/end_time parse as ISO datetimes so malformed LLM
    output fails fast (falling back to memo) instead of creating an approval
    run whose event cannot be added later.
    """
    for field in ("start_time", "end_time"):
        value = event.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"calendar_event.{field} must be a string")
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"calendar_event.{field} is not a valid ISO datetime: {value!r}"
            ) from exc


def _validate_reminder_due_date(reminder: dict) -> None:
    """
    Validate that due_date parses as an ISO datetime so malformed LLM output
    fails fast (falling back to memo) instead of creating an approval run
    whose reminder cannot be added later. A blank due_date is treated the same
    as None (no due date), matching add_reminder and the reminder HITL helpers.
    """
    due_date = reminder.get("due_date")
    if not due_date:
        return
    if not isinstance(due_date, str):
        raise ValueError("reminder.due_date must be a string")
    try:
        datetime.fromisoformat(due_date)
    except ValueError as exc:
        raise ValueError(
            f"reminder.due_date is not a valid ISO datetime: {due_date!r}"
        ) from exc


def classify_inbox_content(
    content: str, effective_dt: datetime | None = None
) -> InboxClassification:
    try:
        rendered_prompt = _build_classification_prompt(content, effective_dt)
        response = llm_client.generate_llm_response(
            provider=config.INBOX_CLASSIFICATION_PROVIDER,
            model=config.INBOX_CLASSIFICATION_MODEL,
            prompt=rendered_prompt,
            temperature=0.0,
            max_tokens=4096,
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
    urls = extract_urls(content)
    if urls:
        process_web_clips(urls, daily_file, hour_str)
        return "web"

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
        extracter.append_to_subheader_file(
            daily_file.as_posix(), subheader, [content_to_merge]
        )
        return "location"

    effective_dt = _parse_effective_dt(daily_file, hour_str)
    classification = classify_inbox_content(content, effective_dt)
    if classification.category == "research":
        add_research_theme.append_research_theme(content)
    elif classification.category == "calendar" and classification.calendar_event:
        try:
            from obsidian_ai_hub.calendar import register_calendar_event_approval

            run_id = register_calendar_event_approval(
                content=content,
                event=classification.calendar_event,
            )
            if run_id:
                logger.info(
                    "Registered calendar approval HITL run: %s", run_id
                )
        except Exception:
            logger.exception("Failed to register calendar approval HITL run")
    elif classification.category == "reminder" and classification.reminder:
        try:
            from obsidian_ai_hub.reminders import register_reminder_approval

            run_id = register_reminder_approval(
                content=content,
                reminder=classification.reminder,
            )
            if run_id:
                logger.info(
                    "Registered reminder approval HITL run: %s", run_id
                )
        except Exception:
            logger.exception("Failed to register reminder approval HITL run")

    subheader = "## 📝メモ"
    content_to_merge = f"- {hour_str} [{classification.category}] {content}"
    extracter.append_to_subheader_file(
        daily_file.as_posix(), subheader, [content_to_merge]
    )
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
                    logger.warning(
                        "Timeout waiting for iCloud download: %s", inbox_file.name
                    )
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
                with open(inbox_file, "rb") as src, open(tmp_path, "wb") as dst:
                    dst.write(src.read())

                model = whisper.load_model("medium")  # または"medium", "small"
                result = model.transcribe(tmp_path.as_posix(), language="ja")
                raw_content = result["text"]
                try:
                    rendered_prompt = prompt.render_prompt(
                        config.INBOX_TRANSCRIPT_CORRECTION_PROMPT_PATH,
                        {"raw_content": raw_content},
                    )
                    response = llm_client.generate_llm_response(
                        provider=config.INBOX_AUDIO_CORRECTION_PROVIDER,
                        model=config.INBOX_AUDIO_CORRECTION_MODEL,
                        prompt=rendered_prompt,
                        max_tokens=8192,
                    ).strip()
                except Exception:
                    logger.exception("LLM correction failed, using raw content")
                    response = raw_content
                content = response
                if not content:
                    content = raw_content
            except Exception:
                logger.exception("Error transcribing audio file")
                if "tmp_path" in locals():
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                continue

        # 一時ファイルのクリーンアップ（オーディオ処理用）
        if ext in AUDIO_EXTENSIONS and "tmp_path" in locals():
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
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
