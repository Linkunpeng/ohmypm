#!/usr/bin/env python3
"""End-to-end acceptance run of the seven scenarios in the specification.

Installs the built wheel into a fresh virtualenv and drives the *installed*
`ohmypm` command with a throw-away HOME, so nothing on the real machine is
touched::

    ./scripts/build.sh                      # produces dist/ohmypm-*.whl
    python3 scripts/acceptance.py [--web]   # --web also runs the browser test

Requirements: uv; for --web additionally node + pnpm deps in frontend/ and a
Chromium binary (CHROMIUM env var, default /usr/bin/chromium).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASSED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise SystemExit(f"FAIL  {name}  {detail}")
    PASSED.append(name)
    print(f"ok    {name}")


def make_png(width: int, height: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\x2f\x6f\x8f" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        st = path.lstat()
        h.update(str(path.relative_to(root)).encode())
        h.update(str(st.st_mode).encode())
        h.update(str(st.st_mtime_ns).encode())
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", action="store_true", help="also run the browser end-to-end test")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    args = parser.parse_args()

    wheels = sorted((REPO / "dist").glob("ohmypm-*.whl"))
    if not wheels:
        raise SystemExit("No wheel in dist/ - run scripts/build.sh first")
    tmp = Path(tempfile.mkdtemp(prefix="ohmypm-acceptance-"))
    home = tmp / "home"
    home.mkdir()
    venv = tmp / "venv"
    subprocess.run(["uv", "venv", "-q", str(venv)], check=True)
    subprocess.run(
        ["uv", "pip", "install", "-q", "--python", str(venv / "bin" / "python"), str(wheels[-1])], check=True
    )
    exe = venv / "bin" / "ohmypm"
    env = {
        "PATH": f"{venv / 'bin'}:/usr/bin:/bin",
        "HOME": str(home),
        "LANG": "C.UTF-8",
        # Keep `git status` read-only (it otherwise refreshes .git/index).
        "GIT_OPTIONAL_LOCKS": "0",
    }

    def run(*argv: str, cwd: Path, input: str | None = None, ok: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [str(exe), *argv], cwd=cwd, env=env, input=input, capture_output=True, text=True, timeout=120
        )
        if ok and proc.returncode != 0:
            raise SystemExit(f"FAIL  ohmypm {' '.join(argv)}\n{proc.stdout}\n{proc.stderr}")
        return proc

    def js(*argv: str, cwd: Path, input: str | None = None) -> dict:
        return json.loads(run(*argv, "--json", cwd=cwd, input=input).stdout)

    # ------------------------------------------------------------ setup
    robot = home / "Projects" / "Robot_WS"
    camera = robot / "src" / "camera"
    camera.mkdir(parents=True)
    (camera / "v4l2_capture.cpp").write_text("int main() { return 0; }\n")
    (robot / "README.md").write_text("# Robot_WS\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], cwd=robot, check=True, env=env)
    subprocess.run([*git, "add", "."], cwd=robot, check=True, env=env)
    subprocess.run([*git, "commit", "-qm", "init"], cwd=robot, check=True, env=env)
    for d in (".claude", ".codex", ".pi/agent", ".dsh"):
        (home / d).mkdir(parents=True)
    (home / ".codex" / "AGENTS.md").write_text("# My Codex rules\n- keep it short\n")
    before = tree_digest(robot)

    # ---------------------------------------------------- scenario 1
    reg = js("register", cwd=robot)
    check(
        "1 register creates a project", reg["outcome"] == "created" and reg["project"]["name"] == "Robot_WS"
    )
    check("1 project directory unchanged", tree_digest(robot) == before)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=robot, capture_output=True, text=True, env=env
    )
    check("1 git status clean", status.stdout == "")

    # ---------------------------------------------------- agent instructions
    installed = js("agents", "install", cwd=home)
    check("agents install for all four agents", {c["action"] for c in installed["changes"]} == {"installed"})
    codex_md = (home / ".codex" / "AGENTS.md").read_text()
    check("agents keep existing user instructions", codex_md.startswith("# My Codex rules"))
    check(
        "agents re-install is idempotent",
        {c["action"] for c in js("agents", "install", cwd=home)["changes"]} == {"unchanged"},
    )

    # ---------------------------------------------------- scenario 2
    st = js("status", cwd=camera)
    check(
        "2 agent in a subdirectory finds the project",
        st["registered"] and st["relative_path"] == "src/camera",
    )
    ctx = run("context", cwd=camera).stdout
    check("2 context is readable without a server", ctx.startswith("# Project context: Robot_WS"))

    # ---------------------------------------------------- scenario 3
    milestone = """## 完成内容
V4L2 相机驱动完成，30 fps。
## 关键实现
`src/camera/v4l2_capture.cpp` 使用 mmap 缓冲区。
## 验证结果
`colcon test` 全部通过。
## 下一步
相机标定。
"""
    e = js(
        "log",
        "add",
        "--type",
        "milestone",
        "--title",
        "完成相机驱动",
        "--author",
        "codex",
        "--stdin",
        cwd=camera,
        input=milestone,
    )
    check("3 milestone saved via CLI", e["sequence"] == 1 and e["type"] == "milestone")

    # The MCP client runs inside the freshly installed venv (mcp is a dependency).
    mcp_client = f"""
