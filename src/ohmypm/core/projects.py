"""Project registry.

Projects are identified by their canonical root directory, recorded only in
the ohmypm database. Registering never touches the project directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ohmypm.config import Settings
from ohmypm.core.errors import (
    AmbiguousReferenceError,
    ConflictError,
    NotFoundError,
    ProjectNotRegisteredError,
    ValidationError,
)
from ohmypm.core.schemas import ProjectOut
from ohmypm.storage.files import after_commit, remove_tree
from ohmypm.storage.models import Entry, Project, utcnow

MIN_ID_PREFIX = 4


def canonical_path(path: str | os.PathLike[str]) -> str:
    """Absolute, symlink-free, normalised form of ``path`` (need not exist)."""
    return os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _ancestors(path: str) -> list[str]:
    """``path`` and all its parent directories, longest first."""
    result = []
    current = Path(path)
    while True:
        result.append(str(current))
        if current.parent == current:
            break
        current = current.parent
    return result


def to_out(project: Project, entry_count: int | None = None) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        root_path=project.root_path,
        description=project.description,
        archived=project.archived_at is not None,
        archived_at=project.archived_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
        last_activity_at=project.last_activity_at,
        metadata=dict(project.meta or {}),
        root_exists=os.path.isdir(project.root_path),
        entry_count=entry_count,
    )


def _validate_root(path: str | os.PathLike[str]) -> str:
    root = canonical_path(path)
    if not os.path.isdir(root):
        raise ValidationError(f"Not a directory: {root}", details={"path": root})
    if root == os.path.sep:
        raise ValidationError("Refusing to register the filesystem root as a project")
    return root


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValidationError("Project name must not be empty")
    if len(name) > 200:
        raise ValidationError("Project name is longer than 200 characters")
    return name


def find_by_root(session: Session, root: str) -> Project | None:
    return session.scalars(
        select(Project).where(Project.root_path == root, Project.archived_at.is_(None))
    ).first()


def find_project_for_path(session: Session, path: str | os.PathLike[str]) -> Project | None:
    """Return the active project whose root contains ``path`` (longest match).

    Paths are compared component-wise, so ``/a/robot`` never matches a
    project registered at ``/a/rob``. Both the symlink-resolved and the literal
    absolute path are considered.
    """
    raw = os.path.normpath(os.path.abspath(os.path.expanduser(os.fspath(path))))
    candidates = dict.fromkeys(_ancestors(canonical_path(raw)) + _ancestors(raw))
    rows = session.scalars(
        select(Project).where(Project.root_path.in_(list(candidates)), Project.archived_at.is_(None))
    ).all()
    if not rows:
        return None
    return max(rows, key=lambda p: len(Path(p.root_path).parts))


def require_project_for_path(session: Session, path: str | os.PathLike[str]) -> Project:
    project = find_project_for_path(session, path)
    if project is None:
        resolved = canonical_path(path)
        raise ProjectNotRegisteredError(
            f"No registered ohmypm project contains {resolved}",
            details={"path": resolved, "hint": "Run `ohmypm register` in the project root to register it."},
        )
    return project


def get_project(session: Session, ref: str, *, include_archived: bool = True) -> Project:
    """Look a project up by id, unique id prefix or exact name."""
    ref = ref.strip()
    if not ref:
        raise ValidationError("Empty project reference")
    project = session.get(Project, ref)
    if project is not None and (include_archived or project.archived_at is None):
        return project

    base = select(Project)
    if not include_archived:
        base = base.where(Project.archived_at.is_(None))

    matches: list[Project] = []
    if len(ref) >= MIN_ID_PREFIX:
        matches = list(session.scalars(base.where(Project.id.startswith(ref.lower()))).all())
    if not matches:
        matches = list(session.scalars(base.where(func.lower(Project.name) == ref.lower())).all())
        if len(matches) > 1:
            active = [p for p in matches if p.archived_at is None]
            matches = active or matches
    if not matches:
        raise NotFoundError(f"Project not found: {ref}", details={"project": ref})
    if len(matches) > 1:
        raise AmbiguousReferenceError(
            f"Project reference '{ref}' is ambiguous",
            details={"candidates": [{"id": p.id, "name": p.name, "root_path": p.root_path} for p in matches]},
        )
    return matches[0]


def resolve_project(
    session: Session,
    *,
    project: str | None = None,
    path: str | os.PathLike[str] | None = None,
) -> Project:
    """Explicit reference wins; otherwise detect from ``path`` (default: CWD)."""
    if project:
        return get_project(session, project)
    return require_project_for_path(session, path if path is not None else os.getcwd())


def register_project(
    session: Session,
    path: str | os.PathLike[str],
    *,
    name: str | None = None,
    description: str | None = None,
) -> tuple[Project, str]:
    """Register ``path``. Returns ``(project, outcome)``.

    ``outcome`` is ``"created"``, ``"existing"`` or ``"reactivated"`` (an
    unregistered project with the same root is restored with its history).
    """
    root = _validate_root(path)
    existing = find_by_root(session, root)
    if existing is not None:
        return existing, "existing"

    archived = session.scalars(
        select(Project)
        .where(Project.root_path == root, Project.archived_at.is_not(None))
        .order_by(Project.archived_at.desc())
    ).first()
    now = utcnow()
    if archived is not None:
        archived.archived_at = None
        archived.updated_at = now
        if name:
            archived.name = _clean_name(name)
        if description is not None:
            archived.description = description
        session.flush()
        return archived, "reactivated"

    project = Project(
        name=_clean_name(name or os.path.basename(root) or root),
        root_path=root,
        description=description,
        created_at=now,
        updated_at=now,
        meta={},
    )
    session.add(project)
    session.flush()
    return project, "created"


def list_projects(session: Session, *, include_archived: bool = False) -> list[tuple[Project, int]]:
    counts = select(Entry.project_id, func.count(Entry.id).label("n")).group_by(Entry.project_id).subquery()
    stmt = select(Project, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.project_id == Project.id)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    stmt = stmt.order_by(
        Project.archived_at.is_not(None),
        func.coalesce(Project.last_activity_at, Project.created_at).desc(),
    )
    return [(p, int(n)) for p, n in session.execute(stmt).all()]


def entry_count(session: Session, project: Project) -> int:
    return int(session.scalar(select(func.count(Entry.id)).where(Entry.project_id == project.id)) or 0)


def update_project(
    session: Session,
    project: Project,
    *,
    name: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Project:
    if name is not None:
        project.name = _clean_name(name)
    if description is not None:
        project.description = description.strip() or None
    if metadata is not None:
        project.meta = metadata
    project.updated_at = utcnow()
    session.flush()
    return project


def relink_project(session: Session, project: Project, new_path: str | os.PathLike[str]) -> Project:
    """Point ``project`` at a new root directory (e.g. after moving the repo)."""
    root = _validate_root(new_path)
    other = find_by_root(session, root)
    if other is not None and other.id != project.id:
        raise ConflictError(
            f"{root} is already registered as project '{other.name}'",
            details={"project_id": other.id, "path": root},
        )
    previous = project.root_path
    project.root_path = root
    if project.archived_at is not None:
        project.archived_at = None
    meta = dict(project.meta or {})
    history = list(meta.get("previous_roots", []))
    if previous != root and previous not in history:
        history.append(previous)
    meta["previous_roots"] = history[-10:]
    project.meta = meta
    project.updated_at = utcnow()
    session.flush()
    return project


def unregister_project(session: Session, project: Project) -> Project:
    """Stop associating the directory with the project; all records are kept."""
    if project.archived_at is None:
        project.archived_at = utcnow()
        project.updated_at = project.archived_at
        session.flush()
    return project


def purge_project(session: Session, settings: Settings, project: Project) -> None:
    """Permanently delete a project, its records and its asset files."""
    project_assets = settings.assets_dir / project.id
    session.delete(project)
    session.flush()
    if project_assets.is_dir() and project_assets.resolve().parent == settings.assets_dir.resolve():
        after_commit(session, lambda: remove_tree(project_assets))


def touch(project: Project) -> None:
    project.last_activity_at = utcnow()
