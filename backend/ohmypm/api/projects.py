"""/api/projects and /api/workspaces."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from ohmypm.api.deps import AdminCtx, CtxDep, IdempotencyKey, IfMatch, MemberCtx, PageDep, expected_version, set_etag
from ohmypm.schemas import (
    Page,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectUpdate,
    WorkspaceOut,
    WorkspaceResolve,
    WorkspaceUpdate,
)
from ohmypm.services import projects as svc
from ohmypm.services.idempotency import run_idempotent

router = APIRouter(tags=["projects"])


@router.post("/projects", status_code=201, response_model=ProjectOut)
async def create_project(
    data: ProjectCreate, ctx: AdminCtx, response: Response, idempotency_key: IdempotencyKey = None
) -> object:
    async def op() -> object:
        return ProjectOut.model_validate(await svc.create_project(ctx, data)).model_dump(mode="json")

    body, status, _ = await run_idempotent(
        ctx, key=idempotency_key, operation="create_project", body=data.model_dump(mode="json"), fn=op
    )
    response.status_code = status
    return body


@router.get("/projects", response_model=Page[ProjectOut])
async def list_projects(
    ctx: CtxDep,
    page: PageDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    include_archived: bool = False,
) -> Page[ProjectOut]:
    rows, total = await svc.list_projects(
        ctx, q=q, include_archived=include_archived, sort=page.sort, limit=page.limit, offset=page.offset
    )
    return Page(items=[ProjectOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: uuid.UUID, ctx: CtxDep, response: Response) -> ProjectDetail:
    project = await svc.get_project(ctx, project_id)
    workspaces, _ = await svc.list_workspaces(ctx, project_id=project_id, limit=100)
    stats = await svc.project_stats(ctx, project_id)
    set_etag(response, project.version)
    return ProjectDetail.model_validate(
        {
            **ProjectOut.model_validate(project).model_dump(),
            "stats": stats,
            "workspaces": [WorkspaceOut.model_validate(w) for w in workspaces],
        }
    )


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, data: ProjectUpdate, ctx: AdminCtx, if_match: IfMatch = None
) -> ProjectOut:
    data.expected_version = expected_version(data.expected_version, if_match)
    return ProjectOut.model_validate(await svc.update_project(ctx, project_id, data))


@router.post("/workspaces/resolve", response_model=WorkspaceOut)
async def resolve_workspace(data: WorkspaceResolve, ctx: MemberCtx) -> WorkspaceOut:
    """Find-or-create the workspace for (host_id, root_path). Idempotent."""
    return WorkspaceOut.model_validate(await svc.resolve_workspace(ctx, data))


@router.get("/workspaces", response_model=Page[WorkspaceOut])
async def list_workspaces(
    ctx: CtxDep,
    page: PageDep,
    project_id: uuid.UUID | None = None,
    anonymous: bool | None = None,
    host_id: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[WorkspaceOut]:
    rows, total = await svc.list_workspaces(
        ctx, project_id=project_id, anonymous=anonymous, host_id=host_id, q=q, limit=page.limit, offset=page.offset
    )
    return Page(items=[WorkspaceOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(workspace_id: uuid.UUID, ctx: CtxDep) -> WorkspaceOut:
    return WorkspaceOut.model_validate(await svc.get_workspace(ctx, workspace_id))


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(workspace_id: uuid.UUID, data: WorkspaceUpdate, ctx: AdminCtx) -> WorkspaceOut:
    return WorkspaceOut.model_validate(await svc.update_workspace(ctx, workspace_id, data))
