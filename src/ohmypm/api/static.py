"""Location of the compiled Web UI."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIST = Path(__file__).resolve().parent.parent / "webui" / "dist"


def web_dist_dir() -> Path | None:
    """The built frontend (``index.html`` + assets) if it is present."""
    return PACKAGE_DIST if (PACKAGE_DIST / "index.html").is_file() else None
