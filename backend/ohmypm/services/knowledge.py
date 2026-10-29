"""Long-lived project knowledge."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select

from ohmypm.errors import ValidationFailed
from ohmypm.models import Project, ProjectKnowledge, Task
from ohmypm.schemas import KnowledgeCreate, KnowledgeUpdate
from ohmypm.services.common import Ctx, check_version, get_or_404, like_pattern, paginate
from ohmypm_common.enums import KnowledgeCategory


async def create_knowledge(ctx: Ctx, data: KnowledgeCreate) -> ProjectKnowledge:
    if data.project_id is not None:
        await get_or_404(ctx.session, Project, data.project_id, "project")
    project_id = data.project_id
    if data.source_task_id is not None:
        task = await get_or_404(ctx.session, Task, data.source_task_id, "task")
        project_id = project_id or task.project_id
    item = ProjectKnowledge(
        project_id=project_id,
        title=data.title,
        category=data.category.value,
        content=data.content,
        source_task_id=data.source_task_id,
        verified=data.verified,
        tags=list(data.tags),
        created_by=ctx.actor,
        metadata_=data.metadata,
    )
    ctx.session.add(item)
    await ctx.session.flush()
    return item


async def get_knowledge(ctx: Ctx, knowledge_id: uuid.UUID) -> ProjectKnowledge:
    return await get_or_404(ctx.session, ProjectKnowledge, knowledge_id, "knowledge")


async def list_knowledge(
    ctx: Ctx,
    *,
    project_id: uuid.UUID | None = None,
    category: KnowledgeCategory | None = None,
    verified: bool | None = None,
    tag: str | None = None,
    q: str | None = None,
    include_superseded: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[ProjectKnowledge], int]:
    stmt = select(ProjectKnowledge)
    if project_id is not None:
        # Global knowledge (project_id NULL) applies to every project.
        stmt = stmt.where(or_(ProjectKnowledge.project_id == project_id, ProjectKnowledge.project_id.is_(None)))
    if category is not None:
        stmt = stmt.where(ProjectKnowledge.category == category.value)
    if verified is not None:
        stmt = stmt.where(ProjectKnowledge.verified.is_(verified))
    if tag:
        stmt = stmt.where(ProjectKnowledge.tags.any(tag))  # type: ignore[arg-type]
    if not include_superseded:
        stmt = stmt.where(ProjectKnowledge.superseded_by.is_(None))
    if q:
        tsq = func.websearch_to_tsquery("simple", q)
        pattern = like_pattern(q)
        stmt = stmt.where(
            or_(
                ProjectKnowledge.search_vector.op("@@")(tsq),
                ProjectKnowledge.title.ilike(pattern),
                ProjectKnowledge.content.ilike(pattern),
            )
        )
        stmt = stmt.order_by(
            func.ts_rank(ProjectKnowledge.search_vector, tsq).desc(), ProjectKnowledge.updated_at.desc()
        )
    else:
        stmt = stmt.order_by(ProjectKnowledge.verified.desc(), ProjectKnowledge.updated_at.desc(), ProjectKnowledge.id)
    return await paginate(ctx.session, stmt, limit, offset)


async def update_knowledge(ctx: Ctx, knowledge_id: uuid.UUID, data: KnowledgeUpdate) -> ProjectKnowledge:
    item = await get_knowledge(ctx, knowledge_id)
    check_version(item, data.expected_version)
    if data.title is not None:
        item.title = data.title
    if data.content is not None:
        history = list(item.metadata_.get("content_history", []))
        history.append({"version": item.version, "content": item.content})
        item.metadata_ = {**item.metadata_, "content_history": history[-10:]}
        item.content = data.content
    if data.category is not None:
        item.category = data.category.value
    if data.verified is not None:
        item.verified = data.verified
    if data.tags is not None:
        item.tags = list(data.tags)
    if "superseded_by" in data.model_fields_set:
        if data.superseded_by == item.id:
            raise ValidationFailed("knowledge cannot supersede itself")
        if data.superseded_by is not None:
            await get_knowledge(ctx, data.superseded_by)
        item.superseded_by = data.superseded_by
    if data.metadata is not None:
        item.metadata_ = {**item.metadata_, **data.metadata}
    await ctx.session.flush()
    return item
