"""/api/runs, /api/runners, /api/agents, /api/agent-profiles and the runner protocol (/api/runner/*)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ohmypm.api.deps import AdminCtx, CtxDep, IdempotencyKey, MemberCtx, PageDep, RunnerCtx, bearer_token
from ohmypm.config import Settings
from ohmypm.db import Database
from ohmypm.errors import NotFound, Unauthorized
from ohmypm.models import AgentRun, RunEvent
from ohmypm.schemas import (
    AgentAvailability,
    AgentProfileCreate,
    AgentProfileOut,
    AgentProfileUpdate,
    Page,
    RunCancel,
    RunCreate,
    RunEventOut,
    RunnerOut,
    RunOut,
)
from ohmypm.services import profiles as profile_svc
from ohmypm.services import runs as svc
from ohmypm.services.auth import authenticate
from ohmypm.services.idempotency import run_idempotent
from ohmypm_common.enums import TERMINAL_RUN_STATUSES, RunStatus
from ohmypm_common.protocol import (
    ClaimRequest,
    ClaimResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    RunEventsBatch,
    RunFinishRequest,
    RunnerRegisterRequest,
    RunnerRegisterResponse,
    RunProgressUpdate,
)

router = APIRouter()
RunnerIdHeader = Annotated[uuid.UUID, Header(alias="X-Runner-Id")]


# ---------------------------------------------------------------- runs


@router.post("/runs", status_code=201, response_model=RunOut, tags=["runs"])
async def dispatch_run(
    data: RunCreate, ctx: MemberCtx, response: Response, idempotency_key: IdempotencyKey = None
) -> object:
    async def op() -> object:
        run = await svc.dispatch_run(ctx, data, idempotency_key=idempotency_key)
        return RunOut.model_validate(run).model_dump(mode="json")

    body, status, _ = await run_idempotent(
        ctx, key=idempotency_key, operation="dispatch_run", body=data.model_dump(mode="json"), fn=op
    )
    response.status_code = status
    return body


@router.get("/runs", response_model=Page[RunOut], tags=["runs"])
async def list_runs(
    ctx: CtxDep,
    page: PageDep,
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    runner_id: uuid.UUID | None = None,
    status: Annotated[list[RunStatus] | None, Query()] = None,
    active: bool | None = None,
) -> Page[RunOut]:
    rows, total = await svc.list_runs(
        ctx,
        task_id=task_id,
        project_id=project_id,
        workspace_id=workspace_id,
        runner_id=runner_id,
        statuses=status,
        active=active,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(items=[RunOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/runs/{run_id}", response_model=RunOut, tags=["runs"])
async def get_run(run_id: uuid.UUID, ctx: CtxDep) -> RunOut:
    return RunOut.model_validate(await svc.get_run(ctx, run_id))


@router.post("/runs/{run_id}/cancel", response_model=RunOut, tags=["runs"])
async def cancel_run(run_id: uuid.UUID, data: RunCancel, ctx: MemberCtx) -> RunOut:
    run = await svc.get_run(ctx, run_id)
    return RunOut.model_validate(await svc.request_cancel(ctx, run, data.reason))


def _sse(event: str, data: object, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _stream_events(request: Request, run_id: uuid.UUID, after_seq: int) -> AsyncIterator[str]:
    db: Database = request.app.state.db
    settings: Settings = request.app.state.settings
    last = after_seq
    last_send = time.monotonic()
    yield "retry: 2000\n\n"
    while True:
        if await request.is_disconnected():
            return
        async with db.session() as session:
            rows = (
                (
                    await session.execute(
                        select(RunEvent)
                        .where(RunEvent.run_id == run_id, RunEvent.seq > last)
                        .order_by(RunEvent.seq)
                        .limit(500)
                    )
                )
                .scalars()
                .all()
            )
            status = (await session.execute(select(AgentRun.status).where(AgentRun.id == run_id))).scalar_one()
        for row in rows:
            last = row.seq
            yield _sse("run_event", RunEventOut.model_validate(row).model_dump(mode="json"), row.seq)
            last_send = time.monotonic()
        if not rows and status in TERMINAL_RUN_STATUSES:
            yield _sse("end", {"status": status})
            return
        if time.monotonic() - last_send > settings.sse_keepalive_seconds:
            yield ": keepalive\n\n"
            last_send = time.monotonic()
        if len(rows) < 500:
            await asyncio.sleep(settings.sse_poll_interval_seconds)


@router.get(
    "/runs/{run_id}/events",
    tags=["runs"],
    response_model=list[RunEventOut],
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def run_events(
    run_id: uuid.UUID,
    request: Request,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    event_type: Annotated[list[str] | None, Query()] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> object:
    """JSON list of events, or a live SSE stream when ``Accept: text/event-stream``.

    The stream replays events after ``Last-Event-ID`` (or ``after_seq``), so clients can
    reconnect without gaps. Closing the stream never affects the run.
    """
    db: Database = request.app.state.db
    settings: Settings = request.app.state.settings
    async with db.session() as session:
        principal = await authenticate(bearer_token(request), settings, session)
        if principal is None:
            raise Unauthorized("missing or invalid bearer token")
        if await session.get(AgentRun, run_id) is None:
            raise NotFound(f"run {run_id} not found")
        if "text/event-stream" not in request.headers.get("accept", ""):
            from ohmypm.services.common import Ctx

            ctx = Ctx(session=session, principal=principal, settings=settings)
            rows = await svc.list_run_events(ctx, run_id, after_seq=after_seq, limit=limit, event_types=event_type)
            return [RunEventOut.model_validate(r) for r in rows]
    start = after_seq
    if last_event_id and last_event_id.strip().isdigit():
        start = int(last_event_id.strip())
    return StreamingResponse(
        _stream_events(request, run_id, start),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- runners / agents / profiles


@router.get("/runners", response_model=list[RunnerOut], tags=["runners"])
async def list_runners(ctx: CtxDep) -> list[RunnerOut]:
    out = []
    for runner, online, active in await svc.list_runners(ctx):
        item = RunnerOut.model_validate(runner)
        item.online = online
        item.active_runs = active
        out.append(item)
    return out


@router.get("/agents", response_model=list[AgentAvailability], tags=["agents"])
async def list_agents(ctx: CtxDep) -> list[AgentAvailability]:
    return await profile_svc.agent_catalog(ctx)


@router.get("/agent-profiles", response_model=list[AgentProfileOut], tags=["agents"])
async def list_profiles(ctx: CtxDep, agent_type: str | None = None) -> list[AgentProfileOut]:
    return [AgentProfileOut.model_validate(p) for p in await profile_svc.list_profiles(ctx, agent_type)]


@router.post("/agent-profiles", status_code=201, response_model=AgentProfileOut, tags=["agents"])
async def create_profile(data: AgentProfileCreate, ctx: AdminCtx) -> AgentProfileOut:
    return AgentProfileOut.model_validate(await profile_svc.create_profile(ctx, data))


@router.patch("/agent-profiles/{profile_id}", response_model=AgentProfileOut, tags=["agents"])
async def update_profile(profile_id: uuid.UUID, data: AgentProfileUpdate, ctx: AdminCtx) -> AgentProfileOut:
    return AgentProfileOut.model_validate(await profile_svc.update_profile(ctx, profile_id, data))


@router.delete("/agent-profiles/{profile_id}", status_code=204, tags=["agents"])
async def delete_profile(profile_id: uuid.UUID, ctx: AdminCtx) -> None:
    await profile_svc.delete_profile(ctx, profile_id)


# ---------------------------------------------------------------- runner protocol


@router.post("/runner/register", response_model=RunnerRegisterResponse, tags=["runner-protocol"])
async def runner_register(data: RunnerRegisterRequest, ctx: RunnerCtx) -> RunnerRegisterResponse:
    return await svc.register_runner(ctx, data)


@router.post("/runner/heartbeat", response_model=HeartbeatResponse, tags=["runner-protocol"])
async def runner_heartbeat(data: HeartbeatRequest, ctx: RunnerCtx) -> HeartbeatResponse:
    return await svc.heartbeat(ctx, data)


@router.post("/runner/claim", response_model=ClaimResponse, tags=["runner-protocol"])
async def runner_claim(data: ClaimRequest, ctx: RunnerCtx) -> ClaimResponse:
    return ClaimResponse(runs=await svc.claim_runs(ctx, data))


@router.post("/runner/runs/{run_id}/progress", response_model=RunOut, tags=["runner-protocol"])
async def runner_progress(
    run_id: uuid.UUID, data: RunProgressUpdate, ctx: RunnerCtx, runner_id: RunnerIdHeader
) -> RunOut:
    return RunOut.model_validate(await svc.report_progress(ctx, run_id, runner_id, data))


@router.post("/runner/runs/{run_id}/events", tags=["runner-protocol"])
async def runner_events(
    run_id: uuid.UUID, data: RunEventsBatch, ctx: RunnerCtx, runner_id: RunnerIdHeader
) -> dict[str, int]:
    return {"accepted": await svc.append_events(ctx, run_id, runner_id, data.events)}


@router.post("/runner/runs/{run_id}/finish", response_model=RunOut, tags=["runner-protocol"])
async def runner_finish(run_id: uuid.UUID, data: RunFinishRequest, ctx: RunnerCtx, runner_id: RunnerIdHeader) -> RunOut:
    return RunOut.model_validate(await svc.finish_run(ctx, run_id, runner_id, data))
