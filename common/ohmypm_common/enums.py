"""Domain enumerations shared by the backend, runner and CLI.

Values are stored as plain text in PostgreSQL (guarded by CHECK constraints), so adding a
value requires a migration that updates the constraint.
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    AWAITING_USER = "awaiting_user"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


OPEN_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.AWAITING_USER}
)


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


PRIORITY_RANK: dict[TaskPriority, int] = {
    TaskPriority.URGENT: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.NORMAL: 2,
    TaskPriority.LOW: 3,
}


class RunStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    LOST = "lost"


# Runs that hold a runner slot / workspace write lock.
ACTIVE_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.STARTING, RunStatus.RUNNING, RunStatus.WAITING_APPROVAL}
)
TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.INTERRUPTED,
        RunStatus.LOST,
    }
)


class SessionStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class DecisionStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class ArtifactType(StrEnum):
    EXECUTABLE = "executable"
    SCRIPT = "script"
    LIBRARY = "library"
    DOCUMENT = "document"
    MODEL = "model"
    DATASET = "dataset"
    RESOURCE = "resource"
    CONTAINER = "container"
    REPORT = "report"
    OTHER = "other"


class StorageMode(StrEnum):
    REFERENCE = "reference"
    MANAGED = "managed"


class VerificationStatus(StrEnum):
    UNKNOWN = "unknown"
    PASSED = "passed"
    FAILED = "failed"


class KnowledgeCategory(StrEnum):
    ARCHITECTURE = "architecture"
    ENVIRONMENT = "environment"
    CONSTRAINT = "constraint"
    ALGORITHM = "algorithm"
    EXPERIENCE = "experience"
    KNOWN_ISSUE = "known_issue"
    OTHER = "other"


class FindingKind(StrEnum):
    """Epistemic status of a statement recorded in a checkpoint."""

    VERIFIED = "verified"
    INFERRED = "inferred"
    HYPOTHESIS = "hypothesis"


class ContextMode(StrEnum):
    BRIEF = "brief"
    STANDARD = "standard"
    FULL = "full"


class Role(StrEnum):
    ADMIN = "admin"
    RUNNER = "runner"
    AGENT = "agent"


class RunEventType(StrEnum):
    """Normalized run event types emitted by runner adapters and the backend."""

    RUN_QUEUED = "run.queued"
    RUN_CLAIMED = "run.claimed"
    RUN_STATUS = "run.status"
    RUN_CANCEL_REQUESTED = "run.cancel_requested"
    AGENT_STARTED = "agent.started"
    AGENT_MESSAGE = "agent.message"
    AGENT_THINKING = "agent.thinking"
    AGENT_PLAN = "agent.plan"
    AGENT_STATUS = "agent.status"
    AGENT_USAGE = "agent.usage"
    AGENT_RESULT = "agent.result"
    AGENT_WARNING = "agent.warning"
    AGENT_ERROR = "agent.error"
    AGENT_STDERR = "agent.stderr"
    AGENT_OUTPUT = "agent.output"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    FILE_CHANGED = "file.changed"
    CHECKPOINT_CREATED = "checkpoint.created"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DENIED = "approval.denied"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
