# Webclip processing and rendering utilities
# 2025-06-15

from __future__ import annotations

import json
import logging
import re
import yaml
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from obsidian_ai_hub.utils import config, extracter, llm_client, prompt, topics

logger = logging.getLogger(__name__)

def clean_filename(title: str) -> str:
    """
    Normalizes a title to a safe filename, replacing unsafe characters with '_'.
    """
    if not title:
        return "untitled"
    # Unsafe chars for files across OSes: \ / : * ? " < > | %
    safe = re.sub(r'[\x00-\x1f\\/:*?"<>|%]', '_', title)
    # Strip leading/trailing whitespaces and dots
    safe = safe.strip(" .")
    return safe or "untitled"

def find_existing_webclip_file(source_url: str) -> Path | None:
    """
    Searches config.WEBCLIP_PATH recursively for any markdown file with frontmatter having
    the matching source_url, returning its Path if found, otherwise None.
    """
    if not config.WEBCLIP_PATH.exists():
        return None

    for p in config.WEBCLIP_PATH.rglob("*.md"):
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8")
                val = extracter.get_frontmatter_value(content, "source_url")
                if val and val.strip() == source_url.strip():
                    return p
            except Exception:
                # Ignore read/parse errors for irrelevant files
                continue
    return None

def format_date_iso8601(date_str: str | None) -> str | None:
    """
    Normalizes a date string to YYYY-MM-DDTHH:MM:SS+09:00.
    If parsing fails or input is null/empty/not a string, returns None.
    """
    if not date_str or not isinstance(date_str, str):
        return None

    # Strip whitespace
    s = date_str.strip()
    if not s or s.lower() == 'null':
        return None

    # Try standard ISO parsing
    try:
        # Standard isoformat parsing
        dt = datetime.fromisoformat(s)
        # If no timezone is specified, default to JST (+09:00) as per requirements
        if dt.tzinfo is None:
            from datetime import timezone, timedelta
            dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))
        return dt.isoformat()
    except ValueError:
        pass

    # Try common formats
    for fmt in (
        "%Y%m%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            # Default to JST (+09:00)
            return dt.strftime("%Y-%m-%dT%H:%M:%S+09:00")
        except ValueError:
            continue

    # If it is just a year-month-day but has timezone or offset, try dateutil or simple regex normalization if needed,
    # but since standard is standard, we can return None if we truly can't parse it.
    logger.warning(f"Could not parse/normalize date string: '{date_str}'")
    return None

def normalize_webclip_json(payload: dict) -> dict:
    """
    Normalizes the parsed webclip JSON to ensure:
    - Dates are in normalized ISO 8601 or null (represented as None)
    - Category is a single valid topic from TOPIC_ENUM (fallback: 'その他')
    - Topics is list of valid TOPIC_ENUM strings normalized, max 5, preserving order, first is category
    - Key points, tags are lists of strings
    - Summary is a string (fallback: '')
    """
    # Dates
    pub = format_date_iso8601(payload.get("published_at"))
    upd = format_date_iso8601(payload.get("updated_at"))

    # Category
    raw_cat = payload.get("category")
    cat = "その他"
    if raw_cat and isinstance(raw_cat, str):
        normalized_cat_list = topics.normalize_topics([raw_cat], limit=1)
        if normalized_cat_list:
            cat = normalized_cat_list[0]

    # Topics
    raw_topics = payload.get("topics")
    if not isinstance(raw_topics, list):
        normalized_topics_list = []
    else:
        # Make sure category is first topic if not already
        if raw_topics:
            if cat not in raw_topics:
                raw_topics = [cat] + [t for t in raw_topics if t != cat]
            else:
                # Move cat to the first position
                raw_topics = [cat] + [t for t in raw_topics if t != cat]
            normalized_topics_list = topics.normalize_topics(raw_topics, limit=5)
            # Ensure category is actually there as the first element if we have topics
            if normalized_topics_list and normalized_topics_list[0] != cat:
                normalized_topics_list = [cat] + [t for t in normalized_topics_list if t != cat]
                normalized_topics_list = normalized_topics_list[:5]
        else:
            normalized_topics_list = []

    # Lists
    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)] if tags else []
    tags = [str(t) for t in tags if t]

    kps = payload.get("key_points") or []
    if not isinstance(kps, list):
        kps = [str(kps)] if kps else []
    kps = [str(k) for k in kps if k]

    summary = str(payload.get("summary") or "")
    return {
        "published_at": pub,
        "updated_at": upd,
        "category": cat,
        "topics": normalized_topics_list,
        "tags": tags,
        "summary": summary,
        "key_points": kps,
    }

