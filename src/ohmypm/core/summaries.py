"""Project summary: the compressed, current picture of a project.

A summary has six Markdown sections. It can be exchanged as a single Markdown
document whose ``## `` headings name the sections (English or Chinese).
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ohmypm.core.errors import ConflictError, NotFoundError, ValidationError
from ohmypm.core.projects import touch
from ohmypm.core.schemas import MAX_CONTENT_CHARS, SummaryOut, SummaryUpdate
from ohmypm.storage.models import SUMMARY_FIELDS, Project, ProjectSummary, SummaryRevision, utcnow

SECTION_TITLES: dict[str, str] = {
    "overview": "Overview",
    "architecture": "Architecture",
    "current_state": "Current State",
    "important_decisions": "Important Decisions",
    "known_issues": "Known Issues",
    "next_steps": "Next Steps",
}

_ALIASES: dict[str, tuple[str, ...]] = {
    "overview": (
        "overview",
        "project overview",
        "introduction",
        "goal",
        "goals",
        "about",
        "概述",
        "项目概述",
        "简介",
        "项目简介",
        "项目目标",
        "目标",
    ),
    "architecture": (
        "architecture",
        "technical architecture",
        "system architecture",
        "tech stack",
        "design",
        "架构",
        "技术架构",
        "系统架构",
        "主要技术架构",
        "技术栈",
    ),
    "current_state": (
        "current state",
        "current status",
        "status",
        "state",
        "progress",
        "completed work",
        "当前状态",
        "开发状态",
        "当前开发状态",
        "当前进展",
        "进展",
        "已完成",
        "已完成的重要工作",
    ),
    "important_decisions": (
        "important decisions",
        "decisions",
        "key decisions",
        "technical decisions",
        "重要决策",
        "技术决策",
        "关键决策",
        "重要技术方案",
        "已确定的重要技术方案",
    ),
    "known_issues": (
        "known issues",
        "open issues",
        "issues",
        "problems",
        "unresolved issues",
        "已知问题",
        "未解决问题",
        "尚未解决的问题",
        "问题",
    ),
    "next_steps": (
        "next steps",
        "next step",
        "next",
        "todo",
        "to do",
        "plan",
        "roadmap",
        "下一步",
        "下一步建议",
        "后续计划",
        "计划",
        "待办",
    ),
}
_LOOKUP = {alias: field for field, aliases in _ALIASES.items() for alias in aliases}
for _field in SUMMARY_FIELDS:
    _LOOKUP[_field.replace("_", " ")] = _field
    _LOOKUP[_field] = _field

_H2_RE = re.compile(r"^##\s+(.+?)\s*#*\s*$")
_H1_RE = re.compile(r"^#\s+")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def section_key(heading: str) -> str | None:
    """Map a heading such as ``"2. Known Issues"`` or ``"已知问题"`` to a field."""
    text = heading.strip().lower()
    text = re.sub(r"^[\d一二三四五六七八九十]+[.、)）:\s]+", "", text)
    text = text.strip(" :：.-—*_`")
    return _LOOKUP.get(text)


def parse_summary_markdown(markdown: str) -> dict[str, str]:
    """Split a summary document into sections.

    * ``## <section>`` starts a section (aliases accepted, see ``_ALIASES``);
    * a leading ``# Title`` line is ignored;
    * unknown ``##`` headings are kept verbatim inside the preceding section so
      nothing is silently dropped;
    * text before the first section heading belongs to ``overview``.
    """
    lines = markdown.replace("\r\n", "\n").split("\n")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    preamble: list[str] = []
    fence: str | None = None
    first_content_seen = False
    found_heading = False

    for line in lines:
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker[0] * 3
            elif marker.startswith(fence):
                fence = None
        if fence is None and not fence_match:
            if not first_content_seen and line.strip() and _H1_RE.match(line):
                first_content_seen = True
                continue
            heading = _H2_RE.match(line)
            if heading:
                key = section_key(heading.group(1))
                if key is not None:
                    found_heading = True
                    current = key
                    sections.setdefault(key, [])
                    first_content_seen = True
                    continue
        if line.strip():
            first_content_seen = True
        (sections[current] if current is not None else preamble).append(line)

    if not found_heading:
        raise ValidationError(
            "No summary sections found. Use '## <Section>' headings "
            f"({', '.join(SECTION_TITLES.values())}) or update one section explicitly.",
        )
    result = {key: "\n".join(value).strip() for key, value in sections.items()}
    pre = "\n".join(preamble).strip()
    if pre:
        result["overview"] = (pre + ("\n\n" + result["overview"] if result.get("overview") else "")).strip()
    return result


def render_summary_markdown(
    summary: SummaryOut, *, title: str | None = None, include_empty: bool = True
) -> str:
    parts: list[str] = []
    if title:
        parts.append(f"# {title}\n")
    for key in SUMMARY_FIELDS:
        value = getattr(summary, key) or ""
        if not value and not include_empty:
            continue
        parts.append(f"## {SECTION_TITLES[key]}\n")
        if value:
            parts.append(value.strip() + "\n")
    return "\n".join(parts).rstrip() + "\n"


def _row(session: Session, project_id: str) -> ProjectSummary | None:
    return session.get(ProjectSummary, project_id)


def to_out(project_id: str, row: ProjectSummary | None) -> SummaryOut:
    if row is None:
        return SummaryOut(project_id=project_id)
    values = {key: getattr(row, key) or "" for key in SUMMARY_FIELDS}
    return SummaryOut(
        project_id=project_id,
        revision=row.revision,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
        is_empty=not any(v.strip() for v in values.values()),
        **values,
    )


def get_summary(session: Session, project: Project) -> SummaryOut:
    return to_out(project.id, _row(session, project.id))


def set_summary(
    session: Session,
    project: Project,
    update: SummaryUpdate,
    *,
    replace: bool = False,
    changed_by: str | None = None,
    expected_revision: int | None = None,
) -> tuple[SummaryOut, bool]:
    """Update summary sections. Returns ``(summary, changed)``.

    Only provided sections change unless ``replace`` is set, in which case
    missing sections are cleared. The previous version is kept in
    ``summary_revisions``.
    """
    provided = update.provided()
    for key, value in provided.items():
        if len(value) > MAX_CONTENT_CHARS:
            raise ValidationError(f"Summary section '{key}' is too long")
    row = _row(session, project.id)
    current = {key: (getattr(row, key) or "") if row else "" for key in SUMMARY_FIELDS}
    target = {key: "" for key in SUMMARY_FIELDS} if replace else dict(current)
    target.update({key: value.strip() for key, value in provided.items()})

    if expected_revision is not None and (row.revision if row else 0) != expected_revision:
        raise ConflictError(
            "The summary was modified elsewhere",
            details={"current_revision": row.revision if row else 0},
        )
    if target == current and row is not None:
        return to_out(project.id, row), False

    now = utcnow()
    if row is None:
        row = ProjectSummary(
            project_id=project.id, revision=1, created_at=now, updated_at=now, updated_by=changed_by
        )
        for key, value in target.items():
            setattr(row, key, value)
        session.add(row)
    else:
        session.add(
            SummaryRevision(
                project_id=project.id,
                revision=row.revision,
                data={**current, "updated_by": row.updated_by, "updated_at": row.updated_at.isoformat()},
                changed_by=changed_by,
                created_at=now,
            )
        )
        for key, value in target.items():
            setattr(row, key, value)
        row.revision += 1
        row.updated_at = now
        row.updated_by = changed_by
    touch(project)
    session.flush()
    return to_out(project.id, row), True


def list_summary_revisions(session: Session, project: Project) -> list[SummaryRevision]:
    return list(
        session.scalars(
            select(SummaryRevision)
            .where(SummaryRevision.project_id == project.id)
            .order_by(SummaryRevision.revision)
        ).all()
    )


def restore_summary_revision(
    session: Session, project: Project, revision: int, *, changed_by: str | None = None
) -> SummaryOut:
    rev = session.scalars(
        select(SummaryRevision).where(
            SummaryRevision.project_id == project.id, SummaryRevision.revision == revision
        )
    ).first()
    if rev is None:
        raise NotFoundError(f"Summary revision {revision} not found")
    data = {key: rev.data.get(key, "") for key in SUMMARY_FIELDS}
    summary, _ = set_summary(session, project, SummaryUpdate(**data), replace=True, changed_by=changed_by)
    return summary
