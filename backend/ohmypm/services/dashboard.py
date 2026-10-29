"""Dashboard aggregate."""

from __future__ import annotations

from sqlalchemy import func, select

from ohmypm.models import AgentRun, Artifact, Decision, Project, Task
from ohmypm.schemas import ArtifactOut, DashboardOut, DecisionOut, RunOut, TaskOut
from ohmypm.services.common import Ctx
from ohmypm.services.runs import ACTIVE, list_runners
from ohmypm_common.enums import DecisionStatus, RunStatus, TaskStatus


async def dashboard(ctx: Ctx) -> DashboardOut:
    s = ctx.session
    projects_total = (
        await s.execute(select(func.count()).select_from(Project).where(Project.archived.is_(False)))
    ).scalar_one()
    by_status = {
        str(k): int(v) for k, v in (await s.execute(select(Task.status, func.count()).group_by(Task.status))).all()
    }

    async def tasks_with(status: TaskStatus) -> list[TaskOut]:
        rows = (
            (
                await s.execute(
                    select(Task).where(Task.status == status.value).order_by(Task.updated_at.desc()).limit(10)
                )
            )
            .scalars()
            .all()
        )
        return [TaskOut.model_validate(t) for t in rows]

    pending = (
        (
            await s.execute(
                select(Decision)
                .where(Decision.status == DecisionStatus.PENDING.value)
                .order_by(Decision.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    active = (
        (
            await s.execute(
                select(AgentRun)
                .where(AgentRun.status.in_([*ACTIVE, RunStatus.QUEUED.value]))
                .order_by(AgentRun.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    recent = (await s.execute(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(10))).scalars().all()
    artifacts = (await s.execute(select(Artifact).order_by(Artifact.created_at.desc()).limit(8))).scalars().all()
    runners = await list_runners(ctx)
    return DashboardOut(
        projects_total=int(projects_total),
        tasks_by_status=by_status,
        tasks_in_progress=await tasks_with(TaskStatus.IN_PROGRESS),
        tasks_awaiting_user=await tasks_with(TaskStatus.AWAITING_USER),
        pending_decisions=[DecisionOut.model_validate(d) for d in pending],
        active_runs=[RunOut.model_validate(r) for r in active],
        recent_runs=[RunOut.model_validate(r) for r in recent],
        recent_artifacts=[ArtifactOut.model_validate(a) for a in artifacts],
        runners_online=sum(1 for _, online, _ in runners if online),
    )
