"""Public entry point for the long-term memory subsystem.

The implementation is split across the following submodules:

* :mod:`obsidian_ai_hub.memory.models` - column / constant definitions,
  identifiers, serializers, stability / date validators, merge helpers.
* :mod:`obsidian_ai_hub.memory.store` - memories / events CRUD primitives.
* :mod:`obsidian_ai_hub.memory.dedup` - candidate deduplication (exact match,
  vector similarity, and LLM-based assessment).
* :mod:`obsidian_ai_hub.memory.extraction` - weekly source collection and
  candidate extraction.
* :mod:`obsidian_ai_hub.memory.review` - manual lifecycle actions
  (approve / reject / edit / batch / resolve / delete).
* :mod:`obsidian_ai_hub.memory.context` - expiration resolution and
  ContextPack compilation.
* :mod:`obsidian_ai_hub.memory.projection` - approved-memory Markdown
  projection and copilot profile rendering.

This module re-exports the public API for backwards compatibility so that
``from obsidian_ai_hub import memory`` keeps working unchanged.
"""

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import llm_client
from obsidian_ai_hub.utils.embeddings import cosine_similarity, get_embedder

from obsidian_ai_hub.memory.context import (
    compile_context,
    get_currently_valid_approved_memories,
)
from obsidian_ai_hub.memory.dedup import (
    perform_dedup_assessment_llm,
    run_deduplication,
)
from obsidian_ai_hub.memory.extraction import (
    _extract_memory_source_content,
    _load_daily_structured_record,
    _vault_relative_path,
    _week_bounds,
    extract_memories,
)
from obsidian_ai_hub.memory.models import (
    ALLOWED_STABILITY,
    EDITABLE_FIELDS,
    EVENT_COLUMNS,
    MEMORY_COLUMNS,
    STABILITY_DEFAULT,
    deserialize_event,
    deserialize_memory,
    estimate_tokens,
    generate_event_id,
    generate_memory_id,
    get_approved_memories_path,
    get_current_timestamp,
    merge_evidence,
    merge_topics_and_tags,
    normalize_content,
    normalize_stability,
    serialize_event,
    serialize_memory,
    update_target_with_candidate_data,
)
from obsidian_ai_hub.memory.projection import (
    EXPECTED_FILES,
    project_approved_memories,
    render_copilot_profile,
)
from obsidian_ai_hub.memory.review import (
    batch_delete_memories,
    batch_review_memories,
    delete_memory,
    resolve_memory,
    review_memory,
    update_memory_fields,
)
from obsidian_ai_hub.memory.store import (
    get_memory,
    get_memory_events,
    load_all_memories,
    log_memory_event,
    save_all_memories,
)
from obsidian_ai_hub.memory.interview import (
    generate_interview_questions,
    apply_interview_answers,
)


__all__ = [
    "generate_interview_questions",
    "apply_interview_answers",
    "ALLOWED_STABILITY",
    "EDITABLE_FIELDS",
    "EVENT_COLUMNS",
    "EXPECTED_FILES",
    "MEMORY_COLUMNS",
    "STABILITY_DEFAULT",
    "batch_delete_memories",
    "batch_review_memories",
    "compile_context",
    "cosine_similarity",
    "delete_memory",
    "deserialize_event",
    "deserialize_memory",
    "estimate_tokens",
    "extract_memories",
    "generate_event_id",
    "generate_memory_id",
    "get_approved_memories_path",
    "get_current_timestamp",
    "get_currently_valid_approved_memories",
    "get_db_connection",
    "get_embedder",
    "get_memory",
    "get_memory_events",
    "llm_client",
    "load_all_memories",
    "log_memory_event",
    "merge_evidence",
    "merge_topics_and_tags",
    "normalize_content",
    "normalize_stability",
    "perform_dedup_assessment_llm",
    "project_approved_memories",
    "render_copilot_profile",
    "resolve_memory",
    "review_memory",
    "run_deduplication",
    "save_all_memories",
    "serialize_event",
    "serialize_memory",
    "update_memory_fields",
    "update_target_with_candidate_data",
    # Test-only underscored helpers (kept for compatibility).
    "_extract_memory_source_content",
    "_load_daily_structured_record",
    "_vault_relative_path",
    "_week_bounds",
]
