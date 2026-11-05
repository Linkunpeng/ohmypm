"""Filesystem helpers for private data (assets, backups, exports)."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write ``data`` to ``path`` atomically with the given permissions."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode)


def safe_child(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root``; reject anything escaping it."""
    if not relative or os.path.isabs(relative) or "\x00" in relative:
        raise ValueError(f"Invalid storage path: {relative!r}")
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    if candidate == root_resolved or root_resolved not in candidate.parents:
        raise ValueError(f"Storage path escapes data directory: {relative!r}")
    return candidate


def after_commit(session: Session, callback: Callable[[], None]) -> None:
    """Run ``callback`` once the session's current transaction commits.

    Used for irreversible filesystem changes (deleting files) so they only
    happen when the database change actually persisted.
    """

    def _run(_session: Session) -> None:
        callback()

    event.listen(session, "after_commit", _run, once=True)


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def remove_file(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
