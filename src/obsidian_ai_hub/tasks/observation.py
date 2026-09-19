"""Two-layer Observation budgets for the Runtime Orchestrator.

A single executed Action can return a large read/search payload (a research
context snapshot, a periodic note, a conversation excerpt). Feeding every raw
payload forward crowds out earlier conclusions and risks prompt blow-up. Each
Action therefore stores two bounded views of the same raw observation:

* the *detail* observation — display/audit material, capped by the
  capability-specific limit (research reads may keep up to
  ``MAX_DETAIL_LIMIT``; generic registry tools keep the previous runtime
  window, ``DEFAULT_DETAIL_LIMIT``), and
* the *history gist* — about ``HISTORY_GIST_LIMIT`` chars that preserve both
  the leading structure and the trailing conclusion, always fed back to the
  next Action as decision material.

The newest Action's prompt slot shows the detail view; older Actions show the
gist. The whole history section stays bounded by ``HISTORY_TOTAL_BUDGET``.
The registry adapter no longer applies a uniform 800-char head cut: limits
live here so they are capability-specific and testable.
"""

from __future__ import annotations

HISTORY_GIST_LIMIT = 1500
DEFAULT_DETAIL_LIMIT = 2000
MAX_DETAIL_LIMIT = 6000
HISTORY_TOTAL_BUDGET = 60000

# Fraction of the gist budget kept from the head; the rest preserves the tail
# where child-run results report evidence (test counts, commit SHAs).
_GIST_HEAD_RATIO = 0.4

# Capability-specific detail windows. Keys absent here use
# ``DEFAULT_DETAIL_LIMIT`` (the previous runtime-wide 2,000-char cap), so
# existing general capabilities keep their current effective behavior while
# research reads get a larger window.
_DETAIL_LIMITS: dict[str, int] = {
    "research_context_snapshot": MAX_DETAIL_LIMIT,
    "research_theme_history_search": MAX_DETAIL_LIMIT,
    "activity_search": MAX_DETAIL_LIMIT,
    "periodic_note_read": MAX_DETAIL_LIMIT,
    "agent_conversation_search": 4000,
    "coding_history_search": 4000,
    "people_relations_walk": MAX_DETAIL_LIMIT,
    "research_theme_propose": 2000,
    "research_agent": MAX_DETAIL_LIMIT,
    "specialist_agent": MAX_DETAIL_LIMIT,
    "coding_cli": MAX_DETAIL_LIMIT,
}


def detail_limit(capability_key: str) -> int:
    """Return the detail-observation limit (chars) for a capability."""
    return _DETAIL_LIMITS.get(str(capability_key), DEFAULT_DETAIL_LIMIT)


def truncate_detail(text: str, capability_key: str) -> str:
    """Bound a raw observation to its capability-specific detail window."""
    limit = detail_limit(capability_key)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(truncated)"


def build_history_gist(text: str, limit: int = HISTORY_GIST_LIMIT) -> str:
    """Compress an observation to a conclusion-preserving history gist.

    Keeps the head (structure/priority fields) and the tail (evidence such as
    test counts and commit SHAs) within the same overall budget instead of a
    head-only cut that drops the finish decision's evidence.
    """
    if len(text) <= limit:
        return text
    head = int(limit * _GIST_HEAD_RATIO)
    tail = limit - head
    omitted = len(text) - head - tail
    return text[:head] + f"\n...({omitted} chars omitted)...\n" + text[-tail:]


def split_observation(capability_key: str, raw: str) -> tuple[str, str]:
    """Return ``(detail, gist)`` for one raw observation."""
    return truncate_detail(raw, capability_key), build_history_gist(raw)
