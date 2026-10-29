"""Runner service: registers with the backend, claims runs, supervises agent processes.

Loops:
- claim:     when there is free capacity, ``POST /api/runner/claim`` for available agent types
- heartbeat: extends leases of active runs and receives cancel/stop requests

Each claimed run is handled by a :class:`RunExecutor`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import socket
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ohmypm_common.agent_options import OptionsError
from ohmypm_common.client import ApiError, AsyncApiClient
from ohmypm_common.enums import RunEventType, RunStatus
from ohmypm_common.protocol import (
    AgentCapability,
    ClaimRequest,
    ClaimResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    RunAssignment,
    RunFinishRequest,
    RunnerRegisterRequest,
    RunnerRegisterResponse,
    RunProgressUpdate,
)
from ohmypm_common.redact import Redactor, truncate
from ohmypm_runner import __version__
from ohmypm_runner.adapters.base import AgentEvent, BaseAdapter, ParseState, RunContext, RunOutcome
from ohmypm_runner.adapters.registry import build_adapters
from ohmypm_runner.config import RunnerConfig
from ohmypm_runner.process import ProcessHandle, pid_alive, pid_cmdline
from ohmypm_runner.workspace import WorkspaceError, resolve_workspace

log = logging.getLogger("ohmypm.runner")


class RunExecutor:
    def __init__(self, service: RunnerService, assignment: RunAssignment) -> None:
        self.service = service
        self.a = assignment
        self.run_id = str(assignment.run_id)
        self.cancel_event = asyncio.Event()
        self.cancel_reason: str | None = None
        self.handle: ProcessHandle | None = None
        self.buffer: list[dict[str, Any]] = []
        self.redactor = Redactor([assignment.agent_token, service.config.token or ""])
        self.stderr_count = 0
        self.state = ParseState()
        self._approval_reported = False

    # ------------------------------------------------------------ events

    def add(self, event: AgentEvent) -> None:
        self.buffer.append(
            {
                "client_id": uuid.uuid4().hex,
                "event_type": str(event.type),
                "timestamp": event.timestamp.isoformat(),
                "payload": self.redactor.value(event.payload),
            }
        )

    async def flush(self, *, final: bool = False) -> None:
        attempts = 8 if final else 1
        for attempt in range(attempts):
            while self.buffer:
                batch = self.buffer[:200]
                try:
                    await self.service.post_runner(f"/api/runner/runs/{self.run_id}/events", {"events": batch})
                except (httpx.HTTPError, ApiError) as exc:
                    if isinstance(exc, ApiError) and exc.status_code in (403, 404, 409, 422):
                        log.warning("run %s: dropping %d events: %s", self.run_id, len(batch), exc)
                        del self.buffer[: len(batch)]
                        continue
                    if attempt == attempts - 1:
                        log.error("run %s: could not upload events: %s", self.run_id, exc)
                    break
                del self.buffer[: len(batch)]
            if not self.buffer:
                return
            await asyncio.sleep(min(2**attempt * 0.25, 5))

    async def _uploader(self) -> None:
        while True:
            await asyncio.sleep(self.service.config.event_flush_interval_seconds)
            await self.flush()

    async def _progress(self, **fields: Any) -> None:
        try:
            await self.service.post_runner(
                f"/api/runner/runs/{self.run_id}/progress",
                RunProgressUpdate(**fields).model_dump(mode="json", exclude_none=True),
            )
        except (httpx.HTTPError, ApiError) as exc:
            log.warning("run %s: progress update failed: %s", self.run_id, exc)

    # ------------------------------------------------------------ control

    def request_cancel(self, reason: str) -> None:
        if self.cancel_reason is None:
            self.cancel_reason = reason
        self.cancel_event.set()

    async def _read_stdout(self, adapter: BaseAdapter) -> None:
        assert self.handle is not None
        async for line in self.handle.lines(self.handle.proc.stdout):
            try:
                events = adapter.parse_line(line, self.state)
            except Exception as exc:
                events = [
                    AgentEvent(
                        RunEventType.AGENT_WARNING, {"message": f"unparsed output: {exc}", "line": truncate(line, 2000)}
                    )
                ]
            for event in events:
                self.add(event)
            if self.state.native_session_id and not self.state.extra.get("native_reported"):
                self.state.extra["native_reported"] = True
                await self._progress(native_session_id=self.state.native_session_id)
            if self.state.waiting_approval and not self._approval_reported:
                self._approval_reported = True
                await self._progress(status=RunStatus.WAITING_APPROVAL)

    async def _read_stderr(self) -> None:
        assert self.handle is not None
        limit = self.service.config.max_stderr_events
        async for line in self.handle.lines(self.handle.proc.stderr):
            if not line.strip():
                continue
            self.stderr_count += 1
            if self.stderr_count <= limit:
                self.add(AgentEvent(RunEventType.AGENT_STDERR, {"text": truncate(line, 4000)}))
            elif self.stderr_count == limit + 1:
                self.add(
                    AgentEvent(RunEventType.AGENT_WARNING, {"message": "stderr limit reached; further lines dropped"})
                )

    # ------------------------------------------------------------ main

    async def run(self) -> None:
        uploader = asyncio.create_task(self._uploader())
        temp_dir: Path | None = None
        outcome: RunOutcome
        try:
            outcome, temp_dir = await self._execute()
        except asyncio.CancelledError:
            outcome = RunOutcome(RunStatus.INTERRUPTED, error="runner shutting down", error_code="runner_shutdown")
        except Exception as exc:
            log.exception("run %s crashed in the runner", self.run_id)
            outcome = RunOutcome(RunStatus.FAILED, error=f"runner error: {exc}", error_code="runner_error")
        finally:
            uploader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await uploader
            if self.handle is not None and self.handle.proc.returncode is None:
                await self.handle.terminate(self.service.config.cancel_grace_seconds)
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
            self.service.forget_pid(self.run_id)
        await self.flush(final=True)
        await self._finish(outcome)

    async def _finish(self, outcome: RunOutcome) -> None:
        body = RunFinishRequest(
            status=outcome.status,
            exit_code=self.handle.proc.returncode if self.handle else None,
            error=self.redactor.text(outcome.error) if outcome.error else None,
            error_code=outcome.error_code,
            native_session_id=outcome.native_session_id or self.state.native_session_id,
            result_summary=self.redactor.text(outcome.result_summary) if outcome.result_summary else None,
            usage=self.redactor.value(outcome.usage),
        ).model_dump(mode="json")
        for attempt in range(10):
            try:
                await self.service.post_runner(f"/api/runner/runs/{self.run_id}/finish", body)
                log.info("run %s finished: %s", self.run_id, outcome.status.value)
                return
            except ApiError as exc:
                log.error("run %s: finish rejected: %s", self.run_id, exc)
                return
            except httpx.HTTPError as exc:
                log.warning("run %s: finish failed (%s), retrying", self.run_id, exc)
                await asyncio.sleep(min(2**attempt * 0.5, 15))
        log.error("run %s: giving up reporting finish; the server will mark it lost", self.run_id)

    def _fail(self, code: str, message: str) -> RunOutcome:
        self.add(AgentEvent(RunEventType.AGENT_FAILED, {"error": message, "error_code": code}))
        return RunOutcome(RunStatus.FAILED, error=message, error_code=code)

    async def _execute(self) -> tuple[RunOutcome, Path | None]:
        config = self.service.config
        try:
            workspace = resolve_workspace(self.a.workspace_path, config.allowed_roots)
        except WorkspaceError as exc:
            return self._fail("workspace_not_allowed", str(exc)), None
        adapter = self.service.adapters.get(self.a.agent_type)
        capability = self.service.capabilities.get(self.a.agent_type)
        if adapter is None or capability is None or not capability.available:
            detail = capability.detail if capability else "unknown agent type on this runner"
            return self._fail("agent_unavailable", f"agent {self.a.agent_type!r} is not available: {detail}"), None
        try:
            options = adapter.parse_options(self.a.profile.options)
        except OptionsError as exc:
            return self._fail("invalid_profile_options", str(exc)), None
        dangerous = options.dangerous_reasons()
        if dangerous and not config.allow_dangerous:
            return self._fail(
                "dangerous_options_denied",
                "profile requests elevated permissions ("
                + ", ".join(dangerous)
                + "); set allow_dangerous: true in the runner config to permit this",
            ), None

        temp_dir = Path(tempfile.mkdtemp(prefix="ohmypm-run-"))
        os.chmod(temp_dir, 0o700)
        ctx = RunContext(
            run_id=self.run_id,
            task_id=str(self.a.task_id),
            session_id=str(self.a.session_id) if self.a.session_id else None,
            workspace=workspace,
            prompt=self.a.prompt,
            options=options,
            agent_token=self.a.agent_token,
            server_url=config.server_url,
            temp_dir=temp_dir,
            native_session_id=self.a.native_session_id,
            resume_native=self.a.resume_native,
            write_mode=self.a.write_mode,
        )
        spec = adapter.build_launch(ctx)
        try:
            self.handle = await ProcessHandle.spawn(spec)
        except OSError as exc:
            return self._fail("spawn_failed", f"could not start {spec.argv[0]}: {exc}"), temp_dir
        self.service.remember_pid(self.run_id, self.handle.pid, spec.argv[0])
        await self._progress(status=RunStatus.RUNNING, pid=self.handle.pid, command=spec.display_argv)

        readers = [asyncio.create_task(self._read_stdout(adapter)), asyncio.create_task(self._read_stderr())]
        waiter = asyncio.create_task(self.handle.wait())
        canceller = asyncio.create_task(self.cancel_event.wait())
        timeout = self.a.timeout_seconds
        done, _ = await asyncio.wait({waiter, canceller}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        forced: RunOutcome | None = None
        if waiter not in done:
            if canceller in done:
                reason = self.cancel_reason or "user"
                status = RunStatus.CANCELLED if reason == "user" else RunStatus.INTERRUPTED
                forced = RunOutcome(
                    status,
                    error=f"run {'cancelled' if reason == 'user' else 'interrupted'} ({reason})",
                    error_code=f"cancel_{reason}",
                )
            else:
                forced = RunOutcome(RunStatus.FAILED, error=f"timed out after {timeout}s", error_code="timeout")
            self.add(AgentEvent(RunEventType.AGENT_STATUS, {"phase": "terminating", "reason": forced.error_code}))
            await self.handle.terminate(config.cancel_grace_seconds)
        canceller.cancel()
        exit_code = await waiter
        try:
            await asyncio.wait_for(asyncio.gather(*readers), timeout=10)
        except TimeoutError:
            for task in readers:
                task.cancel()
        if forced is not None:
            forced.native_session_id = self.state.native_session_id
            forced.result_summary = self.state.final_text or self.state.last_message
            return forced, temp_dir
        outcome = adapter.finalize(self.state, exit_code)
        if outcome.status is RunStatus.COMPLETED:
            self.add(AgentEvent(RunEventType.AGENT_COMPLETED, {"exit_code": exit_code}))
        else:
            self.add(AgentEvent(RunEventType.AGENT_FAILED, {"exit_code": exit_code, "error": outcome.error}))
        return outcome, temp_dir


class RunnerService:
    def __init__(self, config: RunnerConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not config.token:
            raise ValueError("runner token missing: set OHMYPM_RUNNER_TOKEN or `token` in runner.yaml")
        self.config = config
        self.client = AsyncApiClient(config.server_url, config.token, transport=transport)
        self.adapters, self.warnings = build_adapters(config)
        self.capabilities: dict[str, AgentCapability] = {}
        self.executors: dict[str, RunExecutor] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.runner_id = uuid.UUID(config.runner_id) if config.runner_id else self._load_runner_id()
        self.heartbeat_interval = config.heartbeat_interval_seconds or 5.0
        self.poll_interval = config.poll_interval_seconds or 2.0
        self._stop = asyncio.Event()

    # ------------------------------------------------------------ state files

    @property
    def _pid_dir(self) -> Path:
        path = self.config.state_path / f"runner-{self.runner_id}" / "runs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load_runner_id(self) -> uuid.UUID:
        path = self.config.state_path / "runner_id"
        if path.is_file():
            with contextlib.suppress(ValueError):
                return uuid.UUID(path.read_text().strip())
        path.parent.mkdir(parents=True, exist_ok=True)
        new = uuid.uuid4()
        path.write_text(f"{new}\n")
        return new

    def remember_pid(self, run_id: str, pid: int, executable: str) -> None:
        (self._pid_dir / f"{run_id}.json").write_text(json.dumps({"pid": pid, "executable": executable}))

    def forget_pid(self, run_id: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            (self._pid_dir / f"{run_id}.json").unlink()

    def kill_orphans(self) -> list[int]:
        """Kill agent processes left behind by a previous runner process (crash/kill -9)."""
        killed = []
        for file in self._pid_dir.glob("*.json"):
            with contextlib.suppress(ValueError, OSError):
                info = json.loads(file.read_text())
                pid, exe = int(info["pid"]), os.path.basename(str(info["executable"]))
                # Guard against PID reuse: only kill if the command line still matches.
                if pid_alive(pid) and exe and exe in pid_cmdline(pid):
                    with contextlib.suppress(ProcessLookupError, PermissionError):
                        os.killpg(pid, signal.SIGKILL)
                    killed.append(pid)
            file.unlink(missing_ok=True)
        return killed

    # ------------------------------------------------------------ server calls

    async def post_runner(self, path: str, body: dict[str, Any]) -> Any:
        return await self.client.request("POST", path, json=body, headers={"X-Runner-Id": str(self.runner_id)})

    async def detect_agents(self) -> dict[str, AgentCapability]:
        results = await asyncio.gather(*(a.check_available() for a in self.adapters.values()))
        self.capabilities = {c.agent_type: c for c in results}
        return self.capabilities

    async def register(self) -> RunnerRegisterResponse:
        killed = self.kill_orphans()
        if killed:
            log.warning("killed %d orphaned agent process(es) from a previous runner: %s", len(killed), killed)
        await self.detect_agents()
        request = RunnerRegisterRequest(
            runner_id=self.runner_id,
            name=self.config.name,
            host_id=self.config.host_id,
            version=__version__,
            max_parallel=self.config.max_parallel,
            allowed_roots=self.config.allowed_roots,
            agents=list(self.capabilities.values()),
        )
        response = RunnerRegisterResponse.model_validate(
            await self.client.post("/api/runner/register", request.model_dump(mode="json"))
        )
        self.heartbeat_interval = self.config.heartbeat_interval_seconds or response.heartbeat_interval_seconds
        self.poll_interval = self.config.poll_interval_seconds or response.poll_interval_seconds
        if response.interrupted_run_ids:
            log.warning(
                "server marked %d run(s) from a previous session as interrupted", len(response.interrupted_run_ids)
            )
        return response

    async def heartbeat_once(self) -> HeartbeatResponse:
        request = HeartbeatRequest(runner_id=self.runner_id, active_run_ids=[uuid.UUID(r) for r in self.executors])
        response = HeartbeatResponse.model_validate(
            await self.client.post("/api/runner/heartbeat", request.model_dump(mode="json"))
        )
        for run_id in response.cancel_run_ids:
            if (ex := self.executors.get(str(run_id))) is not None:
                log.info("run %s: cancellation requested", run_id)
                ex.request_cancel("user")
        for run_id in response.stop_run_ids:
            if (ex := self.executors.get(str(run_id))) is not None:
                log.warning("run %s: server no longer considers it active; stopping", run_id)
                ex.request_cancel("server_stop")
        return response

    def _claimable_agent_types(self) -> list[str]:
        running: dict[str, int] = {}
        for ex in self.executors.values():
            running[ex.a.agent_type] = running.get(ex.a.agent_type, 0) + 1
        types = []
        for agent_type, cap in self.capabilities.items():
            if not cap.available:
                continue
            limit = cap.max_parallel
            if limit is not None and running.get(agent_type, 0) >= limit:
                continue
            types.append(agent_type)
        return types

    async def claim_once(self) -> list[RunAssignment]:
        free = self.config.max_parallel - len(self.executors)
        types = self._claimable_agent_types()
        if free <= 0 or not types:
            return []
        request = ClaimRequest(runner_id=self.runner_id, capacity=free, agent_types=types)
        response = ClaimResponse.model_validate(
            await self.client.post("/api/runner/claim", request.model_dump(mode="json"))
        )
        for assignment in response.runs:
            self.start_run(assignment)
        return response.runs

    def start_run(self, assignment: RunAssignment) -> None:
        run_id = str(assignment.run_id)
        executor = RunExecutor(self, assignment)
        self.executors[run_id] = executor
        log.info("run %s: starting %s in %s", run_id, assignment.agent_type, assignment.workspace_path)

        async def runner() -> None:
            try:
                await executor.run()
            finally:
                self.executors.pop(run_id, None)
                self.tasks.pop(run_id, None)

        self.tasks[run_id] = asyncio.create_task(runner())

    # ------------------------------------------------------------ loops

    async def _loop(self, interval: float, fn: Any, name: str) -> None:
        while not self._stop.is_set():
            try:
                await fn()
            except (httpx.HTTPError, ApiError) as exc:
                log.warning("%s failed: %s", name, exc)
            except Exception:
                log.exception("%s crashed", name)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=interval)

    async def serve(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                await self.register()
                break
            except (httpx.HTTPError, ApiError) as exc:
                log.warning("cannot register with %s (%s); retrying in %.0fs", self.config.server_url, exc, delay)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                delay = min(delay * 2, 30)
        available = [k for k, c in self.capabilities.items() if c.available]
        log.info("runner %s (%s) ready; agents: %s", self.config.name, self.runner_id, ", ".join(available) or "none")
        for warning in self.warnings:
            log.warning(warning)
        await asyncio.gather(
            self._loop(self.heartbeat_interval, self.heartbeat_once, "heartbeat"),
            self._loop(self.poll_interval, self.claim_once, "claim"),
        )
        await self.shutdown()

    def stop(self) -> None:
        self._stop.set()

    async def shutdown(self) -> None:
        self._stop.set()
        for executor in list(self.executors.values()):
            executor.request_cancel("shutdown")
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        await self.client.aclose()


def default_name() -> str:
    return socket.gethostname()


def now() -> datetime:
    return datetime.now(UTC)
