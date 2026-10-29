"""Runner ↔ backend wire protocol (``/api/runner/*``).

Both sides import these models so the contract lives in one place.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ohmypm_common.enums import RunStatus


class AgentCapability(BaseModel):
    agent_type: str
    available: bool
    version: str | None = None
    executable: str | None = None
    detail: str | None = None
    builtin: bool = True
    max_parallel: int | None = None
    display_name: str | None = None


class RunnerRegisterRequest(BaseModel):
    runner_id: uuid.UUID
    name: str
    host_id: str
    version: str
    max_parallel: int = Field(ge=1, le=64)
    allowed_roots: list[str] = Field(default_factory=list)
    agents: list[AgentCapability] = Field(default_factory=list)


class RunnerRegisterResponse(BaseModel):
    runner_id: uuid.UUID
    interrupted_run_ids: list[uuid.UUID]
    heartbeat_interval_seconds: float
    poll_interval_seconds: float
    lease_seconds: float


class HeartbeatRequest(BaseModel):
    runner_id: uuid.UUID
    active_run_ids: list[uuid.UUID] = Field(default_factory=list)
    agents: list[AgentCapability] | None = None


class HeartbeatResponse(BaseModel):
    # Runs the user asked to cancel.
    cancel_run_ids: list[uuid.UUID] = Field(default_factory=list)
    # Runs the runner reported but the server no longer considers active for it
    # (e.g. declared lost). The runner must stop them.
    stop_run_ids: list[uuid.UUID] = Field(default_factory=list)


class ClaimRequest(BaseModel):
    runner_id: uuid.UUID
    capacity: int = Field(ge=1, le=64)
    agent_types: list[str]


class ProfileSpec(BaseModel):
    """Typed, whitelisted options; the runner adapter validates them again."""

    id: uuid.UUID | None = None
    name: str
    options: dict[str, Any] = Field(default_factory=dict)


class RunAssignment(BaseModel):
    run_id: uuid.UUID
    task_id: uuid.UUID
    session_id: uuid.UUID | None
    workspace_id: uuid.UUID
    workspace_path: str
    agent_type: str
    write_mode: bool
    profile: ProfileSpec
    prompt: str
    agent_token: str
    timeout_seconds: int
    native_session_id: str | None = None
    resume_native: bool = False
    lease_expires_at: datetime


class ClaimResponse(BaseModel):
    runs: list[RunAssignment] = Field(default_factory=list)


class RunEventIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class RunEventsBatch(BaseModel):
    events: list[RunEventIn] = Field(max_length=500)


class RunProgressUpdate(BaseModel):
    """Runner → server: the process started / changed observable state."""

    status: RunStatus | None = None
    pid: int | None = None
    native_session_id: str | None = None
    command: list[str] | None = None


class RunFinishRequest(BaseModel):
    status: RunStatus
    exit_code: int | None = None
    error: str | None = None
    error_code: str | None = None
    native_session_id: str | None = None
    result_summary: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
