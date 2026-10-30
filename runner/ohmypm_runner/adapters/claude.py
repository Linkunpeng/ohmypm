"""Claude Code adapter.

Verified against claude 2.1.303 ``--help`` and a real ``stream-json`` transcript:
``claude -p --output-format stream-json --verbose`` reads the prompt from stdin and emits
``system/init`` (with ``session_id``), ``assistant``/``user`` messages (text, tool_use,
tool_result blocks) and a final ``result`` event (``is_error``, ``result``, ``permission_denials``).

Unattended policy: ``--permission-prompts none`` makes anything that would prompt fail closed.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ohmypm_common.agent_options import ClaudeOptions
from ohmypm_common.enums import RunEventType
from ohmypm_runner.adapters.base import (
    AgentEvent,
    BaseAdapter,
    ParseState,
    RunContext,
    output_event,
    parse_json_line,
    short,
)
from ohmypm_runner.process import LaunchSpec

FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


class ClaudeAdapter(BaseAdapter):
    supports_native_resume = True
    agent_type = "claude"
    display_name = "Claude Code"
    default_executable = "claude"

    def build_launch(self, ctx: RunContext) -> LaunchSpec:
        opts: ClaudeOptions = ctx.options
        exe = self.executable()
        assert exe is not None
        argv = [
            exe,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-prompts",
            "none",
            "--permission-mode",
            opts.permission_mode,
        ]
        if opts.model:
            argv += ["--model", opts.model]
        if opts.fallback_model:
            argv += ["--fallback-model", opts.fallback_model]
        if opts.effort:
            argv += ["--effort", opts.effort]
        if opts.max_budget_usd:
            argv += ["--max-budget-usd", f"{opts.max_budget_usd:.2f}"]
        allowed = list(opts.allowed_tools)
        if opts.inject_mcp and "mcp__ohmypm" not in allowed:
            # ohmypm's own tools are scoped by the run token; without this they would be auto-denied.
            allowed.append("mcp__ohmypm")
        if allowed:
            argv += ["--allowed-tools", *allowed]
        if opts.disallowed_tools:
            argv += ["--disallowed-tools", *opts.disallowed_tools]
        if opts.append_system_prompt:
            argv += ["--append-system-prompt", opts.append_system_prompt]
        if opts.inject_mcp:
            config = {
                "mcpServers": {
                    "ohmypm": {
                        "type": "http",
                        "url": ctx.mcp_url,
                        "headers": {"Authorization": f"Bearer {ctx.agent_token}"},
                    }
                }
            }
            path = ctx.temp_dir / "mcp.json"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump(config, fh)
            argv += ["--mcp-config", str(path)]
        if ctx.resume_native and ctx.native_session_id:
            argv += ["--resume", ctx.native_session_id]
        display = [a if a != ctx.agent_token else "***" for a in argv]
        return LaunchSpec(
            argv=argv, cwd=ctx.workspace, env=self.base_env(ctx), stdin_data=ctx.prompt.encode(), display_argv=display
        )

    def parse_line(self, line: str, state: ParseState) -> list[AgentEvent]:
        data = parse_json_line(line)
        if data is None:
            return [output_event(line)] if line.strip() else []
        kind = data.get("type")
        if kind == "system":
            if data.get("subtype") == "init":
                state.native_session_id = data.get("session_id") or state.native_session_id
                return [
                    AgentEvent(
                        RunEventType.AGENT_STARTED,
                        {
                            "agent": "claude",
                            "model": data.get("model"),
                            "session_id": data.get("session_id"),
                            "cwd": data.get("cwd"),
                            "permission_mode": data.get("permissionMode"),
                            "version": data.get("claude_code_version"),
                            "tools": len(data.get("tools") or []),
                            "mcp_servers": [
                                s.get("name") for s in data.get("mcp_servers") or [] if isinstance(s, dict)
                            ],
                        },
                    )
                ]
            return [
                AgentEvent(
                    RunEventType.AGENT_STATUS,
                    {
                        "subtype": data.get("subtype"),
                        "detail": short({k: v for k, v in data.items() if k not in ("type",)}, 2000),
                    },
                )
            ]
        if kind == "assistant":
            return self._assistant(data, state)
        if kind == "user":
            return self._tool_results(data, state)
        if kind == "result":
            state.final_text = data.get("result") if isinstance(data.get("result"), str) else state.final_text
            state.native_session_id = data.get("session_id") or state.native_session_id
            state.usage = {
                k: data.get(k)
                for k in ("total_cost_usd", "num_turns", "duration_ms", "usage")
                if data.get(k) is not None
            }
            events = []
            for denial in data.get("permission_denials") or []:
                events.append(AgentEvent(RunEventType.APPROVAL_DENIED, {"denial": short(denial, 2000)}))
            if data.get("is_error") or data.get("subtype") != "success":
                state.errored = True
                state.error = f"claude result {data.get('subtype')}: {short(str(data.get('result') or ''), 2000)}"
            events.append(
                AgentEvent(
                    RunEventType.AGENT_RESULT,
                    {
                        "subtype": data.get("subtype"),
                        "is_error": data.get("is_error"),
                        "result": short(data.get("result") or ""),
                        **state.usage,
                    },
                )
            )
            return events
        return []

    def _assistant(self, data: dict[str, Any], state: ParseState) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        for block in (data.get("message") or {}).get("content") or []:
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                state.last_message = block["text"]
                events.append(AgentEvent(RunEventType.AGENT_MESSAGE, {"text": short(block["text"])}))
            elif btype == "tool_use":
                name = str(block.get("name"))
                state.tools[str(block.get("id"))] = name
                tool_input = block.get("input") or {}
                events.append(
                    AgentEvent(
                        RunEventType.TOOL_STARTED,
                        {"tool": name, "tool_use_id": block.get("id"), "input": short(tool_input, 4000)},
                    )
                )
                if name in FILE_TOOLS and isinstance(tool_input, dict):
                    path = tool_input.get("file_path") or tool_input.get("notebook_path")
                    if path:
                        events.append(AgentEvent(RunEventType.FILE_CHANGED, {"path": path, "tool": name}))
        return events

    def _tool_results(self, data: dict[str, Any], state: ParseState) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, list):
            return events
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_id = str(block.get("tool_use_id"))
                output = block.get("content")
                if isinstance(output, list):
                    output = "\n".join(str(c.get("text", "")) for c in output if isinstance(c, dict))
                events.append(
                    AgentEvent(
                        RunEventType.TOOL_COMPLETED,
                        {
                            "tool": state.tools.get(tool_id),
                            "tool_use_id": tool_id,
                            "is_error": bool(block.get("is_error")),
                            "output": short(str(output or ""), 4000),
                        },
                    )
                )
        return events
