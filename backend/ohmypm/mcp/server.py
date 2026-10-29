"""FastMCP server exposing ohmypm to agents. Shares the application services with the REST API.

Mounted at ``/mcp`` (streamable HTTP). Authentication uses the same bearer tokens as REST;
run-scoped agent tokens are minted by the backend when a runner claims a run.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, ParamSpec, TypeVar

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from pydantic import Field

from ohmypm.config import Settings
from ohmypm.db import Database
from ohmypm.errors import DomainError, Forbidden, Unauthorized
from ohmypm.schemas import (
    ArtifactCreate,
    ArtifactOut,
    CheckpointCreate,
    CheckpointOut,
    DecisionCreate,
    DecisionOut,
    DecisionResolve,
    KnowledgeCreate,
    KnowledgeOut,
    KnowledgeUpdate,
    ProjectOut,
    RunCreate,
    RunEventOut,
    RunOut,
    TaskComplete,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    WorkspaceOut,
    WorkspaceResolve,
)
from ohmypm.services import artifacts as artifact_svc
from ohmypm.services import decisions as decision_svc
from ohmypm.services import knowledge as knowledge_svc
from ohmypm.services import memory
from ohmypm.services import projects as project_svc
from ohmypm.services import runs as run_svc
from ohmypm.services import search as search_svc
from ohmypm.services import tasks as task_svc
from ohmypm.services.auth import Principal, authenticate
from ohmypm.services.common import Ctx
from ohmypm.services.context import build_context
from ohmypm.services.idempotency import run_idempotent
from ohmypm_common.enums import (
    ArtifactType,
    ContextMode,
    DecisionStatus,
    KnowledgeCategory,
    Role,
    RunStatus,
    TaskPriority,
    TaskStatus,
)

P = ParamSpec("P")
R = TypeVar("R")

INSTRUCTIONS = """ohmypm is the persistent project memory and task tracker for this workspace.
Start with pm_bootstrap (pass your working directory and, if present, the content of the PROJECT_ID file).
Use pm_get_context to resume a task, pm_checkpoint to save resumable progress (done / remaining / failed
attempts / verified facts vs hypotheses / next steps), pm_manage_decision to ask the user for high-impact
choices instead of guessing, pm_register_artifact for deliverables, and pm_complete_task only once every
acceptance criterion is verified with evidence."""


class OhmypmTokenVerifier(TokenVerifier):
    def __init__(self, db: Database, settings: Settings) -> None:
        super().__init__()
        self._db = db
        self._settings = settings

    async def verify_token(self, token: str) -> AccessToken | None:
        async with self._db.session() as session:
            principal = await authenticate(token, self._settings, session)
        if principal is None or principal.role is Role.RUNNER:
            return None
        return AccessToken(
            token=token,
            client_id=principal.actor,
            scopes=[principal.role.value],
            claims={
                "role": principal.role.value,
                "name": principal.name,
                "run_id": str(principal.run_id) if principal.run_id else None,
                "task_id": str(principal.task_id) if principal.task_id else None,
                "dispatch_depth": principal.dispatch_depth,
            },
        )


def _principal() -> Principal:
    token = get_access_token()
    if token is None or not token.claims:
        raise Unauthorized("not authenticated")
    c = token.claims
    return Principal(
        role=Role(c["role"]),
        name=str(c["name"]),
        run_id=uuid.UUID(c["run_id"]) if c.get("run_id") else None,
        task_id=uuid.UUID(c["task_id"]) if c.get("task_id") else None,
        dispatch_depth=int(c.get("dispatch_depth") or 0),
    )


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")  # type: ignore[no-any-return]


def build_mcp(db: Database, settings: Settings) -> FastMCP:
    mcp = FastMCP(
        name="ohmypm",
        instructions=INSTRUCTIONS,
        auth=OhmypmTokenVerifier(db, settings),
        mask_error_details=True,
    )

    def tool(fn: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]:
        """Register an async tool whose first parameter is the service context."""

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> R:
            try:
                async with db.session() as session:
                    ctx = Ctx(session=session, principal=_principal(), settings=settings)
                    return await fn(ctx, *args, **kwargs)
            except DomainError as exc:
                detail = f" details={exc.details}" if exc.details else ""
                raise ToolError(f"[{exc.code}] {exc.message}{detail}") from exc

        # Hide the injected ctx parameter from the tool schema.
        import inspect

        sig = inspect.signature(fn)
        wrapper.__signature__ = sig.replace(parameters=list(sig.parameters.values())[1:])  # type: ignore[attr-defined]
        wrapper.__annotations__ = {k: v for k, v in fn.__annotations__.items() if k != "ctx"}
        mcp.tool(wrapper)
        return wrapper

    # ------------------------------------------------------------ bootstrap / projects

    @tool
    async def pm_bootstrap(
        ctx: Ctx,
        cwd: Annotated[str | None, Field(description="Absolute working directory of the agent")] = None,
        project_id: Annotated[str | None, Field(description="Content of the PROJECT_ID file, if any")] = None,
        host_id: Annotated[str | None, Field(description="Host name (defaults to unknown)")] = None,
    ) -> dict[str, Any]:
        """Orient yourself: returns your identity, current run/task (if launched by ohmypm), the project and
        its open/ready tasks. Call this first."""
        p = ctx.principal
        result: dict[str, Any] = {"identity": {"role": p.role.value, "actor": p.actor}}
        project = None
        if p.task_id is not None:
            task = await task_svc.get_task(ctx, p.task_id)
            result["run_id"] = str(p.run_id)
            result["task"] = _dump(TaskOut.model_validate(task))
            result["context"] = (await build_context(ctx, task.id, mode=ContextMode.BRIEF)).markdown
            if task.project_id:
                project = await project_svc.get_project(ctx, task.project_id)
        if project is None and project_id:
            project = await project_svc.get_project(ctx, uuid.UUID(project_id.strip()))
        if cwd and host_id:
            workspace = await project_svc.resolve_workspace(
                ctx, WorkspaceResolve(host_id=host_id, root_path=cwd, project_id=project.id if project else None)
            )
            result["workspace"] = _dump(WorkspaceOut.model_validate(workspace))
        if project is not None:
            result["project"] = _dump(ProjectOut.model_validate(project))
            open_tasks, _ = await task_svc.list_tasks(
                ctx,
                project_id=project.id,
                statuses=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.AWAITING_USER],
                limit=30,
            )
            ready, _ = await task_svc.list_tasks(ctx, project_id=project.id, ready=True, limit=10)
            result["open_tasks"] = [_brief_task(t) for t in open_tasks]
            result["ready_tasks"] = [_brief_task(t) for t in ready]
        result["hint"] = INSTRUCTIONS
        return result

    @tool
    async def pm_list_projects(ctx: Ctx, query: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List projects (optionally filtered by name/description text)."""
        rows, _ = await project_svc.list_projects(ctx, q=query, limit=limit)
        return [_dump(ProjectOut.model_validate(r)) for r in rows]

    @tool
    async def pm_get_project(ctx: Ctx, project_id: str) -> dict[str, Any]:
        """Project details with workspaces and task statistics."""
        pid = uuid.UUID(project_id)
        project = await project_svc.get_project(ctx, pid)
        workspaces, _ = await project_svc.list_workspaces(ctx, project_id=pid)
        stats = await project_svc.project_stats(ctx, pid)
        return {
            **_dump(ProjectOut.model_validate(project)),
            "stats": _dump(stats),
            "workspaces": [_dump(WorkspaceOut.model_validate(w)) for w in workspaces],
        }

    # ------------------------------------------------------------ tasks

    @tool
    async def pm_list_tasks(
        ctx: Ctx,
        project_id: str | None = None,
        status: list[TaskStatus] | None = None,
        query: str | None = None,
        ready_only: bool = False,
        anonymous_only: bool = False,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """List tasks. ready_only returns todo tasks whose dependencies are all completed."""
        rows, _ = await task_svc.list_tasks(
            ctx,
            project_id=uuid.UUID(project_id) if project_id else None,
            statuses=status,
            q=query,
            ready=ready_only,
            anonymous=anonymous_only,
            limit=limit,
        )
        return [_brief_task(t) for t in rows]

    @tool
    async def pm_get_task(
        ctx: Ctx, task: Annotated[str, Field(description="Task UUID or key like T-12")]
    ) -> dict[str, Any]:
        """Full task record including dependencies."""
        obj = await task_svc.get_task_by_ref(ctx, task)
        return _dump(await task_svc.task_detail(ctx, obj))

    @tool
    async def pm_create_task(
        ctx: Ctx,
        raw_request: Annotated[str, Field(description="The request, verbatim as the user phrased it")],
        title: str | None = None,
        description: str = "",
        acceptance_criteria: list[str] | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        project_id: str | None = None,
        workspace_id: str | None = None,
        parent_task_id: str | None = None,
        depends_on: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a task. Keep raw_request verbatim; put your structured interpretation in description."""
        data = TaskCreate(
            raw_request=raw_request,
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria or [],
            priority=priority,
            project_id=uuid.UUID(project_id) if project_id else None,
            workspace_id=uuid.UUID(workspace_id) if workspace_id else None,
            parent_task_id=uuid.UUID(parent_task_id) if parent_task_id else None,
            depends_on=[uuid.UUID(d) for d in depends_on or []],
        )

        async def op() -> object:
            return _dump(TaskOut.model_validate(await task_svc.create_task(ctx, data)))

        body, _, _ = await run_idempotent(
            ctx, key=idempotency_key, operation="create_task", body=data.model_dump(mode="json"), fn=op
        )
        return body  # type: ignore[no-any-return]

    @tool
    async def pm_update_task(
        ctx: Ctx,
        task_id: str,
        status: TaskStatus | None = None,
        description: str | None = None,
        title: str | None = None,
        acceptance_criteria: list[str] | None = None,
        completed_items: list[str] | None = None,
        remaining_items: list[str] | None = None,
        next_action: str | None = None,
        blockers: list[str] | None = None,
        priority: TaskPriority | None = None,
        note: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Update task fields/status (history is kept as task events). Use pm_complete_task to complete."""
        fields = {
            k: v
            for k, v in {
                "status": status,
                "description": description,
                "title": title,
                "acceptance_criteria": acceptance_criteria,
                "completed_items": completed_items,
                "remaining_items": remaining_items,
                "next_action": next_action,
                "blockers": blockers,
                "priority": priority,
                "note": note,
                "expected_version": expected_version,
            }.items()
            if v is not None
        }
        task = await task_svc.update_task(ctx, uuid.UUID(task_id), TaskUpdate(**fields))
        return _dump(TaskOut.model_validate(task))

    @tool
    async def pm_complete_task(
        ctx: Ctx,
        task_id: str,
        summary: Annotated[str, Field(description="What was delivered and how it was verified")],
        results: Annotated[
            list[dict[str, Any]] | None,
            Field(description="One entry per acceptance criterion: {criterion, passed, evidence}"),
        ] = None,
        verification_command: str | None = None,
    ) -> dict[str, Any]:
        """Complete a task. Every acceptance criterion needs a passing result with evidence."""
        data = TaskComplete.model_validate(
            {"summary": summary, "results": results or [], "verification_command": verification_command}
        )
        return _dump(TaskOut.model_validate(await task_svc.complete_task(ctx, uuid.UUID(task_id), data)))

    # ------------------------------------------------------------ memory

    @tool
    async def pm_checkpoint(
        ctx: Ctx,
        task_id: str,
        summary: Annotated[str, Field(description="Concise state of the work; not a log")],
        completed: list[str] | None = None,
        remaining: list[str] | None = None,
        current_issue: Annotated[dict[str, str] | None, Field(description="{description, error, root_cause}")] = None,
        attempts: Annotated[
            list[dict[str, str]] | None,
            Field(description="Important attempts: [{action, result, conclusion}] — include failures"),
        ] = None,
        findings: Annotated[
            list[dict[str, str]] | None,
            Field(description="[{statement, kind: verified|inferred|hypothesis, evidence}]"),
        ] = None,
        relevant_files: list[str] | None = None,
        next_steps: list[str] | None = None,
        verification: Annotated[list[dict[str, Any]] | None, Field(description="[{command, result, passed}]")] = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Save an append-only, resumable checkpoint and update the task's current state."""
        payload: dict[str, Any] = {
            "summary": summary,
            "completed": completed or [],
            "current_issue": current_issue,
            "attempts": attempts or [],
            "findings": findings or [],
            "relevant_files": relevant_files or [],
            "next_steps": next_steps or [],
            "verification": verification or [],
        }
        if remaining is not None:
            # Only an explicit list replaces the task's remaining items.
            payload["remaining"] = remaining
        data = CheckpointCreate.model_validate(payload)
        tid = uuid.UUID(task_id)

        async def op() -> object:
            return _dump(CheckpointOut.model_validate(await memory.create_checkpoint(ctx, tid, data)))

        body, _, _ = await run_idempotent(
            ctx, key=idempotency_key, operation=f"checkpoint:{tid}", body=data.model_dump(mode="json"), fn=op
        )
        return body  # type: ignore[no-any-return]

    @tool
    async def pm_get_context(
        ctx: Ctx,
        task_id: str,
        mode: ContextMode = ContextMode.BRIEF,
        max_tokens: int = 3000,
    ) -> dict[str, Any]:
        """Structured resume context for a task (brief | standard | full), bounded by max_tokens."""
        out = await build_context(ctx, uuid.UUID(task_id), mode=mode, max_tokens=max_tokens)
        return _dump(out)

    @tool
    async def pm_manage_decision(
        ctx: Ctx,
        action: Literal["create", "list", "get", "resolve", "cancel"],
        task_id: str | None = None,
        decision_id: str | None = None,
        question: str | None = None,
        context: str = "",
        options: Annotated[
            list[dict[str, str]] | None, Field(description="[{key, label, description}] for action=create")
        ] = None,
        recommendation: str | None = None,
        reasoning: str | None = None,
        blocking: bool = True,
        status: DecisionStatus | None = None,
        selected_option: str | None = None,
        response: str | None = None,
    ) -> Any:
        """Create/list/get decisions that need the user. Agents create and read decisions; resolving is
        normally done by the user (agents may only resolve when they are admins)."""
        if action == "create":
            if not question:
                raise ToolError("question is required to create a decision")
            data = DecisionCreate.model_validate(
                {
                    "question": question,
                    "task_id": task_id,
                    "context": context,
                    "options": options or [],
                    "recommendation": recommendation,
                    "reasoning": reasoning,
                    "blocking": blocking,
                }
            )
            return _dump(DecisionOut.model_validate(await decision_svc.create_decision(ctx, data)))
        if action == "list":
            rows, _ = await decision_svc.list_decisions(
                ctx, status=status, task_id=uuid.UUID(task_id) if task_id else None, limit=50
            )
            return [_dump(DecisionOut.model_validate(d)) for d in rows]
        if not decision_id:
            raise ToolError("decision_id is required")
        did = uuid.UUID(decision_id)
        if action == "get":
            return _dump(DecisionOut.model_validate(await decision_svc.get_decision(ctx, did)))
        if not ctx.principal.is_admin:
            raise Forbidden("only the user (admin) can resolve or cancel decisions")
        if action == "resolve":
            decision, _ = await decision_svc.resolve_decision(
                ctx, did, DecisionResolve(selected_option=selected_option, response=response)
            )
            return _dump(DecisionOut.model_validate(decision))
        return _dump(DecisionOut.model_validate(await decision_svc.cancel_decision(ctx, did, response or "")))

    @tool
    async def pm_knowledge(
        ctx: Ctx,
        action: Literal["search", "add", "update", "supersede"],
        query: str | None = None,
        project_id: str | None = None,
        knowledge_id: str | None = None,
        title: str | None = None,
        content: str | None = None,
        category: KnowledgeCategory | None = None,
        verified: bool | None = None,
        tags: list[str] | None = None,
        source_task_id: str | None = None,
        superseded_by: str | None = None,
    ) -> Any:
        """Search or record long-lived project knowledge (architecture, environment, constraints, verified
        conclusions, known issues). Mark outdated entries with action=supersede."""
        if action == "search":
            rows, _ = await knowledge_svc.list_knowledge(
                ctx, project_id=uuid.UUID(project_id) if project_id else None, q=query, category=category, limit=20
            )
            return [_dump(KnowledgeOut.model_validate(k)) for k in rows]
        if action == "add":
            if not title or not content:
                raise ToolError("title and content are required")
            data = KnowledgeCreate.model_validate(
                {
                    "title": title,
                    "content": content,
                    "project_id": project_id,
                    "category": category or KnowledgeCategory.OTHER,
                    "verified": bool(verified),
                    "tags": tags or [],
                    "source_task_id": source_task_id,
                }
            )
            return _dump(KnowledgeOut.model_validate(await knowledge_svc.create_knowledge(ctx, data)))
        if not knowledge_id:
            raise ToolError("knowledge_id is required")
        kid = uuid.UUID(knowledge_id)
        if action == "supersede":
            if not superseded_by:
                raise ToolError("superseded_by is required")
            update = KnowledgeUpdate(superseded_by=uuid.UUID(superseded_by))
        else:
            fields = {
                k: v
                for k, v in {
                    "title": title,
                    "content": content,
                    "category": category,
                    "verified": verified,
                    "tags": tags,
                }.items()
                if v is not None
            }
            update = KnowledgeUpdate(**fields)
        return _dump(KnowledgeOut.model_validate(await knowledge_svc.update_knowledge(ctx, kid, update)))

    # ------------------------------------------------------------ artifacts / search

    @tool
    async def pm_register_artifact(
        ctx: Ctx,
        name: str,
        storage_uri: Annotated[str, Field(description="Path or URI of the artifact (reference mode)")],
        type: ArtifactType = ArtifactType.OTHER,
        task_id: str | None = None,
        description: str = "",
        usage: Annotated[
            dict[str, Any] | None, Field(description="{prerequisites[], command, expected_result, manual}")
        ] = None,
        build: Annotated[dict[str, Any] | None, Field(description="{command, source_path, notes}")] = None,
        verification: Annotated[
            dict[str, Any] | None, Field(description="{status: unknown|passed|failed, command, result}")
        ] = None,
        environment: dict[str, Any] | None = None,
        sha256: str | None = None,
        version_label: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Register a deliverable with how to build, use and verify it."""
        data = ArtifactCreate.model_validate(
            {
                "name": name,
                "storage_uri": storage_uri,
                "type": type,
                "task_id": task_id,
                "description": description,
                "usage": usage or {},
                "build": build or {},
                "verification": verification or {},
                "environment": environment or {},
                "sha256": sha256,
                "version_label": version_label,
            }
        )

        async def op() -> object:
            return _dump(ArtifactOut.model_validate(await artifact_svc.create_artifact(ctx, data)))

        body, _, _ = await run_idempotent(
            ctx, key=idempotency_key, operation="create_artifact", body=data.model_dump(mode="json"), fn=op
        )
        return body  # type: ignore[no-any-return]

    @tool
    async def pm_list_artifacts(
        ctx: Ctx,
        project_id: str | None = None,
        task_id: str | None = None,
        query: str | None = None,
        type: ArtifactType | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """List registered artifacts."""
        rows, _ = await artifact_svc.list_artifacts(
            ctx,
            project_id=uuid.UUID(project_id) if project_id else None,
            task_id=uuid.UUID(task_id) if task_id else None,
            q=query,
            type=type,
            limit=limit,
        )
        return [_dump(ArtifactOut.model_validate(a)) for a in rows]

    @tool
    async def pm_search(
        ctx: Ctx,
        query: str,
        kinds: Annotated[
            list[str] | None, Field(description="Subset of project, workspace, task, decision, artifact, knowledge")
        ] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Full-text search across projects, workspaces, tasks, decisions, artifacts and knowledge."""
        return [_dump(h) for h in await search_svc.search(ctx, query, kinds=kinds, limit=limit)]

    # ------------------------------------------------------------ runs

    @tool
    async def pm_list_runs(
        ctx: Ctx, task_id: str | None = None, active_only: bool = False, limit: int = 20
    ) -> list[dict[str, Any]]:
        """List agent runs (most recent first)."""
        rows, _ = await run_svc.list_runs(
            ctx, task_id=uuid.UUID(task_id) if task_id else None, active=True if active_only else None, limit=limit
        )
        return [_brief_run(r) for r in rows]

    @tool
    async def pm_get_run(ctx: Ctx, run_id: str, include_events: bool = False, after_seq: int = 0) -> dict[str, Any]:
        """Run details; optionally the normalized event log (after_seq for paging)."""
        run = await run_svc.get_run(ctx, uuid.UUID(run_id))
        out = _dump(RunOut.model_validate(run))
        if include_events:
            events = await run_svc.list_run_events(ctx, run.id, after_seq=after_seq, limit=200)
            out["events"] = [_dump(RunEventOut.model_validate(e)) for e in events]
        return out

    @tool
    async def pm_dispatch_task(
        ctx: Ctx,
        task_id: str,
        agent_type: str | None = None,
        profile_name: str | None = None,
        instructions: str = "",
        workspace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Queue an agent run for a task. Agents may only dispatch within the configured depth limit."""
        data = RunCreate.model_validate(
            {
                "task_id": task_id,
                "agent_type": agent_type,
                "profile_name": profile_name,
                "instructions": instructions,
                "workspace_id": workspace_id,
            }
        )

        async def op() -> object:
            return _dump(RunOut.model_validate(await run_svc.dispatch_run(ctx, data, idempotency_key=idempotency_key)))

        body, _, _ = await run_idempotent(
            ctx, key=idempotency_key, operation="dispatch_run", body=data.model_dump(mode="json"), fn=op
        )
        return body  # type: ignore[no-any-return]

    @tool
    async def pm_cancel_run(ctx: Ctx, run_id: str, reason: str = "") -> dict[str, Any]:
        """Request cancellation of a run (agents: only their own run or runs they dispatched)."""
        run = await run_svc.get_run(ctx, uuid.UUID(run_id))
        return _brief_run(await run_svc.request_cancel(ctx, run, reason))

    @tool
    async def pm_resume_task(
        ctx: Ctx, task_id: str, agent_type: str | None = None, instructions: str = ""
    ) -> dict[str, Any]:
        """Dispatch a new run that continues the task from its latest checkpoint (defaults to the last agent)."""
        tid = uuid.UUID(task_id)
        last, _ = await run_svc.list_runs(ctx, task_id=tid, limit=1)
        chosen = agent_type or (last[0].agent_type if last else None)
        if not chosen:
            raise ToolError("no previous run; pass agent_type")
        checkpoint = await memory.latest_checkpoint(ctx, tid)
        data = RunCreate(
            task_id=tid,
            agent_type=chosen,
            workspace_id=last[0].workspace_id if last else None,
            from_checkpoint_id=checkpoint.id if checkpoint else None,
            instructions=instructions,
        )
        return _dump(RunOut.model_validate(await run_svc.dispatch_run(ctx, data)))

    return mcp


def _brief_task(task: Any) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "key": f"T-{task.number}",
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "next_action": task.next_action,
        "project_id": str(task.project_id) if task.project_id else None,
        "updated_at": task.updated_at.isoformat(),
    }


def _brief_run(run: Any) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "task_id": str(run.task_id),
        "agent_type": run.agent_type,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "exit_code": run.exit_code,
        "error": run.error,
        "result_summary": (run.result_summary or "")[:1000],
        "cancel_requested": run.cancel_requested_at is not None,
        "active": RunStatus(run.status)
        not in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED, RunStatus.LOST),
    }