import asyncio, json
from mcp import Client, StdioServerParameters

async def main():
    transport = StdioServerParameters(command={str(exe)!r}, args=["mcp"], env={env!r}, cwd="/")
    async with Client(transport) as client:
        result = await client.call_tool("pm_add_entry", {{
            "workspace_path": {str(camera)!r}, "type": "milestone", "title": "MCP: 完成图像发布",
            "content": "发布 /camera/image_raw，验证：rostopic hz 30Hz", "author": "claude"}})
        print(json.dumps(result.structured_content))

asyncio.run(main())
"""
    proc = subprocess.run(
        [str(venv / "bin" / "python"), "-c", mcp_client], capture_output=True, text=True, timeout=120, env=env
    )
    if proc.returncode != 0:
        raise SystemExit(f"FAIL  MCP client\n{proc.stderr}")
    mcp_entry = json.loads(proc.stdout.strip().splitlines()[-1])
    check("3 milestone saved via MCP stdio", mcp_entry["sequence"] == 2 and mcp_entry["source"] == "mcp")

    # ---------------------------------------------------- scenario 4
    issue = """## 错误表现
`undefined reference to TIFFReadDirectory`
## 相关文件
`src/perception/CMakeLists.txt`
## 已尝试
- 重装 libtiff-dev：无效
## 已确认
Conda 的 libtiff 覆盖了系统版本。
## 下一步
检查 LD_LIBRARY_PATH。
"""
    js("log", "add", "--type", "issue", "--title", "OpenCV 链接失败", "--stdin", cwd=robot, input=issue)
    fresh = js("context", cwd=camera)  # a "new session"
    md = fresh["markdown"]
    check("4 new session sees the open issue", "OpenCV 链接失败" in md and "LD_LIBRARY_PATH" in md)
    check("4 issue is reported as open", fresh["stats"]["open_issues"] == 1)
    summary = "## Overview\nROS 2 巡检机器人\n## Next Steps\n- 解决 OpenCV 链接问题\n"
    js("summary", "set", "--stdin", cwd=robot, input=summary)
    check("4 summary appears in context", "ROS 2 巡检机器人" in run("context", cwd=robot).stdout)

    # ---------------------------------------------------- scenario 6
    other = home / "Projects" / "webapp"
    other.mkdir()
    js("register", cwd=other)
    js("log", "add", "--title", "only in webapp", cwd=other)
    robot_titles = [x["title"] for x in js("log", "list", cwd=robot)["items"]]
    check("6 projects are isolated (list)", "only in webapp" not in robot_titles and len(robot_titles) == 3)
    check("6 projects are isolated (search)", js("search", "webapp", cwd=robot)["total"] == 0)
    check("6 projects are isolated (context)", "only in webapp" not in run("context", cwd=robot).stdout)

    # ---------------------------------------------------- scenario 5 (web)
    if args.web:
        token_url = None
        web = subprocess.Popen(
            [str(exe), "web", "--port", "8791"], env=env, stdout=subprocess.PIPE, text=True
        )
        try:
            token_url = web.stdout.readline().split()[-1]  # "ohmypm web UI: <url>"
            time.sleep(1.5)
            run("register", str(home / "Projects" / "Robot_WS"), cwd=home)
            png = tmp / "shot.png"
            png.write_bytes(make_png(40, 30))
            proc = subprocess.run(
                [
                    "node",
                    "scripts/e2e-web.mjs",
                    token_url,
                    str(png),
                    os.environ.get("CHROMIUM", "/usr/bin/chromium"),
                ],
                cwd=REPO / "frontend",
                capture_output=True,
                text=True,
                timeout=300,
            )
            print(proc.stdout.rstrip())
            check("5 web rich text scenario", proc.returncode == 0, proc.stderr[-2000:])
        finally:
            web.terminate()
            web.wait(10)

    # ---------------------------------------------------- scenario 7
    data_dir = home / ".local" / "share" / "ohmypm"
    check(
        "7 data lives in the XDG data dir",
        (data_dir / "ohmypm.db").is_file() and (data_dir / "assets").is_dir(),
    )
    check("7 database is private", oct((data_dir / "ohmypm.db").stat().st_mode & 0o777) == "0o600")
    check("7 registered project still unchanged", tree_digest(robot) == before)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--ignored"], cwd=robot, capture_output=True, text=True, env=env
    )
    check("7 git status clean (incl. ignored files)", status.stdout == "")
    backup = js("backup", cwd=home)
    check("7 backup goes to the data dir", backup["path"].startswith(str(data_dir)))

    removed = js("agents", "remove", cwd=home)
    check(
        "agents remove restores the user's file",
        (home / ".codex" / "AGENTS.md").read_text() == "# My Codex rules\n- keep it short\n"
        and {c["action"] for c in removed["changes"]} == {"removed"},
    )

    print(f"\nAll {len(PASSED)} acceptance checks passed ({tmp})")
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
