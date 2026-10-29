"""SQLAlchemy ORM models — the authoritative data model.

Conventions:
- UUID primary keys for core entities; bigserial ids for append-only event tables.
- Enumerations are text columns guarded by CHECK constraints (see ``ohmypm_common.enums``).
- ``metadata_`` maps to the ``metadata`` JSONB column (``metadata`` is reserved by SQLAlchemy).
- ``version`` is the optimistic-concurrency counter (SQLAlchemy ``version_id_col``).
- ``search_vector`` columns are generated tsvectors (``simple`` config) with GIN indexes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ohmypm_common.enums import (
    ArtifactType,
    DecisionStatus,
    KnowledgeCategory,
    RunStatus,
    SessionStatus,
    StorageMode,
    TaskPriority,
    TaskStatus,
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _enum_check(column: str, values: type[Any]) -> str:
    joined = ", ".join(f"'{v.value}'" for v in values)
    return f"{column} IN ({joined})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


def _metadata() -> Mapped[dict[str, Any]]:
    return mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


def _json_list() -> Mapped[list[Any]]:
    return mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)


def _json_obj() -> Mapped[dict[str, Any]]:
    return mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    created_by: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = _metadata()
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(description, ''))", persisted=True),
    )

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        Index("ix_projects_search", "search_vector", postgresql_using="gin"),
        Index("ix_projects_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )


class Workspace(Base):
    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    host_id: Mapped[str] = mapped_column(Text, nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    metadata_: Mapped[dict[str, Any]] = _metadata()

    __table_args__ = (
        UniqueConstraint("host_id", "root_path"),
        Index(
            "ix_workspaces_root_path_trgm",
            "root_path",
            postgresql_using="gin",
            postgresql_ops={"root_path": "gin_trgm_ops"},
        ),
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Human-friendly sequential number (T-42).
    number: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_request: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=TaskStatus.TODO.value)
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default=TaskPriority.NORMAL.value)
    acceptance_criteria: Mapped[list[Any]] = _json_list()
    acceptance_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    completed_items: Mapped[list[Any]] = _json_list()
    remaining_items: Mapped[list[Any]] = _json_list()
    next_action: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    blockers: Mapped[list[Any]] = _json_list()
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}", default=list)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = _metadata()
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(description, '') || ' ' "
            "|| coalesce(raw_request, '') || ' ' || coalesce(next_action, ''))",
            persisted=True,
        ),
    )

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        CheckConstraint(_enum_check("status", TaskStatus), name="status"),
        CheckConstraint(_enum_check("priority", TaskPriority), name="priority"),
        Index("ix_tasks_status_updated", "status", "updated_at"),
        Index("ix_tasks_search", "search_vector", postgresql_using="gin"),
        Index("ix_tasks_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
        Index(
            "ix_tasks_raw_request_trgm",
            "raw_request",
            postgresql_using="gin",
            postgresql_ops={"raw_request": "gin_trgm_ops"},
        ),
    )


class TaskDependency(Base):
    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "task_dependencies"

    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"))
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        PrimaryKeyConstraint("task_id", "depends_on_id"),
        CheckConstraint("task_id <> depends_on_id", name="no_self_dependency"),
    )


class TaskEvent(Base):
    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = _json_obj()
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (Index("ix_task_events_task_id_id", "task_id", "id"),)


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    agent_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    options: Mapped[dict[str, Any]] = _json_obj()
    write_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    metadata_: Mapped[dict[str, Any]] = _metadata()
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        # At most one default profile per agent type.
        Index(
            "uq_agent_profiles_default_per_type",
            "agent_type",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class AgentSession(Base):
    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    agent_type: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=SessionStatus.ACTIVE.value)
    native_session_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    created_by: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = _metadata()

    __table_args__ = (CheckConstraint(_enum_check("status", SessionStatus), name="status"),)


class Runner(Base):
    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "runners"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    host_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    max_parallel: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    allowed_roots: Mapped[list[Any]] = _json_list()
    agents: Mapped[list[Any]] = _json_list()
    registered_at: Mapped[datetime] = _created_at()
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_: Mapped[dict[str, Any]] = _metadata()


class AgentRun(Base):
    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="SET NULL"), index=True
    )
    runner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runners.id", ondelete="SET NULL"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    agent_type: Mapped[str] = mapped_column(Text, nullable=False)
    agent_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_profiles.id", ondelete="SET NULL")
    )
    profile_snapshot: Mapped[dict[str, Any]] = _json_obj()
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=RunStatus.QUEUED.value)
    write_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    instructions: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    context_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="standard")
    from_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checkpoints.id", ondelete="SET NULL")
    )
    resume_native: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    pid: Mapped[int | None] = mapped_column(Integer)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, Any]] = _json_obj()
    native_session_id: Mapped[str | None] = mapped_column(Text)
    command: Mapped[list[Any]] = _json_list()
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0", default=0)
    dispatch_depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    agent_token_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    created_by: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = _metadata()

    __table_args__ = (
        CheckConstraint(_enum_check("status", RunStatus), name="status"),
        CheckConstraint("timeout_seconds > 0", name="timeout_positive"),
        Index("ix_agent_runs_status_created", "status", "created_at"),
        # Single active writer per workspace.
        Index(
            "uq_agent_runs_active_writer_per_workspace",
            "workspace_id",
            unique=True,
            postgresql_where=text("write_mode AND status IN ('starting', 'running', 'waiting_approval')"),
        ),
    )


class RunEvent(Base):
    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = _json_obj()
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        UniqueConstraint("run_id", "seq"),
        Index(
            "uq_run_events_client_id",
            "run_id",
            "client_id",
            unique=True,
            postgresql_where=text("client_id IS NOT NULL"),
        ),
    )


class Checkpoint(Base):
    """Append-only. A trigger (see migration) rejects UPDATE."""

    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "checkpoints"

    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="SET NULL")
    )
    # No FK to agent_runs: avoids a cycle with agent_runs.from_checkpoint_id.
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    completed: Mapped[list[Any]] = _json_list()
    remaining: Mapped[list[Any]] = _json_list()
    current_issue: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[list[Any]] = _json_list()
    findings: Mapped[list[Any]] = _json_list()
    relevant_files: Mapped[list[Any]] = _json_list()
    next_steps: Mapped[list[Any]] = _json_list()
    verification: Mapped[list[Any]] = _json_list()
    auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    created_at: Mapped[datetime] = _created_at()
    created_by: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = _metadata()
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)

    __table_args__ = (Index("ix_checkpoints_task_created", "task_id", "created_at"),)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    options: Mapped[list[Any]] = _json_list()
    recommendation: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=DecisionStatus.PENDING.value)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    selected_option: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = _metadata()
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(question, '') || ' ' || coalesce(context, '') || ' ' "
            "|| coalesce(response, ''))",
            persisted=True,
        ),
    )

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        CheckConstraint(_enum_check("status", DecisionStatus), name="status"),
        Index("ix_decisions_status", "status"),
        Index("ix_decisions_search", "search_vector", postgresql_using="gin"),
        Index(
            "ix_decisions_question_trgm",
            "question",
            postgresql_using="gin",
            postgresql_ops={"question": "gin_trgm_ops"},
        ),
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=StorageMode.REFERENCE.value)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    version_label: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    usage: Mapped[dict[str, Any]] = _json_obj()
    build: Mapped[dict[str, Any]] = _json_obj()
    environment: Mapped[dict[str, Any]] = _json_obj()
    deployment: Mapped[dict[str, Any]] = _json_obj()
    verification: Mapped[dict[str, Any]] = _json_obj()
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}", default=list)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    created_by: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = _metadata()
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(description, '') || ' ' "
            "|| coalesce(storage_uri, ''))",
            persisted=True,
        ),
    )

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        CheckConstraint(_enum_check("type", ArtifactType), name="type"),
        CheckConstraint(_enum_check("storage_mode", StorageMode), name="storage_mode"),
        Index("ix_artifacts_search", "search_vector", postgresql_using="gin"),
        Index("ix_artifacts_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )


class ArtifactVersion(Base):
    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "artifact_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    version_label: Mapped[str | None] = mapped_column(Text)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="", default="")
    created_at: Mapped[datetime] = _created_at()
    created_by: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = _metadata()


class ProjectKnowledge(Base):
    __tablename__ = "project_knowledge"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default=KnowledgeCategory.OTHER.value)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL")
    )
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_knowledge.id", ondelete="SET NULL")
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}", default=list)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    created_by: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = _metadata()
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))", persisted=True),
    )

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        CheckConstraint(_enum_check("category", KnowledgeCategory), name="category"),
        Index("ix_project_knowledge_search", "search_vector", postgresql_using="gin"),
        Index("ix_project_knowledge_tags", "tags", postgresql_using="gin"),
        Index(
            "ix_project_knowledge_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_project_knowledge_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
    )


class IdempotencyKey(Base):
    __mapper_args__ = {"eager_defaults": True}
    __tablename__ = "idempotency_keys"

    scope: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (PrimaryKeyConstraint("scope", "key"),)
