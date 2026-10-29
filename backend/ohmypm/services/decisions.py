"""Decisions that need a human answer.

A blocking decision moves its task to ``awaiting_user``; resolving the last pending blocking
decision restores the task's previous status and can optionally dispatch a follow-up run.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from ohmypm.errors import Conflict, ValidationFailed
from ohmypm.models import AgentRun, Decision, Task
from ohmypm.schemas import DecisionCreate, DecisionResolve, RunCreate
from ohmypm.services import tasks as task_service
from ohmypm.services.common import Ctx, check_version, get_or_404, paginate, record_task_event, utcnow
from ohmypm_common.enums import ContextMode, DecisionStatus, TaskStatus

STATUS_BEFORE_KEY = "status_before_decision"


async def create_decision(ctx: Ctx, data: DecisionCreate) -> Decision:
    task: Task | None = None
    project_id = data.project_id
    if data.task_id is not None:
        task = await task_service.get_task(ctx, data.task_id)
        task_service.ensure_can_write_task(ctx, task)
        project_id = project_id or task.project_id
    keys = [o.key for o in data.options]
    if len(keys) != len(set(keys)):
        raise ValidationFailed("option keys must be unique")
    decision = Decision(
        task_id=data.task_id,
        project_id=project_id,
        question=data.question,
        context=data.context,
        options=[o.model_dump() for o in data.options],
        recommendation=data.recommendation,
        reasoning=data.reasoning,
        blocking=data.blocking and task is not None,
        created_by=ctx.actor,
        metadata_=data.metadata,
    )
    ctx.session.add(decision)
    await ctx.session.flush()
    if task is not None:
        await record_task_event(
            ctx,
            task.id,
            "decision.created",
            {"decision_id": str(decision.id), "question": data.question[:500], "blocking": decision.blocking},
        )
        if decision.blocking and task.status not in (
            TaskStatus.AWAITING_USER,
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
        ):
            task.metadata_ = {**task.metadata_, STATUS_BEFORE_KEY: task.status}
            await task_service.set_task_status(
                ctx, task, TaskStatus.AWAITING_USER, f"waiting for decision {decision.id}"
            )
    await ctx.session.flush()
    return decision


async def get_decision(ctx: Ctx, decision_id: uuid.UUID) -> Decision:
    return await get_or_404(ctx.session, Decision, decision_id, "decision")


async def list_decisions(
    ctx: Ctx,
    *,
    status: DecisionStatus | None = None,
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Decision], int]:
    stmt = select(Decision)
    if status is not None:
        stmt = stmt.where(Decision.status == status.value)
    if task_id is not None:
        stmt = stmt.where(Decision.task_id == task_id)
    if project_id is not None:
        stmt = stmt.where(Decision.project_id == project_id)
    stmt = stmt.order_by(Decision.created_at.desc(), Decision.id)
    return await paginate(ctx.session, stmt, limit, offset)


async def _maybe_release_task(ctx: Ctx, decision: Decision) -> Task | None:
    if decision.task_id is None or not decision.blocking:
        return None
    task = await task_service.get_task(ctx, decision.task_id)
    if task.status != TaskStatus.AWAITING_USER:
        return task
    still_pending = (
        await ctx.session.execute(
            select(func.count())
            .select_from(Decision)
            .where(
                Decision.task_id == task.id,
                Decision.status == DecisionStatus.PENDING.value,
                Decision.blocking.is_(True),
                Decision.id != decision.id,
            )
        )
    ).scalar_one()
    if still_pending:
        return task
    previous = task.metadata_.get(STATUS_BEFORE_KEY) or TaskStatus.IN_PROGRESS.value
    if previous == TaskStatus.AWAITING_USER.value:
        previous = TaskStatus.IN_PROGRESS.value
    task.metadata_ = {k: v for k, v in task.metadata_.items() if k != STATUS_BEFORE_KEY}
    await task_service.set_task_status(ctx, task, TaskStatus(previous), f"decision {decision.id} answered")
    return task


async def resolve_decision(ctx: Ctx, decision_id: uuid.UUID, data: DecisionResolve) -> tuple[Decision, AgentRun | None]:
    decision = await get_decision(ctx, decision_id)
    check_version(decision, data.expected_version)
    if decision.status != DecisionStatus.PENDING:
        raise Conflict(f"decision is already {decision.status}", code="decision_closed")
    if decision.options and data.selected_option is None and not data.response:
        raise ValidationFailed("select an option or provide a response")
    if data.selected_option is not None and decision.options:
        valid = {o.get("key") for o in decision.options}
        if data.selected_option not in valid:
            raise ValidationFailed(f"unknown option {data.selected_option!r}", details={"valid": sorted(valid)})
    decision.status = DecisionStatus.RESOLVED.value
    decision.selected_option = data.selected_option
    decision.response = data.response
    decision.resolved_at = utcnow()
    decision.resolved_by = ctx.actor
    await ctx.session.flush()
    task = await _maybe_release_task(ctx, decision)
    resumed: AgentRun | None = None
    if task is not None:
        await record_task_event(
            ctx,
            task.id,
            "decision.resolved",
            {
                "decision_id": str(decision.id),
                "selected_option": data.selected_option,
                "response": (data.response or "")[:1000],
            },
        )
        if data.resume:
            resumed = await _resume_after_decision(ctx, task, decision)
    return decision, resumed


async def _resume_after_decision(ctx: Ctx, task: Task, decision: Decision) -> AgentRun | None:
    from ohmypm.services import runs

    last = (
        await ctx.session.execute(
            select(AgentRun).where(AgentRun.task_id == task.id).order_by(AgentRun.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if last is None:
        return None
    answer = decision.selected_option or ""
    if decision.response:
        answer = f"{answer} — {decision.response}" if answer else decision.response
    return await runs.dispatch_run(
        ctx,
        RunCreate(
            task_id=task.id,
            agent_type=last.agent_type,
            profile_id=last.agent_profile_id,
            workspace_id=last.workspace_id,
            session_id=last.session_id,
            context_mode=ContextMode.STANDARD,
            instructions=(
                f"The user answered decision {decision.id}.\nQuestion: {decision.question}\n"
                f"Answer: {answer}\nContinue the task accordingly."
            ),
        ),
    )


async def cancel_decision(ctx: Ctx, decision_id: uuid.UUID, reason: str = "") -> Decision:
    decision = await get_decision(ctx, decision_id)
    if decision.status != DecisionStatus.PENDING:
        raise Conflict(f"decision is already {decision.status}", code="decision_closed")
    decision.status = DecisionStatus.CANCELLED.value
    decision.response = reason or decision.response
    decision.resolved_at = utcnow()
    decision.resolved_by = ctx.actor
    await ctx.session.flush()
    task = await _maybe_release_task(ctx, decision)
    if task is not None:
        await record_task_event(ctx, task.id, "decision.cancelled", {"decision_id": str(decision.id), "reason": reason})
    return decision
