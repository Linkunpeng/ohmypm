"""Subprocess supervision: argv-only spawn in its own process group, line streaming, group kill."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

MAX_LINE_BYTES = 4 * 1024 * 1024


@dataclass
class LaunchSpec:
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    stdin_data: bytes | None = None
    # Shown in the UI / stored on the run; must not contain the prompt or secrets.
    display_argv: list[str] = field(default_factory=list)


class ProcessHandle:
    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc

    @property
    def pid(self) -> int:
        return self.proc.pid

    @classmethod
    async def spawn(cls, spec: LaunchSpec) -> ProcessHandle:
        if not spec.argv or not os.path.isabs(spec.argv[0]):
            raise ValueError("argv[0] must be an absolute executable path")
        proc = await asyncio.create_subprocess_exec(
            *spec.argv,
            cwd=str(spec.cwd),
            env=spec.env,
            stdin=asyncio.subprocess.PIPE if spec.stdin_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=MAX_LINE_BYTES,
            # New session → own process group, so cancellation reaches grandchildren too.
            start_new_session=True,
        )
        handle = cls(proc)
        if spec.stdin_data is not None and proc.stdin is not None:
            try:
                proc.stdin.write(spec.stdin_data)
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                proc.stdin.close()
        return handle

    async def lines(self, stream: asyncio.StreamReader | None) -> AsyncIterator[str]:
        if stream is None:
            return
        while True:
            try:
                raw = await stream.readline()
            except ValueError:
                # Line longer than the limit: drain what is buffered and continue.
                raw = await stream.read(MAX_LINE_BYTES)
            if not raw:
                return
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")

    async def wait(self) -> int:
        return await self.proc.wait()

    def _signal_group(self, sig: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(self.proc.pid, sig)

    async def terminate(self, grace_seconds: float) -> None:
        """SIGTERM the whole group, then SIGKILL after ``grace_seconds``."""
        if self.proc.returncode is not None:
            self._signal_group(signal.SIGKILL)  # reap leftovers of the group
            return
        self._signal_group(signal.SIGTERM)
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=grace_seconds)
        except TimeoutError:
            self._signal_group(signal.SIGKILL)
            await self.proc.wait()
        self._signal_group(signal.SIGKILL)


def child_env(base: Mapping[str, str], drop: Sequence[str], extra: Mapping[str, str]) -> dict[str, str]:
    env = {k: v for k, v in base.items() if k not in drop}
    env.update(extra)
    return env


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""
