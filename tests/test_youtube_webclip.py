from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from obsidian_ai_hub import obsidian_inbox_merge
from obsidian_ai_hub.utils import config, webclip, youtube


def test_extract_video_id_supports_common_youtube_urls():
    video_id = "dQw4w9WgXcQ"
    urls = [
        f"https://www.youtube.com/watch?v={video_id}&feature=share",
        f"https://youtu.be/{video_id}",
        f"https://www.youtube.com/shorts/{video_id}",
        f"https://www.youtube.com/embed/{video_id}",
        f"https://www.youtube.com/live/{video_id}",
    ]

    assert [youtube.extract_video_id(url) for url in urls] == [video_id] * len(urls)
    assert not youtube.is_youtube_url("https://example.com/watch?v=dQw4w9WgXcQ")


def test_youtube_transcript_api_precedes_other_fallbacks():
    with (
        patch.object(youtube, "_get_video_metadata", return_value=("Video title", "20260715")),
        patch.object(youtube, "_fetch_transcript_api", return_value="[00:00:00] caption") as api,
        patch.object(youtube, "_fetch_yt_dlp_subtitles") as ytdlp,
        patch.object(youtube, "_transcribe_with_whisper") as whisper,
    ):
        result = youtube.extract_youtube_content("https://youtu.be/dQw4w9WgXcQ")

    assert result.title == "Video title"
    assert result.published_at == "20260715"
    assert result.transcript == "[00:00:00] caption"
    assert result.transcript_source == "youtube-transcript-api"
    api.assert_called_once_with("dQw4w9WgXcQ")
    ytdlp.assert_not_called()
    whisper.assert_not_called()


def test_youtube_falls_back_to_whisper_then_unavailable():
    with (
        patch.object(youtube, "_get_video_metadata", return_value=(None, None)),
        patch.object(youtube, "_fetch_transcript_api", return_value=None),
        patch.object(youtube, "_fetch_yt_dlp_subtitles", return_value=None),
        patch.object(youtube, "_transcribe_with_whisper", return_value="[00:00:02] spoken"),
    ):
        transcribed = youtube.extract_youtube_content("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert transcribed.transcript_source == "whisper"
    assert transcribed.transcript == "[00:00:02] spoken"

    with (
        patch.object(youtube, "_get_video_metadata", return_value=(None, None)),
        patch.object(youtube, "_fetch_transcript_api", return_value=None),
        patch.object(youtube, "_fetch_yt_dlp_subtitles", return_value=None),
        patch.object(youtube, "_transcribe_with_whisper", return_value=None),
    ):
        unavailable = youtube.extract_youtube_content("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert unavailable.transcript is None
    assert unavailable.transcript_source == "unavailable"


def test_youtube_webclip_writes_extra_frontmatter_and_deterministic_date(tmp_path: Path):
    webclip_dir = tmp_path / "webclip"
    metadata = {
        "category": "学習・教育",
        "topics": ["学習・教育"],
        "summary": "動画の要約",
        "tags": ["video"],
        "key_points": ["要点"],
        "why_saved": "LLM が出力した理由は保存しない",
        "published_at": None,
        "updated_at": None,
    }

    with (
        patch.object(config, "WEBCLIP_PATH", webclip_dir),
        patch.object(config, "WEBCLIP_DIR_NAME", "webclip"),
        patch.object(webclip.llm_client, "generate_llm_response", return_value=json.dumps(metadata)),
    ):
        link = webclip.process_single_webclip(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            raw_content="[00:00:00] 動画の字幕",
            extracted_title="動画タイトル",
            hour_str="10:30",
            daily_file=tmp_path / "2026-07-15.md",
            clipped_at_str="2026-07-15T10:30:00+09:00",
            content_type="youtube",
            extra_frontmatter={
                "video_id": "dQw4w9WgXcQ",
                "transcript_source": "youtube-transcript-api",
            },
            deterministic_published_at="20260714",
        )

    note_path = webclip_dir / "学習・教育" / "動画タイトル.md"
    frontmatter = yaml.safe_load(note_path.read_text(encoding="utf-8").split("---", 2)[1])
    assert "[[webclip/学習・教育/動画タイトル]]" in link
    assert frontmatter["content_type"] == "youtube"
    assert frontmatter["video_id"] == "dQw4w9WgXcQ"
    assert frontmatter["transcript_source"] == "youtube-transcript-api"
    assert frontmatter["published_at"] == "2026-07-14T00:00:00+09:00"
    assert frontmatter["why_saved"] == ""
    assert "[00:00:00] 動画の字幕" in note_path.read_text(encoding="utf-8")


def test_youtube_long_transcript_uses_partial_summaries():
    transcript = "a" * 25
    final_payload = json.dumps({"category": "その他", "topics": ["その他"]})
    with (
        patch.object(config, "YOUTUBE_SUMMARY_CHUNK_CHARS", 10),
        patch.object(webclip, "_generate_youtube_chunk_summary", side_effect=["part 1", "part 2", "part 3"]) as partial,
        patch.object(webclip.llm_client, "generate_llm_response", return_value=final_payload) as llm,
    ):
        result = webclip.generate_webclip_metadata(transcript, is_youtube=True)

    assert partial.call_count == 3
    assert result["category"] == "その他"
    assert llm.call_args.kwargs["max_tokens"] == 2048


def test_youtube_urls_skip_tavily_and_pass_video_fields_to_webclip(tmp_path: Path):
    video = youtube.YouTubeContent(
        video_id="dQw4w9WgXcQ",
        title="Video title",
        published_at="20260714",
        transcript="[00:00:00] caption",
        transcript_source="youtube-transcript-api",
    )
    with (
        patch.object(obsidian_inbox_merge.youtube, "extract_youtube_content", return_value=video),
        patch.object(obsidian_inbox_merge.web_extract, "web_extract", MagicMock()) as tavily,
        patch.object(obsidian_inbox_merge.webclip, "process_single_webclip", return_value="- link") as clip,
        patch.object(obsidian_inbox_merge.extracter, "append_to_subheader_file") as append,
    ):
        obsidian_inbox_merge.process_web_clips(
            ["https://youtu.be/dQw4w9WgXcQ"], tmp_path / "2026-07-15.md", "10:30"
        )

    tavily.invoke.assert_not_called()
    assert clip.call_args.kwargs["content_type"] == "youtube"
    assert clip.call_args.kwargs["extra_frontmatter"]["transcript_source"] == "youtube-transcript-api"
    append.assert_called_once()
