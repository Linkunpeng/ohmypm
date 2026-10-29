"""Application factory and server entry point (``ohmypm-server serve|migrate``)."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastmcp.utilities.lifespan import combine_lifespans
from starlette.types import ASGIApp, Receive, Scope, Send

from ohmypm import __version__
from ohmypm.api import memory, misc, projects, runs, tasks
from ohmypm.api.errors import install_error_handlers
from ohmypm.config import Settings, get_settings
from ohmypm.db import Database
from ohmypm.mcp.server import build_mcp
from ohmypm.services import runs as run_service
from ohmypm.services.auth import SYSTEM
from ohmypm.services.common import Ctx

log = logging.getLogger("ohmypm")


class _McpPathFix:
    """Serve ``/mcp`` without a redirect to ``/mcp/`` (MCP clients POST and may not follow 307s)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            scope = dict(scope, path="/mcp/", raw_path=b"/mcp/")
        await self.app(scope, receive, send)


async def _reaper(db: Database, settings: Settings) -> None:
    while True:
        await asyncio.sleep(settings.reaper_interval_seconds)
        try:
            async with db.session() as session:
                await run_service.reap_expired_leases(Ctx(session=session, principal=SYSTEM, settings=settings))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("lease reaper iteration failed")


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = db or Database(settings.database_url)
    if settings.api_token is None:
        log.warning("OHMYPM_API_TOKEN is not set: the REST API and Web UI will reject every request")

    mcp = build_mcp(db, settings)
    mcp_app = mcp.http_app(path="/")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        reaper = asyncio.create_task(_reaper(db, settings))
        try:
            yield
        finally:
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)
            await db.dispose()

    app = FastAPI(
        title="ohmypm",
        version=__version__,
        description="Project memory, task management and agent execution.",
        lifespan=combine_lifespans(lifespan, mcp_app.lifespan),
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.db = db
    install_error_handlers(app)
    for module in (projects, tasks, memory, runs, misc):
        app.include_router(module.router, prefix="/api")

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"], include_in_schema=False)
    async def api_not_found(path: str) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": f"no route /api/{path}", "details": None}},
        )

    app.mount("/mcp", mcp_app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["ETag"],
        )
    _mount_web(app, settings.web_dist)
    app.add_middleware(_McpPathFix)
    return app


def _mount_web(app: FastAPI, dist: Path | None) -> None:
    if dist is None or not (dist / "index.html").is_file():
        return
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> Any:
        candidate = (root / path).resolve()
        # Only serve files inside the dist directory; everything else falls back to the SPA shell.
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})


def migrate(database_url: str | None = None, revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.attributes["configure_logger"] = False
    if database_url:
        cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, revision)


def run() -> None:
    parser = argparse.ArgumentParser(prog="ohmypm-server")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the API/MCP/Web server (default)")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--migrate", action="store_true", help="apply database migrations before starting")
    sub.add_parser("migrate", help="apply database migrations and exit")
    args = parser.parse_args()
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "migrate":
        migrate()
        return
    if getattr(args, "migrate", False):
        migrate()
    import uvicorn

    uvicorn.run(
        create_app(settings),
        host=getattr(args, "host", None) or settings.host,
        port=getattr(args, "port", None) or settings.port,
        log_level=settings.log_level,
        proxy_headers=False,
    )


if __name__ == "__main__":
    run()
