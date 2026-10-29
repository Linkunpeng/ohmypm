"""Artifact registry (reference storage mode).

Reference mode records where an artifact lives plus how to build/use/verify it; the server never
reads the referenced path (it may not even exist on this machine). Managed mode is planned.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select

from ohmypm.errors import ValidationFailed
from ohmypm.models import Artifact, ArtifactVersion, Project, Task, Workspace
from ohmypm.schemas import ArtifactCreate, ArtifactUpdate
from ohmypm.services.common import Ctx, check_version, get_or_404, like_pattern, paginate, record_task_event
from ohmypm_common.enums import ArtifactType, StorageMode

VERSIONED_FIELDS = ("storage_uri", "sha256", "size_bytes", "version_label")


async def create_artifact(ctx: Ctx, data: ArtifactCreate) -> Artifact:
    if data.storage_mode is StorageMode.MANAGED:
        raise ValidationFailed(
            "managed storage is not implemented yet; use storage_mode=reference", code="not_implemented"
        )
    project_id = data.project_id
    task: Task | None = None
    if data.task_id is not None:
        task = await get_or_404(ctx.session, Task, data.task_id, "task")
        project_id = project_id or task.project_id
    if project_id is not None:
        await get_or_404(ctx.session, Project, project_id, "project")
    workspace_id = data.workspace_id or (task.workspace_id if task else None)
    if data.workspace_id is not None:
        await get_or_404(ctx.session, Workspace, data.workspace_id, "workspace")
    artifact = Artifact(
        task_id=data.task_id,
        project_id=project_id,
        workspace_id=workspace_id,
        name=data.name,
        type=data.type.value,
        storage_mode=data.storage_mode.value,
        storage_uri=data.storage_uri,
        sha256=data.sha256,
        size_bytes=data.size_bytes,
        version_label=data.version_label,
        description=data.description,
        usage=data.usage.model_dump(),
        build=data.build.model_dump(),
        environment=data.environment,
        deployment=data.deployment,
        verification=data.verification.model_dump(mode="json"),
        tags=list(data.tags),
        created_by=ctx.actor,
        metadata_=data.metadata,
    )
    ctx.session.add(artifact)
    await ctx.session.flush()
    ctx.session.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_label=artifact.version_label,
            storage_uri=artifact.storage_uri,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            notes="initial registration",
            created_by=ctx.actor,
        )
    )
    if task is not None:
        await record_task_event(
            ctx,
            task.id,
            "artifact.registered",
            {"artifact_id": str(artifact.id), "name": artifact.name, "type": artifact.type},
        )
    await ctx.session.flush()
    return artifact


async def get_artifact(ctx: Ctx, artifact_id: uuid.UUID) -> Artifact:
    return await get_or_404(ctx.session, Artifact, artifact_id, "artifact")


async def list_versions(ctx: Ctx, artifact_id: uuid.UUID) -> Sequence[ArtifactVersion]:
    stmt = (
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.created_at.desc(), ArtifactVersion.id)
    )
    return (await ctx.session.execute(stmt)).scalars().all()


async def list_artifacts(
    ctx: Ctx,
    *,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    type: ArtifactType | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Artifact], int]:
    stmt = select(Artifact)
    if project_id is not None:
        stmt = stmt.where(Artifact.project_id == project_id)
    if task_id is not None:
        stmt = stmt.where(Artifact.task_id == task_id)
    if type is not None:
        stmt = stmt.where(Artifact.type == type.value)
    if q:
        pattern = like_pattern(q)
        stmt = stmt.where(
            or_(
                Artifact.search_vector.op("@@")(func.websearch_to_tsquery("simple", q)),
                Artifact.name.ilike(pattern),
                Artifact.storage_uri.ilike(pattern),
            )
        )
    stmt = stmt.order_by(Artifact.updated_at.desc(), Artifact.id)
    return await paginate(ctx.session, stmt, limit, offset)


async def update_artifact(ctx: Ctx, artifact_id: uuid.UUID, data: ArtifactUpdate) -> Artifact:
    artifact = await get_artifact(ctx, artifact_id)
    check_version(artifact, data.expected_version)
    fields = data.model_fields_set
    versioned_change = False
    for name in VERSIONED_FIELDS:
        if name in fields and getattr(data, name) is not None and getattr(data, name) != getattr(artifact, name):
            setattr(artifact, name, getattr(data, name))
            versioned_change = True
    if data.name is not None:
        artifact.name = data.name
    if data.type is not None:
        artifact.type = data.type.value
    if data.description is not None:
        artifact.description = data.description
    if data.usage is not None:
        artifact.usage = data.usage.model_dump()
    if data.build is not None:
        artifact.build = data.build.model_dump()
    if data.environment is not None:
        artifact.environment = data.environment
    if data.deployment is not None:
        artifact.deployment = data.deployment
    if data.verification is not None:
        artifact.verification = data.verification.model_dump(mode="json")
    if data.tags is not None:
        artifact.tags = list(data.tags)
    if data.metadata is not None:
        artifact.metadata_ = {**artifact.metadata_, **data.metadata}
    if versioned_change:
        ctx.session.add(
            ArtifactVersion(
                artifact_id=artifact.id,
                version_label=artifact.version_label,
                storage_uri=artifact.storage_uri,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                notes=data.version_notes,
                created_by=ctx.actor,
            )
        )
    await ctx.session.flush()
    return artifact
