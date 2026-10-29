"""Backend settings (environment variables prefixed with ``OHMYPM_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OHMYPM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ohmypm:ohmypm@127.0.0.1:55432/ohmypm"
    host: str = "127.0.0.1"
    port: int = 8765
    # Public base URL that runners/agents use to reach this server (MCP URL is derived from it).
    public_url: str = "http://127.0.0.1:8765"

    api_token: SecretStr | None = None
    runner_token: SecretStr | None = None
    # Optional static token for agents the user launches themselves (not via the runner).
    agent_token: SecretStr | None = None

    # Run scheduling
    lease_seconds: float = 45.0
    heartbeat_interval_seconds: float = 5.0
    poll_interval_seconds: float = 2.0
    reaper_interval_seconds: float = 15.0
    runner_offline_after_seconds: float = 45.0
    default_run_timeout_seconds: int = 3600
    max_run_timeout_seconds: int = 24 * 3600
    # How many levels of agent→agent dispatch are allowed (0 = agents cannot dispatch).
    agent_max_dispatch_depth: int = 0
    agent_max_child_runs: int = 3

    # SSE
    sse_poll_interval_seconds: float = 0.5
    sse_keepalive_seconds: float = 15.0

    # Context builder default budget
    context_default_max_tokens: int = 3000

    web_dist: Path | None = Field(default=None, description="Built web UI directory to serve at /")
    cors_origins: list[str] = Field(default_factory=list)
    log_level: str = "info"


@lru_cache
def get_settings() -> Settings:
    return Settings()
