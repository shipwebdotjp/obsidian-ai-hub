from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

ALLOWED_STABILITY = frozenset({"stable", "tentative", "explicitly_settled"})
STABILITY_DEFAULT = "tentative"

MEMORY_COLUMNS = [
    "schema_version",
    "memory_id",
    "status",
    "kind",
    "memory_key",
    "content",
    "topics",
    "tags",
    "evidence",
    "valid_from",
    "valid_until",
    "review_due_at",
    "stability",
    "sensitivity",
    "extraction_confidence",
    "supersedes",
    "contradicts",
    "provenance",
    "created_at",
    "updated_at",
    "reviewed_by",
    "reviewed_at",
    "dedup_suggestions",
    "dedup_assessment",
]

EVENT_COLUMNS = [
    "schema_version",
    "event_id",
    "occurred_at",
    "actor",
    "event_type",
    "memory_id",
    "previous_status",
    "new_status",
    "changes",
    "reason",
]


def normalize_stability(raw: object, default: str = STABILITY_DEFAULT) -> str:
    if not isinstance(raw, str) or raw not in ALLOWED_STABILITY:
        logger.warning(
            "Invalid or missing stability value %r; coercing to %r",
            raw,
            default,
        )
        return default
    return raw


def get_current_timestamp() -> str:
    # Use JST timezone for standard +09:00 formatting
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).isoformat(timespec="seconds")


def generate_memory_id(date_str: str) -> str:
    clean_date = date_str.replace("-", "")
    rand_part = uuid.uuid4().hex[:6]
    return f"mem_{clean_date}_{rand_part}"


def generate_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def normalize_content(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    return text


def serialize_memory(m: dict) -> dict:
    db_row = dict(m)
    for col in [
        "topics",
        "tags",
        "evidence",
        "contradicts",
        "provenance",
        "dedup_suggestions",
        "dedup_assessment",
    ]:
        if col in db_row:
            if db_row[col] is not None:
                db_row[col] = json.dumps(db_row[col], ensure_ascii=False)
            else:
                db_row[col] = None
    return db_row


def deserialize_memory(row: dict) -> dict:
    m = dict(row)
    for col in [
        "topics",
        "tags",
        "evidence",
        "contradicts",
        "provenance",
        "dedup_suggestions",
        "dedup_assessment",
    ]:
        if col in m and m[col] is not None:
            try:
                m[col] = json.loads(m[col])
            except Exception:
                logger.warning(
                    "Failed to deserialize %s for memory %s: %r",
                    col,
                    m.get("memory_id"),
                    m[col],
                )
                m[col] = None
    return m


def serialize_event(e: dict) -> dict:
    db_row = dict(e)
    if "changes" in db_row and db_row["changes"] is not None:
        db_row["changes"] = json.dumps(db_row["changes"], ensure_ascii=False)
    return db_row


def deserialize_event(row: dict) -> dict:
    e = dict(row)
    if "changes" in e and e["changes"] is not None:
        try:
            e["changes"] = json.loads(e["changes"])
        except Exception:
            e["changes"] = {}
    return e


def estimate_tokens(text: str) -> int:
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # Fallback approximation for mixed Japanese and English text
        return int(len(text) * 1.2)


def get_approved_memories_path() -> Path:
    vault_copilot = Path(config.VAULT_PATH) / "copilot"
    return vault_copilot / "memory" / "approved.md"


def _vault_relative_path(path: Path) -> str:
    try:
        return path.relative_to(config.VAULT_PATH).as_posix()
    except ValueError:
        return path.as_posix()


def merge_topics_and_tags(existing: list[str], new_vals: list[str]) -> list[str]:
    merged = list(existing)
    for val in new_vals:
        if val not in merged:
            merged.append(val)
    return merged


def merge_evidence(existing: list[dict], new_vals: list[dict]) -> list[dict]:
    merged = list(existing)
    for item in new_vals:
        path = item.get("path", "")
        quote = item.get("quote", "")
        observed_at = item.get("observed_at")

        duplicate = False
        for ex in merged:
            if (
                ex.get("path", "") == path
                and ex.get("quote", "") == quote
                and ex.get("observed_at") == observed_at
            ):
                duplicate = True
                break
        if not duplicate:
            merged.append(item)
    return merged


def update_target_with_candidate_data(
    target: dict, cand: dict, reviewed_by: str
) -> dict:
    timestamp_now = get_current_timestamp()
    target["content"] = cand.get("content", "")
    for field in [
        "kind",
        "valid_from",
        "valid_until",
        "review_due_at",
        "sensitivity",
        "extraction_confidence",
        "contradicts",
        "provenance",
    ]:
        target[field] = cand.get(field)
    target["stability"] = normalize_stability(
        cand.get("stability"), default="tentative"
    )
    target["topics"] = merge_topics_and_tags(
        target.get("topics") or [], cand.get("topics") or []
    )
    target["tags"] = merge_topics_and_tags(
        target.get("tags") or [], cand.get("tags") or []
    )
    target["evidence"] = merge_evidence(
        target.get("evidence") or [], cand.get("evidence") or []
    )
    target["updated_at"] = timestamp_now
    target["reviewed_by"] = reviewed_by
    target["reviewed_at"] = timestamp_now
    return target


# Fields that the Web UI can edit. Other fields (kind, memory_key, evidence,
# dedup_suggestions, contradicts, supersedes, provenance, sensitivity,
# extraction_confidence) are intentionally not editable from the review UI to
# keep dedup fingerprints stable.
EDITABLE_FIELDS = (
    "content",
    "topics",
    "tags",
    "valid_from",
    "valid_until",
    "review_due_at",
    "stability",
)


def _validate_date_str(value, field_name: str):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string in YYYY-MM-DD format")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def _validate_edit_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    unknown = set(payload.keys()) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(
            f"editable fields are {sorted(EDITABLE_FIELDS)}; got unknown: {sorted(unknown)}"
        )

    if "content" in payload and (
        not isinstance(payload["content"], str) or not payload["content"].strip()
    ):
        raise ValueError("content must be a non-empty string")

    if "topics" in payload:
        if not isinstance(payload["topics"], list):
            raise ValueError("topics must be a list of strings")
        from obsidian_ai_hub.utils.topics import normalize_topics

        payload["topics"] = normalize_topics(payload["topics"])

    if "tags" in payload:
        if not isinstance(payload["tags"], list) or not all(
            isinstance(t, str) for t in payload["tags"]
        ):
            raise ValueError("tags must be a list of strings")

    if "stability" in payload:
        if payload["stability"] not in ALLOWED_STABILITY:
            raise ValueError(
                f"stability must be one of {sorted(ALLOWED_STABILITY)}; got {payload['stability']!r}"
            )

    for date_field in ("valid_from", "valid_until", "review_due_at"):
        if date_field in payload:
            _validate_date_str(payload[date_field], date_field)

    if "valid_from" in payload and "valid_until" in payload:
        vf = payload.get("valid_from")
        vu = payload.get("valid_until")
        if vf and vu and vf > vu:
            raise ValueError("valid_from must be on or before valid_until")

    return payload
