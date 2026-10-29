"""PROJECT_ID file discovery.

A formal project root contains a ``PROJECT_ID`` file whose only content is a UUIDv4.
Discovery walks from a start directory up to the filesystem root and returns the first
valid file. Directories without one are anonymous workspaces.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

PROJECT_ID_FILENAME = "PROJECT_ID"


class ProjectIdError(Exception):
    """Raised when a PROJECT_ID file exists but is unreadable or invalid."""


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: uuid.UUID
    root: Path

    @property
    def file(self) -> Path:
        return self.root / PROJECT_ID_FILENAME


@dataclass(frozen=True)
class WorkspaceLocation:
    """Where a command is running: either inside a formal project or an anonymous directory."""

    root: Path
    project: ProjectIdentity | None

    @property
    def is_anonymous(self) -> bool:
        return self.project is None


def parse_project_id(text: str) -> uuid.UUID:
    value = text.strip()
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ProjectIdError(f"PROJECT_ID content is not a UUID: {value[:60]!r}") from exc
    if str(parsed) != value.lower():
        raise ProjectIdError(f"PROJECT_ID must be a canonical UUID string, got {value[:60]!r}")
    return parsed


def read_project_id(path: Path) -> uuid.UUID:
    try:
        # A real PROJECT_ID is 36 bytes; refuse to read anything large.
        if path.stat().st_size > 1024:
            raise ProjectIdError(f"{path} is too large to be a PROJECT_ID file")
        return parse_project_id(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectIdError(f"cannot read {path}: {exc}") from exc


def find_project(start: Path | str | None = None, *, stop_at: Path | None = None) -> ProjectIdentity | None:
    """Find the nearest PROJECT_ID at or above ``start``.

    ``stop_at`` (inclusive) bounds the search, which tests use to avoid escaping a temp dir.
    Invalid PROJECT_ID files raise :class:`ProjectIdError` instead of being skipped silently,
    so a corrupted identity is never mistaken for "no project".
    """
    current = Path(start if start is not None else os.getcwd()).resolve()
    bound = stop_at.resolve() if stop_at is not None else None
    for directory in (current, *current.parents):
        candidate = directory / PROJECT_ID_FILENAME
        if candidate.is_file():
            return ProjectIdentity(project_id=read_project_id(candidate), root=directory)
        if bound is not None and directory == bound:
            break
    return None


def locate_workspace(start: Path | str | None = None, *, stop_at: Path | None = None) -> WorkspaceLocation:
    """Resolve the workspace root: the project root if one is found, else ``start`` itself."""
    current = Path(start if start is not None else os.getcwd()).resolve()
    project = find_project(current, stop_at=stop_at)
    return WorkspaceLocation(root=project.root if project else current, project=project)


def init_project_id(directory: Path | str, project_id: uuid.UUID | None = None) -> ProjectIdentity:
    """Create ``directory/PROJECT_ID``. Never overwrites an existing file."""
    root = Path(directory).resolve()
    target = root / PROJECT_ID_FILENAME
    if target.exists():
        existing = read_project_id(target)
        if project_id is not None and existing != project_id:
            raise ProjectIdError(f"{target} already contains {existing}; refusing to overwrite with {project_id}")
        return ProjectIdentity(project_id=existing, root=root)
    new_id = project_id or uuid.uuid4()
    # O_EXCL guards against a concurrent creator between the exists() check and the write.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"{new_id}\n")
    return ProjectIdentity(project_id=new_id, root=root)
