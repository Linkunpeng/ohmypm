"""Idempotent POST handling (``Idempotency-Key`` header or MCP ``idempotency_key`` argument).

The key row is inserted *before* the operation runs, inside the same transaction. A concurrent
request with the same key blocks on the primary key until the first one commits, then sees the
stored response. A key reused with a different request body is rejected.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ohmypm.errors import Conflict
from ohmypm.models import IdempotencyKey
from ohmypm.services.common import Ctx

PENDING = 0


def request_hash(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


async def run_idempotent(
    ctx: Ctx,
    *,
    key: str | None,
    operation: str,
    body: Any,
    fn: Callable[[], Awaitable[Any]],
    status_code: int = 201,
) -> tuple[Any, int, bool]:
    """Returns ``(response_json, status_code, replayed)``. ``fn`` must return JSON-able data."""
    if not key:
        return await fn(), status_code, False
    if len(key) > 200:
        raise Conflict("idempotency key too long (max 200)", code="idempotency_key_invalid")
    scope = f"{ctx.principal.actor}:{operation}"
    digest = request_hash(body)
    inserted = (
        await ctx.session.execute(
            insert(IdempotencyKey)
            .values(scope=scope, key=key, request_hash=digest, status_code=PENDING, response={})
            .on_conflict_do_nothing()
            .returning(IdempotencyKey.key)
        )
    ).first()
    if inserted is None:
        row = (
            await ctx.session.execute(
                select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key)
            )
        ).scalar_one()
        if row.request_hash != digest:
            raise Conflict("idempotency key was already used with a different request", code="idempotency_key_reused")
        if row.status_code == PENDING:
            raise Conflict("a request with this idempotency key is still in progress", code="idempotency_in_progress")
        return row.response, row.status_code, True
    result = await fn()
    row = (
        await ctx.session.execute(
            select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key)
        )
    ).scalar_one()
    row.response = result
    row.status_code = status_code
    await ctx.session.flush()
    return result, status_code, False
