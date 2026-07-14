from datetime import date, datetime
from typing import Literal, Optional, Any

from pydantic import BaseModel, Field, field_validator, model_validator

EDITABLE_FIELDS = (
    "content",
    "topics",
    "tags",
    "valid_from",
    "valid_until",
    "review_due_at",
    "stability",
)

ALLOWED_STABILITY = {"stable", "tentative", "explicitly_settled"}
ALLOWED_STATUS = {"candidate", "approved", "rejected", "expired", "superseded"}
ALLOWED_ACTIONS = {"approve", "reject"}
ALLOWED_KINDS = {
    "preference",
    "decision_policy",
    "fact",
    "commitment",
    "pattern",
    "episode",
}


class Evidence(BaseModel):
    path: str = Field(..., min_length=1, description="Vault-relative path to the source note")
    quote: str = ""
    observed_at: Optional[str] = None


class DedupSuggestion(BaseModel):
    target_memory_id: str
    relation: str
    reason: Optional[str] = None
    score: Optional[float] = None


class DedupAssessment(BaseModel):
    decision: Literal["merge", "new", "supersede", "failed"]
    target_memory_id: Optional[str] = None
    similarity_score: Optional[float] = None
    reason: Optional[str] = None
    integrated_content: Optional[str] = None
    failure_kind: Optional[Literal["request_failed", "response_invalid"]] = None


class Memory(BaseModel):
    model_config = {"populate_by_name": True}

    memory_id: str
    status: Literal["candidate", "approved", "rejected", "expired", "superseded"]
    kind: Optional[Literal[
        "preference",
        "decision_policy",
        "fact",
        "commitment",
        "pattern",
        "episode",
    ]] = None
    memory_key: Optional[str] = None
    content: str
    topics: Optional[list[str]] = Field(default_factory=list)
    tags: Optional[list[str]] = Field(default_factory=list)
    evidence: Optional[list[Evidence]] = Field(default_factory=list)
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    review_due_at: Optional[str] = None
    stability: Optional[Literal["stable", "tentative", "explicitly_settled"]] = None
    sensitivity: Optional[str] = None
    extraction_confidence: Optional[float] = None
    supersedes: Optional[str] = None
    contradicts: Optional[list[str]] = Field(default_factory=list)
    dedup_suggestions: Optional[list[DedupSuggestion]] = Field(default_factory=list)
    dedup_assessment: Optional[DedupAssessment] = None
    provenance: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


class MemoryEvent(BaseModel):
    event_id: str
    occurred_at: str
    actor: Optional[str] = None
    event_type: str
    memory_id: str
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    changes: dict = Field(default_factory=dict)
    reason: Optional[str] = None


class MemoryDetail(Memory):
    events: list[MemoryEvent] = Field(default_factory=list)


class MemoryListResponse(BaseModel):
    items: list[Memory]
    total: int


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject", "edit"]
    new_content: Optional[str] = None


class ReviewResponse(BaseModel):
    memory: Memory


class EditRequest(BaseModel):
    content: Optional[str] = None
    topics: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    review_due_at: Optional[str] = None
    stability: Optional[Literal["stable", "tentative", "explicitly_settled"]] = None


class BatchReviewRequest(BaseModel):
    memory_ids: list[str]
    action: Literal["approve", "reject"]

    @field_validator("memory_ids")
    @classmethod
    def _memory_ids_must_be_unique_and_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("memory_ids must not be empty")
        if len(v) != len(set(v)):
            raise ValueError("memory_ids must not contain duplicates")
        return v


class BatchReviewResponse(BaseModel):
    updated: list[str]
    not_found: list[str]
    events: int


class UpdateResponse(BaseModel):
    found: bool
    updated: bool
    changes: dict
    memory: Optional[Memory] = None

class ResolveRequest(BaseModel):
    action: Literal["keep_both", "replace_existing", "merge_existing", "supersede_existing"]
    target_memory_id: str
    integrated_content: Optional[str] = None
    switch_date: Optional[str] = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "ResolveRequest":
        if self.action == "merge_existing":
            if not self.integrated_content or not self.integrated_content.strip():
                raise ValueError("integrated_content is required when action is merge_existing")
        elif self.action == "supersede_existing":
            if not self.switch_date or not self.switch_date.strip():
                raise ValueError("switch_date is required when action is supersede_existing")
        return self


class ResolveResponse(BaseModel):
    candidate: Memory
    target: Optional[Memory] = None


class DeleteResponse(BaseModel):
    found: bool
    deleted: bool
    events_deleted: int = 0
    memory: Optional[Memory] = None


class BatchDeleteRequest(BaseModel):
    memory_ids: list[str]

    @field_validator("memory_ids")
    @classmethod
    def _memory_ids_must_be_unique_and_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("memory_ids must not be empty")
        if len(v) != len(set(v)):
            raise ValueError("memory_ids must not contain duplicates")
        return v


class BatchDeleteResponse(BaseModel):
    deleted: list[str]
    not_found: list[str]
    events_deleted: int = 0


class MemoryOptionsResponse(BaseModel):
    kinds: list[str]
    topics: list[str]


class RenderCopilotProfileResponse(BaseModel):
    updated_files: list[str]
