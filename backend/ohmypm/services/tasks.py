"""Tasks: CRUD, status machine, dependencies, ready queue, history."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, delete, exists, func, or_, select, text
from sqlalchemy.orm import aliased

from ohmypm.errors import Conflict, Forbidden, InvalidTransition, NotFound, ValidationFailed
from ohmypm.models import AgentRun, Project, Task, TaskDependency, TaskEvent, Workspace
from ohmypm.schemas import TaskComplete, TaskCreate, TaskDetail, TaskUpdate
from ohmypm.services.common import (
    Ctx,
    check_version,
    get_or_404,
    jsonable,
    like_pattern,
    paginate,
    record_task_event,
    utcnow,
)
from ohmypm_common.enums import ACTIVE_RUN_STATUSES, PRIORITY_RANK, RunStatus, TaskPriority, TaskStatus

TS = TaskStatus
# Completion goes through complete_task() (acceptance required), never a plain update.
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TS.TODO: frozenset({TS.IN_PROGRESS, TS.BLOCKED, TS.AWAITING_USER, TS.CANCELLED}),
    TS.IN_PROGRESS: frozenset({TS.TODO, TS.BLOCKED, TS.AWAITING_USER, TS.CANCELLED}),
    TS.BLOCKED: frozenset({TS.TODO, TS.IN_PROGRESS, TS.AWAITING_USER, TS.CANCELLED}),
    TS.AWAITING_USER: frozenset({TS.TODO, TS.IN_PROGRESS, TS.BLOCKED, TS.CANCELLED}),
    # Reopen.
    TS.COMPLETED: frozenset({TS.TODO, TS.IN_PROGRESS}),
    TS.CANCELLED: frozenset({TS.TODO}),
}
COMPLETABLE_FROM = frozenset({TS.TODO, TS.IN_PROGRESS, TS.BLOCKED, TS.AWAITING_USER})

TRACKED_FIELDS = (
    "title",
    "description",
    "priority",
    "project_id",
    "workspace_id",
    "acceptance_criteria",
    "completed_items",
    "remaining_items",
    "next_action",
    "blockers",
    "tags",
)


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return current == target or target in ALLOWED_TRANSITIONS[current]


def _derive_title(raw: str) -> str:
    first = next((line.strip() for line in raw.splitlines() if line.strip()), raw.strip())
    return first if len(first) <= 120 else first[:117] + "…"


def ensure_can_write_task(ctx: Ctx, task: Task) -> None:
    """Run-scoped agents may only modify their own task, its subtasks, or tasks they created."""
    p = ctx.principal
    if p.run_id is None:
        return
    if task.id == p.task_id or task.parent_task_id == p.task_id or task.created_by == p.actor:
        return
    raise Forbidden(f"agent run {p.run_id} may not modify task T-{task.number}")


async def get_task(ctx: Ctx, task_id: uuid.UUID) -> Task:
    return await get_or_404(ctx.session, Task, task_id, "task")


async def get_task_by_ref(ctx: Ctx, ref: str) -> Task:
    """Accept a UUID, ``T-42`` or ``42``."""
    value = ref.strip()
    number: int | None = None
    if value.upper().startswith("T-"):
        value = value[2:]
    if value.isdigit():
        number = int(value)
    if number is not None:
        task = (await ctx.session.execute(select(Task).where(Task.number == number))).scalar_one_or_none()
        if task is None:
            raise NotFound(f"task T-{number} not found")
        return task
    try:
        return await get_task(ctx, uuid.UUID(value))
    except ValueError as exc:
        raise ValidationFailed(f"invalid task reference {ref!r}") from exc


async def _validate_links(ctx: Ctx, project_id: uuid.UUID | None, workspace_id: uuid.UUID | None) -> Workspace | None:
    if project_id is not None:
        await get_or_404(ctx.session, Project, project_id, "project")
    workspace = None
    if workspace_id is not None:
        workspace = await get_or_404(ctx.session, Workspace, workspace_id, "workspace")
    return workspace


async def create_task(ctx: Ctx, data: TaskCreate) -> Task:
    workspace = await _validate_links(ctx, data.project_id, data.workspace_id)
    project_id = data.project_id
    if project_id is None and workspace is not None:
        project_id = workspace.project_id
    if data.status in (TS.COMPLETED, TS.CANCELLED):
        raise ValidationFailed("new tasks cannot start completed or cancelled")
    if data.parent_task_id is not None:
        await get_task(ctx, data.parent_task_id)
    task = Task(
        project_id=project_id,
        workspace_id=data.workspace_id,
        parent_task_id=data.parent_task_id,
        title=data.title or _derive_title(data.raw_request),
        raw_request=data.raw_request,
        description=data.description,
        status=data.status.value,
        priority=data.priority.value,
        acceptance_criteria=list(data.acceptance_criteria),
        tags=list(data.tags),
        created_by=ctx.actor,
        metadata_=data.metadata,
    )
    ctx.session.add(task)
    await ctx.session.flush()
    for dep in dict.fromkeys(data.depends_on):
        await get_task(ctx, dep)
        ctx.session.add(TaskDependency(task_id=task.id, depends_on_id=dep))
    await record_task_event(
        ctx,
        task.id,
        "task.created",
        jsonable(
            {"title": task.title, "status": task.status, "priority": task.priority, "depends_on": list(data.depends_on)}
        ),
    )
    await ctx.session.flush()
    await ctx.session.refresh(task)
    return task


def _search_condition(q: str) -> Any:
    tsq = func.websearch_to_tsquery("simple", q)
    pattern = like_pattern(q)
    return or_(
        Task.search_vector.op("@@")(tsq),
        Task.title.ilike(pattern),
        Task.raw_request.ilike(pattern),
        Task.description.ilike(pattern),
    )


def _unmet_dependency_exists() -> Any:
    dep_task = aliased(Task)
    return exists().where(
        TaskDependency.task_id == Task.id,
        TaskDependency.depends_on_id == dep_task.id,
        dep_task.status != TS.COMPLETED.value,
    )


async def list_tasks(
    ctx: Ctx,
    *,
    project_id: uuid.UUID | None = None,
    anonymous: bool = False,
    workspace_id: uuid.UUID | None = None,
    statuses: Sequence[TaskStatus] | None = None,
    priority: TaskPriority | None = None,
    parent_task_id: uuid.UUID | None = None,
    tag: str | None = None,
    q: str | None = None,
    ready: bool = False,
    sort: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Task], int]:
    stmt = select(Task)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    if anonymous:
        stmt = stmt.where(Task.project_id.is_(None))
    if workspace_id is not None:
        stmt = stmt.where(Task.workspace_id == workspace_id)
    if statuses:
        stmt = stmt.where(Task.status.in_([s.value for s in statuses]))
    if priority is not None:
        stmt = stmt.where(Task.priority == priority.value)
    if parent_task_id is not None:
        stmt = stmt.where(Task.parent_task_id == parent_task_id)
    if tag:
        stmt = stmt.where(Task.tags.any(tag))  # type: ignore[arg-type]
    if q:
        stmt = stmt.where(_search_condition(q))
    if ready:
        stmt = stmt.where(Task.status == TS.TODO.value, ~_unmet_dependency_exists())
    key = (sort or ("priority" if ready else "-updated_at")).lstrip("+")
    descending = key.startswith("-")
    name = key.lstrip("-")
    if name == "priority":
        rank = func.array_position(text("ARRAY['urgent','high','normal','low']::text[]"), Task.priority)
        stmt = stmt.order_by(rank.desc() if descending else rank.asc(), Task.created_at.asc())
    elif name in {"created_at", "updated_at", "number", "title", "status"}:
        column = getattr(Task, name)
        stmt = stmt.order_by(column.desc() if descending else column.asc(), Task.id)
    else:
        stmt = stmt.order_by(Task.updated_at.desc(), Task.id)
    return await paginate(ctx.session, stmt, limit, offset)


async def task_detail(ctx: Ctx, task: Task) -> TaskDetail:
    deps = (
        await ctx.session.execute(
            select(TaskDependency.depends_on_id, Task.status)
            .join(Task, Task.id == TaskDependency.depends_on_id)
            .where(TaskDependency.task_id == task.id)
        )
    ).all()
    dependents = (
        (await ctx.session.execute(select(TaskDependency.task_id).where(TaskDependency.depends_on_id == task.id)))
        .scalars()
        .all()
    )
    detail = TaskDetail.model_validate(task)
    detail.depends_on = [d for d, _ in deps]
    detail.unmet_dependencies = [d for d, st in deps if st != TS.COMPLETED.value]
    detail.dependents = list(dependents)
    return detail


async def unmet_dependencies(ctx: Ctx, task_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await ctx.session.execute(
        select(TaskDependency.depends_on_id)
        .join(Task, Task.id == TaskDependency.depends_on_id)
        .where(TaskDependency.task_id == task_id, Task.status != TS.COMPLETED.value)
    )
    return list(rows.scalars().all())


async def _set_status(ctx: Ctx, task: Task, target: TaskStatus, note: str | None = None) -> None:
    current = TaskStatus(task.status)
    if current == target:
        return
    if not can_transition(current, target):
        raise InvalidTransition(
            f"cannot move task from {current} to {target}", details={"from": current.value, "to": target.value}
        )
    task.status = target.value
    if current == TS.COMPLETED:
        task.completed_at = None
    await record_task_event(
        ctx, task.id, "task.status_changed", {"from": current.value, "to": target.value, "note": note}
    )
    if target == TS.CANCELLED:
        await _cancel_task_runs(ctx, task)


async def _cancel_task_runs(ctx: Ctx, task: Task) -> None:
    from ohmypm.services import runs  # local import: runs depends on tasks

    stmt = select(AgentRun).where(
        AgentRun.task_id == task.id,
        AgentRun.status.in_([RunStatus.QUEUED.value, *[s.value for s in ACTIVE_RUN_STATUSES]]),
    )
    for run in (await ctx.session.execute(stmt)).scalars():
        await runs.request_cancel(ctx, run, reason="task cancelled")


async def set_task_status(ctx: Ctx, task: Task, target: TaskStatus, note: str | None = None) -> None:
    """Internal status change used by other services (decisions, runs)."""
    await _set_status(ctx, task, target, note)


async def update_task(ctx: Ctx, task_id: uuid.UUID, data: TaskUpdate) -> Task:
    task = await get_task(ctx, task_id)
    ensure_can_write_task(ctx, task)
    check_version(task, data.expected_version)
    fields = data.model_fields_set
    if "project_id" in fields or "workspace_id" in fields:
        await _validate_links(
            ctx,
            data.project_id if "project_id" in fields else None,
            data.workspace_id if "workspace_id" in fields else None,
        )
    changes: dict[str, Any] = {}
    for name in TRACKED_FIELDS:
        if name not in fields:
            continue
        new = getattr(data, name)
        if new is None and name not in ("project_id", "workspace_id"):
            continue
        if isinstance(new, TaskPriority):
            new = new.value
        if isinstance(new, list):
            new = list(new)
        old = getattr(task, name)
        if old != new:
            changes[name] = {"old": jsonable(old), "new": jsonable(new)}
            setattr(task, name, new)
    if data.metadata is not None:
        task.metadata_ = {**task.metadata_, **data.metadata}
        changes["metadata"] = {"merged": jsonable(data.metadata)}
    if changes:
        await record_task_event(ctx, task.id, "task.updated", {"changes": changes, "note": data.note})
    if data.status is not None:
        if data.status == TS.COMPLETED:
            raise ValidationFailed(
                "use the complete endpoint (pm_complete_task) to complete a task", code="use_complete"
            )
        await _set_status(ctx, task, data.status, data.note)
    await ctx.session.flush()
    await ctx.session.refresh(task)
    return task


async def complete_task(ctx: Ctx, task_id: uuid.UUID, data: TaskComplete) -> Task:
    """Completion requires an acceptance record; with criteria, every one must pass."""
    task = await get_task(ctx, task_id)
    ensure_can_write_task(ctx, task)
    check_version(task, data.expected_version)
    current = TaskStatus(task.status)
    if current not in COMPLETABLE_FROM:
        raise InvalidTransition(f"cannot complete a task in status {current}")
    results = {r.criterion.strip(): r for r in data.results}
    missing = [c for c in task.acceptance_criteria if c.strip() not in results]
    failed = [c for c in task.acceptance_criteria if c.strip() in results and not results[c.strip()].passed]
    if (missing or failed) and not data.force:
        raise ValidationFailed(
            "acceptance criteria not satisfied",
            code="acceptance_not_met",
            details={"missing": missing, "failed": failed},
        )
    if data.force and not ctx.principal.is_admin:
        raise Forbidden("only an admin can force completion")
    open_deps = await unmet_dependencies(ctx, task.id)
    if open_deps and not data.force:
        raise Conflict(
            "task has unfinished dependencies",
            code="dependencies_unmet",
            details={"unmet": [str(d) for d in open_deps]},
        )
    task.acceptance_result = jsonable(
        {
            "summary": data.summary,
            "results": [r.model_dump() for r in data.results],
            "verification_command": data.verification_command,
            "forced": data.force,
            "missing": missing,
            "failed": failed,
            "verified_by": ctx.actor,
            "verified_at": utcnow(),
        }
    )
    task.status = TS.COMPLETED.value
    task.completed_at = utcnow()
    task.remaining_items = []
    task.blockers = []
    task.next_action = ""
    await record_task_event(
        ctx,
        task.id,
        "task.completed",
        {"from": current.value, "summary": data.summary, "forced": data.force},
    )
    await ctx.session.flush()
    await ctx.session.refresh(task)
    return task


async def _reaches(ctx: Ctx, start: uuid.UUID, target: uuid.UUID) -> bool:
    """True if ``start`` (transitively) depends on ``target``."""
    query = text(
        """
        WITH RECURSIVE chain(id) AS (
            SELECT depends_on_id FROM task_dependencies WHERE task_id = :start
            UNION
            SELECT d.depends_on_id FROM task_dependencies d JOIN chain c ON d.task_id = c.id
        )
        SELECT EXISTS (SELECT 1 FROM chain WHERE id = :target)
        """
    )
    return bool((await ctx.session.execute(query, {"start": start, "target": target})).scalar())


async def add_dependency(ctx: Ctx, task_id: uuid.UUID, depends_on_id: uuid.UUID) -> None:
    task = await get_task(ctx, task_id)
    ensure_can_write_task(ctx, task)
    await get_task(ctx, depends_on_id)
    if task_id == depends_on_id:
        raise ValidationFailed("a task cannot depend on itself")
    # Serialize dependency edits to keep cycle detection sound under concurrency.
    await ctx.session.execute(text("SELECT pg_advisory_xact_lock(hashtext('ohmypm.task_dependencies'))"))
    if await _reaches(ctx, depends_on_id, task_id):
        raise Conflict("dependency would create a cycle", code="dependency_cycle")
    existing = await ctx.session.get(TaskDependency, (task_id, depends_on_id))
    if existing is not None:
        return
    ctx.session.add(TaskDependency(task_id=task_id, depends_on_id=depends_on_id))
    await record_task_event(ctx, task_id, "task.dependency_added", {"depends_on": str(depends_on_id)})
    await ctx.session.flush()


async def remove_dependency(ctx: Ctx, task_id: uuid.UUID, depends_on_id: uuid.UUID) -> None:
    task = await get_task(ctx, task_id)
    ensure_can_write_task(ctx, task)
    result = await ctx.session.execute(
        delete(TaskDependency).where(
            and_(TaskDependency.task_id == task_id, TaskDependency.depends_on_id == depends_on_id)
        )
    )
    if result.rowcount:  # type: ignore[attr-defined]
        await record_task_event(ctx, task_id, "task.dependency_removed", {"depends_on": str(depends_on_id)})


async def list_task_events(ctx: Ctx, task_id: uuid.UUID, *, after_id: int = 0, limit: int = 200) -> Sequence[TaskEvent]:
    await get_task(ctx, task_id)
    stmt = (
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id, TaskEvent.id > after_id)
        .order_by(TaskEvent.id)
        .limit(max(1, min(limit, 1000)))
    )
    return (await ctx.session.execute(stmt)).scalars().all()


def priority_rank(priority: str) -> int:
    return PRIORITY_RANK.get(TaskPriority(priority), 9)
