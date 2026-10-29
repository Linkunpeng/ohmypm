"""Cross-entity search: PostgreSQL FTS (``simple`` config) plus trigram ILIKE fallback (CJK-friendly)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, literal, or_, select

from ohmypm.models import Artifact, Decision, Project, ProjectKnowledge, Task, Workspace
from ohmypm.schemas import SearchHit
from ohmypm.services.common import Ctx, like_pattern

KINDS = ("project", "workspace", "task", "decision", "artifact", "knowledge")


def _snippet(text: str | None, q: str, width: int = 160) -> str:
    if not text:
        return ""
    idx = text.lower().find(q.lower())
    if idx < 0:
        return text[:width].replace("\n", " ")
    start = max(0, idx - width // 3)
    return ("…" if start else "") + text[start : start + width].replace("\n", " ")


async def search(ctx: Ctx, q: str, *, kinds: Sequence[str] | None = None, limit: int = 30) -> list[SearchHit]:
    q = q.strip()
    if not q:
        return []
    wanted = set(kinds or KINDS)
    tsq = func.websearch_to_tsquery("simple", q)
    pattern = like_pattern(q)
    per_kind = max(5, min(limit, 50))
    hits: list[SearchHit] = []
    s = ctx.session

    async def run(stmt: Any) -> Sequence[Any]:
        return (await s.execute(stmt.limit(per_kind))).all()

    def score(vector: Any) -> Any:
        # Exact-substring matches get a floor so ILIKE-only hits (e.g. CJK) still rank.
        return func.ts_rank(vector, tsq) + literal(0.05)

    if "project" in wanted:
        for p, sc in await run(
            select(Project, score(Project.search_vector))
            .where(
                or_(
                    Project.search_vector.op("@@")(tsq), Project.name.ilike(pattern), Project.description.ilike(pattern)
                )
            )
            .order_by(score(Project.search_vector).desc())
        ):
            hits.append(
                SearchHit(
                    kind="project",
                    id=p.id,
                    title=p.name,
                    snippet=_snippet(p.description, q),
                    score=float(sc) + 0.1,
                    project_id=p.id,
                )
            )
    if "workspace" in wanted:
        for w in (
            await s.execute(
                select(Workspace)
                .where(or_(Workspace.root_path.ilike(pattern), Workspace.display_name.ilike(pattern)))
                .limit(per_kind)
            )
        ).scalars():
            hits.append(
                SearchHit(
                    kind="workspace",
                    id=w.id,
                    title=w.display_name,
                    snippet=f"{w.host_id}:{w.root_path}",
                    score=0.1,
                    project_id=w.project_id,
                )
            )
    if "task" in wanted:
        for t, sc in await run(
            select(Task, score(Task.search_vector))
            .where(
                or_(
                    Task.search_vector.op("@@")(tsq),
                    Task.title.ilike(pattern),
                    Task.raw_request.ilike(pattern),
                    Task.description.ilike(pattern),
                )
            )
            .order_by(score(Task.search_vector).desc())
        ):
            hits.append(
                SearchHit(
                    kind="task",
                    id=t.id,
                    title=f"T-{t.number} {t.title}",
                    snippet=_snippet(t.raw_request, q),
                    score=float(sc),
                    project_id=t.project_id,
                    task_id=t.id,
                    status=t.status,
                )
            )
    if "decision" in wanted:
        for d, sc in await run(
            select(Decision, score(Decision.search_vector))
            .where(
                or_(
                    Decision.search_vector.op("@@")(tsq),
                    Decision.question.ilike(pattern),
                    Decision.context.ilike(pattern),
                )
            )
            .order_by(score(Decision.search_vector).desc())
        ):
            hits.append(
                SearchHit(
                    kind="decision",
                    id=d.id,
                    title=d.question[:200],
                    snippet=_snippet(d.context, q),
                    score=float(sc),
                    project_id=d.project_id,
                    task_id=d.task_id,
                    status=d.status,
                )
            )
    if "artifact" in wanted:
        for a, sc in await run(
            select(Artifact, score(Artifact.search_vector))
            .where(
                or_(
                    Artifact.search_vector.op("@@")(tsq),
                    Artifact.name.ilike(pattern),
                    Artifact.description.ilike(pattern),
                    Artifact.storage_uri.ilike(pattern),
                )
            )
            .order_by(score(Artifact.search_vector).desc())
        ):
            hits.append(
                SearchHit(
                    kind="artifact",
                    id=a.id,
                    title=a.name,
                    snippet=_snippet(a.description, q) or a.storage_uri,
                    score=float(sc),
                    project_id=a.project_id,
                    task_id=a.task_id,
                    status=a.type,
                )
            )
    if "knowledge" in wanted:
        for k, sc in await run(
            select(ProjectKnowledge, score(ProjectKnowledge.search_vector))
            .where(
                or_(
                    ProjectKnowledge.search_vector.op("@@")(tsq),
                    ProjectKnowledge.title.ilike(pattern),
                    ProjectKnowledge.content.ilike(pattern),
                )
            )
            .order_by(score(ProjectKnowledge.search_vector).desc())
        ):
            hits.append(
                SearchHit(
                    kind="knowledge",
                    id=k.id,
                    title=k.title,
                    snippet=_snippet(k.content, q),
                    score=float(sc) + (0.02 if k.verified else 0),
                    project_id=k.project_id,
                    task_id=k.source_task_id,
                    status="superseded" if k.superseded_by else k.category,
                )
            )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]
