"""Bearer-token authentication and role checks.

Roles (see .plan/decisions.md D-004):
- admin  — OHMYPM_API_TOKEN (Web UI, CLI)
- runner — OHMYPM_RUNNER_TOKEN (runner endpoints only)
- agent  — per-run tokens minted at claim time, or the optional static OHMYPM_AGENT_TOKEN
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ohmypm.config import Settings
from ohmypm.errors import Forbidden
from ohmypm.models import AgentRun
from ohmypm_common.enums import ACTIVE_RUN_STATUSES, Role

RUN_TOKEN_PREFIX = "omr_"  # noqa: S105 - prefix, not a secret


@dataclass(frozen=True)
class Principal:
    role: Role
    name: str
    run_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    dispatch_depth: int = 0

    @property
    def actor(self) -> str:
        """Value recorded in created_by / event actor columns."""
        if self.run_id is not None:
            return f"agent:run:{self.run_id}"
        return self.name

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


SYSTEM = Principal(role=Role.ADMIN, name="system")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_run_token() -> tuple[str, str]:
    token = RUN_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token)


def _matches(candidate: str, configured: object) -> bool:
    secret = getattr(configured, "get_secret_value", lambda: None)()
    return bool(secret) and hmac.compare_digest(candidate.encode(), str(secret).encode())


async def authenticate(token: str | None, settings: Settings, session: AsyncSession) -> Principal | None:
    if not token:
        return None
    if _matches(token, settings.api_token):
        return Principal(role=Role.ADMIN, name="admin")
    if _matches(token, settings.runner_token):
        return Principal(role=Role.RUNNER, name="runner")
    if _matches(token, settings.agent_token):
        return Principal(role=Role.AGENT, name="agent")
    if token.startswith(RUN_TOKEN_PREFIX):
        run = (
            await session.execute(select(AgentRun).where(AgentRun.agent_token_hash == hash_token(token)))
        ).scalar_one_or_none()
        # Run tokens are only valid while the run is active.
        if run is not None and run.status in ACTIVE_RUN_STATUSES:
            return Principal(
                role=Role.AGENT,
                name="agent",
                run_id=run.id,
                task_id=run.task_id,
                dispatch_depth=run.dispatch_depth,
            )
    return None


def require_role(principal: Principal, *roles: Role) -> None:
    if principal.role not in roles:
        allowed = ", ".join(r.value for r in roles)
        raise Forbidden(f"this operation requires role: {allowed}")
