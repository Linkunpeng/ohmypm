"""Links between entries of one project.

Explicit links are set by users and agents: ``relates``, ``fixes`` (resolves
an open issue) and ``supersedes`` (marks the target obsolete). ``mentions``
links are derived from ``#N`` references in the source's Markdown body and
are recomputed whenever the body changes. Links are not revisioned; deleting
either entry removes them (foreign keys with ON DELETE CASCADE).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, aliased

from ohmypm.core import entries as entries_core
from ohmypm.core.errors import ValidationError
from ohmypm.core.schemas import LINK_KINDS, EntryUpdate, LinkOut
from ohmypm.core.text import entry_mentions
from ohmypm.storage.models import Entry, EntryLink

# Status a link kind sets on its target, and the target statuses it applies to.
_TARGET_STATUS = {
    "fixes": ("resolved", {"open"}),
    "supersedes": ("obsolete", {None, "open", "resolved"}),
}


def _exists(session: Session, source: Entry, target: Entry, kind: str) -> bool:
    stmt = select(EntryLink.id).where(
        EntryLink.source_id == source.id, EntryLink.target_id == target.id, EntryLink.kind == kind
    )
    return session.scalars(stmt).first() is not None


def add_link(
    session: Session,
    source: Entry,
    target_ref: str,
    kind: str,
    *,
    changed_by: str | None = None,
) -> bool:
    """Link ``source`` to the entry ``target_ref`` of the same project. Returns whether it is new.

    ``fixes`` resolves an open target issue; ``supersedes`` marks the target
    obsolete. Both status changes are normal edits with a revision.
    """
    if kind not in LINK_KINDS:
        raise ValidationError(f"Unknown link kind '{kind}'", details={"allowed": list(LINK_KINDS)})
    target = entries_core.get_entry(session, target_ref, project=source.project)
    if target.id == source.id:
        raise ValidationError(f"Entry #{source.sequence} cannot link to itself")
    if kind == "fixes" and target.type != "issue":
        raise ValidationError(f"'fixes' needs an issue; #{target.sequence} is a {target.type}")
    if _exists(session, source, target, kind):
        return False
    session.add(EntryLink(project_id=source.project_id, source_id=source.id, target_id=target.id, kind=kind))
    if kind in _TARGET_STATUS:
        status, applies_to = _TARGET_STATUS[kind]
        if target.status in applies_to:
            entries_core.update_entry(
                session,
                target,
                EntryUpdate(status=status),  # type: ignore[arg-type]
                changed_by=changed_by,
            )
    session.flush()
    return True


def remove_links(session: Session, source: Entry, target_ref: str) -> int:
    """Remove the explicit links from ``source`` to ``target_ref``. Statuses are left unchanged."""
    target = entries_core.get_entry(session, target_ref, project=source.project)
    result = session.execute(
        delete(EntryLink).where(
            EntryLink.source_id == source.id,
            EntryLink.target_id == target.id,
            EntryLink.kind.in_(LINK_KINDS),
        )
    )
    session.flush()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def sync_mentions(session: Session, entry: Entry) -> None:
    """Recompute the ``mentions`` links of ``entry`` from its body."""
    session.execute(delete(EntryLink).where(EntryLink.source_id == entry.id, EntryLink.kind == "mentions"))
    numbers = entry_mentions(entry.content) - {entry.sequence}
    if numbers:
        targets = session.scalars(
            select(Entry.id).where(Entry.project_id == entry.project_id, Entry.sequence.in_(numbers))
        ).all()
        session.add_all(
            EntryLink(project_id=entry.project_id, source_id=entry.id, target_id=t, kind="mentions")
            for t in targets
        )
    session.flush()


def _link_out(kind: str, entry: Entry) -> LinkOut:
    return LinkOut(
        kind=kind,
        entry_id=entry.id,
        sequence=entry.sequence,
        type=entry.type,
        title=entry.title,
        status=entry.status,
    )


def _collect(rows: Iterable[tuple[str, str, Entry]]) -> dict[str, list[LinkOut]]:
    """Group ``(owner_id, kind, other)`` rows; a mention is dropped when an explicit link exists."""
    grouped: dict[str, dict[str, list[str]]] = {}
    others: dict[str, Entry] = {}
    for owner_id, kind, other in rows:
        grouped.setdefault(owner_id, {}).setdefault(other.id, []).append(kind)
        others[other.id] = other
    result: dict[str, list[LinkOut]] = {}
    for owner_id, by_other in grouped.items():
        items = []
        for other_id, kinds in by_other.items():
            explicit = [k for k in LINK_KINDS if k in kinds]
            for kind in explicit or ["mentions"]:
                items.append(_link_out(kind, others[other_id]))
        result[owner_id] = sorted(items, key=lambda link: (link.sequence, link.kind))
    return result


Links = dict[str, list[LinkOut]]


def _query(
    session: Session, *, entry_ids: Sequence[str] | None, project_id: str | None
) -> tuple[Links, Links]:
    other = aliased(Entry)
    outgoing = select(EntryLink.source_id, EntryLink.kind, other).join(other, other.id == EntryLink.target_id)
    incoming = select(EntryLink.target_id, EntryLink.kind, other).join(other, other.id == EntryLink.source_id)
    if entry_ids is not None:
        outgoing = outgoing.where(EntryLink.source_id.in_(entry_ids))
        incoming = incoming.where(EntryLink.target_id.in_(entry_ids))
    if project_id is not None:
        outgoing = outgoing.where(EntryLink.project_id == project_id)
        incoming = incoming.where(EntryLink.project_id == project_id)
    return _collect(session.execute(outgoing).all()), _collect(session.execute(incoming).all())  # type: ignore[arg-type]


def links_for(session: Session, entry_ids: Sequence[str]) -> tuple[Links, Links]:
    """Outgoing links and backlinks of the given entries, keyed by entry id."""
    if not entry_ids:
        return {}, {}
    return _query(session, entry_ids=entry_ids, project_id=None)


def project_links(session: Session, project_id: str) -> tuple[Links, Links]:
    """Outgoing links and backlinks of every entry of a project."""
    return _query(session, entry_ids=None, project_id=project_id)
