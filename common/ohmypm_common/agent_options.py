"""Typed, whitelisted options for built-in agent adapters.

Agent profiles live on the server but are executed on a runner host. The server never sends raw
argv; it sends these options, which both sides validate. Anything that widens permissions is
flagged ``dangerous`` and additionally requires ``allow_dangerous: true`` in the runner config.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@\-\[\]]*$")
# Claude tool rules such as "Bash(git diff:*)" or "Edit".
_TOOL_RULE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*(\([^()\x00\n]{0,200}\))?$|^mcp__[A-Za-z0-9_\-]+$")


def _check_token(value: str | None, field: str) -> str | None:
    if value is not None and not _SAFE_TOKEN.match(value):
        raise ValueError(f"{field} contains unsupported characters")
    return value


class _Options(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def dangerous_reasons(self) -> list[str]:
        return []


class ClaudeOptions(_Options):
    model: str | None = None
    fallback_model: str | None = None
    permission_mode: Literal["default", "acceptEdits", "plan", "dontAsk", "auto", "bypassPermissions"] = "acceptEdits"
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    disallowed_tools: list[str] = Field(default_factory=list, max_length=100)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    max_budget_usd: float | None = Field(default=None, gt=0, le=1000)
    append_system_prompt: str | None = Field(default=None, max_length=20_000)
    inject_mcp: bool = True

    @field_validator("model", "fallback_model")
    @classmethod
    def _model(cls, v: str | None) -> str | None:
        return _check_token(v, "model")

    @field_validator("allowed_tools", "disallowed_tools")
    @classmethod
    def _tools(cls, v: list[str]) -> list[str]:
        for rule in v:
            if not _TOOL_RULE.match(rule):
                raise ValueError(f"invalid tool rule {rule!r}")
        return v

    def dangerous_reasons(self) -> list[str]:
        reasons = []
        if self.permission_mode == "bypassPermissions":
            reasons.append("permission_mode=bypassPermissions")
        if any(rule == "Bash" or rule.startswith("Bash(*") for rule in self.allowed_tools):
            reasons.append("unrestricted Bash in allowed_tools")
        return reasons


class CodexOptions(_Options):
    model: str | None = None
    sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"] | None = None
    config_profile: str | None = Field(default=None, description="codex --profile name")
    skip_git_repo_check: bool = True
    network_access: bool = False
    inject_mcp: bool = True

    @field_validator("model", "config_profile")
    @classmethod
    def _token(cls, v: str | None) -> str | None:
        return _check_token(v, "value")

    def dangerous_reasons(self) -> list[str]:
        reasons = []
        if self.sandbox == "danger-full-access":
            reasons.append("sandbox=danger-full-access")
        if self.network_access:
            reasons.append("network_access=true")
        return reasons


PI_TOOLS = {"read", "bash", "edit", "write", "grep", "find", "ls"}


class PiOptions(_Options):
    provider: str | None = None
    model: str | None = None
    thinking: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None
    # pi has no approval system: bash is only enabled when listed (and runner allows dangerous).
    tools: list[str] = Field(default_factory=lambda: ["read", "edit", "write", "grep", "find", "ls"])
    no_extensions: bool = False
    no_skills: bool = False

    @field_validator("provider", "model")
    @classmethod
    def _token(cls, v: str | None) -> str | None:
        return _check_token(v, "value")

    @field_validator("tools")
    @classmethod
    def _tools(cls, v: list[str]) -> list[str]:
        unknown = set(v) - PI_TOOLS
        if unknown:
            raise ValueError(f"unknown pi tools: {sorted(unknown)}")
        return v

    def dangerous_reasons(self) -> list[str]:
        return ["pi bash tool (no approval system)"] if "bash" in self.tools else []


class DshOptions(_Options):
    profile: str = "headless"
    permission_mode: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"

    @field_validator("profile")
    @classmethod
    def _profile(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$", v):
            raise ValueError("invalid dsh profile name")
        return v

    def dangerous_reasons(self) -> list[str]:
        return ["permission_mode=danger-full-access"] if self.permission_mode == "danger-full-access" else []


class FakeOptions(_Options):
    """Options for the test/demo fake agent."""

    script: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    exit_code: int = 0


class CustomOptions(_Options):
    """Custom CLIs take no server-side options; everything is fixed in the runner-local config."""


OPTION_MODELS: dict[str, type[_Options]] = {
    "claude": ClaudeOptions,
    "codex": CodexOptions,
    "pi": PiOptions,
    "dsh": DshOptions,
    "fake": FakeOptions,
}


class OptionsError(ValueError):
    pass


def parse_options(agent_type: str, options: dict[str, Any]) -> _Options:
    model = OPTION_MODELS.get(agent_type, CustomOptions)
    try:
        return model.model_validate(options or {})
    except ValidationError as exc:
        raise OptionsError(f"invalid options for agent {agent_type!r}: {exc}") from exc
