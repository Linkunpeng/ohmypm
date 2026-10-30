"""Pi coding agent adapter.

Verified against pi 0.85.1 ``--help``, its ``AgentEvent`` type definitions and a real
``--mode json`` transcript. ``pi -p --mode json`` reads piped stdin as the prompt and emits JSONL:
``session{id}``, ``agent_start``, ``turn_start``, ``message_start|update|end{message}``,
``tool_execution_start|update|end``, ``turn_end``, ``agent_end``.

Pi exits 0 even when the model call fails, so failures are detected from assistant messages with
``stopReason == "error"``. Pi has no approval system: the ``bash`` tool is only enabled when the
profile lists it *and* the runner allows dangerous options.
"""

from __future__ import annotations

from typing import Any

from ohmypm_common.agent_options import PiOptions
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


def _text_of(message: dict[str, Any]) -> str:
    parts = []
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


class PiAdapter(BaseAdapter):
    supports_native_resume = True
    agent_type = "pi"
    display_name = "Pi"
    default_executable = "pi"

    def build_launch(self, ctx: RunContext) -> LaunchSpec:
        opts: PiOptions = ctx.options
        exe = self.executable()
        assert exe is not None
        argv = [exe, "-p", "--mode", "json"]
        argv += ["--tools", ",".join(opts.tools)] if opts.tools else ["--no-tools"]
        if opts.provider:
            argv += ["--provider", opts.provider]
        if opts.model:
            argv += ["--model", opts.model]
        if opts.thinking:
            argv += ["--thinking", opts.thinking]
        if opts.no_extensions:
            argv.append("--no-extensions")
        if opts.no_skills:
            argv.append("--no-skills")
        if ctx.resume_native and ctx.native_session_id:
            argv += ["--session", ctx.native_session_id]
        return LaunchSpec(
            argv=argv,
            cwd=ctx.workspace,
            env=self.base_env(ctx),
            stdin_data=ctx.prompt.encode(),
            display_argv=list(argv),
        )

    def parse_line(self, line: str, state: ParseState) -> list[AgentEvent]:
        data = parse_json_line(line)
        if data is None:
            return [output_event(line)] if line.strip() else []
        kind = data.get("type")
        if kind == "session":
            state.native_session_id = data.get("id") or state.native_session_id
            return [
                AgentEvent(
                    RunEventType.AGENT_STARTED, {"agent": "pi", "session_id": data.get("id"), "cwd": data.get("cwd")}
                )
            ]
        if kind in ("agent_start", "turn_start", "turn_end", "agent_settled"):
            return [AgentEvent(RunEventType.AGENT_STATUS, {"phase": kind})] if kind != "turn_end" else []
        if kind == "message_end":
            message = data.get("message") or {}
            if message.get("role") != "assistant":
                return []
            events: list[AgentEvent] = []
            text = _text_of(message)
            if text:
                state.last_message = text
                state.final_text = text
                events.append(
                    AgentEvent(RunEventType.AGENT_MESSAGE, {"text": short(text), "model": message.get("model")})
                )
            usage = message.get("usage")
            if isinstance(usage, dict):
                state.usage = {
                    "input": usage.get("input"),
                    "output": usage.get("output"),
                    "cache_read_tokens": usage.get("cacheRead"),
                    "cache_write_tokens": usage.get("cacheWrite"),
                    "cost": (usage.get("cost") or {}).get("total"),
                }
            if message.get("stopReason") == "error":
                state.errored = True
                state.error = short(str(message.get("errorMessage") or "pi reported an error"), 2000)
                events.append(AgentEvent(RunEventType.AGENT_ERROR, {"message": state.error}))
            else:
                state.errored = False
            return events
        if kind == "tool_execution_start":
            state.tools[str(data.get("toolCallId"))] = str(data.get("toolName"))
            events = [
                AgentEvent(
                    RunEventType.TOOL_STARTED,
                    {
                        "tool": data.get("toolName"),
                        "tool_use_id": data.get("toolCallId"),
                        "input": short(data.get("args"), 4000),
                    },
                )
            ]
            args = data.get("args") or {}
            if data.get("toolName") in ("edit", "write") and isinstance(args, dict) and args.get("path"):
                events.append(
                    AgentEvent(RunEventType.FILE_CHANGED, {"path": args.get("path"), "tool": data.get("toolName")})
                )
            return events
        if kind == "tool_execution_end":
            return [
                AgentEvent(
                    RunEventType.TOOL_COMPLETED,
                    {
                        "tool": data.get("toolName"),
                        "tool_use_id": data.get("toolCallId"),
                        "is_error": bool(data.get("isError")),
                        "output": short(data.get("result"), 4000),
                    },
                )
            ]
        return []
