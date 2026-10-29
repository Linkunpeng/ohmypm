"""CLI against a live server: project init/info, task create/list/show, context, checkpoint, runner status."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ohmypm_cli.main import app
from tests.conftest import ADMIN_TOKEN, LiveServer


@pytest.fixture
def cli(live_server: LiveServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OHMYPM_URL", live_server.url)
    monkeypatch.setenv("OHMYPM_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("OHMYPM_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("OHMYPM_HOST_ID", "cli-host")
    for var in ("OHMYPM_RUN_ID", "OHMYPM_AGENT_TOKEN", "OHMYPM_TASK_ID"):
        monkeypatch.delenv(var, raising=False)
    runner = CliRunner()

    def invoke(*args: str) -> str:
        result = runner.invoke(app, list(args), catch_exceptions=False)
        assert result.exit_code == 0, result.output
        return result.output

    return invoke


def test_cli_project_task_flow(cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "robot"
    (root / "src").mkdir(parents=True)
    out = cli("project", "init", str(root), "--name", "Robot")
    assert "created PROJECT_ID" in out and "registered project Robot" in out
    pid = (root / "PROJECT_ID").read_text().strip()
    out = cli("project", "init", str(root))
    assert "found existing" in out and "already registered" in out
    assert (root / "PROJECT_ID").read_text().strip() == pid, "never overwritten"

    monkeypatch.chdir(root / "src")
    out = cli("project", "info")
    assert "Robot" in out and "cli-host" in out
    out = cli("task", "create", "Add lidar driver", "-c", "driver publishes /scan")
    assert "created T-1" in out
    out = cli("task", "list")
    assert "Add lidar driver" in out
    out = cli(
        "checkpoint",
        "add",
        "--task",
        "T-1",
        "--summary",
        "Driver skeleton",
        "--next",
        "wire up serial",
        "--attempt",
        "baud 9600 => garbage",
        "--remaining",
        "publish scans",
    )
    assert "checkpoint" in out
    out = cli("context", "T-1", "--raw")
    assert "wire up serial" in out and "baud 9600" in out
    out = cli("--json", "task", "show", "T-1")
    assert '"next_action": "wire up serial"' in out
    out = cli("project", "list")
    assert "Robot" in out
    out = cli("search", "lidar")
    assert "Add lidar driver" in out
    out = cli("mcp", "config", "codex")
    assert "bearer_token_env_var" in out


def test_cli_anonymous_workspace(cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.chdir(scratch)
    out = cli("project", "info")
    assert "anonymous workspace" in out
    cli("task", "create", "Quick experiment")
    out = cli("task", "list", "--anonymous")
    assert "Quick experiment" in out
    out = cli("status")
    assert "server" in out and "ok" in out
