"""Runner configuration: ``~/.config/ohmypm/runner.yaml`` (or ``--config``), env overrides.

Example::

    server_url: http://127.0.0.1:8765
    token: <OHMYPM_RUNNER_TOKEN>        # or env OHMYPM_RUNNER_TOKEN
    name: arch-desktop
    allowed_roots: [~/workspace]        # agents only run in workspaces under these directories
    max_parallel: 2
    allow_dangerous: false              # bypass-permission / full-access profiles are refused unless true
    agents:
      claude: {enabled: true}
      codex: {enabled: true, executable: /usr/local/bin/codex}
    trusted_custom_agents: [my-agent]   # ids of custom agents in agents.d/ the host user trusts
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from ohmypm_common.config import DEFAULT_SERVER_URL, config_dir, default_host_id, state_dir


class AgentSettings(BaseModel):
    enabled: bool = True
    executable: str | None = None
    max_parallel: int | None = Field(default=None, ge=1)
    env: dict[str, str] = Field(default_factory=dict)


class RunnerConfig(BaseModel):
    server_url: str = DEFAULT_SERVER_URL
    token: str | None = None
    runner_id: str | None = None
    name: str = Field(default_factory=default_host_id)
    host_id: str = Field(default_factory=default_host_id)
    allowed_roots: list[str] = Field(default_factory=list)
    max_parallel: int = Field(default=2, ge=1, le=64)
    allow_dangerous: bool = False
    enable_fake_agent: bool = False
    agents: dict[str, AgentSettings] = Field(default_factory=dict)
    custom_agents_dir: str | None = None
    trusted_custom_agents: list[str] = Field(default_factory=list)
    state_dir: str | None = None
    # Process management
    cancel_grace_seconds: float = 10.0
    max_stderr_events: int = 400
    event_flush_interval_seconds: float = 0.5
    # Optional overrides (the server suggests values at registration)
    heartbeat_interval_seconds: float | None = None
    poll_interval_seconds: float | None = None

    @field_validator("allowed_roots")
    @classmethod
    def _expand(cls, roots: list[str]) -> list[str]:
        return [str(Path(os.path.expandvars(r)).expanduser().resolve()) for r in roots]

    def agent(self, name: str) -> AgentSettings:
        return self.agents.get(name, AgentSettings())

    @property
    def state_path(self) -> Path:
        return Path(self.state_dir).expanduser() if self.state_dir else state_dir()

    @property
    def custom_agents_path(self) -> Path:
        return Path(self.custom_agents_dir).expanduser() if self.custom_agents_dir else config_dir() / "agents.d"


def default_config_path() -> Path:
    return Path(os.environ.get("OHMYPM_RUNNER_CONFIG", str(config_dir() / "runner.yaml"))).expanduser()


def load_config(path: Path | None = None, **overrides: Any) -> RunnerConfig:
    target = path or default_config_path()
    data: dict[str, Any] = {}
    if target.is_file():
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{target} must contain a mapping")
        data.update(loaded)
    if os.environ.get("OHMYPM_URL"):
        data["server_url"] = os.environ["OHMYPM_URL"]
    if os.environ.get("OHMYPM_RUNNER_TOKEN"):
        data["token"] = os.environ["OHMYPM_RUNNER_TOKEN"]
    if os.environ.get("OHMYPM_ALLOWED_ROOTS"):
        data["allowed_roots"] = [r for r in os.environ["OHMYPM_ALLOWED_ROOTS"].split(os.pathsep) if r]
    data.update({k: v for k, v in overrides.items() if v is not None})
    return RunnerConfig.model_validate(data)
