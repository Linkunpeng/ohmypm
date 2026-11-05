from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ohmypm.cli.common import reset_service
from ohmypm.cli.main import app
from tests.conftest import tree_snapshot

runner = CliRunner()


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch):
    def run(*args: str, cwd: Path | None = None, input: str | None = None, ok: bool = True):
        reset_service()
        if cwd is not None:
            monkeypatch.chdir(cwd)
        result = runner.invoke(app, list(args), input=input)
        if ok:
            assert result.exit_code == 0, (
                args,
                result.exit_code,
                result.stdout,
                result.stderr,
                result.exception,
            )
        return result

    yield run
    reset_service()


def js(result) -> object:
    return json.loads(result.stdout)


def test_register_status_and_zero_intrusion(cli, workspace: Path) -> None:
    before = tree_snapshot(workspace)
    r = cli("register", "--json", cwd=workspace)
    data = js(r)
    assert data["outcome"] == "created" and data["project"]["name"] == "Robot_WS"
    status = js(cli("status", "--json", cwd=workspace / "src" / "camera"))
    assert status["registered"] is True and status["project"]["id"] == data["project"]["id"]
    assert status["relative_path"] == "src/camera"
    cli(
        "log",
        "add",
        "--type",
        "milestone",
        "--title",
        "完成相机驱动",
        "--content",
        "V4L2 ok",
        cwd=workspace / "src",
    )
    cli("summary", "set", "--content", "## Overview\nRobot", cwd=workspace)
    cli("context", cwd=workspace)
    assert tree_snapshot(workspace) == before


def test_status_unregistered(cli, tmp_path: Path) -> None:
    r = cli("status", "--json", cwd=tmp_path)
    assert js(r)["registered"] is False
    human = cli("status", cwd=tmp_path)
    assert "Not registered" in human.stdout


def test_commands_fail_cleanly_outside_projects(cli, tmp_path: Path) -> None:
    r = cli("log", "add", "--title", "x", "--json", cwd=tmp_path, ok=False)
    assert r.exit_code == 3
    assert r.stdout == ""
    assert json.loads(r.stderr)["error"]["code"] == "project_not_registered"
    r = cli("context", cwd=tmp_path, ok=False)
    assert r.exit_code == 3 and "ohmypm register" in r.stderr


def test_log_add_variants(cli, workspace: Path, tmp_path: Path) -> None:
    cli("register", cwd=workspace)
    e1 = js(
        cli(
            "log",
            "add",
            "-T",
            "milestone",
            "-t",
            "完成相机驱动",
            "-c",
            "已实现 V4L2。",
            "--author",
            "codex",
            "--json",
            cwd=workspace,
        )
    )
    assert e1["sequence"] == 1 and e1["source"] == "cli" and e1["author"] == "codex"

    md = tmp_path / "issue.md"
    md.write_text("## 错误\n```\nundefined reference\n```\n", encoding="utf-8")
    e2 = js(
        cli(
            "log",
            "add",
            "--type",
            "issue",
            "--title",
            "OpenCV 链接失败",
            "--file",
            str(md),
            "--json",
            cwd=workspace,
        )
    )
    assert e2["status"] == "open" and "undefined reference" in e2["content"]

    e3 = js(
        cli(
            "log",
            "add",
            "--type",
            "issue",
            "--title",
            "stdin",
            "--stdin",
            "--json",
            cwd=workspace,
            input="来自标准输入 ✓\n",
        )
    )
    assert e3["content"] == "来自标准输入 ✓\n"

    e4 = js(
        cli(
            "log",
            "add",
            "-t",
            "meta",
            "-m",
            "confidence=hypothesis",
            "-m",
            'files=["a.c"]',
            "--json",
            cwd=workspace,
        )
    )
    assert e4["metadata"] == {"confidence": "hypothesis", "files": ["a.c"]}

    r = cli("log", "add", "-t", "x", "-c", "a", "--stdin", cwd=workspace, ok=False)
    assert r.exit_code == 5
    r = cli("log", "add", "-t", "x", "--type", "bogus", cwd=workspace, ok=False)
    assert r.exit_code == 5 and "Allowed" in r.stderr
    r = cli("log", "add", "-t", "x", "--status", "done", "--json", cwd=workspace, ok=False)
    assert r.exit_code == 5 and json.loads(r.stderr)["error"]["code"] == "validation_error"


