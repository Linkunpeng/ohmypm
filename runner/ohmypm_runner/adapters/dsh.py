"""DeepSeek Harness (dsh) adapter.

Verified against dsh 0.2.0-rc.2 ``dsh headless --help`` and a real ``--json`` transcript:
``dsh --profile headless --json -`` reads the task from stdin and writes newline-delimited run events
(``session{sessionId}``, ``status{phase, ...}``, ``final{text}``); exit code 1 on failure. The
sandbox is selected with the ``DSH_PERMISSION_MODE`` environment variable (read by the shipped
``sandbox-policy`` and ``approval`` plugins). Event types beyond these are passed through as
``agent.status`` until their schema is confirmed.
"""

from __future__ import annotations

from ohmypm_common.agent_options import DshOptions
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


class DshAdapter(BaseAdapter):
    agent_type = "dsh"
    display_name = "DeepSeek Harness"
    default_executable = "dsh"

    def build_launch(self, ctx: RunContext) -> LaunchSpec:
        opts: DshOptions = ctx.options
        exe = self.executable()
        assert exe is not None
        argv = [exe, "--profile", opts.profile, "--json"]
        if ctx.resume_native and ctx.native_session_id:
            argv += ["--session-id", ctx.native_session_id]
        argv.append("-")
        env = self.base_env(ctx)
        env["DSH_PERMISSION_MODE"] = opts.permission_mode
        return LaunchSpec(
            argv=argv, cwd=ctx.workspace, env=env, stdin_data=ctx.prompt.encode(), display_argv=list(argv)
        )

    def parse_line(self, line: str, state: ParseState) -> list[AgentEvent]:
        data = parse_json_line(line)
        if data is None:
            return [output_event(line)] if line.strip() else []
        kind = data.get("type")
        if kind == "session":
            state.native_session_id = data.get("sessionId") or state.native_session_id
            return [
                AgentEvent(
                    RunEventType.AGENT_STARTED,
                    {"agent": "dsh", "session_id": data.get("sessionId"), "cwd": data.get("cwd")},
                )
            ]
        if kind == "final":
            text = str(data.get("text") or "")
            if text:
                state.final_text = text
                state.last_message = text
            return [AgentEvent(RunEventType.AGENT_RESULT, {"result": short(text)})]
        if kind == "status":
            reason = data.get("reason") or {}
            if isinstance(reason, dict) and reason.get("kind") == "error":
                err = reason.get("error") or {}
                state.errored = True
                state.error = short(f"{err.get('code', 'error')}: {err.get('message', '')}", 2000)
                return [AgentEvent(RunEventType.AGENT_ERROR, {"message": state.error, "code": err.get("code")})]
            return [AgentEvent(RunEventType.AGENT_STATUS, {k: v for k, v in data.items() if k != "type"})]
        if kind in ("message", "assistant", "text") and data.get("text"):
            state.last_message = str(data["text"])
            return [AgentEvent(RunEventType.AGENT_MESSAGE, {"text": short(str(data["text"]))})]
        return [AgentEvent(RunEventType.AGENT_STATUS, {"dsh_event": kind, "detail": short(data, 2000)})]
