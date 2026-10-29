"""Agent sessions and checkpoints (append-only resumable state)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select

from ohmypm.errors import ValidationFailed
from ohmypm.models import AgentRun, AgentSession, Checkpoint
from ohmypm.schemas import CheckpointCreate, SessionCreate
from ohmypm.services.common import Ctx, dedupe, get_or_404, paginate, record_task_event
from ohmypm.services.tasks import ensure_can_write_task, get_task
from ohmypm_common.enums import RunEventType, SessionStatus


async def create_session(ctx: Ctx, data: SessionCreate) -> AgentSession:
    task = await get_task(ctx, data.task_id)
    ensure_can_write_task(ctx, task)
    session = AgentSession(
        task_id=task.id,
        agent_type=data.agent_type,
        model=data.model,
        native_session_id=data.native_session_id,
        created_by=ctx.actor,
        metadata_=data.metadata,
    )
    ctx.session.add(session)
    await ctx.session.flush()
    await record_task_event(
        ctx, task.id, "session.created", {"session_id": str(session.id), "agent_type": data.agent_type}
    )
    return session


async def get_session(ctx: Ctx, session_id: uuid.UUID) -> AgentSession:
    return await get_or_404(ctx.session, AgentSession, session_id, "session")


async def list_sessions(ctx: Ctx, task_id: uuid.UUID) -> Sequence[AgentSession]:
    stmt = select(AgentSession).where(AgentSession.task_id == task_id).order_by(AgentSession.created_at)
    return (await ctx.session.execute(stmt)).scalars().all()


async def close_session(ctx: Ctx, session_id: uuid.UUID) -> AgentSession:
    session = await get_session(ctx, session_id)
    session.status = SessionStatus.CLOSED.value
    await ctx.session.flush()
    return session


async def create_checkpoint(ctx: Ctx, task_id: uuid.UUID, data: CheckpointCreate) -> Checkpoint:
    from ohmypm.services import runs  # local import to avoid a cycle

    task = await get_task(ctx, task_id)
    ensure_can_write_task(ctx, task)
    run_id = data.run_id
    session_id = data.session_id
    # Agents launched by the runner write checkpoints for their own run by default.
    if ctx.principal.run_id is not None and ctx.principal.task_id == task.id:
        run_id = run_id or ctx.principal.run_id
    run: AgentRun | None = None
    if run_id is not None:
        run = await ctx.session.get(AgentRun, run_id)
        if run is None or run.task_id != task.id:
            raise ValidationFailed("run_id does not belong to this task")
        session_id = session_id or run.session_id
    if session_id is not None:
        session = await get_session(ctx, session_id)
        if session.task_id != task.id:
            raise ValidationFailed("session_id does not belong to this task")

    checkpoint = Checkpoint(
        task_id=task.id,
        session_id=session_id,
        run_id=run_id,
        summary=data.summary,
        completed=list(data.completed),
        remaining=list(data.remaining),
        current_issue=data.current_issue.model_dump() if data.current_issue else None,
        attempts=[a.model_dump() for a in data.attempts],
        findings=[f.model_dump(mode="json") for f in data.findings],
        relevant_files=list(data.relevant_files),
        next_steps=list(data.next_steps),
        verification=[v.model_dump() for v in data.verification],
        created_by=ctx.actor,
        metadata_=data.metadata,
    )
    ctx.session.add(checkpoint)
    await ctx.session.flush()

    if data.apply_to_task:
        task.completed_items = dedupe([*task.completed_items, *data.completed])
        if "remaining" in data.model_fields_set:
            task.remaining_items = list(data.remaining)
        if data.next_steps:
            task.next_action = data.next_steps[0]
        if data.current_issue and data.current_issue.description:
            task.blockers = dedupe([*task.blockers, data.current_issue.description])
    await record_task_event(
        ctx,
        task.id,
        "checkpoint.created",
        {"checkpoint_id": str(checkpoint.id), "summary": data.summary[:500], "run_id": str(run_id) if run_id else None},
    )
    if run is not None:
        await runs.append_server_event(
            ctx.session,
            run,
            RunEventType.CHECKPOINT_CREATED,
            {"checkpoint_id": str(checkpoint.id), "summary": data.summary[:500]},
        )
    await ctx.session.flush()
    return checkpoint


async def create_auto_checkpoint(ctx: Ctx, run: AgentRun, summary: str) -> Checkpoint:
    """Minimal handoff record written by the system when a run ends without a checkpoint."""
    task = await get_task(ctx, run.task_id)
    checkpoint = Checkpoint(
        task_id=task.id,
        session_id=run.session_id,
        run_id=run.id,
        summary=summary,
        remaining=list(task.remaining_items),
        next_steps=[task.next_action] if task.next_action else [],
        auto_generated=True,
        created_by="system",
        metadata_={"run_status": run.status, "exit_code": run.exit_code},
    )
    ctx.session.add(checkpoint)
    await ctx.session.flush()
    await record_task_event(
        ctx,
        task.id,
        "checkpoint.created",
        {"checkpoint_id": str(checkpoint.id), "summary": summary[:500], "run_id": str(run.id), "auto": True},
    )
    return checkpoint


async def list_checkpoints(
    ctx: Ctx, task_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> tuple[Sequence[Checkpoint], int]:
    await get_task(ctx, task_id)
    stmt = select(Checkpoint).where(Checkpoint.task_id == task_id).order_by(Checkpoint.created_at.desc(), Checkpoint.id)
    return await paginate(ctx.session, stmt, limit, offset)


async def get_checkpoint(ctx: Ctx, checkpoint_id: uuid.UUID) -> Checkpoint:
    return await get_or_404(ctx.session, Checkpoint, checkpoint_id, "checkpoint")


async def latest_checkpoint(ctx: Ctx, task_id: uuid.UUID, *, include_auto: bool = True) -> Checkpoint | None:
    stmt = select(Checkpoint).where(Checkpoint.task_id == task_id)
    if not include_auto:
        stmt = stmt.where(Checkpoint.auto_generated.is_(False))
    stmt = stmt.order_by(Checkpoint.created_at.desc()).limit(1)
    return (await ctx.session.execute(stmt)).scalar_one_or_none()


async def run_has_checkpoint(ctx: Ctx, run_id: uuid.UUID) -> bool:
    stmt = select(Checkpoint.id).where(Checkpoint.run_id == run_id).limit(1)
    return (await ctx.session.execute(stmt)).first() is not None
