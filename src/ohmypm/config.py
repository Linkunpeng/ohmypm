"""Paths and user configuration.

Follows the XDG Base Directory convention:

* data:   ``$OHMYPM_DATA_DIR``   or ``$XDG_DATA_HOME/ohmypm``   or ``~/.local/share/ohmypm``
* config: ``$OHMYPM_CONFIG_DIR`` or ``$XDG_CONFIG_HOME/ohmypm`` or ``~/.config/ohmypm``

``config.toml`` is optional. Unknown keys are ignored so the file can be shared
with other tools; ohmypm never rewrites an existing config file.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8737
DEFAULT_MAX_UPLOAD_MB = 20
_TYPE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if value:
        return Path(value).expanduser()
    return None


def default_data_dir() -> Path:
    explicit = _env_path("OHMYPM_DATA_DIR")
    if explicit:
        return explicit
    xdg = _env_path("XDG_DATA_HOME")
    base = xdg if xdg and xdg.is_absolute() else Path.home() / ".local" / "share"
    return base / "ohmypm"


def default_config_dir() -> Path:
    explicit = _env_path("OHMYPM_CONFIG_DIR")
    if explicit:
        return explicit
    xdg = _env_path("XDG_CONFIG_HOME")
    base = xdg if xdg and xdg.is_absolute() else Path.home() / ".config"
    return base / "ohmypm"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    config_dir: Path
    web_host: str = DEFAULT_WEB_HOST
    web_port: int = DEFAULT_WEB_PORT
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_MB * 1024 * 1024
    default_author: str | None = None
    extra_entry_types: tuple[str, ...] = ()
    raw_config: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def entry_types(self) -> tuple[str, ...]:
        from ohmypm.core.schemas import BUILTIN_ENTRY_TYPES

        return tuple(BUILTIN_ENTRY_TYPES) + tuple(
            t for t in self.extra_entry_types if t not in BUILTIN_ENTRY_TYPES
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ohmypm.db"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def agent_instructions_file(self) -> Path:
        return self.config_dir / "agent-instructions.md"

    @property
    def web_token_file(self) -> Path:
        return self.data_dir / "web-token"


def _read_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        # A broken or foreign config must never prevent agents from working.
        return {}


def load_settings(data_dir: Path | None = None, config_dir: Path | None = None) -> Settings:
    data_dir = (data_dir or default_data_dir()).expanduser().absolute()
    config_dir = (config_dir or default_config_dir()).expanduser().absolute()
    raw = _read_config(config_dir / "config.toml")

    web = raw.get("web") if isinstance(raw.get("web"), dict) else {}
    assets = raw.get("assets") if isinstance(raw.get("assets"), dict) else {}
    general = raw.get("ohmypm") if isinstance(raw.get("ohmypm"), dict) else {}
    entries = raw.get("entries") if isinstance(raw.get("entries"), dict) else {}
    extra_types = entries.get("extra_types", [])
    if not isinstance(extra_types, list):
        extra_types = []

    host = web.get("host", DEFAULT_WEB_HOST)
    port = web.get("port", DEFAULT_WEB_PORT)
    max_mb = assets.get("max_upload_mb", DEFAULT_MAX_UPLOAD_MB)
    author = general.get("author")

    return Settings(
        data_dir=data_dir,
        config_dir=config_dir,
        web_host=host if isinstance(host, str) and host else DEFAULT_WEB_HOST,
        web_port=port if isinstance(port, int) and 0 < port < 65536 else DEFAULT_WEB_PORT,
        max_upload_bytes=int(max_mb * 1024 * 1024)
        if isinstance(max_mb, (int, float)) and max_mb > 0
        else DEFAULT_MAX_UPLOAD_MB * 1024 * 1024,
        default_author=author if isinstance(author, str) and author else None,
        extra_entry_types=tuple(
            t.strip().lower() for t in extra_types if isinstance(t, str) and _TYPE_RE.match(t.strip().lower())
        ),
        raw_config=raw,
    )


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` (and parents) with owner-only permissions."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        if path.stat().st_mode & 0o077:
            path.chmod(0o700)
    except OSError:
        pass
    return path
