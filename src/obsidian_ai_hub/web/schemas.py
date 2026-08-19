from datetime import datetime
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
    path: str = Field(
        ..., min_length=1, description="Vault-relative path to the source note"
    )
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
    kind: Optional[
        Literal[
            "preference",
            "decision_policy",
            "fact",
            "commitment",
            "pattern",
            "episode",
        ]
    ] = None
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
    action: Literal[
        "keep_both", "replace_existing", "merge_existing", "supersede_existing"
    ]
    target_memory_id: str
    integrated_content: Optional[str] = None
    switch_date: Optional[str] = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "ResolveRequest":
        if self.action == "merge_existing":
            if not self.integrated_content or not self.integrated_content.strip():
                raise ValueError(
                    "integrated_content is required when action is merge_existing"
                )
        elif self.action == "supersede_existing":
            if not self.switch_date or not self.switch_date.strip():
                raise ValueError(
                    "switch_date is required when action is supersede_existing"
                )
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


# --- Research Theme schemas ---

ALLOWED_RESEARCH_THEME_STATUS = frozenset(
    {"candidate", "approved", "rejected", "duplicate"}
)
ALLOWED_RESEARCH_JOB_STATUS = frozenset({"pending", "running", "succeeded", "failed"})


class ResearchJob(BaseModel):
    job_id: str
    status: str
    generated_title: Optional[str] = None
    mode: Optional[str] = None
    markdown: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class ResearchTheme(BaseModel):
    theme_id: str
    status: str
    theme: str
    direction: Optional[str] = None
    kind: Optional[str] = None
    why_now: Optional[str] = None
    confidence: Optional[float] = None
    normalized_key: str
    duplicate_of_theme_id: Optional[str] = None
    duplicate_reason: Optional[str] = None
    related_theme_ids: list[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    latest_job: Optional[ResearchJob] = None
    origin: Optional[str] = None
    hitl_run_id: Optional[str] = None


class ResearchThemeListResponse(BaseModel):
    items: list[ResearchTheme]
    total: int


class ResearchRunRequest(BaseModel):
    theme: str
    mode: Literal["auto", "internal", "web", "deep"] = "auto"


class ResearchRunAcceptedResponse(BaseModel):
    theme: ResearchTheme
    job: ResearchJob


# --- Vault Search schemas ---

ALLOWED_VAULT_SEARCH_MODES = frozenset({"keyword", "similarity", "hybrid"})


class VaultSearchHitMetadata(BaseModel):
    collection_name: Optional[str] = None
    source_path: Optional[str] = None
    file_path: Optional[str] = None
    relative_path: Optional[str] = None
    vault_name: Optional[str] = None
    chunk_index: Optional[int] = None
    mtime: Optional[float] = None
    content_hash: Optional[str] = None


class VaultSearchHit(BaseModel):
    content: str
    metadata: VaultSearchHitMetadata
    score: float


class VaultSearchResponse(BaseModel):
    items: list[VaultSearchHit]
    total: int


class VaultFileResponse(BaseModel):
    content: str
    relative_path: str


# --- Summary schemas ---

ALLOWED_PERIOD_TYPES = frozenset({"day", "week", "month"})


class SummaryItem(BaseModel):
    summary_item_id: str
    kind: str
    body: str
    display_order: int = 0


class SummaryPerson(BaseModel):
    name: str
    note: str = ""
    person_id: Optional[str] = None
    resolution_status: Optional[str] = None
    candidate_id: Optional[str] = None


class SummaryProjectNote(BaseModel):
    project_id: int
    display_name: str
    note: str = ""
    display_order: int = 0


class SummaryProjectNoteInput(BaseModel):
    project_id: int
    note: str = ""


class ProjectCandidate(BaseModel):
    candidate_id: int
    display_name: str
    normalized_name: str
    domain: Literal["work", "personal"]
    status: Literal["unresolved", "resolved", "rejected"]
    goal: Optional[str] = None
    description: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    completed_date: Optional[str] = None
    evidence: Optional[str] = None
    created_at: str
    updated_at: str


class SummaryListItem(BaseModel):
    summary_id: str
    period_type: Literal["day", "week", "month"]
    period_key: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    generated_at: Optional[str] = None
    summary: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    mood: Optional[str] = None
    sleep_raw: Optional[str] = None
    sleep_hours: Optional[float] = None
    topics: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    project_notes: list[SummaryProjectNote] = Field(default_factory=list)
    project_candidates: list[ProjectCandidate] = Field(default_factory=list)
    people: list[SummaryPerson] = Field(default_factory=list)


class SummaryDetail(BaseModel):
    summary_id: str
    period_type: Literal["day", "week", "month"]
    period_key: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    generated_at: Optional[str] = None
    summary: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    mood: Optional[str] = None
    sleep_raw: Optional[str] = None
    sleep_hours: Optional[float] = None
    topics: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    project_notes: list[SummaryProjectNote] = Field(default_factory=list)
    project_candidates: list[ProjectCandidate] = Field(default_factory=list)
    people: list[SummaryPerson] = Field(default_factory=list)
    items: list[SummaryItem] = Field(default_factory=list)


class SummaryItemInput(BaseModel):
    kind: str
    body: str
    display_order: int = 0


class SummaryPersonInput(BaseModel):
    person_id: str
    note: str = ""


class SummaryUpdateRequest(BaseModel):
    summary: Optional[str] = None
    keywords: Optional[list[str]] = None
    mood: Optional[str] = None
    sleep_raw: Optional[str] = None
    items: Optional[list[SummaryItemInput]] = None
    topics: Optional[list[str]] = None
    projects: Optional[list[int]] = None
    project_notes: Optional[list[SummaryProjectNoteInput]] = None
    people: Optional[list[SummaryPersonInput]] = None


class SummaryDeleteResponse(BaseModel):
    deleted: bool
    summary_id: str


class EditOptionsResponse(BaseModel):
    topics: list[str]
    item_kinds: dict[str, list[str]]


class SummaryOptionsResponse(BaseModel):
    period_types: list[Literal["day", "week", "month"]] = Field(
        default_factory=lambda: ["day", "week", "month"]
    )
    topics: list[str]
    projects: list[str]
    people: list[str]


class SummaryListResponse(BaseModel):
    items: list[SummaryListItem]
    total: int


# --- Dashboard schemas ---


class DashboardActivityLog(BaseModel):
    activity_id: str
    occurred_at: str
    app_name: Optional[str] = None
    window_title: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    keywords: list[str] = []
    project_id: Optional[int] = None
    project_name: Optional[str] = None


class TodayActivity(BaseModel):
    date: str
    active_minutes: float
    inactive_minutes: float
    logs: list[DashboardActivityLog] = []


class DashboardHomeResponse(BaseModel):
    this_month_summary: Optional[SummaryDetail] = None
    latest_week_summary: Optional[SummaryDetail] = None
    yesterday_summary: Optional[SummaryDetail] = None
    today_activity: TodayActivity


class BrowseDayItem(BaseModel):
    date: str
    has_summary: bool
    summary_id: Optional[str] = None
    summary: Optional[str] = None
    topics: list[str] = []


class DashboardBrowseResponse(BaseModel):
    selectable_years: list[str]
    selected_year: str
    selected_month: Optional[str] = None
    months: list[SummaryDetail] = []
    weeks: list[SummaryDetail] = []
    days: list[BrowseDayItem] = []
    missing_summary_targets: list["MissingSummaryTarget"] = []


class MissingSummaryTarget(BaseModel):
    period_type: Literal["day", "week", "month"]
    period_key: str
    period_start: str
    period_end: str


class SummaryGenerateRequest(BaseModel):
    period_type: Literal["day", "week", "month"]
    target_date: Optional[str] = None
    target_month: Optional[str] = None

    @model_validator(mode="after")
    def validate_target(self):
        if self.period_type in {"day", "week"}:
            if not self.target_date or self.target_month is not None:
                raise ValueError("day and week generation require target_date only")
            datetime.strptime(self.target_date, "%Y-%m-%d")
        else:
            if not self.target_month or self.target_date is not None:
                raise ValueError("month generation requires target_month only")
            datetime.strptime(self.target_month, "%Y-%m")
        return self


class DashboardDayDetailsResponse(BaseModel):
    date: str
    summary: Optional[SummaryDetail] = None
    active_minutes: float
    inactive_minutes: float
    logs: list[DashboardActivityLog] = []


class StatsBucket(BaseModel):
    key: str
    display_label: str
    start_date: str
    end_date: str
    active_minutes: float
    inactive_minutes: float
    daily_summary_count: int
    topic_counts: dict[str, int] = {}
    keyword_counts: dict[str, int] = {}


class HourlyCategoryBucket(BaseModel):
    hour: int
    total_log_count: int
    category_counts: dict[str, int] = {}


class DashboardStatsResponse(BaseModel):
    granularity: Literal["day", "week", "month"]
    buckets: list[StatsBucket]
    candidate_topics: list[str]
    candidate_keywords: list[str]
    activity_categories: list[str] = []
    hourly_category_buckets: list[HourlyCategoryBucket] = []


# --- People Management schemas ---


class PersonAlias(BaseModel):
    normalized_name: str
    display_name: str


class Person(BaseModel):
    person_id: str
    display_name: str
    normalized_name: str
    vault_id: Optional[str] = None
    aliases: list[PersonAlias] = []
    summary_count: int = 0


class PersonCandidate(BaseModel):
    candidate_id: str
    display_name: str
    normalized_name: str
    status: str


class AssociatedSummary(BaseModel):
    summary_id: str
    period_type: str
    period_key: str
    note: Optional[str] = None
    display_order: Optional[int] = None


class PersonCandidateDetail(PersonCandidate):
    summaries: list[AssociatedSummary] = []
    assigned_summaries_count: int = 0


class PersonAssignmentRequest(BaseModel):
    target_person_id: str


class RelationCounts(BaseModel):
    summaries: int
    aliases: int
    assignments: int


class PersonDetail(Person):
    summaries: list[AssociatedSummary] = []
    relation_counts: Optional[RelationCounts] = None


class PersonEditRequest(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[list[str]] = None


class PersonDeleteResponse(BaseModel):
    success: bool
    deleted_summary_people: int
    deleted_aliases: int
    deleted_assignments: int


class PersonActionResponse(BaseModel):
    success: bool


class CandidateResolveRequest(BaseModel):
    target_person_id: str


class PersonPromoteRequest(BaseModel):
    display_name: str


class PeopleMergeRequest(BaseModel):
    from_person_id: str
    to_person_id: str


class DuplicateVaultMatch(BaseModel):
    unlinked_person: Person
    vault_person: dict[str, Any]


class DuplicateSameVaultIdGroup(BaseModel):
    vault_id: str
    people: list[Person]


class DuplicatesResponse(BaseModel):
    vault_matches: list[DuplicateVaultMatch] = []
    same_vault_id_groups: list[DuplicateSameVaultIdGroup] = []


class SyncPeopleResponse(BaseModel):
    # True when a sync was actually applied (POST /people/sync); False for the
    # read-only vault report (GET /people/vault-report), which never syncs.
    synced: bool
    loader_report: dict[str, Any]
    db_conflicts: dict[str, Any]


class MergedSummaryPreview(BaseModel):
    summary_id: str
    period_key: str
    period_type: str
    from_note: Optional[str] = None
    to_note: Optional[str] = None
    merged_note: Optional[str] = None
    merged_display_order: Optional[int] = None


class AliasTransferPreview(BaseModel):
    normalized_name: str
    display_name: str


class PeopleMergePreviewResponse(BaseModel):
    allowed: bool
    reason: Optional[str] = None
    from_person: Optional[Person] = None
    to_person: Optional[Person] = None
    transferred_summaries_count: int
    transferred_aliases_count: int
    alias_transfers: list[AliasTransferPreview] = []
    merged_summaries: list[MergedSummaryPreview] = []


# --- Project Management Schemas ---

class Project(BaseModel):
    project_id: int
    normalized_name: str
    display_name: str
    domain: Literal["work", "personal"]
    status: Literal["inquiry", "active", "paused", "completed", "cancelled"]
    goal: Optional[str] = None
    description: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    completed_date: Optional[str] = None
    project_path: Optional[str] = None
    reference_url: Optional[str] = None
    created_at: str
    updated_at: str
    summary_count: int = 0


class ProjectDetail(Project):
    summaries: list[AssociatedSummary] = []


class ProjectCreateRequest(BaseModel):
    display_name: str
    domain: Literal["work", "personal"] = "personal"
    status: Literal["inquiry", "active", "paused", "completed", "cancelled"] = "inquiry"
    goal: Optional[str] = None
    description: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    completed_date: Optional[str] = None
    project_path: Optional[str] = None
    reference_url: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    domain: Optional[Literal["work", "personal"]] = None
    status: Optional[Literal["inquiry", "active", "paused", "completed", "cancelled"]] = None
    goal: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[list[str]] = None
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    completed_date: Optional[str] = None
    project_path: Optional[str] = None
    reference_url: Optional[str] = None


class ProjectCandidateDetail(ProjectCandidate):
    summaries: list[AssociatedSummary] = []
    assigned_summaries_count: int = 0


class ProjectCandidateResolveRequest(BaseModel):
    action: Literal["approve_new", "link_existing", "reject", "reopen_rejected"]
    target_project_id: Optional[int] = None
    # Allowed editing field values during resolution/approval
    display_name: Optional[str] = None
    domain: Optional[Literal["work", "personal"]] = None
    status: Optional[Literal["inquiry", "active", "paused", "completed", "cancelled"]] = None
    goal: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[list[str]] = None
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    completed_date: Optional[str] = None
    project_path: Optional[str] = None
    reference_url: Optional[str] = None

    @model_validator(mode="after")
    def validate_resolve_request(self) -> "ProjectCandidateResolveRequest":
        if self.action == "link_existing":
            if self.target_project_id is None or self.target_project_id <= 0:
                raise ValueError("target_project_id is required and must be a valid positive integer for link_existing")
        return self


# --- Task Config schemas ---

class TaskItem(BaseModel):
    id: str
    enabled: bool = True
    schedule: dict
    command: str
    is_preset: bool
    preset_flag: Optional[str] = None
    preset_name: Optional[str] = None
    next_run: Optional[str] = None


# --- Execution Log schemas ---

class ExecutionLogItem(BaseModel):
    id: str
    kind: Literal["command", "llm"]
    status: Literal["running", "succeeded", "failed"]
    name: str
    started_at: str
    finished_at: Optional[str] = None
    summary: Optional[str] = None


class ExecutionLogListResponse(BaseModel):
    items: list[ExecutionLogItem]
    total: int


class ExecutionChildLLMCall(BaseModel):
    call_id: str
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None
    status: str
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None


class CommandRunDetail(BaseModel):
    run_id: str
    command: str
    args_json: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None
    status: str
    summary: Optional[str] = None
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    traceback: Optional[str] = None
    llm_calls: list[ExecutionChildLLMCall] = []


class LLMCallDetail(BaseModel):
    call_id: str
    run_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    prompt: Optional[str] = None
    response: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    started_at: str
    finished_at: Optional[str] = None
    status: str
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    traceback: Optional[str] = None


# --- Task State schemas ---

class TaskState(BaseModel):
    task_id: str
    last_check_at: str
    consecutive_empty_count: int
    last_processed_at: Optional[str] = None
    last_error_at: Optional[str] = None
    last_error_message: Optional[str] = None
    last_error_type: Optional[str] = None
    processed_count: int
    skipped_count: int
    failed_count: int
    updated_at: str


class TaskStateListResponse(BaseModel):
    items: list[TaskState]


class TaskConfigResponse(BaseModel):
    tasks: list[TaskItem]
    filepath: str
    revision: str


class TaskConfigRequest(BaseModel):
    revision: str
    tasks: list[dict]


class TaskConfigUpdateResponse(BaseModel):
    success: bool
    revision: str


class CommandPreviewRequest(BaseModel):
    command: str


class CommandSegment(BaseModel):
    cwd: Optional[str] = None
    args: list[str]


class CommandPreviewResponse(BaseModel):
    segments: list[CommandSegment]
    is_preset: bool
    preset_flag: Optional[str] = None
    preset_name: Optional[str] = None

# --- HITL schemas ---

class HitlQuestion(BaseModel):
    question_id: str
    run_id: str
    question_set_id: str
    question_key: str
    status: str
    question_type: str
    display_text: str
    choices: Optional[Any] = None
    answer: Optional[Any] = None
    is_required: int
    expires_at: Optional[str] = None
    answered_at: Optional[str] = None
    created_at: str
    updated_at: str
    sequence: int = 0
    title: Optional[str] = None
    prompt: Optional[str] = None
    context: Optional[Any] = None


class HitlRun(BaseModel):
    run_id: str
    handler: str
    status: str
    checkpoint: Optional[str] = None
    active_question_set_id: Optional[str] = None
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[str] = None
    retry_count: int
    error_message: Optional[str] = None
    created_at: str
    updated_at: str
    title: Optional[str] = None
    description: Optional[str] = None
    display_type: Optional[str] = None
    display_title: Optional[str] = None


class HitlRunDetail(HitlRun):
    questions: list[HitlQuestion] = []


class HitlRunListResponse(BaseModel):
    items: list[HitlRun]
    total: int


class SubmitAnswerRequest(BaseModel):
    answer: Any
    comment: Optional[str] = None
