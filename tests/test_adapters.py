"""Adapter argv construction and output parsing (fixtures are trimmed real transcripts)."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from ohmypm_common.agent_options import OptionsError, parse_options
from ohmypm_common.enums import RunStatus
from ohmypm_common.redact import Redactor
from ohmypm_runner.adapters.base import ParseState, RunContext
from ohmypm_runner.adapters.claude import ClaudeAdapter
from ohmypm_runner.adapters.codex import CodexAdapter
from ohmypm_runner.adapters.custom import CustomAgentSpec, load_custom_agents
from ohmypm_runner.adapters.dsh import DshAdapter
from ohmypm_runner.adapters.pi import PiAdapter
from ohmypm_runner.config import AgentSettings, RunnerConfig
from ohmypm_runner.workspace import WorkspaceError, resolve_workspace

FIXTURES = Path(__file__).parent / "fixtures" / "agent_output"
TRUE = shutil.which("true") or "/usr/bin/true"


def config(tmp_path: Path, **kw: object) -> RunnerConfig:
    agents = {name: AgentSettings(executable=TRUE) for name in ("claude", "codex", "pi", "dsh")}
    return RunnerConfig(
        token="t",
        allowed_roots=[str(tmp_path)],
        agents=agents,
        state_dir=str(tmp_path / "state"),
        custom_agents_dir=str(tmp_path / "agents.d"),
        **kw,
    )  # type: ignore[arg-type]


def ctx(tmp_path: Path, agent: str, options: dict[str, object] | None = None, **kw: object) -> RunContext:
    return RunContext(
        run_id="r1",
        task_id="t1",
        session_id=None,
        workspace=tmp_path,
        prompt="do it",
        options=parse_options(agent, options or {}),
        agent_token="omr_secret_token_value_123456",
        server_url="http://127.0.0.1:8765",
        temp_dir=tmp_path,
        **kw,
    )  # type: ignore[arg-type]


def parse(adapter, name: str) -> tuple[list, ParseState]:  # type: ignore[no-untyped-def]
    state = ParseState()
    events = []
    for line in (FIXTURES / name).read_text().splitlines():
        events.extend(adapter.parse_line(line, state))
    return events, state


def test_claude_argv_and_mcp_injection(tmp_path: Path) -> None:
    adapter = ClaudeAdapter(config(tmp_path))
    spec = adapter.build_launch(ctx(tmp_path, "claude", {"model": "sonnet", "allowed_tools": ["Bash(git diff:*)"]}))
    argv = spec.argv
    assert argv[:5] == [TRUE, "-p", "--output-format", "stream-json", "--verbose"]
    assert argv[argv.index("--permission-prompts") + 1] == "none", "unattended runs fail closed"
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "--dangerously-skip-permissions" not in argv
    mcp_file = Path(argv[argv.index("--mcp-config") + 1])
    assert oct(mcp_file.stat().st_mode & 0o777) == "0o600"
    assert json.loads(mcp_file.read_text())["mcpServers"]["ohmypm"]["url"] == "http://127.0.0.1:8765/mcp"
    assert spec.stdin_data == b"do it", "prompt goes through stdin, not argv"
    assert "do it" not in argv
    assert spec.env["OHMYPM_AGENT_TOKEN"] == "omr_secret_token_value_123456"
    assert spec.cwd == tmp_path
    tools = argv[argv.index("--allowed-tools") + 1 : argv.index("--mcp-config")]
    assert tools == ["Bash(git diff:*)", "mcp__ohmypm"], "injected ohmypm tools are pre-approved"


def test_claude_resume(tmp_path: Path) -> None:
    spec = ClaudeAdapter(config(tmp_path)).build_launch(
        ctx(tmp_path, "claude", {"inject_mcp": False}, native_session_id="abc", resume_native=True)
    )
    assert spec.argv[-2:] == ["--resume", "abc"]


def test_claude_parse_real_transcript(tmp_path: Path) -> None:
    events, state = parse(ClaudeAdapter(config(tmp_path)), "claude_stream.jsonl")
    types = [e.type for e in events]
    assert types[0] == "agent.started"
    assert "tool.started" in types and "tool.completed" in types
    assert any(e.type == "file.changed" and e.payload["path"] == "/work/demo/app.py" for e in events)
    assert any(e.type == "approval.denied" for e in events)
    assert types[-1] == "agent.result"
    assert state.native_session_id == "d75b0db2-8a0a-496f-9a7d-35bbe350e3e4"
    outcome = ClaudeAdapter(config(tmp_path)).finalize(state, 0)
    assert outcome.status is RunStatus.COMPLETED and outcome.result_summary == "OK"
    assert outcome.usage["total_cost_usd"] > 0


def test_codex_argv(tmp_path: Path) -> None:
    adapter = CodexAdapter(config(tmp_path))
    argv = adapter.build_launch(ctx(tmp_path, "codex", {"model": "gpt-5"})).argv
    assert argv[:3] == [TRUE, "exec", "--json"]
    assert 'sandbox_mode="workspace-write"' in argv and 'approval_policy="never"' in argv
    assert 'mcp_servers.ohmypm.bearer_token_env_var="OHMYPM_AGENT_TOKEN"' in argv
    assert not any("omr_" in a for a in argv), "token is passed by env var name, not value"
    assert argv[-1] == "-"
    resumed = adapter.build_launch(
        ctx(tmp_path, "codex", {"config_profile": "work"}, native_session_id="thread-1", resume_native=True)
    ).argv
    assert resumed[:3] == [TRUE, "exec", "resume"] and resumed[-2:] == ["thread-1", "-"]
    assert "-p" not in resumed, "exec resume does not accept --profile"


def test_codex_parse(tmp_path: Path) -> None:
    adapter = CodexAdapter(config(tmp_path))
    events, state = parse(adapter, "codex_stream.jsonl")
    types = [e.type for e in events]
    assert types[0] == "agent.started" and state.native_session_id == "01a18607-4b15-76f3-a088-625ac961fd13"
    assert "agent.warning" in types, "reconnect notices are warnings, not failures"
    assert any(e.type == "tool.completed" and e.payload["output"] == "3 passed" for e in events)
    assert any(e.type == "file.changed" for e in events)
    outcome = adapter.finalize(state, 0)
    assert outcome.status is RunStatus.COMPLETED and outcome.result_summary == "Done. Tests pass."
    assert state.usage["input_tokens"] == 1200
    state2 = ParseState()
    adapter.parse_line(json.dumps({"type": "turn.failed", "error": {"message": "quota"}}), state2)
    assert adapter.finalize(state2, 1).status is RunStatus.FAILED


def test_pi_failure_detected_despite_exit_zero(tmp_path: Path) -> None:
    adapter = PiAdapter(config(tmp_path))
    events, state = parse(adapter, "pi_stream.jsonl")
    assert any(e.type == "agent.error" for e in events)
    outcome = adapter.finalize(state, 0)
    assert outcome.status is RunStatus.FAILED and "failed to load model" in (outcome.error or "")


def test_pi_success_and_tools(tmp_path: Path) -> None:
    adapter = PiAdapter(config(tmp_path))
    state = ParseState()
    lines = [
        {"type": "session", "id": "s-1"},
        {"type": "tool_execution_start", "toolCallId": "c1", "toolName": "write", "args": {"path": "a.txt"}},
        {"type": "tool_execution_end", "toolCallId": "c1", "toolName": "write", "result": "ok", "isError": False},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "All done"}],
                "stopReason": "stop",
                "usage": {"input": 5, "output": 2},
            },
        },
    ]
    events = [e for line in lines for e in adapter.parse_line(json.dumps(line), state)]
    assert [e.type for e in events] == [
        "agent.started",
        "tool.started",
        "file.changed",
        "tool.completed",
        "agent.message",
    ]
    assert adapter.finalize(state, 0).status is RunStatus.COMPLETED


def test_pi_argv_defaults_exclude_bash(tmp_path: Path) -> None:
    argv = PiAdapter(config(tmp_path)).build_launch(ctx(tmp_path, "pi")).argv
    tools = argv[argv.index("--tools") + 1].split(",")
    assert "bash" not in tools and "edit" in tools
    assert parse_options("pi", {"tools": ["read", "bash"]}).dangerous_reasons()


def test_dsh(tmp_path: Path) -> None:
    adapter = DshAdapter(config(tmp_path))
    spec = adapter.build_launch(ctx(tmp_path, "dsh"))
    assert spec.argv == [TRUE, "--profile", "headless", "--json", "-"]
    assert spec.env["DSH_PERMISSION_MODE"] == "workspace-write"
    _, state = parse(adapter, "dsh_stream.jsonl")
    assert state.native_session_id == "session-c6b822f4-8cb0-4438-91b0-d22d91e65272"
    outcome = adapter.finalize(state, 1)
    assert outcome.status is RunStatus.FAILED and "MISSING_CREDENTIAL" in (outcome.error or "")


def test_options_validation() -> None:
    with pytest.raises(OptionsError):
        parse_options("claude", {"permission_mode": "yolo"})
    with pytest.raises(OptionsError):
        parse_options("claude", {"extra_args": ["--dangerously-skip-permissions"]})
    with pytest.raises(OptionsError):
        parse_options("codex", {"model": "gpt; rm -rf /"})
    assert parse_options("claude", {"permission_mode": "bypassPermissions"}).dangerous_reasons()
    assert parse_options("codex", {"sandbox": "danger-full-access"}).dangerous_reasons()
    assert not parse_options("codex", {}).dangerous_reasons()
    with pytest.raises(OptionsError):
        parse_options("my-custom", {"anything": 1})


def test_unavailable_cli(tmp_path: Path) -> None:
    import asyncio

    cfg = config(tmp_path)
    cfg.agents["claude"] = AgentSettings(executable="/nonexistent/claude")
    cap = asyncio.run(ClaudeAdapter(cfg).check_available())
    assert cap.available is False and "not found" in (cap.detail or "")


def test_workspace_allowlist(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    (allowed / "proj").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (allowed / "escape").symlink_to(outside)
    assert resolve_workspace(str(allowed / "proj"), [str(allowed)]) == (allowed / "proj").resolve()
    with pytest.raises(WorkspaceError, match="outside"):
        resolve_workspace(str(allowed / "escape"), [str(allowed)])
    with pytest.raises(WorkspaceError, match="outside"):
        resolve_workspace(str(allowed / ".." / "outside"), [str(allowed)])
    with pytest.raises(WorkspaceError, match="does not exist"):
        resolve_workspace(str(allowed / "missing"), [str(allowed)])
    with pytest.raises(WorkspaceError, match="no allowed_roots"):
        resolve_workspace(str(allowed / "proj"), [])


def test_custom_agents_require_trust(tmp_path: Path) -> None:
    agents = tmp_path / "agents.d"
    agents.mkdir()
    (agents / "mine.yaml").write_text(
        "id: mine\nname: Mine\nexecutable: " + sys.executable + "\nargs: ['-c', 'print(1)', '{workspace}']\n"
    )
    adapters, warnings = load_custom_agents(config(tmp_path))
    assert adapters == [] and "not listed in trusted_custom_agents" in warnings[0]
    adapters, warnings = load_custom_agents(config(tmp_path, trusted_custom_agents=["mine"]))
    assert [a.agent_type for a in adapters] == ["mine"]
    spec = adapters[0].build_launch(ctx(tmp_path, "mine"))
    assert spec.argv == [sys.executable, "-c", "print(1)", str(tmp_path)]
    with pytest.raises(ValueError):
        CustomAgentSpec.model_validate({"id": "rel", "name": "x", "executable": "my-agent"})
    with pytest.raises(ValueError):
        CustomAgentSpec.model_validate({"id": "claude", "name": "x", "executable": "/bin/true"})


def test_redaction() -> None:
    r = Redactor(["omr_secret_token_value_123456"])
    text = r.text("token omr_secret_token_value_123456 key sk-ant-abcdefghijklmnopqrstuv Bearer abcdefghijklmnopqrstu")
    assert "omr_secret" not in text and "sk-ant-abc" not in text and "abcdefghijklmnopqrstu" not in text
    assert r.text("password=hunter2hunter") == "password=[REDACTED]"
    assert r.value({"a": ["api_key: 1234567890abc"]}) == {"a": ["api_key: [REDACTED]"]}


def test_child_env_drops_runner_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHMYPM_RUNNER_TOKEN", "runner-secret")
    monkeypatch.setenv("OHMYPM_TOKEN", "admin-secret")
    monkeypatch.setenv("HOME", os.environ.get("HOME", "/root"))
    env = ClaudeAdapter(config(tmp_path)).build_launch(ctx(tmp_path, "claude")).env
    assert "OHMYPM_RUNNER_TOKEN" not in env and "OHMYPM_TOKEN" not in env
    assert env["HOME"] and env["OHMYPM_RUN_ID"] == "r1"
