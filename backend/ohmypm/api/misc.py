"""/api/health, /api/search, /api/dashboard, /api/whoami."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import text

from ohmypm import __version__
from ohmypm.api.deps import CtxDep
from ohmypm.db import Database
from ohmypm.schemas import DashboardOut, SearchResults
from ohmypm.services import search as search_svc
from ohmypm.services.dashboard import dashboard as build_dashboard

router = APIRouter()


@router.get("/health", tags=["system"])
async def health(request: Request) -> dict[str, Any]:
    """Unauthenticated liveness + database check."""
    db: Database = request.app.state.db
    try:
        async with db.session() as session:
            revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
        database = "ok"
    except Exception:
        revision, database = None, "unavailable"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "version": __version__,
        "database": database,
        "schema_revision": revision,
    }


@router.get("/whoami", tags=["system"])
async def whoami(ctx: CtxDep) -> dict[str, Any]:
    p = ctx.principal
    return {"role": p.role.value, "name": p.name, "run_id": p.run_id, "task_id": p.task_id}


@router.get("/search", response_model=SearchResults, tags=["search"])
async def search(
    ctx: CtxDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    kind: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> SearchResults:
    return SearchResults(query=q, hits=await search_svc.search(ctx, q, kinds=kind, limit=limit))


@router.get("/dashboard", response_model=DashboardOut, tags=["system"])
async def dashboard(ctx: CtxDep) -> DashboardOut:
    return await build_dashboard(ctx)
