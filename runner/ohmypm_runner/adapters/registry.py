"""Adapter registry: built-in adapters plus trusted custom agents from the runner host."""

from __future__ import annotations

from ohmypm_runner.adapters.base import BaseAdapter
from ohmypm_runner.adapters.claude import ClaudeAdapter
from ohmypm_runner.adapters.codex import CodexAdapter
from ohmypm_runner.adapters.custom import FakeAdapter, load_custom_agents
from ohmypm_runner.adapters.dsh import DshAdapter
from ohmypm_runner.adapters.pi import PiAdapter
from ohmypm_runner.config import RunnerConfig

BUILTIN: tuple[type[BaseAdapter], ...] = (ClaudeAdapter, CodexAdapter, PiAdapter, DshAdapter)


def build_adapters(config: RunnerConfig) -> tuple[dict[str, BaseAdapter], list[str]]:
    adapters: dict[str, BaseAdapter] = {cls.agent_type: cls(config) for cls in BUILTIN}
    if config.enable_fake_agent:
        adapters["fake"] = FakeAdapter(config)
    custom, warnings = load_custom_agents(config)
    for adapter in custom:
        adapters[adapter.agent_type] = adapter
    return adapters, warnings
