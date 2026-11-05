#!/usr/bin/env python3
"""Verify that coding agents really load the instructions `ohmypm agents install` writes.

For every agent the script:

1. creates a throw-away HOME and runs ``ohmypm agents install --force`` in it;
2. points the agent's model endpoint at a local capture server (which records
   each request and answers HTTP 400, so no model ever runs);
3. sends one non-interactive prompt from a temporary project directory;
4. checks whether the captured request contains a marker string from the
   ohmypm instructions (for Claude Code this proves the ``@~/...`` import is
   resolved, because CLAUDE.md itself only contains the import line).

Safety: by default everything runs inside a private network namespace
(``unshare -rn``) that only has a loopback interface, so no real API endpoint
is reachable. Real agent configuration is never read or written: HOME and all
agent config variables point into the temporary directory.

Usage::

    python3 scripts/verify_agents.py                 # all agents
    python3 scripts/verify_agents.py claude codex    # a subset
    python3 scripts/verify_agents.py --keep          # keep the temp dir for inspection
    python3 scripts/verify_agents.py --no-netns      # skip namespace isolation (not recommended)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OHMYPM = REPO / ".venv" / "bin" / "ohmypm"
REAL_HOME = Path(os.environ.get("OHMYPM_VERIFY_REAL_HOME") or Path.home())
MARKER = "ohmypm status --json"
TIMEOUT = 90

CLAUDE_BIN = shutil.which("claude") or str(REAL_HOME / ".local/bin/claude")
CODEX_JS = REAL_HOME / ".local/lib/node_modules/@openai/codex/bin/codex.js"
PI_BIN = REAL_HOME / ".pi/agent/bin/pi"
DSH_BIN = shutil.which("dsh") or str(REAL_HOME / ".local/bin/dsh")
NODE_DIR = str(Path(shutil.which("node") or REAL_HOME / ".local/bin/node").parent)


# --------------------------------------------------------------- capture server


class Capture:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.lock = threading.Lock()
        self.records: list[dict] = []
        capture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:  # silence
                pass

            def _record(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                if not length and self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                    chunks = []
                    while True:
                        size = int(self.rfile.readline().strip() or b"0", 16)
                        if size == 0:
                            self.rfile.readline()
                            break
                        chunks.append(self.rfile.read(size))
                        self.rfile.readline()
                    body = b"".join(chunks)
                record = {
                    "agent": capture.current_agent,
                    "method": self.command,
                    "path": self.path,
                    "user_agent": self.headers.get("User-Agent"),
                    "body": body.decode("utf-8", errors="replace"),
                }
                with capture.lock:
                    capture.records.append(record)
                    with capture.log_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

            def _reply(self, status: int, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802 - model listings etc.
                self._record()
                self._reply(200, {"object": "list", "data": [], "models": []})

            def do_POST(self) -> None:  # noqa: N802
                self._record()
                # A non-retryable client error: the agent gives up after sending
                # the request we want to inspect.
                self._reply(
                    400,
                    {
                        "type": "error",
                        "error": {
                            "type": "invalid_request_error",
                            "message": "ohmypm verify_agents capture server: request recorded",
                            "code": "invalid_request_error",
                        },
                    },
                )

        self.current_agent = "-"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Capture:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()

    def for_agent(self, agent: str) -> list[dict]:
        with self.lock:
            return [r for r in self.records if r["agent"] == agent]


# --------------------------------------------------------------------- helpers


def base_env(tmp: Path) -> dict[str, str]:
    home = tmp / "home"
    return {
        "PATH": f"{NODE_DIR}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "USER": os.environ.get("USER", "user"),
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "OHMYPM_DATA_DIR": str(home / ".local" / "share" / "ohmypm"),
        "OHMYPM_CONFIG_DIR": str(home / ".config" / "ohmypm"),
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "TMPDIR": str(tmp / "tmp"),
    }


def run(cmd: list[str], env: dict[str, str], cwd: Path) -> dict:
    try:
        proc = subprocess.run(
            cmd, env=env, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL
        )
        return {"exit": proc.returncode, "stdout": proc.stdout[-1500:], "stderr": proc.stderr[-1500:]}
    except subprocess.TimeoutExpired as exc:
        return {
            "exit": "timeout",
            "stdout": str(exc.stdout or "")[-1500:],
            "stderr": str(exc.stderr or "")[-1500:],
        }
    except FileNotFoundError as exc:
        return {"exit": "missing", "stdout": "", "stderr": str(exc)}


# ---------------------------------------------------------------------- agents


def agent_claude(env: dict[str, str], tmp: Path, port: int) -> tuple[list[str], dict[str, str]]:
    env = {
        **env,
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
        "ANTHROPIC_API_KEY": "sk-ant-dummy-ohmypm-verify",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "CLAUDE_CODE_MAX_RETRIES": "0",
    }
    return [CLAUDE_BIN, "-p", "hi", "--max-turns", "1"], env


def agent_codex(env: dict[str, str], tmp: Path, port: int) -> tuple[list[str], dict[str, str]]:
    codex_home = Path(env["HOME"]) / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text(
        f"""model = "verify-model"
model_provider = "capture"

