"""/api/decisions, /api/knowledge, /api/artifacts."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from ohmypm.api.deps import CtxDep, IdempotencyKey, IfMatch, MemberCtx, PageDep, expected_version, set_etag
from ohmypm.schemas import (
    ArtifactCreate,
    ArtifactDetail,
    ArtifactOut,
    ArtifactUpdate,
    ArtifactVersionOut,
    DecisionCancel,
    DecisionCreate,
    DecisionOut,
    DecisionResolve,
    KnowledgeCreate,
    KnowledgeOut,
    KnowledgeUpdate,
    Page,
    RunOut,
)
from ohmypm.services import artifacts as artifact_svc
from ohmypm.services import decisions as decision_svc
from ohmypm.services import knowledge as knowledge_svc
from ohmypm.services.idempotency import run_idempotent
from ohmypm_common.enums import ArtifactType, DecisionStatus, KnowledgeCategory

router = APIRouter()


class DecisionResolution(BaseModel):
    decision: DecisionOut
    resumed_run: RunOut | None = None


@router.post("/decisions", status_code=201, response_model=DecisionOut, tags=["decisions"])
async def create_decision(data: DecisionCreate, ctx: MemberCtx) -> DecisionOut:
    return DecisionOut.model_validate(await decision_svc.create_decision(ctx, data))


@router.get("/decisions", response_model=Page[DecisionOut], tags=["decisions"])
async def list_decisions(
    ctx: CtxDep,
    page: PageDep,
    status: DecisionStatus | None = None,
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> Page[DecisionOut]:
    rows, total = await decision_svc.list_decisions(
        ctx, status=status, task_id=task_id, project_id=project_id, limit=page.limit, offset=page.offset
    )
    return Page(items=[DecisionOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/decisions/{decision_id}", response_model=DecisionOut, tags=["decisions"])
async def get_decision(decision_id: uuid.UUID, ctx: CtxDep, response: Response) -> DecisionOut:
    decision = await decision_svc.get_decision(ctx, decision_id)
    set_etag(response, decision.version)
    return DecisionOut.model_validate(decision)


@router.post("/decisions/{decision_id}/resolve", response_model=DecisionResolution, tags=["decisions"])
async def resolve_decision(
    decision_id: uuid.UUID, data: DecisionResolve, ctx: MemberCtx, if_match: IfMatch = None
) -> DecisionResolution:
    data.expected_version = expected_version(data.expected_version, if_match)
    decision, run = await decision_svc.resolve_decision(ctx, decision_id, data)
    return DecisionResolution(
        decision=DecisionOut.model_validate(decision), resumed_run=RunOut.model_validate(run) if run else None
    )


@router.post("/decisions/{decision_id}/cancel", response_model=DecisionOut, tags=["decisions"])
async def cancel_decision(decision_id: uuid.UUID, data: DecisionCancel, ctx: MemberCtx) -> DecisionOut:
    return DecisionOut.model_validate(await decision_svc.cancel_decision(ctx, decision_id, data.reason))


@router.post("/knowledge", status_code=201, response_model=KnowledgeOut, tags=["knowledge"])
async def create_knowledge(data: KnowledgeCreate, ctx: MemberCtx) -> KnowledgeOut:
    return KnowledgeOut.model_validate(await knowledge_svc.create_knowledge(ctx, data))


@router.get("/knowledge", response_model=Page[KnowledgeOut], tags=["knowledge"])
async def list_knowledge(
    ctx: CtxDep,
    page: PageDep,
    project_id: uuid.UUID | None = None,
    category: KnowledgeCategory | None = None,
    verified: bool | None = None,
    tag: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    include_superseded: bool = False,
) -> Page[KnowledgeOut]:
    rows, total = await knowledge_svc.list_knowledge(
        ctx,
        project_id=project_id,
        category=category,
        verified=verified,
        tag=tag,
        q=q,
        include_superseded=include_superseded,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(items=[KnowledgeOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/knowledge/{knowledge_id}", response_model=KnowledgeOut, tags=["knowledge"])
async def get_knowledge(knowledge_id: uuid.UUID, ctx: CtxDep) -> KnowledgeOut:
    return KnowledgeOut.model_validate(await knowledge_svc.get_knowledge(ctx, knowledge_id))


@router.patch("/knowledge/{knowledge_id}", response_model=KnowledgeOut, tags=["knowledge"])
async def update_knowledge(
    knowledge_id: uuid.UUID, data: KnowledgeUpdate, ctx: MemberCtx, if_match: IfMatch = None
) -> KnowledgeOut:
    data.expected_version = expected_version(data.expected_version, if_match)
    return KnowledgeOut.model_validate(await knowledge_svc.update_knowledge(ctx, knowledge_id, data))


@router.post("/artifacts", status_code=201, response_model=ArtifactOut, tags=["artifacts"])
async def create_artifact(
    data: ArtifactCreate, ctx: MemberCtx, response: Response, idempotency_key: IdempotencyKey = None
) -> object:
    async def op() -> object:
        return ArtifactOut.model_validate(await artifact_svc.create_artifact(ctx, data)).model_dump(mode="json")

    body, status, _ = await run_idempotent(
        ctx, key=idempotency_key, operation="create_artifact", body=data.model_dump(mode="json"), fn=op
    )
    response.status_code = status
    return body


@router.get("/artifacts", response_model=Page[ArtifactOut], tags=["artifacts"])
async def list_artifacts(
    ctx: CtxDep,
    page: PageDep,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    type: ArtifactType | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[ArtifactOut]:
    rows, total = await artifact_svc.list_artifacts(
        ctx, project_id=project_id, task_id=task_id, type=type, q=q, limit=page.limit, offset=page.offset
    )
    return Page(items=[ArtifactOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/artifacts/{artifact_id}", response_model=ArtifactDetail, tags=["artifacts"])
async def get_artifact(artifact_id: uuid.UUID, ctx: CtxDep, response: Response) -> ArtifactDetail:
    artifact = await artifact_svc.get_artifact(ctx, artifact_id)
    versions = await artifact_svc.list_versions(ctx, artifact_id)
    set_etag(response, artifact.version)
    return ArtifactDetail.model_validate(
        {
            **ArtifactOut.model_validate(artifact).model_dump(),
            "versions": [ArtifactVersionOut.model_validate(v) for v in versions],
        }
    )


@router.patch("/artifacts/{artifact_id}", response_model=ArtifactOut, tags=["artifacts"])
async def update_artifact(
    artifact_id: uuid.UUID, data: ArtifactUpdate, ctx: MemberCtx, if_match: IfMatch = None
) -> ArtifactOut:
    data.expected_version = expected_version(data.expected_version, if_match)
    return ArtifactOut.model_validate(await artifact_svc.update_artifact(ctx, artifact_id, data))
