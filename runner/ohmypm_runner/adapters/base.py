"""Agent adapter contract.

Each adapter turns a :class:`RunContext` into a :class:`LaunchSpec` (argv, env, stdin), parses the
CLI's stdout line by line into normalized :class:`AgentEvent` objects, and decides the outcome.

The protocol in the spec (``check_available``/``launch``/``parse_event``/``cancel``) maps onto
:class:`BaseAdapter` as: ``check_available`` → same; ``launch`` → ``build_launch`` + the executor's
``ProcessHandle.spawn``; ``parse_event`` → ``parse_line`` (one line may yield several events);
``cancel`` → process-group termination in the executor (adapters may override ``graceful_stop``).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ohmypm_common.agent_options import parse_options
from ohmypm_common.enums import RunEventType, RunStatus
from ohmypm_common.protocol import AgentCapability
from ohmypm_common.redact import truncate
from ohmypm_runner.config import AgentSettings, RunnerConfig
from ohmypm_runner.process import LaunchSpec, child_env

# Secrets of the runner itself never reach agent processes.
DROP_ENV = ("OHMYPM_RUNNER_TOKEN", "OHMYPM_TOKEN", "OHMYPM_API_TOKEN", "OHMYPM_AGENT_TOKEN")
MAX_TEXT = 8000


@dataclass
class AgentEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RunContext:
    run_id: str
    task_id: str
    session_id: str | None
    workspace: Path
    prompt: str
    options: Any
    agent_token: str
    server_url: str
    temp_dir: Path
    native_session_id: str | None = None
    resume_native: bool = False
    write_mode: bool = True

    @property
    def mcp_url(self) -> str:
        return f"{self.server_url.rstrip('/')}/mcp"


@dataclass
class ParseState:
    native_session_id: str | None = None
    final_text: str | None = None
    last_message: str | None = None
    errored: bool = False
    error: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, str] = field(default_factory=dict)
    waiting_approval: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunOutcome:
    status: RunStatus
    error: str | None = None
    error_code: str | None = None
    result_summary: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    native_session_id: str | None = None


class BaseAdapter(ABC):
    agent_type: str = ""
    display_name: str = ""
    default_executable: str = ""
    version_args: tuple[str, ...] = ("--version",)
    builtin = True
    supports_native_resume = False

    def __init__(self, runner: RunnerConfig, settings: AgentSettings | None = None) -> None:
        self.runner = runner
        self.settings = settings or runner.agent(self.agent_type)

    # ------------------------------------------------------------ availability

    def executable(self) -> str | None:
        candidate = self.settings.executable or self.default_executable
        if os.path.isabs(candidate):
            return candidate if os.access(candidate, os.X_OK) else None
        return shutil.which(candidate)

    async def check_available(self) -> AgentCapability:
        cap = AgentCapability(
            agent_type=self.agent_type,
            available=False,
            builtin=self.builtin,
            display_name=self.display_name,
            max_parallel=self.settings.max_parallel,
        )
        if not self.settings.enabled:
            cap.detail = "disabled in runner config"
            return cap
        exe = self.executable()
        if exe is None:
            cap.detail = f"{self.settings.executable or self.default_executable} not found on PATH"
            return cap
        cap.executable = exe
        try:
            proc = await asyncio.create_subprocess_exec(
                exe,
                *self.version_args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
        except (TimeoutError, OSError) as exc:
            cap.detail = f"version check failed: {exc}"
            return cap
        text = (out or err).decode(errors="replace").strip().splitlines()
        cap.version = text[0][:200] if text else None
        cap.available = proc.returncode == 0
        if not cap.available:
            cap.detail = f"version check exited with {proc.returncode}"
        return cap

    # ------------------------------------------------------------ launch

    def parse_options(self, options: dict[str, Any]) -> Any:
        return parse_options(self.agent_type, options)

    def base_env(self, ctx: RunContext) -> dict[str, str]:
        extra = {
            "OHMYPM_URL": ctx.server_url,
            "OHMYPM_AGENT_TOKEN": ctx.agent_token,
            "OHMYPM_RUN_ID": ctx.run_id,
            "OHMYPM_TASK_ID": ctx.task_id,
            "OHMYPM_WORKSPACE": str(ctx.workspace),
            **self.settings.env,
        }
        return child_env(os.environ, DROP_ENV, extra)

    @abstractmethod
    def build_launch(self, ctx: RunContext) -> LaunchSpec: ...

    # ------------------------------------------------------------ output

    @abstractmethod
    def parse_line(self, line: str, state: ParseState) -> list[AgentEvent]: ...

    def finalize(self, state: ParseState, exit_code: int) -> RunOutcome:
        summary = state.final_text or state.last_message
        if exit_code == 0 and not state.errored:
            return RunOutcome(
                RunStatus.COMPLETED,
                result_summary=summary,
                usage=state.usage,
                native_session_id=state.native_session_id,
            )
        error = state.error or f"{self.agent_type} exited with code {exit_code}"
        return RunOutcome(
            RunStatus.FAILED,
            error=error,
            error_code="agent_error",
            result_summary=summary,
            usage=state.usage,
            native_session_id=state.native_session_id,
        )


def parse_json_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def short(value: Any, limit: int = MAX_TEXT) -> Any:
    if isinstance(value, str):
        return truncate(value, limit)
    if isinstance(value, dict | list):
        text = json.dumps(value, ensure_ascii=False, default=str)
        return value if len(text) <= limit else truncate(text, limit)
    return value


def output_event(line: str) -> AgentEvent:
    return AgentEvent(RunEventType.AGENT_OUTPUT, {"text": truncate(line, MAX_TEXT)})
