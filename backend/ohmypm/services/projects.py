"""Projects and workspaces."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import PurePosixPath

from sqlalchemy import func, or_, select

from ohmypm.errors import Conflict, NotFound
from ohmypm.models import AgentRun, Artifact, Decision, Project, Task, Workspace
from ohmypm.schemas import ProjectCreate, ProjectStats, ProjectUpdate, WorkspaceResolve, WorkspaceUpdate
from ohmypm.services.auth import require_role
from ohmypm.services.common import Ctx, apply_sort, check_version, get_or_404, like_pattern, paginate, utcnow
from ohmypm_common.enums import ACTIVE_RUN_STATUSES, DecisionStatus, Role


async def create_project(ctx: Ctx, data: ProjectCreate) -> Project:
    if data.id is not None:
        existing = await ctx.session.get(Project, data.id)
        if existing is not None:
            raise Conflict(f"project {data.id} already exists", code="project_exists", details={"id": str(data.id)})
    project = Project(
        id=data.id or uuid.uuid4(),
        name=data.name,
        description=data.description,
        created_by=ctx.actor,
        metadata_=data.metadata,
    )
    ctx.session.add(project)
    await ctx.session.flush()
    return project


async def get_project(ctx: Ctx, project_id: uuid.UUID) -> Project:
    return await get_or_404(ctx.session, Project, project_id, "project")


async def list_projects(
    ctx: Ctx,
    *,
    q: str | None = None,
    include_archived: bool = False,
    sort: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Project], int]:
    stmt = select(Project)
    if not include_archived:
        stmt = stmt.where(Project.archived.is_(False))
    if q:
        stmt = stmt.where(
            or_(
                Project.name.ilike(like_pattern(q)),
                Project.search_vector.op("@@")(func.plainto_tsquery("simple", q)),
            )
        )
    stmt = apply_sort(stmt, Project, sort, ["name", "created_at", "updated_at"], "-updated_at")
    return await paginate(ctx.session, stmt, limit, offset)


async def update_project(ctx: Ctx, project_id: uuid.UUID, data: ProjectUpdate) -> Project:
    require_role(ctx.principal, Role.ADMIN)
    project = await get_project(ctx, project_id)
    check_version(project, data.expected_version)
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    if data.archived is not None:
        project.archived = data.archived
    if data.metadata is not None:
        project.metadata_ = {**project.metadata_, **data.metadata}
    await ctx.session.flush()
    return project


async def project_stats(ctx: Ctx, project_id: uuid.UUID) -> ProjectStats:
    s = ctx.session
    by_status = dict(
        (
            await s.execute(
                select(Task.status, func.count()).where(Task.project_id == project_id).group_by(Task.status)
            )
        ).all()
    )
    active_runs = (
        await s.execute(
            select(func.count())
            .select_from(AgentRun)
            .join(Task, Task.id == AgentRun.task_id)
            .where(Task.project_id == project_id, AgentRun.status.in_([st.value for st in ACTIVE_RUN_STATUSES]))
        )
    ).scalar_one()
    artifacts = (
        await s.execute(select(func.count()).select_from(Artifact).where(Artifact.project_id == project_id))
    ).scalar_one()
    pending = (
        await s.execute(
            select(func.count())
            .select_from(Decision)
            .outerjoin(Task, Task.id == Decision.task_id)
            .where(
                Decision.status == DecisionStatus.PENDING.value,
                or_(Decision.project_id == project_id, Task.project_id == project_id),
            )
        )
    ).scalar_one()
    return ProjectStats(
        tasks_total=sum(by_status.values()),
        tasks_by_status={str(k): int(v) for k, v in by_status.items()},
        active_runs=int(active_runs),
        artifacts=int(artifacts),
        pending_decisions=int(pending),
    )


# ---------------------------------------------------------------- workspaces


def _display_name(root_path: str) -> str:
    return PurePosixPath(root_path).name or root_path


async def resolve_workspace(ctx: Ctx, data: WorkspaceResolve) -> Workspace:
    """Find-or-create the workspace for (host_id, root_path) and refresh ``last_seen_at``.

    The PROJECT_ID found in the directory is authoritative: if it differs from the stored
    link, the link is updated (an anonymous workspace becomes part of a project this way).
    """
    if data.project_id is not None and await ctx.session.get(Project, data.project_id) is None:
        raise NotFound(f"project {data.project_id} is not registered", code="project_not_registered")
    stmt = select(Workspace).where(Workspace.host_id == data.host_id, Workspace.root_path == data.root_path)
    workspace = (await ctx.session.execute(stmt.with_for_update())).scalar_one_or_none()
    if workspace is None:
        workspace = Workspace(
            host_id=data.host_id,
            root_path=data.root_path,
            project_id=data.project_id,
            display_name=data.display_name or _display_name(data.root_path),
            metadata_=data.metadata,
        )
        ctx.session.add(workspace)
    else:
        workspace.last_seen_at = utcnow()
        if data.project_id is not None and workspace.project_id != data.project_id:
            history = list(workspace.metadata_.get("project_history", []))
            history.append(
                {
                    "from": str(workspace.project_id) if workspace.project_id else None,
                    "to": str(data.project_id),
                    "at": utcnow().isoformat(),
                }
            )
            workspace.metadata_ = {**workspace.metadata_, "project_history": history[-20:]}
            workspace.project_id = data.project_id
        if data.display_name:
            workspace.display_name = data.display_name
    await ctx.session.flush()
    return workspace


async def get_workspace(ctx: Ctx, workspace_id: uuid.UUID) -> Workspace:
    return await get_or_404(ctx.session, Workspace, workspace_id, "workspace")


async def list_workspaces(
    ctx: Ctx,
    *,
    project_id: uuid.UUID | None = None,
    anonymous: bool | None = None,
    host_id: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[Sequence[Workspace], int]:
    stmt = select(Workspace)
    if project_id is not None:
        stmt = stmt.where(Workspace.project_id == project_id)
    if anonymous is True:
        stmt = stmt.where(Workspace.project_id.is_(None))
    elif anonymous is False:
        stmt = stmt.where(Workspace.project_id.is_not(None))
    if host_id:
        stmt = stmt.where(Workspace.host_id == host_id)
    if q:
        stmt = stmt.where(
            or_(Workspace.root_path.ilike(like_pattern(q)), Workspace.display_name.ilike(like_pattern(q)))
        )
    stmt = stmt.order_by(Workspace.last_seen_at.desc(), Workspace.id)
    return await paginate(ctx.session, stmt, limit, offset)


async def update_workspace(ctx: Ctx, workspace_id: uuid.UUID, data: WorkspaceUpdate) -> Workspace:
    require_role(ctx.principal, Role.ADMIN)
    workspace = await get_workspace(ctx, workspace_id)
    fields = data.model_fields_set
    if "project_id" in fields:
        if data.project_id is not None:
            await get_or_404(ctx.session, Project, data.project_id, "project")
        workspace.project_id = data.project_id
    if data.display_name:
        workspace.display_name = data.display_name
    if data.metadata is not None:
        workspace.metadata_ = {**workspace.metadata_, **data.metadata}
    await ctx.session.flush()
    return workspace
