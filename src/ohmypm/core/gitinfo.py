"""Read-only Git state of a project directory.

ohmypm stamps new records and summary updates with the commit the project
was on (``{"commit": <sha>, "branch": <name or null>}``) so a later reader
can tell how far the code has moved since. Only ``git`` read commands are
run, with a short timeout; any failure (no Git, not a repository, no commits
yet, unknown commit after a rebase) yields ``None`` and never blocks writes.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

TIMEOUT_SECONDS = 3.0
SHORT_SHA = 7
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")


def _git(root: str | os.PathLike[str], *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(root), *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            # Never prompt and never take locks: this runs alongside agents.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def head(root: str | os.PathLike[str]) -> dict[str, Any] | None:
    """``{"commit", "branch"}`` of ``root``'s HEAD; ``branch`` is ``None`` when detached."""
    if not os.path.isdir(root):
        return None
    commit = _git(root, "rev-parse", "--verify", "-q", "HEAD")
    if not commit or not _SHA_RE.match(commit):
        return None
    return {"commit": commit, "branch": _git(root, "symbolic-ref", "-q", "--short", "HEAD") or None}


def commits_since(root: str | os.PathLike[str], commit: str) -> int | None:
    """Number of commits on HEAD that are not reachable from ``commit``."""
    if not _SHA_RE.match(commit) or not os.path.isdir(root):
        return None
    count = _git(root, "rev-list", "--count", f"{commit}..HEAD")
    return int(count) if count and count.isdigit() else None


def valid_stamp(value: Any) -> dict[str, Any] | None:
    """A stored ``git`` stamp if it is well-formed, else ``None``."""
    if not isinstance(value, dict) or not isinstance(value.get("commit"), str):
        return None
    if not _SHA_RE.match(value["commit"]):
        return None
    branch = value.get("branch")
    return {"commit": value["commit"], "branch": branch if isinstance(branch, str) else None}


def short(commit: str) -> str:
    return commit[:SHORT_SHA]


def label(stamp: dict[str, Any]) -> str:
    """``abc1234 (main)`` or just ``abc1234`` for a detached HEAD."""
    branch = stamp.get("branch")
    return short(stamp["commit"]) + (f" ({branch})" if branch else "")
