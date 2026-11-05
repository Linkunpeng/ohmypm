"""Entries: the structured development records of a project."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.orm import Session

from ohmypm.core.errors import AmbiguousReferenceError, ConflictError, NotFoundError, ValidationError
from ohmypm.core.projects import touch
from ohmypm.core.schemas import (
    BUILTIN_ENTRY_TYPES,
    EntryCreate,
    EntryOut,
    EntryRevisionOut,
    EntryUpdate,
)
from ohmypm.core.text import asset_refs, excerpt
from ohmypm.storage.models import Asset, Entry, EntryRevision, Project, utcnow

_SEQ_RE = re.compile(r"^#?(\d+)$")
MIN_ID_PREFIX = 6
MAX_LIST_LIMIT = 500


def like_escape(term: str) -> str:
    """Escape ``term`` for a ``LIKE ... ESCAPE '\\'`` pattern."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def to_out(entry: Entry, *, include_content: bool = True, excerpt_chars: int = 240) -> EntryOut:
    return EntryOut(
        id=entry.id,
        project_id=entry.project_id,
        sequence=entry.sequence,
        type=entry.type,
        title=entry.title,
        content=entry.content if include_content else None,
        excerpt=excerpt(entry.content, excerpt_chars),
        status=entry.status,
        author=entry.author,
        source=entry.source,
        revision=entry.revision,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        metadata=dict(entry.meta or {}),
        asset_ids=sorted(asset_refs(entry.content)),
    )


def revision_to_out(rev: EntryRevision) -> EntryRevisionOut:
    return EntryRevisionOut.model_validate(rev)


def check_type(entry_type: str, allowed: Iterable[str] | None) -> None:
    allowed_set = set(allowed) if allowed is not None else set(BUILTIN_ENTRY_TYPES)
    if entry_type not in allowed_set:
        raise ValidationError(
            f"Unknown entry type '{entry_type}'",
            details={"allowed": sorted(allowed_set)},
        )


def _link_assets(session: Session, entry: Entry) -> None:
    """Attach not-yet-linked assets referenced by the entry's Markdown."""
    refs = asset_refs(entry.content)
    if not refs:
        return
    session.execute(
        update(Asset)
        .where(Asset.id.in_(refs), Asset.project_id == entry.project_id, Asset.entry_id.is_(None))
        .values(entry_id=entry.id)
        .execution_options(synchronize_session=False)
    )


def _allocate_sequence(session: Session, project: Project) -> int:
    # Atomic within the (BEGIN IMMEDIATE) write transaction; never reuses
    # numbers of deleted entries, so "#12" stays a stable reference.
    new_next = session.execute(
        update(Project)
        .where(Project.id == project.id)
        .values(next_sequence=Project.next_sequence + 1)
        .returning(Project.next_sequence)
        .execution_options(synchronize_session=False)
    ).scalar_one()
    return int(new_next) - 1


def add_entry(
    session: Session,
    project: Project,
    data: EntryCreate,
    *,
    allowed_types: Iterable[str] | None = None,
) -> Entry:
    check_type(data.type, allowed_types)
    status = data.status
    if status is None and data.type == "issue":
        status = "open"
    now = utcnow()
    entry = Entry(
        project_id=project.id,
        sequence=_allocate_sequence(session, project),
        type=data.type,
        title=data.title,
        content=data.content,
        status=status,
        author=data.author,
        source=data.source,
        revision=1,
        created_at=now,
        updated_at=now,
        meta=dict(data.metadata),
    )
    session.add(entry)
    touch(project)
    session.flush()
    _link_assets(session, entry)
    return entry


