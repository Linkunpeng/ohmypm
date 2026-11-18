"""Detection of running ohmypm servers that use outdated code (doctor)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ohmypm.processes import package_dir, server_kind, server_processes

TOOL_PY = "/home/u/.local/share/uv/tools/ohmypm/bin/python"


@pytest.mark.parametrize(
    ("argv", "kind"),
    [
        ([TOOL_PY, "/home/u/.local/bin/ohmypm", "mcp"], "mcp"),
        ([TOOL_PY, "/home/u/.local/bin/ohmypm", "web", "--host", "127.0.0.1"], "web"),
        ([TOOL_PY, "-I", "/home/u/.local/bin/ohmypm-mcp"], "mcp"),
        (["/repo/.venv/bin/python3", "-m", "ohmypm", "mcp"], "mcp"),
        (["/home/u/.local/bin/ohmypm", "web"], "web"),
        ([TOOL_PY, "/home/u/.local/bin/ohmypm", "context"], None),  # short-lived command
        (["grep", "ohmypm", "mcp"], None),
        (["/usr/bin/python3", "/tmp/other.py", "mcp"], None),
        ([], None),
    ],
)
def test_server_kind(argv: list[str], kind: str | None) -> None:
    assert server_kind(argv) == kind


def _package(root: Path) -> Path:
    pkg = root / "ohmypm"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    return pkg


def test_package_dir_installed_and_editable(tmp_path: Path) -> None:
    site = tmp_path / "tool" / "lib" / "python3.12" / "site-packages"
    pkg = _package(site)
    assert package_dir([str(tmp_path / "tool" / "bin" / "python"), "x"]) == pkg

    src = _package(tmp_path / "repo" / "src")
    dev_site = tmp_path / "repo" / ".venv" / "lib" / "python3.12" / "site-packages"
    dev_site.mkdir(parents=True)
    (dev_site / "_editable_impl_ohmypm.pth").write_text(str(tmp_path / "repo" / "src"))
    assert package_dir([str(tmp_path / "repo" / ".venv" / "bin" / "python3")]) == src

    assert package_dir(["python3", "-m", "ohmypm"]) is None  # relative interpreter: unknown
    assert package_dir([str(tmp_path / "nowhere" / "bin" / "python")]) is None


def _fake_proc(tmp_path: Path, boot: int) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text(f"cpu 1 2 3\nbtime {boot}\n")
    return proc


def _add_process(proc: Path, pid: int, argv: list[str], start_seconds: float, cgroup: str = "") -> None:
    d = proc / str(pid)
    d.mkdir()
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    ticks = int(start_seconds * os.sysconf("SC_CLK_TCK"))
    rest = ["S"] + ["0"] * 18 + [str(ticks)] + ["0"] * 5
    (d / "stat").write_text(f"{pid} (py thon) " + " ".join(rest))
    (d / "cgroup").write_text(cgroup)


def test_server_processes_flags_outdated_code(tmp_path: Path) -> None:
    site = tmp_path / "tool" / "lib" / "python3.12" / "site-packages"
    pkg = _package(site)
    python = str(tmp_path / "tool" / "bin" / "python")
    boot = 1_700_000_000
    installed = boot + 1000
    os.utime(pkg / "__init__.py", (installed, installed))

    proc = _fake_proc(tmp_path, boot)
    _add_process(proc, 101, [python, "/x/bin/ohmypm", "mcp"], 500)  # before the install
    unit = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/ohmypm-web.service\n"
    _add_process(proc, 102, [python, "/x/bin/ohmypm", "web"], 999.5, cgroup=unit)  # within the slack
    _add_process(proc, 103, ["/usr/bin/python3", "/x/bin/ohmypm", "mcp"], 10)  # package unknown
    _add_process(proc, 104, [python, "/x/bin/ohmypm", "list"], 10)  # not a server
    (proc / "self").mkdir()

    found = {p.pid: p for p in server_processes(proc)}
    assert set(found) == {101, 102, 103}
    assert found[101].outdated is True and found[101].kind == "mcp"
    assert found[101].code_updated_at == datetime.fromtimestamp(installed, UTC)
    assert found[101].restart_hint() == "restart the agent session that started it"
    assert found[102].outdated is False and found[102].unit == "ohmypm-web.service"
    assert found[102].restart_hint() == "systemctl --user restart ohmypm-web.service"
    assert found[103].outdated is None
    assert found[101].to_dict()["outdated"] is True


def test_no_proc_means_no_processes(tmp_path: Path) -> None:
    assert server_processes(tmp_path / "missing") == []


def test_doctor_lists_servers() -> None:
    import json

    from typer.testing import CliRunner

    from ohmypm.cli.common import reset_service
    from ohmypm.cli.main import app

    reset_service()
    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    assert isinstance(json.loads(result.output)["processes"], list)
    result = CliRunner().invoke(app, ["doctor"])
    assert "servers:" in result.output
