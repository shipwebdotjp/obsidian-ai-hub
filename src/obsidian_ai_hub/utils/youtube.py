"""YouTube transcript extraction with progressively more expensive fallbacks."""

from __future__ import annotations

from dataclasses import dataclass
import html
import logging
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class YouTubeContent:
    video_id: str
    title: str | None
    published_at: str | None
    transcript: str | None
    transcript_source: str


def extract_video_id(url: str) -> str | None:
    """Return a video ID for the public YouTube URL forms we support."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if host in {"youtu.be", "www.youtu.be"}:
        return path_parts[0] if path_parts else None

    youtube_hosts = {
        "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    }
    if host not in youtube_hosts:
        return None

    if parsed.path == "/watch":
        return parse_qs(parsed.query).get("v", [None])[0]
    if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live"}:
        return path_parts[1]
    return None


def is_youtube_url(url: str) -> bool:
    return extract_video_id(url) is not None


def _format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_timestamped_transcript(items: list[Any]) -> str:
    """Format transcript snippets from either caption provider or Whisper."""
    lines: list[str] = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("text", "")
            start = item.get("start", 0)
        else:
            text = getattr(item, "text", "")
            start = getattr(item, "start", 0)
        text = " ".join(str(text).split())
        if not text:
            continue
        try:
            timestamp = _format_timestamp(float(start))
        except (TypeError, ValueError):
            timestamp = "00:00:00"
        lines.append(f"[{timestamp}] {text}")
    return "\n".join(lines)


def _fetch_transcript_api(video_id: str) -> str | None:
    """Prefer manual captions, then generated captions, in configured languages."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        transcripts = api.list(video_id)
        for finder_name in (
            "find_manually_created_transcript",
            "find_generated_transcript",
        ):
            try:
                transcript = getattr(transcripts, finder_name)(
                    config.YOUTUBE_TRANSCRIPT_LANGUAGES
                )
                text = format_timestamped_transcript(list(transcript.fetch()))
                if text:
                    return text
            except Exception:
                logger.debug("YouTube %s captions unavailable for %s", finder_name, video_id)
    except Exception:
        logger.info("youtube-transcript-api failed for %s", video_id, exc_info=True)
    return None


def _metadata_from_info(info: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not info:
        return None, None
    title = info.get("title")
    published_at = info.get("upload_date") or info.get("release_date")
    return (str(title) if title else None, str(published_at) if published_at else None)


def _get_video_metadata(url: str) -> tuple[str | None, str | None]:
    try:
        from yt_dlp import YoutubeDL

        with YoutubeDL({"quiet": True, "noplaylist": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return _metadata_from_info(info)
    except Exception:
        logger.info("yt-dlp metadata lookup failed for %s", url, exc_info=True)
        return None, None


def _parse_vtt(vtt_content: str) -> str:
    """Convert VTT cues to timestamped text without markup or duplicate lines."""
    lines: list[str] = []
    cue_start: str | None = None
    cue_text: list[str] = []

    def flush() -> None:
        nonlocal cue_start, cue_text
        if cue_start is None:
            return
        text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(cue_text)))
        text = " ".join(text.split())
        if text:
            lines.append(f"[{cue_start}] {text}")
        cue_start = None
        cue_text = []

    for raw_line in vtt_content.splitlines():
        line = raw_line.strip()
        if " --> " in line:
            flush()
            start = line.split(" --> ", 1)[0].strip().replace(",", ".")
            match = re.match(r"(?:(\d+):)?(\d{2}):(\d{2})(?:\.\d+)?", start)
            if match:
                hours = int(match.group(1) or 0)
                cue_start = f"{hours:02d}:{int(match.group(2)):02d}:{int(match.group(3)):02d}"
            continue
        if not line:
            flush()
        elif cue_start is not None and not line.startswith(("WEBVTT", "NOTE", "STYLE")):
            cue_text.append(line)
    flush()
    return "\n".join(dict.fromkeys(lines))


def _fetch_yt_dlp_subtitles(url: str, video_id: str) -> str | None:
    try:
        from yt_dlp import YoutubeDL

        with tempfile.TemporaryDirectory(prefix="obsidian-youtube-subtitles-") as tmpdir:
            output_template = str(Path(tmpdir) / "%(id)s.%(ext)s")
            options = {
                "quiet": True,
                "noplaylist": True,
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": config.YOUTUBE_TRANSCRIPT_LANGUAGES,
                "subtitlesformat": "vtt",
                "outtmpl": output_template,
            }
            with YoutubeDL(options) as ydl:
                ydl.extract_info(url, download=True)

            vtt_files = list(Path(tmpdir).glob(f"{video_id}*.vtt"))
            for language in config.YOUTUBE_TRANSCRIPT_LANGUAGES:
                preferred = [path for path in vtt_files if f".{language}." in path.name]
                if preferred:
                    vtt_files = preferred + [path for path in vtt_files if path not in preferred]
                    break
            for vtt_file in vtt_files:
                transcript = _parse_vtt(vtt_file.read_text(encoding="utf-8"))
                if transcript:
                    return transcript
    except Exception:
        logger.info("yt-dlp subtitle extraction failed for %s", url, exc_info=True)
    return None


def _transcribe_with_whisper(url: str, video_id: str) -> str | None:
    try:
        from yt_dlp import YoutubeDL
        import whisper

        with tempfile.TemporaryDirectory(prefix="obsidian-youtube-audio-") as tmpdir:
            output_template = str(Path(tmpdir) / "%(id)s.%(ext)s")
            with YoutubeDL(
                {
                    "quiet": True,
                    "noplaylist": True,
                    "format": "bestaudio/best",
                    "outtmpl": output_template,
                }
            ) as ydl:
                info = ydl.extract_info(url, download=True)
                audio_path = Path(ydl.prepare_filename(info))
            if not audio_path.exists():
                candidates = [path for path in Path(tmpdir).iterdir() if path.stem == video_id]
                if not candidates:
                    return None
                audio_path = candidates[0]

            model = whisper.load_model(config.YOUTUBE_WHISPER_MODEL)
            result = model.transcribe(audio_path.as_posix())
            return format_timestamped_transcript(result.get("segments") or [])
    except Exception:
        logger.info("Whisper transcription failed for %s", url, exc_info=True)
    return None


def extract_youtube_content(url: str) -> YouTubeContent:
    """Extract metadata and a timestamped transcript without raising to inbox merge."""
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"Not a supported YouTube URL: {url}")

    title, published_at = _get_video_metadata(url)
    transcript = _fetch_transcript_api(video_id)
    if transcript:
        return YouTubeContent(video_id, title, published_at, transcript, "youtube-transcript-api")

    transcript = _fetch_yt_dlp_subtitles(url, video_id)
    if transcript:
        return YouTubeContent(video_id, title, published_at, transcript, "yt-dlp")

    transcript = _transcribe_with_whisper(url, video_id)
    if transcript:
        return YouTubeContent(video_id, title, published_at, transcript, "whisper")

    return YouTubeContent(video_id, title, published_at, None, "unavailable")
