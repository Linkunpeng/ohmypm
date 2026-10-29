"""FastAPI dependencies: authenticated service context, pagination, concurrency headers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Header, Query, Request, Response

from ohmypm.config import Settings
from ohmypm.db import Database
from ohmypm.errors import Unauthorized, ValidationFailed
from ohmypm.services.auth import authenticate, require_role
from ohmypm.services.common import Ctx
from ohmypm_common.enums import Role


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


async def _ctx(request: Request) -> AsyncIterator[Ctx]:
    db: Database = request.app.state.db
    settings: Settings = request.app.state.settings
    async with db.session() as session:
        principal = await authenticate(bearer_token(request), settings, session)
        if principal is None:
            raise Unauthorized("missing or invalid bearer token")
        yield Ctx(session=session, principal=principal, settings=settings)


# scope="function": the transaction commits right after the endpoint returns, before the
# response is sent, so commit-time errors become proper error responses.
CtxDep = Annotated[Ctx, Depends(_ctx, scope="function")]


def role_ctx(*roles: Role) -> Callable[[Ctx], Coroutine[Any, Any, Ctx]]:
    async def dependency(ctx: CtxDep) -> Ctx:
        require_role(ctx.principal, *roles)
        return ctx

    return dependency


AdminCtx = Annotated[Ctx, Depends(role_ctx(Role.ADMIN))]
RunnerCtx = Annotated[Ctx, Depends(role_ctx(Role.RUNNER, Role.ADMIN))]
MemberCtx = Annotated[Ctx, Depends(role_ctx(Role.ADMIN, Role.AGENT))]


class PageParams:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        sort: Annotated[str | None, Query(max_length=40, description="e.g. -updated_at")] = None,
    ) -> None:
        self.limit = limit
        self.offset = offset
        self.sort = sort


PageDep = Annotated[PageParams, Depends()]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]


def expected_version(body_version: int | None, if_match: str | None) -> int | None:
    if body_version is not None:
        return body_version
    if not if_match:
        return None
    value = if_match.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise ValidationFailed("If-Match must contain the entity version")
    return int(value)


def set_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'W/"{version}"'
