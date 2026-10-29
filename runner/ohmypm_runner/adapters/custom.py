"""Custom CLI agents defined on the runner host (``agents.d/*.yaml``) and the built-in fake agent.

A custom agent is only loaded when its id is listed in the runner config's ``trusted_custom_agents``
— explicit authorization by the host user. The server can select a custom agent by id but can never
change its executable or arguments. Commands are argv arrays; placeholders are substituted only as
whole arguments, never through a shell.

Example ``~/.config/ohmypm/agents.d/my-agent.yaml``::

    id: my-agent
    name: My Agent
    executable: /usr/local/bin/my-agent
    args: ["--non-interactive", "--cwd", "{workspace}"]
    prompt_delivery: stdin            # stdin | arg | file
    output: {format: jsonl}           # jsonl | text
    runtime: {timeout_seconds: 3600, max_parallel: 1}
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ohmypm_common.enums import RunEventType
from ohmypm_common.protocol import AgentCapability
from ohmypm_runner.adapters.base import (
    AgentEvent,
    BaseAdapter,
    ParseState,
    RunContext,
    output_event,
    parse_json_line,
    short,
)
from ohmypm_runner.config import AgentSettings, RunnerConfig
from ohmypm_runner.process import LaunchSpec

PLACEHOLDERS = {"{workspace}", "{run_id}", "{task_id}", "{prompt}", "{prompt_file}"}
KNOWN_EVENTS = {e.value for e in RunEventType}


class CustomOutput(BaseModel):
    format: Literal["jsonl", "text"] = "text"


class CustomRuntime(BaseModel):
    timeout_seconds: int | None = Field(default=None, gt=0)
    max_parallel: int = Field(default=1, ge=1)


class CustomAgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_\-]{1,40}$")
    name: str
    executable: str
    args: list[str] = Field(default_factory=list)
    version_args: list[str] = Field(default_factory=lambda: ["--version"])
    prompt_delivery: Literal["stdin", "arg", "file"] = "stdin"
    working_directory: Literal["workspace"] = "workspace"
    output: CustomOutput = Field(default_factory=CustomOutput)
    runtime: CustomRuntime = Field(default_factory=CustomRuntime)
    env: dict[str, str] = Field(default_factory=dict)

    @field_validator("executable")
    @classmethod
    def _absolute(cls, value: str) -> str:
        if not os.path.isabs(value):
            raise ValueError("executable must be an absolute path")
        return value

    @field_validator("id")
    @classmethod
    def _not_builtin(cls, value: str) -> str:
        if value in {"claude", "codex", "pi", "dsh", "fake"}:
            raise ValueError(f"{value!r} is a built-in agent id")
        return value


def parse_normalized(line: str, state: ParseState) -> list[AgentEvent]:
    """Parse a line in ohmypm's normalized JSONL format: ``{"type": "agent.message", ...payload}``."""
    data = parse_json_line(line)
    if data is None:
        return [output_event(line)] if line.strip() else []
    kind = str(data.get("type") or data.get("event_type") or "")
    payload = {k: short(v) for k, v in data.items() if k not in ("type", "event_type")}
    if kind == "session":
        state.native_session_id = str(data.get("id") or data.get("session_id") or "") or state.native_session_id
        return [AgentEvent(RunEventType.AGENT_STARTED, payload)]
    if kind == RunEventType.AGENT_MESSAGE.value and isinstance(data.get("text"), str):
        state.last_message = data["text"]
    if kind in ("result", RunEventType.AGENT_RESULT.value):
        text = data.get("text") or data.get("result")
        if isinstance(text, str):
            state.final_text = text
        if data.get("is_error"):
            state.errored = True
            state.error = str(text or "agent reported an error")[:2000]
        return [AgentEvent(RunEventType.AGENT_RESULT, payload)]
    if kind == RunEventType.AGENT_ERROR.value:
        state.errored = True
        state.error = str(data.get("message") or "agent error")[:2000]
    if kind == RunEventType.APPROVAL_REQUESTED.value:
        state.waiting_approval = True
    if kind in KNOWN_EVENTS:
        return [AgentEvent(kind, payload)]
    return [AgentEvent(RunEventType.AGENT_OUTPUT, {"raw": short(data, 4000)})]