def build_webclip_markdown(frontmatter: dict, content_body: str) -> str:
    """
    Renders frontmatter and content body into an Obsidian markdown file string.
    """
    # Ensure keys always exist in standard order:
    # title, source_url, clipped_at, published_at, updated_at, category, topics, tags, summary, key_points, why_saved
    ordered_keys = [
        "title", "source_url", "clipped_at", "published_at", "updated_at",
        "category", "topics", "tags", "summary", "key_points", "why_saved"
    ]
    ordered_keys.extend(
        key for key in ("content_type", "video_id", "transcript_source")
        if key in frontmatter
    )

    fm_dict = {}
    for k in ordered_keys:
        fm_dict[k] = frontmatter.get(k)

    # Use allow_unicode to prevent escaping Japanese chars
    yaml_text = yaml.safe_dump(fm_dict, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return f"---\n{yaml_text}---\n\n{content_body or ''}\n"

def get_unique_webclip_path(category: str, title: str, exclude_path: Path | None = None) -> Path:
    """
    Computes a unique filepath within config.WEBCLIP_PATH / category / title.md.
    If the file already exists (and is not exclude_path), appends serial number.
    e.g., 'title 2.md', 'title 3.md', etc.
    """
    safe_title = clean_filename(title)
    base_dir = config.WEBCLIP_PATH / category

    # Check simple case first
    target = base_dir / f"{safe_title}.md"
    if not target.exists() or (exclude_path and target.resolve() == exclude_path.resolve()):
        return target

    # Try incrementing serial
    serial = 2
    while True:
        target = base_dir / f"{safe_title} {serial}.md"
        if not target.exists() or (exclude_path and target.resolve() == exclude_path.resolve()):
            return target
        serial += 1

def parse_llm_json(response: str) -> dict:
    """
    Attempts to extract and parse JSON object from LLM response.
    Returns empty dict on failure.
    """
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        # Search for first '{' and last '}'
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end >= start:
            payload = json.loads(cleaned[start:end+1])
            if isinstance(payload, dict):
                return payload
    except Exception:
        logger.warning(f"Failed to parse LLM JSON response: {response}")
    return {}


def _split_text(text: str, chunk_size: int) -> list[str]:
    """Split long transcripts at a newline where possible."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    remaining = text
    while remaining:
        split_at = min(len(remaining), chunk_size)
        if split_at < len(remaining):
            newline = remaining.rfind("\n", 0, split_at)
            if newline > chunk_size // 2:
                split_at = newline
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


def _generate_youtube_chunk_summary(chunk: str) -> str:
    rendered_prompt = prompt.render_prompt(
        config.YOUTUBE_CHUNK_SUMMARY_PROMPT_PATH,
        {"transcript_chunk": chunk},
    )
    return llm_client.generate_llm_response(
        provider=config.INBOX_WEB_SUMMARY_PROVIDER,
        model=config.INBOX_WEB_SUMMARY_MODEL,
        prompt=rendered_prompt,
        temperature=0.2,
        max_tokens=1024,
    ).strip()


def generate_webclip_metadata(raw_content: str, *, is_youtube: bool = False) -> dict:
    """Generate structured metadata, reducing long YouTube transcripts first."""
    content_for_summary = raw_content
    if is_youtube and len(raw_content) > config.YOUTUBE_SUMMARY_CHUNK_CHARS:
        partial_summaries = [
            _generate_youtube_chunk_summary(chunk)
            for chunk in _split_text(raw_content, config.YOUTUBE_SUMMARY_CHUNK_CHARS)
        ]
        content_for_summary = "\n\n".join(
            summary for summary in partial_summaries if summary
        )

    rendered_prompt = prompt.render_prompt(
        config.INBOX_WEB_SUMMARY_PROMPT_PATH,
        {"raw_content": content_for_summary},
    )
    response = llm_client.generate_llm_response(
        provider=config.INBOX_WEB_SUMMARY_PROVIDER,
        model=config.INBOX_WEB_SUMMARY_MODEL,
        prompt=rendered_prompt,
        temperature=0.3,
        max_tokens=2048,
    ).strip()
    return parse_llm_json(response)

def process_single_webclip(
    url: str,
    raw_content: str | None,
    extracted_title: str | None,
    hour_str: str,
    daily_file: Path,
    clipped_at_str: str,
    *,
    content_type: str | None = None,
    extra_frontmatter: dict | None = None,
    deterministic_published_at: str | None = None,
) -> str:
    """
    Processes a single webclip URL:
    - Resolves title (determines clean title).
    - Checks for duplicate source_url.
    - Runs LLM with JSON prompt on raw_content to extract structured metadata.
    - Normalizes topics, category, dates, and lists.
    - If LLM fails or content is missing, builds fallback structured metadata.
    - Computes unique target path and moves/deletes old version if changed.
    - Saves webclip markdown file.
    - Returns the formatted daily note internal link string.
    """
    # 1. Title Resolution (Deterministic)
    title = extracted_title
    if not title:
        # Fall back to URL domain/path label
        parsed = urlparse(url)
        domain = parsed.netloc
        path = parsed.path.rstrip('/')
        if path:
            title = f"{domain}{path}"
        else:
            title = domain

    # 2. Duplicate Detection
    existing_file = find_existing_webclip_file(url)

    # 3. LLM Call or Fallback
    parsed_json = {}
    if raw_content:
        try:
            parsed_json = generate_webclip_metadata(
                raw_content, is_youtube=content_type == "youtube"
            )
        except Exception:
            logger.exception("LLM call failed during webclip processing")

    # 4. Normalize JSON fields
    normalized = normalize_webclip_json(parsed_json)
    known_published_at = format_date_iso8601(deterministic_published_at)
    if known_published_at:
        normalized["published_at"] = known_published_at

    # 5. Build Frontmatter and File Writing
    frontmatter = {
        "title": title,
        "source_url": url,
        "clipped_at": clipped_at_str,
        "published_at": normalized["published_at"],
        "updated_at": normalized["updated_at"],
        "category": normalized["category"],
        "topics": normalized["topics"],
        "tags": normalized["tags"],
        "summary": normalized["summary"],
        "key_points": normalized["key_points"],
        "why_saved": "",
    }
    if existing_file:
        try:
            existing_frontmatter = extracter.parse_frontmatter(
                existing_file.read_text(encoding="utf-8")
            )
            existing_why_saved = existing_frontmatter.get("why_saved")
            if isinstance(existing_why_saved, str) and existing_why_saved:
                frontmatter["why_saved"] = existing_why_saved
        except Exception:
            logger.exception(
                "Failed to preserve why_saved from existing webclip %s", existing_file
            )
    if content_type:
        frontmatter["content_type"] = content_type
    if extra_frontmatter:
        frontmatter.update(extra_frontmatter)

    category_folder = normalized["category"]
    # Target Path determination (considering duplicate moving)
    target_path = get_unique_webclip_path(category_folder, title, exclude_path=existing_file)

    # Ensure output directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Build markdown content
    md_content = build_webclip_markdown(frontmatter, raw_content or "")
    target_path.write_text(md_content, encoding="utf-8")
    logger.info(f"Saved webclip to {target_path}")

    # If duplicate exists, handle potential move/update
    if existing_file:
        if existing_file.resolve() != target_path.resolve():
            # Old file had a different path, delete it
            try:
                existing_file.unlink()
                logger.info(f"Deleted old webclip at {existing_file}")
            except Exception:
                logger.exception(f"Failed to delete old webclip {existing_file}")

    # 6. Generate Daily Note link format
    # - HH:MM [webclip] [[webclip/{主topic}/{タイトル}]]
    # (Note: path in double brackets should be relative to vault root, but we use webclip/{category}/{actual_filename_without_md})
    actual_filename = target_path.stem
    webclip_rel_dir = config.WEBCLIP_DIR_NAME  # e.g. "webclip"
    internal_link = f"{webclip_rel_dir}/{category_folder}/{actual_filename}"

    return f"- {hour_str} [webclip] [[{internal_link}]]"