[model_providers.capture]
name = "Capture"
base_url = "http://127.0.0.1:{port}/v1"
env_key = "CAPTURE_API_KEY"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
""",
        encoding="utf-8",
    )
    env = {**env, "CODEX_HOME": str(codex_home), "CAPTURE_API_KEY": "dummy"}
    return ["node", str(CODEX_JS), "exec", "--skip-git-repo-check", "hi"], env


def agent_pi(env: dict[str, str], tmp: Path, port: int) -> tuple[list[str], dict[str, str]]:
    agent_dir = Path(env["HOME"]) / ".pi" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "capture": {
                        "baseUrl": f"http://127.0.0.1:{port}/v1",
                        "api": "openai-completions",
                        "apiKey": "dummy",
                        "models": [{"id": "verify-model"}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    env = {
        **env,
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "PI_OFFLINE": "1",
        "PI_SKIP_VERSION_CHECK": "1",
        "PI_TELEMETRY": "0",
    }
    cmd = [str(PI_BIN), "--print", "--no-session", "--provider", "capture", "--model", "verify-model", "hi"]
    return cmd, env


def agent_dsh(env: dict[str, str], tmp: Path, port: int) -> tuple[list[str], dict[str, str]]:
    env = {
        **env,
        "DSH_HOME": str(Path(env["HOME"]) / ".dsh"),
        "DEEPSEEK_API_KEY": "dummy",
        "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{port}",
    }
    return [DSH_BIN, "--profile", "headless", "hi"], env


AGENTS = {"claude": agent_claude, "codex": agent_codex, "pi": agent_pi, "dsh": agent_dsh}


# ------------------------------------------------------------------------ main


def verify(selected: list[str], keep: bool) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ohmypm-verify-agents-"))
    (tmp / "tmp").mkdir()
    env = base_env(tmp)
    home = Path(env["HOME"])
    for d in (".claude", ".codex", ".pi/agent", ".dsh"):
        (home / d).mkdir(parents=True, exist_ok=True)
    project = tmp / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=False, env=env)
    (project / "main.c").write_text("int main(void) { return 0; }\n")

    install = run([str(OHMYPM), "agents", "install", "--force", "--json"], env, tmp)
    print(f"temp dir: {tmp}")
    print(f"ohmypm agents install: exit {install['exit']}")
    if install["exit"] != 0:
        print(install["stderr"])
        return 1
    for change in json.loads(install["stdout"])["changes"]:
        print(f"  {change['agent']:<7} {change['action']:<10} {change['target']}")

    results = {}
    with Capture(tmp / "requests.jsonl") as capture:
        for name in selected:
            capture.current_agent = name
            cmd, agent_env = AGENTS[name](dict(env), tmp, capture.port)
            proc = run(cmd, agent_env, project)
            requests = capture.for_agent(name)
            posts = [r for r in requests if r["method"] == "POST"]
            marker = any(MARKER in r["body"] for r in posts)
            comment = any("ohmypm:start" in r["body"] for r in posts)
            results[name] = {
                "command": " ".join(cmd),
                "exit": proc["exit"],
                "requests": [f"{r['method']} {r['path']}" for r in requests],
                "captured_model_request": bool(posts),
                "marker_in_request": marker,
                "block_comment_in_request": comment,
                "stderr_tail": proc["stderr"][-400:] if not marker else "",
            }
            status = "OK " if marker else "FAIL"
            print(f"\n[{status}] {name}: {' '.join(cmd)}")
            print(f"  exit={proc['exit']} requests={results[name]['requests'][:6]}")
            print(f"  marker {MARKER!r} in request: {marker}; '<!-- ohmypm:start' visible: {comment}")
            if not marker:
                print(f"  stderr: {proc['stderr'][-600:]}")
                print(f"  stdout: {proc['stdout'][-300:]}")

    (tmp / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nrequest log: {tmp / 'requests.jsonl'}\nresults: {tmp / 'results.json'}")
    if not keep:
        shutil.rmtree(tmp, ignore_errors=True)
        print("(temp dir removed; use --keep to inspect it)")
    return 0 if all(r["marker_in_request"] for r in results.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("agents", nargs="*", help=f"subset of: {', '.join(AGENTS)} (default: all)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary directory")
    parser.add_argument("--no-netns", action="store_true", help="do not isolate the network (unshare -rn)")
    args = parser.parse_args()
    selected = args.agents or list(AGENTS)
    unknown = [a for a in selected if a not in AGENTS]
    if unknown:
        parser.error(f"unknown agent(s): {', '.join(unknown)}")

    if not args.no_netns and os.environ.get("OHMYPM_VERIFY_IN_NETNS") != "1":
        if not shutil.which("unshare"):
            print("unshare not found; re-run with --no-netns to skip network isolation", file=sys.stderr)
            return 2
        inner = [sys.executable, str(Path(__file__).resolve()), *selected] + (["--keep"] if args.keep else [])
        script = "ip link set lo up && exec " + " ".join(f"'{a}'" for a in inner)
        env = {**os.environ, "OHMYPM_VERIFY_IN_NETNS": "1", "OHMYPM_VERIFY_REAL_HOME": str(Path.home())}
        return subprocess.call(["unshare", "-rn", "sh", "-c", script], env=env)
    return verify(selected, args.keep)


if __name__ == "__main__":
    sys.exit(main())