class CustomAdapter(BaseAdapter):
    builtin = False

    def __init__(self, runner: RunnerConfig, spec: CustomAgentSpec) -> None:
        self.spec = spec
        self.agent_type = spec.id
        self.display_name = spec.name
        self.default_executable = spec.executable
        self.version_args = tuple(spec.version_args)
        super().__init__(
            runner, AgentSettings(executable=spec.executable, max_parallel=spec.runtime.max_parallel, env=spec.env)
        )

    async def check_available(self) -> AgentCapability:
        if not self.spec.version_args:
            ok = self.executable() is not None
            return AgentCapability(
                agent_type=self.agent_type,
                available=ok,
                builtin=False,
                display_name=self.display_name,
                executable=self.spec.executable,
                max_parallel=self.spec.runtime.max_parallel,
                detail=None if ok else "executable missing or not executable",
            )
        return await super().check_available()

    def build_launch(self, ctx: RunContext) -> LaunchSpec:
        prompt_file = ctx.temp_dir / "prompt.md"
        if self.spec.prompt_delivery == "file" or "{prompt_file}" in self.spec.args:
            fd = os.open(prompt_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(ctx.prompt)
        values = {
            "{workspace}": str(ctx.workspace),
            "{run_id}": ctx.run_id,
            "{task_id}": ctx.task_id,
            "{prompt}": ctx.prompt,
            "{prompt_file}": str(prompt_file),
        }
        args = [values.get(a, a) for a in self.spec.args]
        if self.spec.prompt_delivery == "arg" and "{prompt}" not in self.spec.args:
            args.append(ctx.prompt)
        argv = [self.spec.executable, *args]
        display = [("<prompt>" if a == ctx.prompt else a) for a in argv]
        stdin = ctx.prompt.encode() if self.spec.prompt_delivery == "stdin" else None
        return LaunchSpec(argv=argv, cwd=ctx.workspace, env=self.base_env(ctx), stdin_data=stdin, display_argv=display)

    def parse_line(self, line: str, state: ParseState) -> list[AgentEvent]:
        if self.spec.output.format == "jsonl":
            return parse_normalized(line, state)
        if line.strip():
            state.last_message = line
            return [output_event(line)]
        return []


class FakeAdapter(BaseAdapter):
    """Deterministic agent for tests and demos (enable with ``enable_fake_agent: true``)."""

    agent_type = "fake"
    display_name = "Fake agent (testing)"
    default_executable = sys.executable

    def executable(self) -> str | None:
        return sys.executable

    async def check_available(self) -> AgentCapability:
        return AgentCapability(
            agent_type="fake",
            available=True,
            version="ohmypm fake agent",
            executable=sys.executable,
            display_name=self.display_name,
            max_parallel=self.settings.max_parallel,
        )

    def build_launch(self, ctx: RunContext) -> LaunchSpec:
        import json

        env = self.base_env(ctx)
        env["OHMYPM_FAKE_SCRIPT"] = json.dumps(ctx.options.script)
        env["OHMYPM_FAKE_EXIT_CODE"] = str(ctx.options.exit_code)
        argv = [sys.executable, "-m", "ohmypm_runner.fake_agent"]
        return LaunchSpec(
            argv=argv,
            cwd=ctx.workspace,
            env=env,
            stdin_data=ctx.prompt.encode(),
            display_argv=["python", "-m", "ohmypm_runner.fake_agent"],
        )

    def parse_line(self, line: str, state: ParseState) -> list[AgentEvent]:
        return parse_normalized(line, state)


def load_custom_agents(runner: RunnerConfig) -> tuple[list[CustomAdapter], list[str]]:
    """Returns (trusted adapters, warnings)."""
    adapters: list[CustomAdapter] = []
    warnings: list[str] = []
    directory: Path = runner.custom_agents_path
    if not directory.is_dir():
        return adapters, warnings
    for file in sorted(directory.glob("*.y*ml")):
        try:
            raw: Any = yaml.safe_load(file.read_text(encoding="utf-8"))
            spec = CustomAgentSpec.model_validate(raw)
        except Exception as exc:
            warnings.append(f"{file}: {exc}")
            continue
        if spec.id not in runner.trusted_custom_agents:
            warnings.append(f"{file}: custom agent {spec.id!r} is not listed in trusted_custom_agents; ignored")
            continue
        adapters.append(CustomAdapter(runner, spec))
    return adapters, warnings
