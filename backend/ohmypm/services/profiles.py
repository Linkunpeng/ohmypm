"""Agent profiles and the agent catalog (which agent types runners can execute)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, update

from ohmypm.errors import Conflict, ValidationFailed
from ohmypm.models import AgentProfile
from ohmypm.schemas import AgentAvailability, AgentProfileCreate, AgentProfileUpdate
from ohmypm.services.auth import require_role
from ohmypm.services.common import Ctx, check_version, get_or_404
from ohmypm.services.runs import list_runners
from ohmypm_common.agent_options import OptionsError, parse_options
from ohmypm_common.enums import Role

BUILTIN_AGENTS = {
    "claude": "Claude Code",
    "codex": "Codex CLI",
    "pi": "Pi",
    "dsh": "DeepSeek Harness (dsh)",
}


def _validate(agent_type: str, options: dict[str, object]) -> None:
    try:
        parse_options(agent_type, dict(options))
    except OptionsError as exc:
        raise ValidationFailed(str(exc), code="invalid_profile_options") from exc


async def _clear_default(ctx: Ctx, agent_type: str, keep: uuid.UUID | None = None) -> None:
    stmt = update(AgentProfile).where(AgentProfile.agent_type == agent_type, AgentProfile.is_default.is_(True))
    if keep is not None:
        stmt = stmt.where(AgentProfile.id != keep)
    await ctx.session.execute(
        stmt.values(is_default=False, version=AgentProfile.version + 1).execution_options(synchronize_session="fetch")
    )


async def create_profile(ctx: Ctx, data: AgentProfileCreate) -> AgentProfile:
    require_role(ctx.principal, Role.ADMIN)
    _validate(data.agent_type, data.options)
    exists = (await ctx.session.execute(select(AgentProfile.id).where(AgentProfile.name == data.name))).first()
    if exists:
        raise Conflict(f"profile {data.name!r} already exists", code="profile_exists")
    if data.is_default:
        await _clear_default(ctx, data.agent_type)
    profile = AgentProfile(
        name=data.name,
        agent_type=data.agent_type,
        description=data.description,
        instructions=data.instructions,
        options=data.options,
        write_mode=data.write_mode,
        timeout_seconds=data.timeout_seconds,
        is_default=data.is_default,
        metadata_=data.metadata,
    )
    ctx.session.add(profile)
    await ctx.session.flush()
    return profile


async def update_profile(ctx: Ctx, profile_id: uuid.UUID, data: AgentProfileUpdate) -> AgentProfile:
    require_role(ctx.principal, Role.ADMIN)
    profile = await get_or_404(ctx.session, AgentProfile, profile_id, "agent profile")
    check_version(profile, data.expected_version)
    if data.name is not None and data.name != profile.name:
        exists = (await ctx.session.execute(select(AgentProfile.id).where(AgentProfile.name == data.name))).first()
        if exists:
            raise Conflict(f"profile {data.name!r} already exists", code="profile_exists")
        profile.name = data.name
    if data.options is not None:
        _validate(profile.agent_type, data.options)
        profile.options = data.options
    if data.description is not None:
        profile.description = data.description
    if data.instructions is not None:
        profile.instructions = data.instructions
    if data.write_mode is not None:
        profile.write_mode = data.write_mode
    if "timeout_seconds" in data.model_fields_set:
        profile.timeout_seconds = data.timeout_seconds
    if data.is_default is not None:
        if data.is_default:
            await _clear_default(ctx, profile.agent_type, keep=profile.id)
        profile.is_default = data.is_default
    if data.metadata is not None:
        profile.metadata_ = {**profile.metadata_, **data.metadata}
    await ctx.session.flush()
    return profile


async def delete_profile(ctx: Ctx, profile_id: uuid.UUID) -> None:
    require_role(ctx.principal, Role.ADMIN)
    profile = await get_or_404(ctx.session, AgentProfile, profile_id, "agent profile")
    await ctx.session.delete(profile)


async def list_profiles(ctx: Ctx, agent_type: str | None = None) -> Sequence[AgentProfile]:
    stmt = select(AgentProfile).order_by(AgentProfile.agent_type, AgentProfile.name)
    if agent_type:
        stmt = stmt.where(AgentProfile.agent_type == agent_type)
    return (await ctx.session.execute(stmt)).scalars().all()


async def agent_catalog(ctx: Ctx) -> list[AgentAvailability]:
    catalog: dict[str, AgentAvailability] = {
        key: AgentAvailability(agent_type=key, display_name=name) for key, name in BUILTIN_AGENTS.items()
    }
    for runner, online, _active in await list_runners(ctx):
        for agent in runner.agents:
            agent_type = str(agent.get("agent_type"))
            entry = catalog.setdefault(
                agent_type, AgentAvailability(agent_type=agent_type, display_name=agent.get("display_name"))
            )
            entry.available_on.append(
                {
                    "runner_id": str(runner.id),
                    "runner": runner.name,
                    "host_id": runner.host_id,
                    "online": online,
                    "available": bool(agent.get("available")),
                    "version": agent.get("version"),
                    "detail": agent.get("detail"),
                }
            )
    return list(catalog.values())
