"""Agent runs: dispatch, cancel, the PostgreSQL lease queue and the runner protocol.

Queue semantics (see .plan/decisions.md D-003):
- ``dispatch_run`` inserts a ``queued`` run.
- Runners ``claim`` runs for their host with ``FOR UPDATE SKIP LOCKED``; a claim sets a lease.
- Heartbeats extend leases; expired leases are declared ``lost`` by the reaper.
- A partial unique index guarantees a single active *write* run per workspace.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ohmypm.errors import Conflict, Forbidden, NotFound, ValidationFailed
from ohmypm.models import AgentProfile, AgentRun, AgentSession, Checkpoint, RunEvent, Runner, Task, Workspace
from ohmypm.schemas import RunCreate
from ohmypm.services import memory
from ohmypm.services import tasks as task_service
from ohmypm.services.auth import new_run_token, require_role
from ohmypm.services.common import Ctx, get_or_404, paginate, record_task_event, utcnow
from ohmypm_common.enums import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    ContextMode,
    Role,
    RunEventType,
    RunStatus,
    SessionStatus,
    TaskStatus,
)
from ohmypm_common.protocol import (
    ClaimRequest,
    HeartbeatRequest,
    HeartbeatResponse,
    ProfileSpec,
    RunAssignment,
    RunEventIn,
    RunFinishRequest,
    RunnerRegisterRequest,
    RunnerRegisterResponse,
    RunProgressUpdate,
)
from ohmypm_common.redact import redact, truncate

log = logging.getLogger(__name__)

ACTIVE = [s.value for s in ACTIVE_RUN_STATUSES]
TERMINAL = [s.value for s in TERMINAL_RUN_STATUSES]
MAX_EVENT_TEXT = 20_000


# ---------------------------------------------------------------- events


async def _allocate_seq(session: AsyncSession, run_id: uuid.UUID, count: int) -> int:
    """Reserve ``count`` sequence numbers; returns the last one.

    The UPDATE row-locks the run until commit, so commit order equals seq order and SSE
    readers polling ``seq > last`` never skip an event.
    """
    result = await session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(event_seq=AgentRun.event_seq + count)
        .returning(AgentRun.event_seq)
        .execution_options(synchronize_session=False)
    )
    return int(result.scalar_one())


async def append_server_event(
    session: AsyncSession, run: AgentRun, event_type: RunEventType | str, payload: dict[str, Any] | None = None
) -> None:
    seq = await _allocate_seq(session, run.id, 1)
    session.add(RunEvent(run_id=run.id, seq=seq, event_type=str(event_type), timestamp=utcnow(), payload=payload or {}))


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return truncate(value, MAX_EVENT_TEXT)
        if isinstance(value, dict):
            return {str(k): walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value[:200]]
        return value

    return walk(redact(payload))  # type: ignore[no-any-return]


async def list_run_events(
    ctx: Ctx, run_id: uuid.UUID, *, after_seq: int = 0, limit: int = 500, event_types: Sequence[str] | None = None
) -> Sequence[RunEvent]:
    stmt = select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
    if event_types:
        stmt = stmt.where(RunEvent.event_type.in_(list(event_types)))
    stmt = stmt.order_by(RunEvent.seq).limit(max(1, min(limit, 2000)))
    return (await ctx.session.execute(stmt)).scalars().all()


# ---------------------------------------------------------------- dispatch / query / cancel


async def _resolve_profile(ctx: Ctx, data: RunCreate) -> AgentProfile | None:
    if data.profile_id is not None:
        return await get_or_404(ctx.session, AgentProfile, data.profile_id, "agent profile")
    if data.profile_name:
        profile = (
            await ctx.session.execute(select(AgentProfile).where(AgentProfile.name == data.profile_name))
        ).scalar_one_or_none()
        if profile is None:
            raise NotFound(f"agent profile {data.profile_name!r} not found")
        return profile
    if data.agent_type:
        return (
            await ctx.session.execute(
                select(AgentProfile).where(
                    AgentProfile.agent_type == data.agent_type, AgentProfile.is_default.is_(True)
                )
            )
        ).scalar_one_or_none()
    return None


async def _check_dispatch_permission(ctx: Ctx) -> int:
    """Returns the dispatch depth for the new run."""
    p = ctx.principal
    if p.role is Role.ADMIN:
        return 0
    if p.role is not Role.AGENT:
        raise Forbidden("only admins and agents can dispatch runs")
    depth = p.dispatch_depth + 1
    if depth > ctx.settings.agent_max_dispatch_depth:
        raise Forbidden(
            "agents are not allowed to dispatch runs at this depth",
            code="dispatch_depth_exceeded",
            details={"depth": depth, "max": ctx.settings.agent_max_dispatch_depth},
        )
    if p.run_id is not None:
        children = (
            await ctx.session.execute(
                select(func.count()).select_from(AgentRun).where(AgentRun.parent_run_id == p.run_id)
            )
        ).scalar_one()
        if children >= ctx.settings.agent_max_child_runs:
            raise Forbidden("child run limit reached", code="child_run_limit")
    return depth


async def dispatch_run(ctx: Ctx, data: RunCreate, *, idempotency_key: str | None = None) -> AgentRun:
    depth = await _check_dispatch_permission(ctx)
    task = await task_service.get_task(ctx, data.task_id)
    if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        raise Conflict(f"task T-{task.number} is {task.status}; reopen it first", code="task_closed")
    unmet = await task_service.unmet_dependencies(ctx, task.id)
    if unmet and not data.force:
        raise Conflict(
            "task has unfinished dependencies", code="dependencies_unmet", details={"unmet": [str(u) for u in unmet]}
        )
    profile = await _resolve_profile(ctx, data)
    agent_type = data.agent_type or (profile.agent_type if profile else None)
    if not agent_type:
        raise ValidationFailed("agent_type or profile is required")
    if profile is not None and profile.agent_type != agent_type:
        raise ValidationFailed(f"profile {profile.name!r} is for agent {profile.agent_type!r}, not {agent_type!r}")
    workspace_id = data.workspace_id or task.workspace_id
    if workspace_id is None:
        raise ValidationFailed("a workspace is required to run an agent (task has none)", code="workspace_required")
    await get_or_404(ctx.session, Workspace, workspace_id, "workspace")

    session: AgentSession | None = None
    if data.session_id is not None:
        session = await memory.get_session(ctx, data.session_id)
        if session.task_id != task.id:
            raise ValidationFailed("session does not belong to this task")
        if session.agent_type != agent_type:
            raise ValidationFailed("session belongs to a different agent type")
    elif data.resume_native:
        session = (
            await ctx.session.execute(
                select(AgentSession)
                .where(
                    AgentSession.task_id == task.id,
                    AgentSession.agent_type == agent_type,
                    AgentSession.native_session_id.is_not(None),
                )
                .order_by(AgentSession.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if session is None:
        session = AgentSession(
            task_id=task.id,
            agent_type=agent_type,
            created_by=ctx.actor,
            model=(profile.options.get("model") if profile else None),
        )
        ctx.session.add(session)
        await ctx.session.flush()
        await record_task_event(
            ctx, task.id, "session.created", {"session_id": str(session.id), "agent_type": agent_type}
        )
    elif session.status != SessionStatus.ACTIVE:
        session.status = SessionStatus.ACTIVE.value

    if data.from_checkpoint_id is not None:
        checkpoint = await get_or_404(ctx.session, Checkpoint, data.from_checkpoint_id, "checkpoint")
        if checkpoint.task_id != task.id:
            raise ValidationFailed("checkpoint does not belong to this task")

    timeout = (
        data.timeout_seconds
        or (profile.timeout_seconds if profile else None)
        or ctx.settings.default_run_timeout_seconds
    )
    timeout = min(timeout, ctx.settings.max_run_timeout_seconds)
    write_mode = data.write_mode if data.write_mode is not None else (profile.write_mode if profile else True)
    run = AgentRun(
        task_id=task.id,
        session_id=session.id,
        workspace_id=workspace_id,
        agent_type=agent_type,
        agent_profile_id=profile.id if profile else None,
        profile_snapshot=(
            {"id": str(profile.id), "name": profile.name, "options": profile.options}
            if profile
            else {"name": f"{agent_type} (defaults)", "options": {}}
        ),
        status=RunStatus.QUEUED.value,
        write_mode=write_mode,
        instructions=data.instructions,
        context_mode=data.context_mode.value,
        from_checkpoint_id=data.from_checkpoint_id,
        resume_native=data.resume_native,
        timeout_seconds=timeout,
        dispatch_depth=depth,
        parent_run_id=ctx.principal.run_id,
        idempotency_key=idempotency_key,
        created_by=ctx.actor,
        metadata_=data.metadata,
    )
    ctx.session.add(run)
    await ctx.session.flush()
    await append_server_event(
        ctx.session,
        run,
        RunEventType.RUN_QUEUED,
        {"agent_type": agent_type, "profile": run.profile_snapshot.get("name")},
    )
    await record_task_event(
        ctx,
        task.id,
        "run.dispatched",
        {
            "run_id": str(run.id),
            "agent_type": agent_type,
            "workspace_id": str(workspace_id),
            "session_id": str(session.id),
        },
    )
    await ctx.session.flush()
    await ctx.session.refresh(run)
    return run


async def get_run(ctx: Ctx, run_id: uuid.UUID) -> AgentRun:
    return await get_or_404(ctx.session, AgentRun, run_id, "run")


async def list_runs(
    ctx: Ctx,
    *,
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    runner_id: uuid.UUID | None = None,
    statuses: Sequence[RunStatus] | None = None,
    active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[AgentRun], int]:
    stmt = select(AgentRun)
    if task_id is not None:
        stmt = stmt.where(AgentRun.task_id == task_id)
    if project_id is not None:
        stmt = stmt.join(Task, Task.id == AgentRun.task_id).where(Task.project_id == project_id)
    if workspace_id is not None:
        stmt = stmt.where(AgentRun.workspace_id == workspace_id)
    if runner_id is not None:
        stmt = stmt.where(AgentRun.runner_id == runner_id)
    if statuses:
        stmt = stmt.where(AgentRun.status.in_([s.value for s in statuses]))
    if active is True:
        stmt = stmt.where(AgentRun.status.in_([*ACTIVE, RunStatus.QUEUED.value]))
    elif active is False:
        stmt = stmt.where(AgentRun.status.in_(TERMINAL))
    stmt = stmt.order_by(AgentRun.created_at.desc(), AgentRun.id)
    return await paginate(ctx.session, stmt, limit, offset)


async def request_cancel(ctx: Ctx, run: AgentRun, reason: str = "") -> AgentRun:
    p = ctx.principal
    if p.role is Role.AGENT and p.run_id is not None and run.id != p.run_id and run.parent_run_id != p.run_id:
        raise Forbidden("agents may only cancel their own run or runs they dispatched")
    if run.status in TERMINAL:
        raise Conflict(f"run is already {run.status}", code="run_finished")
    now = utcnow()
    if run.status == RunStatus.QUEUED:
        run.status = RunStatus.CANCELLED.value
        run.finished_at = now
        run.error = reason or "cancelled before start"
        await append_server_event(
            ctx.session, run, RunEventType.RUN_STATUS, {"status": RunStatus.CANCELLED.value, "reason": reason}
        )
        await record_task_event(ctx, run.task_id, "run.cancelled", {"run_id": str(run.id), "reason": reason})
    elif run.cancel_requested_at is None:
        run.cancel_requested_at = now
        await append_server_event(ctx.session, run, RunEventType.RUN_CANCEL_REQUESTED, {"reason": reason})
        await record_task_event(ctx, run.task_id, "run.cancel_requested", {"run_id": str(run.id), "reason": reason})
    await ctx.session.flush()
    return run


# ---------------------------------------------------------------- runners


async def list_runners(ctx: Ctx) -> list[tuple[Runner, bool, int]]:
    runners = (await ctx.session.execute(select(Runner).order_by(Runner.name))).scalars().all()
    counts = dict(
        (
            await ctx.session.execute(
                select(AgentRun.runner_id, func.count()).where(AgentRun.status.in_(ACTIVE)).group_by(AgentRun.runner_id)
            )
        ).all()
    )
    cutoff = utcnow() - timedelta(seconds=ctx.settings.runner_offline_after_seconds)
    return [(r, r.last_heartbeat_at >= cutoff, int(counts.get(r.id, 0))) for r in runners]


def _require_runner(ctx: Ctx) -> None:
    require_role(ctx.principal, Role.RUNNER, Role.ADMIN)


async def _get_runner(ctx: Ctx, runner_id: uuid.UUID) -> Runner:
    runner = await ctx.session.get(Runner, runner_id)
    if runner is None:
        raise Conflict("runner is not registered; call /api/runner/register first", code="runner_not_registered")
    return runner


async def _finalize(
    ctx: Ctx, run: AgentRun, status: RunStatus, *, error: str | None = None, error_code: str | None = None
) -> None:
    run.status = status.value
    run.finished_at = utcnow()
    run.lease_expires_at = None
    if error:
        run.error = error
    if error_code:
        run.error_code = error_code
    await append_server_event(
        ctx.session, run, RunEventType.RUN_STATUS, {"status": status.value, "error": error, "error_code": error_code}
    )
    await record_task_event(
        ctx,
        run.task_id,
        "run.finished",
        {"run_id": str(run.id), "status": status.value, "error": error, "exit_code": run.exit_code},
    )


async def register_runner(ctx: Ctx, req: RunnerRegisterRequest) -> RunnerRegisterResponse:
    _require_runner(ctx)
    runner = await ctx.session.get(Runner, req.runner_id)
    if runner is None:
        runner = Runner(id=req.runner_id, name=req.name, host_id=req.host_id)
        ctx.session.add(runner)
    runner.name = req.name
    runner.host_id = req.host_id
    runner.version = req.version
    runner.max_parallel = req.max_parallel
    runner.allowed_roots = list(req.allowed_roots)
    runner.agents = [a.model_dump() for a in req.agents]
    runner.last_heartbeat_at = utcnow()
    await ctx.session.flush()
    # A (re)registering runner has no live processes from a previous incarnation.
    orphaned = (
        (
            await ctx.session.execute(
                select(AgentRun).where(AgentRun.runner_id == runner.id, AgentRun.status.in_(ACTIVE)).with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for run in orphaned:
        await _finalize(
            ctx,
            run,
            RunStatus.INTERRUPTED,
            error="runner restarted while the run was active",
            error_code="runner_restarted",
        )
        await _auto_checkpoint(ctx, run)
    await ctx.session.flush()
    s = ctx.settings
    return RunnerRegisterResponse(
        runner_id=runner.id,
        interrupted_run_ids=[r.id for r in orphaned],
        heartbeat_interval_seconds=s.heartbeat_interval_seconds,
        poll_interval_seconds=s.poll_interval_seconds,
        lease_seconds=s.lease_seconds,
    )


async def heartbeat(ctx: Ctx, req: HeartbeatRequest) -> HeartbeatResponse:
    _require_runner(ctx)
    runner = await _get_runner(ctx, req.runner_id)
    now = utcnow()
    runner.last_heartbeat_at = now
    if req.agents is not None:
        runner.agents = [a.model_dump() for a in req.agents]
    response = HeartbeatResponse()
    if req.active_run_ids:
        runs = (
            (await ctx.session.execute(select(AgentRun).where(AgentRun.id.in_(req.active_run_ids)).with_for_update()))
            .scalars()
            .all()
        )
        found = {r.id: r for r in runs}
        for run_id in req.active_run_ids:
            run = found.get(run_id)
            if run is None or run.runner_id != runner.id or run.status not in ACTIVE:
                response.stop_run_ids.append(run_id)
                continue
            run.heartbeat_at = now
            run.lease_expires_at = now + timedelta(seconds=ctx.settings.lease_seconds)
            if run.cancel_requested_at is not None:
                response.cancel_run_ids.append(run_id)
    await ctx.session.flush()
    return response


def _path_allowed(path: str, roots: Sequence[str]) -> bool:
    if not roots:
        return False
    candidate = PurePosixPath(path)
    return any(candidate == PurePosixPath(r) or PurePosixPath(r) in candidate.parents for r in roots)


async def claim_runs(ctx: Ctx, req: ClaimRequest) -> list[RunAssignment]:
    from ohmypm.services.prompt import build_run_prompt

    _require_runner(ctx)
    runner = await _get_runner(ctx, req.runner_id)
    runner.last_heartbeat_at = utcnow()
    await reap_expired_leases(ctx)
    if not req.agent_types:
        return []
    candidates = (
        await ctx.session.execute(
            select(AgentRun, Workspace)
            .join(Workspace, Workspace.id == AgentRun.workspace_id)
            .where(
                AgentRun.status == RunStatus.QUEUED.value,
                Workspace.host_id == runner.host_id,
                AgentRun.agent_type.in_(req.agent_types),
                or_(AgentRun.runner_id.is_(None), AgentRun.runner_id == runner.id),
            )
            .order_by(AgentRun.created_at)
            .limit(req.capacity * 5)
            .with_for_update(of=AgentRun, skip_locked=True)
        )
    ).all()
    busy = set(
        (
            await ctx.session.execute(
                select(AgentRun.workspace_id).where(AgentRun.status.in_(ACTIVE), AgentRun.write_mode.is_(True))
            )
        )
        .scalars()
        .all()
    )
    assignments: list[RunAssignment] = []
    for run, workspace in candidates:
        if len(assignments) >= req.capacity:
            break
        if run.write_mode and workspace.id in busy:
            continue
        if not _path_allowed(workspace.root_path, runner.allowed_roots):
            continue
        token, token_hash = new_run_token()
        now = utcnow()
        try:
            async with ctx.session.begin_nested():
                run.status = RunStatus.STARTING.value
                run.runner_id = runner.id
                run.claimed_at = now
                run.heartbeat_at = now
                run.lease_expires_at = now + timedelta(seconds=ctx.settings.lease_seconds)
                run.agent_token_hash = token_hash
                await ctx.session.flush()
        except IntegrityError:
            # Lost a race for the workspace write lock; leave it queued.
            await ctx.session.refresh(run)
            continue
        if run.write_mode:
            busy.add(workspace.id)
        task = await task_service.get_task(ctx, run.task_id)
        if task.status in (TaskStatus.TODO, TaskStatus.BLOCKED):
            await task_service.set_task_status(ctx, task, TaskStatus.IN_PROGRESS, f"run {run.id} claimed")
        await append_server_event(
            ctx.session, run, RunEventType.RUN_CLAIMED, {"runner_id": str(runner.id), "runner": runner.name}
        )
        native_session_id = None
        if run.resume_native and run.session_id is not None:
            session = await ctx.session.get(AgentSession, run.session_id)
            native_session_id = session.native_session_id if session else None
        prompt = await build_run_prompt(ctx, run, task)
        snapshot = run.profile_snapshot or {}
        assignments.append(
            RunAssignment(
                run_id=run.id,
                task_id=run.task_id,
                session_id=run.session_id,
                workspace_id=workspace.id,
                workspace_path=workspace.root_path,
                agent_type=run.agent_type,
                write_mode=run.write_mode,
                profile=ProfileSpec(
                    id=run.agent_profile_id,
                    name=str(snapshot.get("name", run.agent_type)),
                    options=dict(snapshot.get("options") or {}),
                ),
                prompt=prompt,
                agent_token=token,
                timeout_seconds=run.timeout_seconds,
                native_session_id=native_session_id,
                resume_native=run.resume_native,
                lease_expires_at=run.lease_expires_at,
            )
        )
    await ctx.session.flush()
    return assignments


async def _owned_run(ctx: Ctx, run_id: uuid.UUID, runner_id: uuid.UUID) -> AgentRun:
    _require_runner(ctx)
    run = (
        await ctx.session.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
    ).scalar_one_or_none()
    if run is None:
        raise NotFound(f"run {run_id} not found")
    if run.runner_id != runner_id:
        raise Forbidden("run is not assigned to this runner", code="not_run_owner")
    return run


async def report_progress(ctx: Ctx, run_id: uuid.UUID, runner_id: uuid.UUID, req: RunProgressUpdate) -> AgentRun:
    run = await _owned_run(ctx, run_id, runner_id)
    if run.status in TERMINAL:
        raise Conflict(f"run is already {run.status}", code="run_finished")
    if req.status is not None and req.status.value != run.status:
        if req.status not in (RunStatus.RUNNING, RunStatus.WAITING_APPROVAL):
            raise ValidationFailed("progress may only set running or waiting_approval; use finish")
        if req.status is RunStatus.RUNNING and run.started_at is None:
            run.started_at = utcnow()
        run.status = req.status.value
        await append_server_event(ctx.session, run, RunEventType.RUN_STATUS, {"status": req.status.value})
        if req.status is RunStatus.RUNNING and run.claimed_at is not None:
            await record_task_event(
                ctx, run.task_id, "run.started", {"run_id": str(run.id), "agent_type": run.agent_type}
            )
    if req.pid is not None:
        run.pid = req.pid
    if req.command is not None:
        run.command = [truncate(str(redact(a)), 500) for a in req.command[:100]]
    if req.native_session_id:
        await _set_native_session(ctx, run, req.native_session_id)
    await ctx.session.flush()
    return run


async def _set_native_session(ctx: Ctx, run: AgentRun, native_id: str) -> None:
    run.native_session_id = native_id
    if run.session_id is not None:
        session = await ctx.session.get(AgentSession, run.session_id)
        if session is not None:
            session.native_session_id = native_id


async def append_events(ctx: Ctx, run_id: uuid.UUID, runner_id: uuid.UUID, events: Sequence[RunEventIn]) -> int:
    run = await _owned_run(ctx, run_id, runner_id)
    if run.status in TERMINAL and run.finished_at and utcnow() - run.finished_at > timedelta(minutes=5):
        raise Conflict("run finished too long ago to accept events", code="run_finished")
    if not events:
        return 0
    existing = set(
        (
            await ctx.session.execute(
                select(RunEvent.client_id).where(
                    RunEvent.run_id == run.id, RunEvent.client_id.in_([e.client_id for e in events])
                )
            )
        )
        .scalars()
        .all()
    )
    fresh = [e for e in dict((e.client_id, e) for e in events).values() if e.client_id not in existing]
    if not fresh:
        return 0
    last = await _allocate_seq(ctx.session, run.id, len(fresh))
    first = last - len(fresh) + 1
    for offset, event in enumerate(fresh):
        ctx.session.add(
            RunEvent(
                run_id=run.id,
                seq=first + offset,
                client_id=event.client_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                payload=_clean_payload(event.payload),
            )
        )
    await ctx.session.flush()
    return len(fresh)


async def finish_run(ctx: Ctx, run_id: uuid.UUID, runner_id: uuid.UUID, req: RunFinishRequest) -> AgentRun:
    if req.status not in TERMINAL_RUN_STATUSES:
        raise ValidationFailed("finish requires a terminal status")
    run = await _owned_run(ctx, run_id, runner_id)
    if run.status in TERMINAL:
        return run  # idempotent: retried finish after a network error
    status = req.status
    if run.cancel_requested_at is not None and status in (RunStatus.FAILED, RunStatus.INTERRUPTED):
        status = RunStatus.CANCELLED
    run.exit_code = req.exit_code
    if req.result_summary:
        run.result_summary = truncate(str(redact(req.result_summary)), MAX_EVENT_TEXT)
    if req.usage:
        run.usage = _clean_payload(req.usage)
    if req.native_session_id:
        await _set_native_session(ctx, run, req.native_session_id)
    await _finalize(ctx, run, status, error=redact(req.error) if req.error else None, error_code=req.error_code)
    await _auto_checkpoint(ctx, run)
    await ctx.session.flush()
    return run


async def _auto_checkpoint(ctx: Ctx, run: AgentRun) -> None:
    if await memory.run_has_checkpoint(ctx, run.id):
        return
    parts = [f"Run {run.id} ({run.agent_type}) ended with status {run.status}."]
    if run.exit_code is not None:
        parts.append(f"Exit code {run.exit_code}.")
    if run.error:
        parts.append(f"Error: {truncate(run.error, 1000)}")
    if run.result_summary:
        parts.append(f"Agent's final message:\n{truncate(run.result_summary, 4000)}")
    parts.append("The agent did not record a checkpoint; verify the workspace state before continuing.")
    await memory.create_auto_checkpoint(ctx, run, "\n".join(parts))


async def reap_expired_leases(ctx: Ctx) -> list[uuid.UUID]:
    """Declare active runs whose lease expired as ``lost``."""
    expired = (
        (
            await ctx.session.execute(
                select(AgentRun)
                .where(AgentRun.status.in_(ACTIVE), AgentRun.lease_expires_at < func.now())
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for run in expired:
        await _finalize(
            ctx, run, RunStatus.LOST, error="runner stopped heartbeating (lease expired)", error_code="lease_expired"
        )
        await _auto_checkpoint(ctx, run)
    if expired:
        log.warning("declared %d run(s) lost after lease expiry", len(expired))
    await ctx.session.flush()
    return [r.id for r in expired]


def context_mode_of(run: AgentRun) -> ContextMode:
    try:
        return ContextMode(run.context_mode)
    except ValueError:
        return ContextMode.STANDARD