def test_log_list_show_edit_delete(cli, workspace: Path) -> None:
    cli("register", cwd=workspace)
    for i in range(5):
        cli(
            "log",
            "add",
            "-t",
            f"entry {i}",
            "-T",
            "issue" if i == 2 else "note",
            "-c",
            f"body {i}",
            cwd=workspace,
        )
    listing = js(cli("log", "list", "--json", cwd=workspace))
    assert [e["sequence"] for e in listing["items"]] == [1, 2, 3, 4, 5] and listing["total"] == 5
    latest = js(cli("log", "list", "-n", "2", "--json", cwd=workspace))
    assert [e["sequence"] for e in latest["items"]] == [4, 5]
    newest = js(cli("log", "list", "-n", "2", "--reverse", "--json", cwd=workspace))
    assert [e["sequence"] for e in newest["items"]] == [5, 4]
    assert js(cli("log", "list", "--type", "issue", "--json", cwd=workspace))["total"] == 1
    assert js(cli("log", "list", "--since", "1h", "--until", "today", "--json", cwd=workspace))["total"] == 5
    assert "entry 3" in cli("log", "list", cwd=workspace).stdout

    show = js(cli("log", "show", "#3", "--json", cwd=workspace))
    assert show["content"] == "body 2"
    assert cli("log", "show", "3", "--raw", cwd=workspace).stdout.strip() == "body 2"

    edited = js(
        cli(
            "log",
            "edit",
            "3",
            "--status",
            "resolved",
            "--append",
            "-c",
            "Fix: relink",
            "--json",
            cwd=workspace,
        )
    )
    assert edited["changed"] and edited["entry"]["content"] == "body 2\n\nFix: relink"
    assert edited["entry"]["status"] == "resolved"
    history = js(cli("log", "history", "3", "--json", cwd=workspace))
    assert history[0]["content"] == "body 2"
    restored = js(cli("log", "restore", "3", "--revision", "1", "--json", cwd=workspace))
    assert restored["content"] == "body 2"

    r = cli("log", "delete", "1", cwd=workspace, ok=False)  # no TTY, no --yes
    assert r.exit_code == 5 and "--yes" in r.stderr
    cli("log", "delete", "1", "--yes", cwd=workspace)
    assert js(cli("log", "list", "--json", cwd=workspace))["total"] == 4
    assert js(cli("log", "deleted", "--json", cwd=workspace))[0]["sequence"] == 1
    r = cli("log", "show", "1", cwd=workspace, ok=False)
    assert r.exit_code == 4


def test_summary_commands(cli, workspace: Path, tmp_path: Path) -> None:
    cli("register", cwd=workspace)
    summary_file = tmp_path / "summary.md"
    summary_file.write_text(
        "# Robot\n\n## 项目简介\nROS2 工作空间\n\n## Next Steps\n- 标定\n", encoding="utf-8"
    )
    r = js(cli("summary", "set", "--file", str(summary_file), "--author", "claude", "--json", cwd=workspace))
    assert (
        r["changed"]
        and r["summary"]["overview"] == "ROS2 工作空间"
        and r["summary"]["updated_by"] == "claude"
    )
    cli("summary", "set", "--section", "known-issues", "--content", "- 丢帧", cwd=workspace, ok=False)
    cli("summary", "set", "--section", "Known Issues", "--content", "- 丢帧", cwd=workspace)
    shown = cli("summary", "show", cwd=workspace).stdout
    assert "## Overview" in shown and "ROS2 工作空间" in shown and "- 丢帧" in shown
    assert cli("summary", "show", "--section", "next_steps", cwd=workspace).stdout.strip() == "- 标定"
    # Round trip: show -> set leaves it unchanged.
    again = js(cli("summary", "set", "--stdin", "--json", cwd=workspace, input=shown))
    assert again["changed"] is False
    assert len(js(cli("summary", "history", "--json", cwd=workspace))) == 1
    r = cli("summary", "set", "--content", "no headings here", cwd=workspace, ok=False)
    assert r.exit_code == 5


