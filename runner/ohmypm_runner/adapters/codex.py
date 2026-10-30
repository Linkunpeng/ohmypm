"""Codex CLI adapter.

Verified against codex-cli 0.164.0 ``codex exec --help`` / ``codex exec resume --help`` and a real
``--json`` transcript. ``codex exec --json -`` reads the prompt from stdin and emits JSONL events:
``thread.started{thread_id}``, ``turn.started``, ``item.started|updated|completed{item}``,
``turn.completed{usage}``, ``turn.failed{error}`` and top-level ``error{message}`` (often transient
"Reconnecting…" notices). ``exec resume`` lacks ``-s``/``-C``/``-p``, so sandbox and approval policy
are passed as ``-c`` config overrides, which both forms accept.
"""

from __future__ import annotations

import json
from typing import Any

from ohmypm_common.agent_options import CodexOptions
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


def _toml(value: str) -> str:
    return json.dumps(value)  # a JSON string literal is a valid TOML basic string


class CodexAdapter(BaseAdapter):
    supports_native_resume = True
    agent_type = "codex"
    display_name = "Codex CLI"
    default_executable = "codex"

    def build_launch(self, ctx: RunContext) -> LaunchSpec:
        opts: CodexOptions = ctx.options
        exe = self.executable()
        assert exe is not None
        resume = bool(ctx.resume_native and ctx.native_session_id)
        argv = [exe, "exec"] + (["resume"] if resume else [])
        argv += ["--json", "-c", f"sandbox_mode={_toml(opts.sandbox)}", "-c", 'approval_policy="never"']
        if opts.skip_git_repo_check:
            argv.append("--skip-git-repo-check")
        if opts.model:
            argv += ["-m", opts.model]
        if opts.reasoning_effort:
            argv += ["-c", f"model_reasoning_effort={_toml(opts.reasoning_effort)}"]
        if opts.network_access:
            argv += ["-c", "sandbox_workspace_write.network_access=true"]
        if opts.config_profile and not resume:
            argv += ["-p", opts.config_profile]
        if opts.inject_mcp:
            argv += [
                "-c",
                f"mcp_servers.ohmypm.url={_toml(ctx.mcp_url)}",
                "-c",
                'mcp_servers.ohmypm.bearer_token_env_var="OHMYPM_AGENT_TOKEN"',
            ]
        if resume:
            argv.append(str(ctx.native_session_id))
        argv.append("-")
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
        if kind == "thread.started":
            state.native_session_id = data.get("thread_id") or state.native_session_id
            return [AgentEvent(RunEventType.AGENT_STARTED, {"agent": "codex", "session_id": data.get("thread_id")})]
        if kind == "turn.started":
            return [AgentEvent(RunEventType.AGENT_STATUS, {"phase": "turn.started"})]
        if kind == "turn.completed":
            usage = data.get("usage") or {}
            for key, value in usage.items():
                if isinstance(value, int | float):
                    state.usage[key] = state.usage.get(key, 0) + value
            return [AgentEvent(RunEventType.AGENT_USAGE, {"usage": usage})]
        if kind == "turn.failed":
            state.errored = True
            err = data.get("error") or {}
            state.error = str(err.get("message") if isinstance(err, dict) else err)[:2000]
            return [AgentEvent(RunEventType.AGENT_ERROR, {"message": state.error})]
        if kind == "error":
            # Usually transient (reconnects); a real failure also produces turn.failed / non-zero exit.
            return [AgentEvent(RunEventType.AGENT_WARNING, {"message": short(str(data.get("message")), 2000)})]
        if kind in ("item.started", "item.updated", "item.completed"):
            return self._item(kind, data.get("item") or {}, state)
        return []

    def _item(self, kind: str, item: dict[str, Any], state: ParseState) -> list[AgentEvent]:
        itype = item.get("type")
        done = kind == "item.completed"
        if itype == "agent_message":
            if not done:
                return []
            text = str(item.get("text") or "")
            state.last_message = text
            state.final_text = text
            return [AgentEvent(RunEventType.AGENT_MESSAGE, {"text": short(text)})]
        if itype == "reasoning":
            return (
                [AgentEvent(RunEventType.AGENT_THINKING, {"text": short(str(item.get("text") or ""), 2000)})]
                if done
                else []
            )
        if itype == "command_execution":
            if kind == "item.started":
                return [
                    AgentEvent(
                        RunEventType.TOOL_STARTED,
                        {"tool": "shell", "tool_use_id": item.get("id"), "input": short(item.get("command"), 4000)},
                    )
                ]
            if done:
                return [
                    AgentEvent(
                        RunEventType.TOOL_COMPLETED,
                        {
                            "tool": "shell",
                            "tool_use_id": item.get("id"),
                            "exit_code": item.get("exit_code"),
                            "is_error": item.get("status") == "failed" or (item.get("exit_code") not in (0, None)),
                            "output": short(str(item.get("aggregated_output") or ""), 4000),
                        },
                    )
                ]
            return []
        if itype == "file_change":
            if not done:
                return []
            return [
                AgentEvent(RunEventType.FILE_CHANGED, {"path": c.get("path"), "kind": c.get("kind")})
                for c in item.get("changes") or []
                if isinstance(c, dict)
            ]
        if itype == "mcp_tool_call":
            name = f"{item.get('server')}.{item.get('tool')}"
            if kind == "item.started":
                return [
                    AgentEvent(
                        RunEventType.TOOL_STARTED,
                        {"tool": name, "tool_use_id": item.get("id"), "input": short(item.get("arguments"), 4000)},
                    )
                ]
            if done:
                return [
                    AgentEvent(
                        RunEventType.TOOL_COMPLETED,
                        {
                            "tool": name,
                            "tool_use_id": item.get("id"),
                            "is_error": bool(item.get("error")),
                            "output": short(item.get("error") or item.get("result"), 4000),
                        },
                    )
                ]
            return []
        if itype == "web_search" and done:
            return [AgentEvent(RunEventType.TOOL_COMPLETED, {"tool": "web_search", "input": item.get("query")})]
        if itype == "todo_list":
            return [AgentEvent(RunEventType.AGENT_PLAN, {"items": short(item.get("items"), 4000)})]
        if itype == "error" and done:
            return [AgentEvent(RunEventType.AGENT_WARNING, {"message": short(str(item.get("message")), 2000)})]
        return []
