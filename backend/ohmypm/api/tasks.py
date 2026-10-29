"""/api/tasks — tasks, dependencies, events, checkpoints, sessions, context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from ohmypm.api.deps import CtxDep, IdempotencyKey, IfMatch, MemberCtx, PageDep, expected_version, set_etag
from ohmypm.schemas import (
    CheckpointCreate,
    CheckpointOut,
    ContextOut,
    DependencyChange,
    Page,
    SessionCreate,
    SessionOut,
    TaskComplete,
    TaskCreate,
    TaskDetail,
    TaskEventOut,
    TaskOut,
    TaskUpdate,
)
from ohmypm.services import memory
from ohmypm.services import tasks as svc
from ohmypm.services.context import build_context
from ohmypm.services.idempotency import run_idempotent
from ohmypm_common.enums import ContextMode, TaskPriority, TaskStatus

router = APIRouter(tags=["tasks"])


@router.post("/tasks", status_code=201, response_model=TaskOut)
async def create_task(
    data: TaskCreate, ctx: MemberCtx, response: Response, idempotency_key: IdempotencyKey = None
) -> object:
    async def op() -> object:
        return TaskOut.model_validate(await svc.create_task(ctx, data)).model_dump(mode="json")

    body, status, _ = await run_idempotent(
        ctx, key=idempotency_key, operation="create_task", body=data.model_dump(mode="json"), fn=op
    )
    response.status_code = status
    return body


@router.get("/tasks", response_model=Page[TaskOut])
async def list_tasks(
    ctx: CtxDep,
    page: PageDep,
    project_id: uuid.UUID | None = None,
    anonymous: bool = Query(False, description="Only tasks without a project"),
    workspace_id: uuid.UUID | None = None,
    status: Annotated[list[TaskStatus] | None, Query()] = None,
    priority: TaskPriority | None = None,
    parent_task_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    ready: bool = Query(False, description="Only todo tasks whose dependencies are all completed"),
) -> Page[TaskOut]:
    rows, total = await svc.list_tasks(
        ctx,
        project_id=project_id,
        anonymous=anonymous,
        workspace_id=workspace_id,
        statuses=status,
        priority=priority,
        parent_task_id=parent_task_id,
        tag=tag,
        q=q,
        ready=ready,
        sort=page.sort,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(items=[TaskOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/tasks/{task_ref}", response_model=TaskDetail)
async def get_task(task_ref: str, ctx: CtxDep, response: Response) -> TaskDetail:
    """``task_ref`` is a UUID or a task key such as ``T-42``."""
    task = await svc.get_task_by_ref(ctx, task_ref)
    set_etag(response, task.version)
    return await svc.task_detail(ctx, task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: uuid.UUID, data: TaskUpdate, ctx: MemberCtx, if_match: IfMatch = None) -> TaskOut:
    data.expected_version = expected_version(data.expected_version, if_match)
    return TaskOut.model_validate(await svc.update_task(ctx, task_id, data))


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
async def complete_task(task_id: uuid.UUID, data: TaskComplete, ctx: MemberCtx, if_match: IfMatch = None) -> TaskOut:
    data.expected_version = expected_version(data.expected_version, if_match)
    return TaskOut.model_validate(await svc.complete_task(ctx, task_id, data))


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(task_id: uuid.UUID, ctx: MemberCtx, reason: str = "") -> TaskOut:
    return TaskOut.model_validate(
        await svc.update_task(ctx, task_id, TaskUpdate(status=TaskStatus.CANCELLED, note=reason or None))
    )


@router.post("/tasks/{task_id}/dependencies", status_code=204)
async def add_dependency(task_id: uuid.UUID, data: DependencyChange, ctx: MemberCtx) -> None:
    await svc.add_dependency(ctx, task_id, data.depends_on_id)


@router.delete("/tasks/{task_id}/dependencies/{depends_on_id}", status_code=204)
async def remove_dependency(task_id: uuid.UUID, depends_on_id: uuid.UUID, ctx: MemberCtx) -> None:
    await svc.remove_dependency(ctx, task_id, depends_on_id)


@router.get("/tasks/{task_id}/events", response_model=list[TaskEventOut])
async def task_events(
    task_id: uuid.UUID, ctx: CtxDep, after_id: int = 0, limit: Annotated[int, Query(ge=1, le=1000)] = 200
) -> list[TaskEventOut]:
    return [
        TaskEventOut.model_validate(e) for e in await svc.list_task_events(ctx, task_id, after_id=after_id, limit=limit)
    ]


@router.get("/tasks/{task_id}/context", response_model=ContextOut)
async def task_context(
    task_id: uuid.UUID,
    ctx: CtxDep,
    mode: ContextMode = ContextMode.BRIEF,
    max_tokens: Annotated[int | None, Query(ge=200, le=50_000)] = None,
    checkpoint_id: uuid.UUID | None = None,
) -> ContextOut:
    return await build_context(ctx, task_id, mode=mode, max_tokens=max_tokens, checkpoint_id=checkpoint_id)


@router.post("/tasks/{task_id}/checkpoints", status_code=201, response_model=CheckpointOut)
async def create_checkpoint(
    task_id: uuid.UUID,
    data: CheckpointCreate,
    ctx: MemberCtx,
    response: Response,
    idempotency_key: IdempotencyKey = None,
) -> object:
    async def op() -> object:
        return CheckpointOut.model_validate(await memory.create_checkpoint(ctx, task_id, data)).model_dump(mode="json")

    body, status, _ = await run_idempotent(
        ctx, key=idempotency_key, operation=f"checkpoint:{task_id}", body=data.model_dump(mode="json"), fn=op
    )
    response.status_code = status
    return body


@router.get("/tasks/{task_id}/checkpoints", response_model=Page[CheckpointOut])
async def list_checkpoints(task_id: uuid.UUID, ctx: CtxDep, page: PageDep) -> Page[CheckpointOut]:
    rows, total = await memory.list_checkpoints(ctx, task_id, limit=page.limit, offset=page.offset)
    return Page(
        items=[CheckpointOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.get("/checkpoints/{checkpoint_id}", response_model=CheckpointOut, tags=["memory"])
async def get_checkpoint(checkpoint_id: uuid.UUID, ctx: CtxDep) -> CheckpointOut:
    return CheckpointOut.model_validate(await memory.get_checkpoint(ctx, checkpoint_id))


@router.get("/tasks/{task_id}/sessions", response_model=list[SessionOut])
async def list_sessions(task_id: uuid.UUID, ctx: CtxDep) -> list[SessionOut]:
    return [SessionOut.model_validate(s) for s in await memory.list_sessions(ctx, task_id)]


@router.post("/sessions", status_code=201, response_model=SessionOut, tags=["memory"])
async def create_session(data: SessionCreate, ctx: MemberCtx) -> SessionOut:
    return SessionOut.model_validate(await memory.create_session(ctx, data))


@router.post("/sessions/{session_id}/close", response_model=SessionOut, tags=["memory"])
async def close_session(session_id: uuid.UUID, ctx: MemberCtx) -> SessionOut:
    return SessionOut.model_validate(await memory.close_session(ctx, session_id))
