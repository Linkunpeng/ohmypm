"""Workspace path authorization on the runner host (the only place paths are resolved)."""

from __future__ import annotations

import os
from pathlib import Path


class WorkspaceError(Exception):
    pass


def resolve_workspace(path: str, allowed_roots: list[str]) -> Path:
    """Resolve symlinks and require the real path to be an existing directory under an allowed root."""
    if not allowed_roots:
        raise WorkspaceError("runner has no allowed_roots configured; refusing to run anywhere")
    if "\x00" in path or not os.path.isabs(path):
        raise WorkspaceError("workspace path must be absolute")
    real = Path(os.path.realpath(path))
    if not real.is_dir():
        raise WorkspaceError(f"workspace {real} does not exist on this host")
    for root in allowed_roots:
        root_real = Path(os.path.realpath(root))
        if real == root_real or root_real in real.parents:
            return real
    raise WorkspaceError(f"workspace {real} is outside the runner's allowed_roots")