def test_context_and_search(cli, workspace: Path, tmp_path: Path) -> None:
    cli("register", cwd=workspace)
    cli(
        "log",
        "add",
        "-T",
        "issue",
        "-t",
        "OpenCV 链接失败",
        "-c",
        "undefined reference to cv::Mat",
        cwd=workspace,
    )
    cli("log", "add", "-T", "milestone", "-t", "完成相机驱动", "-c", "V4L2 图像采集", cwd=workspace)
    md = cli("context", cwd=workspace).stdout
    assert md.startswith("# Project context: Robot_WS") and "OpenCV 链接失败" in md
    data = js(cli("context", "--mode", "standard", "--json", cwd=workspace))
    assert data["mode"] == "standard" and data["stats"]["open_issues"] == 1
    full = js(cli("context", "--mode", "full", "--page-size", "1", "--json", cwd=workspace))
    assert full["pagination"]["has_more"] is True
    assert cli("context", "--mode", "nope", cwd=workspace, ok=False).exit_code == 5

    hits = js(cli("search", "相机", "--json", cwd=workspace))
    assert hits["total"] == 1 and hits["items"][0]["title"] == "完成相机驱动"
    other = tmp_path / "elsewhere"
    other.mkdir()
    outside = cli("search", "cv::Mat", cwd=other)
    assert "searching all projects" in outside.stdout and "OpenCV" in outside.stdout


