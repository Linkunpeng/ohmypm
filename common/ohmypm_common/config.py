"""Client-side configuration (CLI and runner): where the server is and which token to use.

Resolution order for each value: explicit argument → environment → config file → default.
Config file: ``$OHMYPM_CONFIG`` or ``~/.config/ohmypm/config.toml``::

    server_url = "http://127.0.0.1:8765"
    token = "..."          # admin token used by the CLI
    host_id = "my-laptop"  # optional, defaults to the hostname
"""

from __future__ import annotations

import os
import socket
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_SERVER_URL = "http://127.0.0.1:8765"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ohmypm"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "ohmypm"


def config_file() -> Path:
    override = os.environ.get("OHMYPM_CONFIG")
    return Path(override).expanduser() if override else config_dir() / "config.toml"


def load_config_file(path: Path | None = None) -> dict[str, Any]:
    target = path or config_file()
    if not target.is_file():
        return {}
    with target.open("rb") as fh:
        return tomllib.load(fh)


def default_host_id() -> str:
    return os.environ.get("OHMYPM_HOST_ID") or socket.gethostname()


@dataclass(frozen=True)
class ClientConfig:
    server_url: str
    token: str | None
    host_id: str

    @classmethod
    def load(cls, server_url: str | None = None, token: str | None = None) -> ClientConfig:
        file_values = load_config_file()
        url = server_url or os.environ.get("OHMYPM_URL") or file_values.get("server_url") or DEFAULT_SERVER_URL
        # Inside an agent run (OHMYPM_RUN_ID set) the run-scoped token wins so actions are attributed
        # to the run; otherwise an explicit/admin token is preferred.
        in_run = bool(os.environ.get("OHMYPM_RUN_ID") and os.environ.get("OHMYPM_AGENT_TOKEN"))
        resolved_token = token or (
            os.environ.get("OHMYPM_AGENT_TOKEN")
            if in_run
            else os.environ.get("OHMYPM_TOKEN") or file_values.get("token") or os.environ.get("OHMYPM_AGENT_TOKEN")
        )
        host = file_values.get("host_id") or default_host_id()
        return cls(server_url=str(url).rstrip("/"), token=resolved_token, host_id=str(host))