def get_entry(session: Session, ref: str | int, *, project: Project | None = None) -> Entry:
    """Find an entry by ``#sequence`` / sequence (needs ``project``), id or id prefix."""
    text = str(ref).strip()
    match = _SEQ_RE.match(text)
    # "#12" is always a sequence number. A bare number is a sequence number
    # first; long all-digit strings may also be an id prefix ("12345678...").
    if match and (text.startswith("#") or project is not None or len(text) < MIN_ID_PREFIX):
        if project is None:
            raise ValidationError("A project is required to look entries up by sequence number")
        entry = session.scalars(
            select(Entry).where(Entry.project_id == project.id, Entry.sequence == int(match.group(1)))
        ).first()
        if entry is not None:
            return entry
        if text.startswith("#") or len(text) < MIN_ID_PREFIX:
            raise NotFoundError(f"Entry #{match.group(1)} not found in project '{project.name}'")

    entry = session.get(Entry, text)
    if entry is None and len(text) >= MIN_ID_PREFIX:
        stmt = select(Entry).where(Entry.id.startswith(text.lower()))
        if project is not None:
            stmt = stmt.where(Entry.project_id == project.id)
        found = session.scalars(stmt.limit(2)).all()
        if len(found) > 1:
            raise AmbiguousReferenceError(f"Entry reference '{text}' is ambiguous")
        entry = found[0] if found else None
    if entry is None or (project is not None and entry.project_id != project.id):
        raise NotFoundError(f"Entry not found: {text}")
    return entry


def _snapshot(session: Session, entry: Entry, reason: str, changed_by: str | None) -> None:
    session.add(
        EntryRevision(
            entry_id=entry.id,
            project_id=entry.project_id,
            sequence=entry.sequence,
            revision=entry.revision,
            type=entry.type,
            title=entry.title,
            content=entry.content,
            status=entry.status,
            meta=dict(entry.meta or {}),
            reason=reason,
            changed_by=changed_by,
            created_at=utcnow(),
        )
    )


def update_entry(
    session: Session,
    entry: Entry,
    changes: EntryUpdate,
    *,
    changed_by: str | None = None,
    allowed_types: Iterable[str] | None = None,
    expected_revision: int | None = None,
) -> tuple[Entry, bool]:
    """Apply a partial update. Returns ``(entry, changed)``.

    The previous version is kept in ``entry_revisions``. ``expected_revision``
    enables optimistic concurrency (used by the Web editor).
    """
    if expected_revision is not None and expected_revision != entry.revision:
        raise ConflictError(
            f"Entry #{entry.sequence} was modified elsewhere (revision {entry.revision}, "
            f"expected {expected_revision})",
            details={"current_revision": entry.revision},
        )
    new_values: dict[str, object] = {}
    if changes.type is not None and changes.type != entry.type:
        check_type(changes.type, allowed_types)
        new_values["type"] = changes.type
    if changes.title is not None and changes.title != entry.title:
        new_values["title"] = changes.title
    if changes.content is not None and changes.content != entry.content:
        new_values["content"] = changes.content
    if changes.clear_status and entry.status is not None:
        new_values["status"] = None
    elif changes.status is not None and changes.status != entry.status:
        new_values["status"] = changes.status
    if changes.metadata is not None and changes.metadata != (entry.meta or {}):
        new_values["meta"] = dict(changes.metadata)
    if not new_values:
        return entry, False

    _snapshot(session, entry, "edit", changed_by)
    for key, value in new_values.items():
        setattr(entry, key, value)
    entry.revision += 1
    entry.updated_at = utcnow()
    touch(entry.project)
    session.flush()
    if "content" in new_values:
        _link_assets(session, entry)
    return entry, True


def delete_entry(session: Session, entry: Entry, *, changed_by: str | None = None) -> None:
    """Delete an entry. Its last version stays recoverable in ``entry_revisions``."""
    _snapshot(session, entry, "delete", changed_by)
    session.delete(entry)
    session.flush()