def test_project_isolation(cli, tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    cli("register", cwd=a)
    cli("register", cwd=b)
    cli("log", "add", "-t", "only in a", cwd=a)
    cli("log", "add", "-t", "only in b", cwd=b)
    titles_a = [e["title"] for e in js(cli("log", "list", "--json", cwd=a))["items"]]
    assert titles_a == ["only in a"]
    assert js(cli("search", "only", "--json", cwd=b))["items"][0]["title"] == "only in b"
    assert "only in b" not in cli("context", cwd=a).stdout
    # Explicit --project overrides detection.
    titles = [e["title"] for e in js(cli("log", "list", "--project", "b", "--json", cwd=a))["items"]]
    assert titles == ["only in b"]


def test_project_management(cli, workspace: Path, tmp_path: Path) -> None:
    cli("register", "--name", "Robot", "--description", "ROS2", cwd=workspace)
    assert js(cli("list", "--json"))[0]["name"] == "Robot"
    cli("project", "rename", "Robot WS", cwd=workspace)
    cli("project", "describe", "机器人工作空间", cwd=workspace)
    info = js(cli("project", "info", "--json", cwd=workspace))
    assert info["name"] == "Robot WS" and info["description"] == "机器人工作空间"

    moved = tmp_path / "moved"
    workspace.rename(moved)
    r = cli("project", "relink", str(moved), cwd=moved, ok=False)
    assert r.exit_code == 3  # cwd is not registered any more
    relinked = js(cli("project", "relink", str(moved), "--project", info["id"], "--json", cwd=moved))
    assert relinked["root_path"] == str(moved.resolve())
    assert js(cli("status", "--json", cwd=moved))["registered"]

    cli("unregister", cwd=moved)
    assert js(cli("status", "--json", cwd=moved))["registered"] is False
    assert js(cli("list", "--all", "--json"))[0]["archived"] is True
    assert js(cli("register", "--json", cwd=moved))["outcome"] == "reactivated"
    r = cli("unregister", "--purge", cwd=moved, ok=False)
    assert r.exit_code == 5
    cli("unregister", "--purge", "--yes", cwd=moved)
    assert js(cli("list", "--all", "--json")) == []
    assert moved.is_dir()


def test_assets_cli(cli, workspace: Path, tmp_path: Path) -> None:
    from tests.test_assets import make_png

    cli("register", cwd=workspace)
    img = tmp_path / "shot.png"
    img.write_bytes(make_png())
    ref = cli("assets", "add", str(img), cwd=workspace).stdout.strip()
    assert ref.startswith("![shot.png](ohmypm-asset://")
    listed = js(cli("assets", "list", "--json", cwd=workspace))
    assert len(listed) == 1
    path = cli("assets", "path", listed[0]["id"]).stdout.strip()
    assert Path(path).read_bytes() == make_png()
    gc = js(cli("assets", "gc", "--grace-hours", "0", "--json", cwd=workspace))
    assert gc["applied"] is False and len(gc["assets"]) == 1
    bad = tmp_path / "x.bin"
    bad.write_bytes(b"\x00\x01\x02")
    assert cli("assets", "add", str(bad), cwd=workspace, ok=False).exit_code == 5


def test_export_backup_restore(cli, workspace: Path, tmp_path: Path, settings) -> None:
    from tests.test_assets import make_png

    cli("register", cwd=workspace)
    img = tmp_path / "shot.png"
    img.write_bytes(make_png())
    ref = cli("assets", "add", str(img), cwd=workspace).stdout.strip()
    cli("log", "add", "-t", "带图片的记录", "-c", f"截图：{ref}", cwd=workspace)
    cli("summary", "set", "-c", "## Overview\nRobot", cwd=workspace)

    before = tree_snapshot(workspace)
    exported = js(cli("export", "--json", cwd=workspace))
    export_dir = Path(exported["path"])
    assert settings.data_dir in export_dir.parents  # default location is private, not the cwd
    project_dir = export_dir / exported["projects"][0]["dir"]
    entry_file = next((project_dir / "entries").glob("0001-*.md"))
    text = entry_file.read_text(encoding="utf-8")
    assert "../assets/" in text and "ohmypm-asset://" not in text
    assert (project_dir / "summary.md").read_text(encoding="utf-8").count("Robot") >= 1
    assert len(list((project_dir / "assets").iterdir())) == 1
    assert tree_snapshot(workspace) == before

    archive = Path(js(cli("backup", "--json"))["path"])
    assert archive.is_file() and oct(archive.stat().st_mode & 0o777) == "0o600"
    cli("log", "add", "-t", "after backup", cwd=workspace)
    assert cli("restore", str(archive), ok=False).exit_code == 5  # needs --yes
    restored = js(cli("restore", str(archive), "--yes", "--json"))
    assert Path(restored["previous_data"]).is_dir()
    titles = [e["title"] for e in js(cli("log", "list", "--json", cwd=workspace))["items"]]
    assert titles == ["带图片的记录"]
    asset_id = js(cli("assets", "list", "--json", cwd=workspace))[0]["id"]
    assert Path(cli("assets", "path", asset_id).stdout.strip()).is_file()


def test_help_and_version(cli) -> None:
    assert "ohmypm" in cli("--version").stdout
    for args in (
        ["--help"],
        ["log", "--help"],
        ["log", "add", "--help"],
        ["summary", "set", "--help"],
        ["agents", "--help"],
        ["context", "--help"],
    ):
        assert "Usage" in cli(*args).stdout


def test_real_entry_point_subprocess(workspace: Path, tmp_path: Path) -> None:
    """The installed console script works without any server running."""
    exe = Path(sys.executable).with_name("ohmypm")
    assert exe.exists(), "run `uv sync` to install the console script"
    env = {**os.environ}

    def run(*args: str, cwd: Path, input: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(exe), *args], cwd=cwd, env=env, input=input, capture_output=True, text=True, timeout=60
        )

    assert json.loads(run("status", "--json", cwd=tmp_path).stdout)["registered"] is False
    assert run("register", cwd=workspace).returncode == 0
    p = run(
        "log",
        "add",
        "--type",
        "issue",
        "--title",
        "管道输入",
        "--stdin",
        "--json",
        cwd=workspace / "src",
        input="body via pipe\n",
    )
    assert p.returncode == 0 and json.loads(p.stdout)["sequence"] == 1 and p.stderr == ""
    bad = run("log", "show", "99", "--json", cwd=workspace)
    assert bad.returncode == 4 and bad.stdout == "" and json.loads(bad.stderr)["error"]["code"] == "not_found"
    usage = run("log", "add", cwd=workspace)
    assert usage.returncode == 2
