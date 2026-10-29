"""Shared helpers for application services."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ohmypm.config import Settings
from ohmypm.errors import NotFound, VersionConflict
from ohmypm.models import Base, TaskEvent
from ohmypm.services.auth import Principal

M = TypeVar("M", bound=Base)

MAX_PAGE_SIZE = 200


@dataclass
class Ctx:
    """Per-request service context."""

    session: AsyncSession
    principal: Principal
    settings: Settings

    @property
    def actor(self) -> str:
        return self.principal.actor


def utcnow() -> datetime:
    return datetime.now(UTC)


async def get_or_404(session: AsyncSession, model: type[M], ident: uuid.UUID, label: str | None = None) -> M:
    obj = await session.get(model, ident)
    if obj is None:
        raise NotFound(f"{label or model.__name__} {ident} not found")
    return obj


def check_version(obj: Any, expected: int | None) -> None:
    if expected is not None and obj.version != expected:
        raise VersionConflict(
            f"version mismatch: expected {expected}, current {obj.version}",
            details={"expected": expected, "current": obj.version},
        )


async def paginate(session: AsyncSession, stmt: Select[Any], limit: int, offset: int) -> tuple[Sequence[Any], int]:
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    total = (await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
    rows = (await session.execute(stmt.limit(limit).offset(max(0, offset)))).scalars().all()
    return rows, int(total)


def apply_sort(
    stmt: Select[Any], model: type[Base], sort: str | None, allowed: Sequence[str], default: str
) -> Select[Any]:
    """``sort`` like ``-updated_at`` or ``priority``; only whitelisted columns."""
    key = sort or default
    descending = key.startswith("-")
    name = key.lstrip("-+")
    if name not in allowed:
        name = default.lstrip("-")
        descending = default.startswith("-")
    column = getattr(model, name)
    return stmt.order_by(column.desc() if descending else column.asc(), model.id)  # type: ignore[attr-defined]


async def record_task_event(
    ctx: Ctx, task_id: uuid.UUID, event_type: str, payload: dict[str, Any] | None = None
) -> TaskEvent:
    event = TaskEvent(task_id=task_id, event_type=event_type, actor=ctx.actor, payload=payload or {})
    ctx.session.add(event)
    return event


def dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def jsonable(value: Any) -> Any:
    """Convert values for JSONB event payloads."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if hasattr(value, "value") and isinstance(getattr(value, "value", None), str):
        return value.value
    return value


def like_pattern(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
