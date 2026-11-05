"""Shared fixtures.

Every test runs with a temporary HOME, data dir and config dir, and with all
agent configuration locations redirected into it, so the real user's data and
agent configuration can never be touched.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from ohmypm.config import Settings, load_settings
from ohmypm.core.service import MemoryService
from ohmypm.storage.database import Database

AGENT_ENV_VARS = ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "PI_CODING_AGENT_DIR", "DSH_HOME")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("OHMYPM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OHMYPM_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    for var in AGENT_ENV_VARS + ("OHMYPM_AUTHOR", "OHMYPM_PROJECT"):
        monkeypatch.delenv(var, raising=False)
    return home


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = load_settings()
    assert str(s.data_dir).startswith(str(tmp_path)), "tests must never use the real data dir"
    return s


@pytest.fixture
def db(settings: Settings) -> Database:
    database = Database(settings)
    yield database
    database.dispose()


@pytest.fixture
def service(settings: Settings, db: Database) -> MemoryService:
    return MemoryService(settings, db)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A fake source project with some content."""
    root = tmp_path / "Projects" / "Robot_WS"
    (root / "src" / "camera").mkdir(parents=True)
    (root / "src" / "camera" / "driver.cpp").write_text("int main() { return 0; }\n")
    (root / "README.md").write_text("# Robot\n")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return root


def tree_snapshot(root: Path) -> dict[str, tuple[int, str, float]]:
    """Map of relative path -> (mode, sha256, mtime) for every file/dir under root."""
    snapshot: dict[str, tuple[int, str, float]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            st = path.lstat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
            snapshot[str(path.relative_to(root))] = (st.st_mode, digest, st.st_mtime)
    st = root.stat()
    snapshot["."] = (st.st_mode, "", st.st_mtime)
    return snapshot
