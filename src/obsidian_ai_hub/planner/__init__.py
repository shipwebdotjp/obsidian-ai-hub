"""AI proposal planner subpackage.

AI proposals are low-to-medium confidence candidates ("you might want to
schedule/remind this") generated from the app's full context. They live in
their own SQLite table (planner_proposals) and are manipulated through their
own APIs. This layer never touches the existing Inbox -> HITL -> Apple
registration flow.
"""

from obsidian_ai_hub.planner import apple, cache, context, promote, store, suggest
from obsidian_ai_hub.planner.promote import promote_proposal
from obsidian_ai_hub.planner.store import (
    ALLOWED_KINDS,
    ALLOWED_PROPOSAL_STATUS,
    DuplicateActiveProposalError,
    cleanup_expired_proposals,
    compute_fingerprint,
    create_proposal,
    find_active_by_fingerprint,
    get_proposal,
    list_proposals,
    transition_status,
    update_proposal_fields,
)
from obsidian_ai_hub.planner.suggest import generate_proposals

__all__ = [
    "ALLOWED_KINDS",
    "ALLOWED_PROPOSAL_STATUS",
    "DuplicateActiveProposalError",
    "apple",
    "cache",
    "cleanup_expired_proposals",
    "compute_fingerprint",
    "context",
    "create_proposal",
    "find_active_by_fingerprint",
    "generate_proposals",
    "get_proposal",
    "list_proposals",
    "promote",
    "promote_proposal",
    "store",
    "suggest",
    "transition_status",
    "update_proposal_fields",
]
