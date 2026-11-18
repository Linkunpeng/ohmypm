"""Long-running ohmypm processes (MCP and Web servers) and whether they run current code.

Python loads its modules once, so a server started before ohmypm was
reinstalled (or before the source of an editable install changed) keeps
running the old code. ``doctor`` lists such processes so they can be
restarted. Linux only (``/proc``); elsewhere nothing is reported.

A process is *outdated* when it started before the newest ``.py`` file of the
ohmypm package that its interpreter loads (found through the virtual
environment in its command line, including editable ``.pth`` installs).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

SERVER_COMMANDS = {"mcp": "mcp", "web": "web"}
SCRIPTS = {"ohmypm": None, "ohmypm-mcp": "mcp"}
# The boot time in /proc/stat has whole-second resolution, so start times can
# be up to a second early; a restart right after an install is still current.
CLOCK_SLACK = timedelta(seconds=2)


@dataclass
class ServerProcess:
    pid: int
    kind: str
    command: str
    started_at: datetime
    package_dir: str | None
    code_updated_at: datetime | None
    # systemd unit running the process (e.g. "ohmypm-web.service"), if any.
    unit: str | None = None

    @property
    def outdated(self) -> bool | None:
        """``None`` when the package could not be located."""
        if self.code_updated_at is None:
            return None
        return self.started_at + CLOCK_SLACK < self.code_updated_at

    def to_dict(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "kind": self.kind,
            "command": self.command,
            "started_at": self.started_at.isoformat(),
            "package_dir": self.package_dir,
            "code_updated_at": self.code_updated_at.isoformat() if self.code_updated_at else None,
            "outdated": self.outdated,
            "unit": self.unit,
        }

    def restart_hint(self) -> str:
        if self.unit:
            return f"systemctl --user restart {self.unit}"
        if self.kind == "mcp":
            return "restart the agent session that started it"
        return "stop it and start `ohmypm web` again"


def server_kind(argv: list[str]) -> str | None:
    """``"mcp"`` / ``"web"`` when ``argv`` runs an ohmypm server, else ``None``."""
    if not argv:
        return None
    first = os.path.basename(argv[0])
    if first.startswith("python"):
        rest = argv[1:]
        while rest and rest[0].startswith("-") and rest[0] != "-m":
            rest = rest[1:]  # interpreter options such as -I or -u
        if len(rest) >= 2 and rest[0] == "-m" and rest[1] == "ohmypm":
            script, args = "ohmypm", rest[2:]
        elif rest and os.path.basename(rest[0]) in SCRIPTS:
            script, args = os.path.basename(rest[0]), rest[1:]
        else:
            return None
    elif first in SCRIPTS:
        script, args = first, argv[1:]
    else:
        return None
    if SCRIPTS[script]:
        return SCRIPTS[script]
    command = next((a for a in args if not a.startswith("-")), None)
    return SERVER_COMMANDS.get(command or "")


def package_dir(argv: list[str]) -> Path | None:
    """The ``ohmypm`` package directory the process' interpreter imports."""
    interpreter = Path(argv[0]) if argv else None
    if interpreter is None or not interpreter.is_absolute() or not interpreter.name.startswith("python"):
        return None
    venv = interpreter.parent.parent
    for site in sorted(venv.glob("lib/python*/site-packages")):
        if (site / "ohmypm" / "__init__.py").is_file():
            return site / "ohmypm"
        # Editable installs point at the source tree through a .pth file.
        for pth in site.glob("*ohmypm*.pth"):
            try:
                lines = pth.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                candidate = Path(line.strip()) / "ohmypm"
                if (
                    line.strip()
                    and not line.startswith(("#", "import"))
                    and (candidate / "__init__.py").is_file()
                ):
                    return candidate
    return None


def newest_code_mtime(package: Path) -> datetime | None:
    newest = 0.0
    for path in package.rglob("*.py"):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return datetime.fromtimestamp(newest, UTC) if newest else None


def _boot_time(proc: Path) -> float | None:
    try:
        for line in (proc / "stat").read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    except OSError:
        pass
    return None


def _start_time(proc: Path, pid: int, boot: float) -> datetime | None:
    try:
        stat = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    # Field 22 (starttime, clock ticks after boot); the command name in
    # parentheses may contain spaces, so split after its closing bracket.
    fields = stat[stat.rfind(")") + 2 :].split()
    try:
        ticks = int(fields[19])
    except (IndexError, ValueError):
        return None
    return datetime.fromtimestamp(boot + ticks / os.sysconf("SC_CLK_TCK"), UTC)


def _systemd_unit(proc: Path, pid: int) -> str | None:
    """The ``*.service`` unit of the process' cgroup (not the per-user manager)."""
    try:
        lines = (proc / str(pid) / "cgroup").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        last = line.rsplit("/", 1)[-1]
        if last.endswith(".service") and not last.startswith("user@"):
            return last
    return None


def server_processes(proc: Path = Path("/proc")) -> list[ServerProcess]:
    """The current user's running ohmypm MCP / Web servers (excluding this process)."""
    boot = _boot_time(proc)
    if boot is None:
        return []
    uid, me = os.getuid(), os.getpid()
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        argv = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
        kind = server_kind(argv)
        if kind is None:
            continue
        started = _start_time(proc, int(entry.name), boot)
        if started is None:
            continue
        package = package_dir(argv)
        found.append(
            ServerProcess(
                pid=int(entry.name),
                kind=kind,
                command=" ".join(argv),
                started_at=started,
                package_dir=str(package) if package else None,
                code_updated_at=newest_code_mtime(package) if package else None,
                unit=_systemd_unit(proc, int(entry.name)),
            )
        )
    return sorted(found, key=lambda p: p.pid)
