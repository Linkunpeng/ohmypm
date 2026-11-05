"""FastAPI application: local HTTP API + the compiled Web UI."""

from __future__ import annotations

import mimetypes
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ohmypm import __version__
from ohmypm.api.security import LocalSecurityMiddleware
from ohmypm.api.static import web_dist_dir
from ohmypm.core.dates import parse_when
from ohmypm.core.errors import NotFoundError, OhmypmError, ValidationError
from ohmypm.core.schemas import (
    BUILTIN_ENTRY_TYPES,
    ENTRY_STATUSES,
    AssetOut,
    EntryCreate,
    EntryOut,
    EntryRevisionOut,
    EntryUpdate,
    Page,
    ProjectOut,
    SearchHit,
    SummaryOut,
    SummaryUpdate,
)
from ohmypm.core.service import MemoryService
from ohmypm.storage.database import SCHEMA_HEAD
from ohmypm.storage.files import safe_child

MAX_JSON_BODY = 16 * 1024 * 1024
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"


# ------------------------------------------------------------------ bodies


class ProjectCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(description="Absolute path of the project root on this machine.")
    name: str | None = None
    description: str | None = None


class ProjectPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    root_path: str | None = Field(default=None, description="Relink the project to a new directory.")


class EntryCreateBody(EntryCreate):
    project_id: str


class EntryPatchBody(EntryUpdate):
    expected_revision: int | None = None
    author: str | None = None


class SummaryPutBody(SummaryUpdate):
    replace: bool = False
    expected_revision: int | None = None
    author: str | None = None


class RestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    author: str | None = None


class AssetResponse(AssetOut):
    url: str


def _asset_response(asset: AssetOut) -> AssetResponse:
    return AssetResponse(**asset.model_dump(), url=f"/api/assets/{asset.id}")