def restore_revision(
    session: Session, entry: Entry, revision: int, *, changed_by: str | None = None
) -> Entry:
    rev = session.scalars(
        select(EntryRevision).where(EntryRevision.entry_id == entry.id, EntryRevision.revision == revision)
    ).first()
    if rev is None:
        raise NotFoundError(f"Revision {revision} of entry #{entry.sequence} not found")
    updated, _ = update_entry(
        session,
        entry,
        EntryUpdate(
            type=rev.type,
            title=rev.title,
            content=rev.content,
            status=rev.status,  # type: ignore[arg-type]
            clear_status=rev.status is None,
            metadata=dict(rev.meta or {}),
        ),
        changed_by=changed_by,
        allowed_types=None if rev.type in BUILTIN_ENTRY_TYPES else [rev.type],
    )
    return updated


def list_revisions(session: Session, entry_id: str) -> list[EntryRevision]:
    return list(
        session.scalars(
            select(EntryRevision).where(EntryRevision.entry_id == entry_id).order_by(EntryRevision.revision)
        ).all()
    )


def list_deleted(session: Session, project: Project) -> list[EntryRevision]:
    return list(
        session.scalars(
            select(EntryRevision)
            .where(EntryRevision.project_id == project.id, EntryRevision.reason == "delete")
            .order_by(EntryRevision.created_at.desc())
        ).all()
    )


def _filtered(
    stmt: Select,
    *,
    project_ids: Sequence[str] | None,
    types: Sequence[str] | None,
    statuses: Sequence[str] | None,
    since: datetime | None,
    until: datetime | None,
    query: str | None,
    author: str | None,
) -> Select:
    if project_ids is not None:
        stmt = stmt.where(Entry.project_id.in_(project_ids))
    if types:
        stmt = stmt.where(Entry.type.in_(types))
    if statuses:
        clauses = [Entry.status.in_([s for s in statuses if s != "none"])]
        if "none" in statuses:
            clauses.append(Entry.status.is_(None))
        stmt = stmt.where(or_(*clauses))
    if since is not None:
        stmt = stmt.where(Entry.created_at >= since)
    if until is not None:
        stmt = stmt.where(Entry.created_at <= until)
    if author:
        stmt = stmt.where(Entry.author == author)
    if query:
        for term in query.split():
            like = f"%{like_escape(term)}%"
            stmt = stmt.where(or_(Entry.title.like(like, escape="\\"), Entry.content.like(like, escape="\\")))
    return stmt


def list_entries(
    session: Session,
    *,
    project_ids: Sequence[str] | None = None,
    types: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    query: str | None = None,
    author: str | None = None,
    order: str = "asc",
    sort: str = "sequence",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Entry], int]:
    if limit < 1 or limit > MAX_LIST_LIMIT:
        raise ValidationError(f"limit must be between 1 and {MAX_LIST_LIMIT}")
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    if order not in ("asc", "desc"):
        raise ValidationError("order must be 'asc' or 'desc'")
    columns = {"sequence": Entry.sequence, "created_at": Entry.created_at, "updated_at": Entry.updated_at}
    if sort not in columns:
        raise ValidationError(f"sort must be one of {sorted(columns)}")

    filters = dict(
        project_ids=project_ids,
        types=types,
        statuses=statuses,
        since=since,
        until=until,
        query=query,
        author=author,
    )
    total = session.scalar(_filtered(select(func.count(Entry.id)), **filters)) or 0
    column = columns[sort]
    ordering = [column.asc() if order == "asc" else column.desc()]
    # Tie-breakers keep the order deterministic across projects.
    ordering.append(Entry.created_at.asc() if order == "asc" else Entry.created_at.desc())
    ordering.append(Entry.id)
    stmt = _filtered(select(Entry), **filters).order_by(*ordering).limit(limit).offset(offset)
    return list(session.scalars(stmt).all()), int(total)


def type_counts(session: Session, project_id: str | None = None) -> dict[str, int]:
    stmt = select(Entry.type, func.count(Entry.id)).group_by(Entry.type)
    if project_id:
        stmt = stmt.where(Entry.project_id == project_id)
    return {t: int(n) for t, n in session.execute(stmt).all()}
