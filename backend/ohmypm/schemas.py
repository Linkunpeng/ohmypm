"""Pydantic schemas shared by the REST API and MCP tools."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, field_validator

from ohmypm_common.enums import (
    ArtifactType,
    ContextMode,
    DecisionStatus,
    FindingKind,
    KnowledgeCategory,
    RunStatus,
    StorageMode,
    TaskPriority,
    TaskStatus,
    VerificationStatus,
)

T = TypeVar("T")

Metadata = Annotated[
    dict[str, Any],
    Field(default_factory=dict, validation_alias=AliasChoices("metadata_", "metadata")),
]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
LongText = Annotated[str, Field(max_length=200_000)]
StrList = Annotated[list[Annotated[str, Field(max_length=5000)]], Field(max_length=500)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ---------------------------------------------------------------- projects / workspaces


class ProjectCreate(BaseModel):
    id: uuid.UUID | None = Field(default=None, description="Existing PROJECT_ID to register; generated if omitted")
    name: ShortText
    description: LongText = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: ShortText | None = None
    description: LongText | None = None
    archived: bool | None = None
    metadata: dict[str, Any] | None = None
    expected_version: int | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    archived: bool
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    metadata: Metadata
    version: int


class ProjectStats(BaseModel):
    tasks_total: int = 0
    tasks_by_status: dict[str, int] = Field(default_factory=dict)
    active_runs: int = 0
    artifacts: int = 0
    pending_decisions: int = 0


class ProjectDetail(ProjectOut):
    stats: ProjectStats
    workspaces: list[WorkspaceOut] = Field(default_factory=list)


class WorkspaceResolve(BaseModel):
    """Upsert by (host_id, root_path). Used by CLI/runner when they see a directory."""

    host_id: ShortText
    root_path: Annotated[str, Field(min_length=1, max_length=4096)]
    project_id: uuid.UUID | None = None
    display_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("root_path")
    @classmethod
    def _absolute(cls, value: str) -> str:
        if not value.startswith("/") and not (len(value) > 2 and value[1] == ":"):
            raise ValueError("root_path must be absolute")
        if "\x00" in value:
            raise ValueError("root_path contains NUL")
        return value.rstrip("/") or "/"


class WorkspaceUpdate(BaseModel):
    project_id: uuid.UUID | None = None
    display_name: str | None = None
    metadata: dict[str, Any] | None = None


class WorkspaceOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    host_id: str
    root_path: str
    display_name: str
    created_at: datetime
    last_seen_at: datetime
    metadata: Metadata


# ---------------------------------------------------------------- tasks


class TaskCreate(BaseModel):
    raw_request: LongText = Field(min_length=1)
    title: ShortText | None = Field(default=None, description="Defaults to the first line of raw_request")
    description: LongText = ""
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.TODO
    project_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    parent_task_id: uuid.UUID | None = None
    acceptance_criteria: StrList = Field(default_factory=list)
    depends_on: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    title: ShortText | None = None
    description: LongText | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    project_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    acceptance_criteria: StrList | None = None
    completed_items: StrList | None = None
    remaining_items: StrList | None = None
    next_action: LongText | None = None
    blockers: StrList | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    note: str | None = Field(default=None, description="Free-text reason recorded in the task event")
    expected_version: int | None = None


class CriterionResult(BaseModel):
    criterion: str
    passed: bool
    evidence: str = ""


class TaskComplete(BaseModel):
    summary: Annotated[str, Field(min_length=1, max_length=20_000)]
    results: list[CriterionResult] = Field(default_factory=list)
    verification_command: str | None = None
    force: bool = Field(default=False, description="Admin only: complete despite unmet criteria")
    expected_version: int | None = None


class DependencyChange(BaseModel):
    depends_on_id: uuid.UUID


class TaskOut(ORMModel):
    id: uuid.UUID
    number: int
    project_id: uuid.UUID | None
    workspace_id: uuid.UUID | None
    parent_task_id: uuid.UUID | None
    title: str
    raw_request: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    acceptance_criteria: list[str]
    acceptance_result: dict[str, Any] | None
    completed_items: list[str]
    remaining_items: list[str]
    next_action: str
    blockers: list[str]
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    created_by: str | None
    metadata: Metadata
    version: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        return f"T-{self.number}"


class TaskDetail(TaskOut):
    depends_on: list[uuid.UUID] = Field(default_factory=list)
    unmet_dependencies: list[uuid.UUID] = Field(default_factory=list)
    dependents: list[uuid.UUID] = Field(default_factory=list)


class TaskEventOut(ORMModel):
    id: int
    task_id: uuid.UUID
    event_type: str
    actor: str | None
    payload: dict[str, Any]
    created_at: datetime


# ---------------------------------------------------------------- sessions / checkpoints


class SessionCreate(BaseModel):
    task_id: uuid.UUID
    agent_type: ShortText
    model: str | None = None
    native_session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID
    agent_type: str
    model: str | None
    status: str
    native_session_id: str | None
    created_at: datetime
    updated_at: datetime
    metadata: Metadata


class CurrentIssue(BaseModel):
    description: str = ""
    error: str = ""
    root_cause: str = ""


class Attempt(BaseModel):
    action: str
    result: str
    conclusion: str = ""


class Finding(BaseModel):
    statement: str
    kind: FindingKind = FindingKind.VERIFIED
    evidence: str = ""


class Verification(BaseModel):
    command: str
    result: str
    passed: bool | None = None


class CheckpointCreate(BaseModel):
    summary: Annotated[str, Field(min_length=1, max_length=20_000)]
    session_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    completed: StrList = Field(default_factory=list)
    remaining: StrList = Field(default_factory=list)
    current_issue: CurrentIssue | None = None
    attempts: list[Attempt] = Field(default_factory=list, max_length=100)
    findings: list[Finding] = Field(default_factory=list, max_length=100)
    relevant_files: StrList = Field(default_factory=list)
    next_steps: StrList = Field(default_factory=list)
    verification: list[Verification] = Field(default_factory=list, max_length=50)
    apply_to_task: bool = Field(
        default=True, description="Copy completed/remaining/next step/blockers onto the task's current state"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class CheckpointOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID
    session_id: uuid.UUID | None
    run_id: uuid.UUID | None
    summary: str
    completed: list[str]
    remaining: list[str]
    current_issue: dict[str, Any] | None
    attempts: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    relevant_files: list[str]
    next_steps: list[str]
    verification: list[dict[str, Any]]
    auto_generated: bool
    created_at: datetime
    created_by: str | None
    metadata: Metadata


# ---------------------------------------------------------------- decisions


class DecisionOption(BaseModel):
    key: Annotated[str, Field(min_length=1, max_length=100)]
    label: Annotated[str, Field(min_length=1, max_length=500)]
    description: str = ""


class DecisionCreate(BaseModel):
    question: Annotated[str, Field(min_length=1, max_length=5000)]
    task_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    context: LongText = ""
    options: list[DecisionOption] = Field(default_factory=list, max_length=20)
    recommendation: str | None = None
    reasoning: str | None = None
    blocking: bool = Field(default=True, description="Blocking decisions move the task to awaiting_user")
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionResolve(BaseModel):
    selected_option: str | None = None
    response: str | None = None
    resume: bool = Field(default=False, description="Dispatch a new run with the task's last agent afterwards")
    expected_version: int | None = None


class DecisionCancel(BaseModel):
    reason: str = ""


class DecisionOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    project_id: uuid.UUID | None
    question: str
    context: str
    options: list[dict[str, Any]]
    recommendation: str | None
    reasoning: str | None
    status: DecisionStatus
    blocking: bool
    selected_option: str | None
    response: str | None
    created_at: datetime
    resolved_at: datetime | None
    created_by: str | None
    resolved_by: str | None
    metadata: Metadata
    version: int


# ---------------------------------------------------------------- knowledge


class KnowledgeCreate(BaseModel):
    title: ShortText
    content: Annotated[str, Field(min_length=1, max_length=100_000)]
    project_id: uuid.UUID | None = None
    category: KnowledgeCategory = KnowledgeCategory.OTHER
    source_task_id: uuid.UUID | None = None
    verified: bool = False
    tags: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeUpdate(BaseModel):
    title: ShortText | None = None
    content: Annotated[str, Field(min_length=1, max_length=100_000)] | None = None
    category: KnowledgeCategory | None = None
    verified: bool | None = None
    tags: list[str] | None = None
    superseded_by: uuid.UUID | None = None
    metadata: dict[str, Any] | None = None
    expected_version: int | None = None


class KnowledgeOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    title: str
    category: KnowledgeCategory
    content: str
    source_task_id: uuid.UUID | None
    verified: bool
    superseded_by: uuid.UUID | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    metadata: Metadata
    version: int


# ---------------------------------------------------------------- artifacts


class ArtifactUsage(BaseModel):
    prerequisites: list[str] = Field(default_factory=list)
    command: str = ""
    expected_result: str = ""
    manual: str = Field(default="", description="Free-form usage manual (markdown)")


class ArtifactBuild(BaseModel):
    command: str = ""
    source_path: str = ""
    notes: str = ""


class ArtifactVerification(BaseModel):
    status: VerificationStatus = VerificationStatus.UNKNOWN
    checked_at: datetime | None = None
    command: str = ""
    result: str = ""


class ArtifactCreate(BaseModel):
    name: ShortText
    type: ArtifactType = ArtifactType.OTHER
    storage_uri: Annotated[str, Field(min_length=1, max_length=4096)]
    storage_mode: StorageMode = StorageMode.REFERENCE
    task_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    version_label: str | None = None
    description: LongText = ""
    usage: ArtifactUsage = Field(default_factory=ArtifactUsage)
    build: ArtifactBuild = Field(default_factory=ArtifactBuild)
    environment: dict[str, Any] = Field(default_factory=dict)
    deployment: dict[str, Any] = Field(default_factory=dict)
    verification: ArtifactVerification = Field(default_factory=ArtifactVerification)
    tags: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactUpdate(BaseModel):
    name: ShortText | None = None
    type: ArtifactType | None = None
    storage_uri: Annotated[str, Field(min_length=1, max_length=4096)] | None = None
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    version_label: str | None = None
    description: LongText | None = None
    usage: ArtifactUsage | None = None
    build: ArtifactBuild | None = None
    environment: dict[str, Any] | None = None
    deployment: dict[str, Any] | None = None
    verification: ArtifactVerification | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    version_notes: str = ""
    expected_version: int | None = None


class ArtifactVersionOut(ORMModel):
    id: uuid.UUID
    artifact_id: uuid.UUID
    version_label: str | None
    storage_uri: str
    sha256: str | None
    size_bytes: int | None
    notes: str
    created_at: datetime
    created_by: str | None


class ArtifactOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    project_id: uuid.UUID | None
    workspace_id: uuid.UUID | None
    name: str
    type: ArtifactType
    storage_mode: StorageMode
    storage_uri: str
    sha256: str | None
    size_bytes: int | None
    version_label: str | None
    description: str
    usage: dict[str, Any]
    build: dict[str, Any]
    environment: dict[str, Any]
    deployment: dict[str, Any]
    verification: dict[str, Any]
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    metadata: Metadata
    version: int


class ArtifactDetail(ArtifactOut):
    versions: list[ArtifactVersionOut] = Field(default_factory=list)


# ---------------------------------------------------------------- agents / profiles / runners / runs


class AgentProfileCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")]
    agent_type: Annotated[str, Field(min_length=1, max_length=100)]
    description: str = ""
    options: dict[str, Any] = Field(default_factory=dict)
    write_mode: bool = True
    timeout_seconds: int | None = Field(default=None, gt=0)
    is_default: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentProfileUpdate(BaseModel):
    description: str | None = None
    options: dict[str, Any] | None = None
    write_mode: bool | None = None
    timeout_seconds: int | None = Field(default=None, gt=0)
    is_default: bool | None = None
    metadata: dict[str, Any] | None = None
    expected_version: int | None = None


class AgentProfileOut(ORMModel):
    id: uuid.UUID
    name: str
    agent_type: str
    description: str
    options: dict[str, Any]
    write_mode: bool
    timeout_seconds: int | None
    is_default: bool
    created_at: datetime
    updated_at: datetime
    metadata: Metadata
    version: int


class RunnerOut(ORMModel):
    id: uuid.UUID
    name: str
    host_id: str
    version: str
    max_parallel: int
    allowed_roots: list[str]
    agents: list[dict[str, Any]]
    registered_at: datetime
    last_heartbeat_at: datetime
    online: bool = False
    active_runs: int = 0


class AgentAvailability(BaseModel):
    agent_type: str
    display_name: str | None = None
    available_on: list[dict[str, Any]] = Field(default_factory=list)


class RunCreate(BaseModel):
    task_id: uuid.UUID
    agent_type: str | None = Field(default=None, description="Required unless profile is given")
    profile_id: uuid.UUID | None = None
    profile_name: str | None = None
    workspace_id: uuid.UUID | None = Field(default=None, description="Defaults to the task's workspace")
    instructions: LongText = ""
    context_mode: ContextMode = ContextMode.STANDARD
    session_id: uuid.UUID | None = Field(default=None, description="Continue an existing AgentSession")
    resume_native: bool = Field(default=False, description="Ask the CLI to resume its native session")
    from_checkpoint_id: uuid.UUID | None = None
    timeout_seconds: int | None = Field(default=None, gt=0)
    write_mode: bool | None = None
    force: bool = Field(default=False, description="Dispatch even if task dependencies are unmet")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunCancel(BaseModel):
    reason: str = ""


class RunOut(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID
    session_id: uuid.UUID | None
    runner_id: uuid.UUID | None
    workspace_id: uuid.UUID
    agent_type: str
    agent_profile_id: uuid.UUID | None
    profile_snapshot: dict[str, Any]
    status: RunStatus
    write_mode: bool
    instructions: str
    context_mode: str
    from_checkpoint_id: uuid.UUID | None
    resume_native: bool
    timeout_seconds: int
    pid: int | None
    exit_code: int | None
    error: str | None
    error_code: str | None
    result_summary: str | None
    usage: dict[str, Any]
    native_session_id: str | None
    command: list[str]
    created_at: datetime
    updated_at: datetime
    claimed_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    cancel_requested_at: datetime | None
    dispatch_depth: int
    parent_run_id: uuid.UUID | None
    created_by: str | None
    metadata: Metadata


class RunEventOut(ORMModel):
    id: int
    run_id: uuid.UUID
    seq: int
    event_type: str
    timestamp: datetime
    payload: dict[str, Any]


# ---------------------------------------------------------------- context / search / dashboard


class ContextOut(BaseModel):
    task_id: uuid.UUID
    mode: ContextMode
    max_tokens: int
    estimated_tokens: int
    truncated: bool
    sections: list[str]
    data: dict[str, Any]
    markdown: str


class SearchHit(BaseModel):
    kind: str
    id: uuid.UUID
    title: str
    snippet: str = ""
    score: float = 0.0
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    status: str | None = None


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]


class DashboardOut(BaseModel):
    projects_total: int
    tasks_by_status: dict[str, int]
    tasks_in_progress: list[TaskOut]
    tasks_awaiting_user: list[TaskOut]
    pending_decisions: list[DecisionOut]
    active_runs: list[RunOut]
    recent_runs: list[RunOut]
    recent_artifacts: list[ArtifactOut]
    runners_online: int


ProjectDetail.model_rebuild()