def _error_response(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return JSONResponse({"error": payload}, status_code=status)


def _when(value: str | None, *, end: bool = False) -> datetime | None:
    return parse_when(value, end_of_day=end)


def create_app(
    service: MemoryService | None = None,
    *,
    token: str | None = None,
    extra_origins: list[str] | None = None,
    public_host: str | None = None,
) -> FastAPI:
    service = service or MemoryService()
    settings = service.settings
    app = FastAPI(
        title="ohmypm",
        version=__version__,
        description="Local API of ohmypm (Oh My Project Memory). Listens on 127.0.0.1 only by default.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.service = service

    # ---------------------------------------------------------- errors
    @app.exception_handler(OhmypmError)
    async def _ohmypm_error(_: Request, exc: OhmypmError) -> JSONResponse:
        return _error_response(exc.http_status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "")).removeprefix("Value error, ")}
            for e in exc.errors()
        ]
        message = "; ".join(f"{'.'.join(map(str, e['loc'][1:] or e['loc']))}: {e['msg']}" for e in errors)
        return _error_response(422, "validation_error", message or "Invalid request", {"errors": errors})

    @app.exception_handler(PydanticValidationError)
    async def _pydantic_validation(_: Request, exc: PydanticValidationError) -> JSONResponse:
        message = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg'].removeprefix('Value error, ')}" for e in exc.errors()
        )
        return _error_response(422, "validation_error", message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error_response(exc.status_code, code, str(exc.detail))

    # ---------------------------------------------------------- meta
    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "schema": SCHEMA_HEAD}

    @app.get("/api/meta", tags=["meta"])
    def meta() -> dict[str, Any]:
        types = {t: BUILTIN_ENTRY_TYPES.get(t, "") for t in settings.entry_types}
        return {
            "version": __version__,
            "entry_types": types,
            "statuses": list(ENTRY_STATUSES),
            "max_upload_bytes": settings.max_upload_bytes,
            "default_author": settings.default_author,
        }

    @app.get("/api/dashboard", tags=["meta"])
    def dashboard(recent: Annotated[int, Query(ge=1, le=100)] = 10) -> dict[str, Any]:
        return service.dashboard(recent=recent)

    # ---------------------------------------------------------- projects
    @app.get("/api/projects", tags=["projects"])
    def list_projects(include_archived: bool = False) -> list[ProjectOut]:
        return service.list_projects(include_archived=include_archived)

    @app.post("/api/projects", status_code=201, tags=["projects"])
    def create_project(body: ProjectCreateBody) -> dict[str, Any]:
        project, outcome = service.register(body.path, name=body.name, description=body.description)
        return {"outcome": outcome, "project": project.model_dump(mode="json")}

    @app.get("/api/projects/{project_id}", tags=["projects"])
    def get_project(project_id: str) -> ProjectOut:
        return service.get_project(project=project_id)

    @app.patch("/api/projects/{project_id}", tags=["projects"])
    def patch_project(project_id: str, body: ProjectPatchBody) -> ProjectOut:
        project = service.get_project(project=project_id)
        if body.root_path is not None:
            service.relink(body.root_path, project=project.id)
        if body.name is not None or body.description is not None:
            return service.update_project(project=project.id, name=body.name, description=body.description)
        return service.get_project(project=project.id)

    @app.delete("/api/projects/{project_id}", tags=["projects"])
    def delete_project(project_id: str, purge: bool = False) -> dict[str, Any]:
        project = service.unregister(project=project_id, purge=purge)
        return {"purged": purge, "project": project.model_dump(mode="json")}

    @app.get("/api/projects/{project_id}/summary", tags=["summary"])
    def get_summary(project_id: str) -> SummaryOut:
        return service.get_summary(project=project_id)

    @app.put("/api/projects/{project_id}/summary", tags=["summary"])
    def put_summary(project_id: str, body: SummaryPutBody) -> dict[str, Any]:
        sections = SummaryUpdate(**{k: v for k, v in body.provided().items()})
        summary, changed = service.set_summary(
            sections,
            project=project_id,
            replace=body.replace,
            changed_by=body.author,
            expected_revision=body.expected_revision,
        )
        return {"changed": changed, "summary": summary.model_dump(mode="json")}

    @app.get("/api/projects/{project_id}/summary/history", tags=["summary"])
    def summary_history(project_id: str) -> list[dict[str, Any]]:
        return service.summary_history(project=project_id)

    @app.get("/api/projects/{project_id}/context", tags=["context"])
    def get_context(
        project_id: str,
        mode: Literal["brief", "standard", "full"] = "brief",
        max_tokens: Annotated[int | None, Query(ge=200, le=200_000)] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 20,
    ) -> dict[str, Any]:
        result = service.context(
            project=project_id, mode=mode, max_tokens=max_tokens, page=page, page_size=page_size
        )
        return result.model_dump(mode="json")

    # ---------------------------------------------------------- entries
    @app.get("/api/entries", tags=["entries"])
    def list_entries(
        project_id: str | None = None,
        type: Annotated[list[str] | None, Query()] = None,
        status: Annotated[list[str] | None, Query()] = None,
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
        author: str | None = None,
        order: Literal["asc", "desc"] = "asc",
        sort: Literal["sequence", "created_at", "updated_at"] = "sequence",
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        include_content: bool = False,
    ) -> Page[EntryOut]:
        return service.list_entries(
            project=project_id,
            all_projects=project_id is None,
            types=type,
            statuses=status,
            query=q,
            since=_when(since),
            until=_when(until, end=True),
            author=author,
            order=order,
            sort=sort,
            limit=limit,
            offset=offset,
            include_content=include_content,
        )

    @app.post("/api/entries", status_code=201, tags=["entries"])
    def create_entry(body: EntryCreateBody) -> EntryOut:
        data = EntryCreate(**body.model_dump(exclude={"project_id", "source"}), source="web")
        return service.add_entry(data, project=body.project_id)

    @app.get("/api/entries/{entry_id}", tags=["entries"])
    def get_entry(entry_id: str) -> EntryOut:
        return service.get_entry(entry_id)

    @app.patch("/api/entries/{entry_id}", tags=["entries"])
    def patch_entry(entry_id: str, body: EntryPatchBody) -> dict[str, Any]:
        changes = EntryUpdate(**body.model_dump(exclude={"expected_revision", "author"}))
        entry, changed = service.update_entry(
            entry_id, changes, changed_by=body.author, expected_revision=body.expected_revision
        )
        return {"changed": changed, "entry": entry.model_dump(mode="json")}

    @app.delete("/api/entries/{entry_id}", tags=["entries"])
    def delete_entry(entry_id: str, author: str | None = None) -> dict[str, Any]:
        entry = service.delete_entry(entry_id, changed_by=author)
        return {"deleted": True, "entry": entry.model_dump(mode="json")}

    @app.get("/api/entries/{entry_id}/revisions", tags=["entries"])
    def entry_revisions(entry_id: str) -> list[EntryRevisionOut]:
        return service.entry_history(entry_id)

    @app.post("/api/entries/{entry_id}/restore", tags=["entries"])
    def restore_entry(entry_id: str, body: RestoreBody) -> EntryOut:
        return service.restore_entry(entry_id, body.revision, changed_by=body.author)

    # ---------------------------------------------------------- search
    @app.get("/api/search", tags=["search"])
    def search(
        q: Annotated[str, Query(min_length=1, max_length=500)],
        project_id: str | None = None,
        kind: Annotated[list[str] | None, Query()] = None,
        type: Annotated[list[str] | None, Query()] = None,
        since: str | None = None,
        until: str | None = None,
        include_archived: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> Page[SearchHit]:
        return service.search(
            q,
            project=project_id,
            all_projects=project_id is None,
            kinds=kind,
            types=type,
            since=_when(since),
            until=_when(until, end=True),
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )

    # ---------------------------------------------------------- assets
    @app.post("/api/assets", status_code=201, tags=["assets"])
    async def upload_asset(
        file: Annotated[UploadFile, File()],
        project_id: Annotated[str, Form()],
        entry_id: Annotated[str | None, Form()] = None,
    ) -> AssetResponse:
        data = await file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise ValidationError(
                f"File is too large (limit {settings.max_upload_bytes} bytes)",
                details={"limit": settings.max_upload_bytes},
            )
        asset = service.add_asset(file.filename or "upload", data, project=project_id, entry=entry_id)
        return _asset_response(asset)

    @app.get("/api/assets", tags=["assets"])
    def list_assets(project_id: str, entry_id: str | None = None) -> list[AssetResponse]:
        return [_asset_response(a) for a in service.list_assets(project=project_id, entry=entry_id)]

    @app.get("/api/assets/{asset_id}/meta", tags=["assets"])
    def asset_meta(asset_id: str) -> AssetResponse:
        return _asset_response(service.get_asset(asset_id)[0])

    @app.get("/api/assets/{asset_id}", tags=["assets"], response_class=FileResponse)
    def get_asset(asset_id: str, download: bool = False) -> Response:
        asset, path = service.get_asset(asset_id)
        if not path.is_file():
            raise NotFoundError(f"File of asset {asset_id} is missing")
        disposition = "attachment" if download else "inline"
        headers = {
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(asset.filename)}",
            "Cache-Control": "private, max-age=31536000, immutable",
        }
        media_type = asset.mime_type
        if media_type == "image/svg+xml":
            headers["Content-Security-Policy"] = SVG_CSP
        elif media_type.startswith("text/"):
            media_type = "text/plain; charset=utf-8"
            headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return FileResponse(path, media_type=media_type, headers=headers)

    # ---------------------------------------------------------- web ui
    dist = web_dist_dir()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path.startswith("api/"):
            raise NotFoundError(f"Unknown API endpoint: /{full_path}")
        if dist is None:
            return JSONResponse(
                {
                    "error": {
                        "code": "web_ui_missing",
                        "message": "The Web UI is not built. "
                        "Run scripts/build-frontend.sh (or use the API at /api/docs).",
                    }
                },
                status_code=503,
            )
        if full_path:
            try:
                candidate = safe_child(dist, full_path)
            except ValueError:
                candidate = None
            if candidate is not None and candidate.is_file():
                media_type = mimetypes.guess_type(candidate.name)[0]
                cache = (
                    "public, max-age=31536000, immutable" if full_path.startswith("assets/") else "no-cache"
                )
                return FileResponse(candidate, media_type=media_type, headers={"Cache-Control": cache})
        return FileResponse(
            dist / "index.html", media_type="text/html", headers={"Cache-Control": "no-cache"}
        )

    # ---------------------------------------------------------- middleware
    origins = list(extra_origins or [])
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "Authorization"],
        )
    hosts = [public_host] if public_host else []
    app.add_middleware(
        LocalSecurityMiddleware,
        token=token,
        allowed_hosts=hosts,
        allowed_origins=origins,
        max_body_bytes=MAX_JSON_BODY,
        max_upload_bytes=settings.max_upload_bytes + 1024 * 1024,
    )
    return app
