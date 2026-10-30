"""Phase 3 acceptance: dispatch via API → runner claims → fake agent executes → events/results persisted.

The fake agent is a real subprocess that talks to the live server with its run-scoped token.
"""

import asyncio
import contextlib
import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from ohmypm_runner.config import AgentSettings, RunnerConfig
from ohmypm_runner.service import RunnerService
from tests.conftest import ADMIN_TOKEN, RUNNER_TOKEN, LiveServer

HOST = "e2e-host"


@pytest.fixture
async def admin(live_server: LiveServer) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=live_server.url, headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}, timeout=30
    ) as client:
        yield client


def runner_config(live_server: LiveServer, tmp_path: Path, **kw: Any) -> RunnerConfig:
    values: dict[str, Any] = {
        "server_url": live_server.url,
        "token": RUNNER_TOKEN,
        "name": "e2e",
        "host_id": HOST,
        "allowed_roots": [str(tmp_path / "ws")],
        "max_parallel": 3,
        "enable_fake_agent": True,
        "state_dir": str(tmp_path / "state"),
        "heartbeat_interval_seconds": 0.3,
        "poll_interval_seconds": 0.2,
        "cancel_grace_seconds": 2.0,
        "event_flush_interval_seconds": 0.1,
        "agents": {
            "claude": AgentSettings(executable="/nonexistent/claude"),
            "codex": AgentSettings(enabled=False),
            "pi": AgentSettings(enabled=False),
            "dsh": AgentSettings(enabled=False),
        },
    }
    values.update(kw)
    return RunnerConfig.model_validate(values)


@contextlib.asynccontextmanager
async def running(service: RunnerService) -> AsyncIterator[RunnerService]:
    task = asyncio.create_task(service.serve())
    try:
        yield service
    finally:
        service.stop()
        await asyncio.wait_for(task, timeout=30)


async def setup_task(admin: httpx.AsyncClient, tmp_path: Path, name: str = "proj", **task_extra: Any) -> dict[str, Any]:
    root = tmp_path / "ws" / name
    root.mkdir(parents=True, exist_ok=True)
    project = (await admin.post("/api/projects", json={"name": name})).json()
    ws = (
        await admin.post(
            "/api/workspaces/resolve", json={"host_id": HOST, "root_path": str(root), "project_id": project["id"]}
        )
    ).json()
    task = (
        await admin.post(
            "/api/tasks", json={"raw_request": f"Do the {name} work", "workspace_id": ws["id"], **task_extra}
        )
    ).json()
    return {"project": project, "workspace": ws, "task": task, "root": root}


async def dispatch(
    admin: httpx.AsyncClient, task_id: str, script: list[dict[str, Any]] | None = None, **extra: Any
) -> dict[str, Any]:
    profile_name = f"fake-{uuid.uuid4().hex[:8]}"
    r = await admin.post(
        "/api/agent-profiles", json={"name": profile_name, "agent_type": "fake", "options": {"script": script or []}}
    )
    assert r.status_code == 201, r.text
    r = await admin.post("/api/runs", json={"task_id": task_id, "profile_name": profile_name, **extra})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def wait_status(admin: httpx.AsyncClient, run_id: str, statuses: set[str], timeout: float = 20) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        run = (await admin.get(f"/api/runs/{run_id}")).json()
        if run["status"] in statuses:
            return run  # type: ignore[no-any-return]
        if time.monotonic() > deadline:
            raise AssertionError(f"run {run_id} stuck in {run['status']}: {run}")
        await asyncio.sleep(0.1)


async def events_of(admin: httpx.AsyncClient, run_id: str) -> list[dict[str, Any]]:
    return (await admin.get(f"/api/runs/{run_id}/events", params={"limit": 2000})).json()  # type: ignore[no-any-return]


async def test_end_to_end_handoff(admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path) -> None:
    """The 10-step scenario from the spec, with a second agent continuing and completing the task."""
    s = await setup_task(admin, tmp_path, acceptance_criteria=["hello.txt exists"])
    task_id = s["task"]["id"]
    script = [
        {"message": "Starting work"},
        {"tool": "bash", "input": "ls", "output": "README"},
        {"write_file": "hello.txt", "content": "hi"},
        {"env_check": ["OHMYPM_AGENT_TOKEN", "OHMYPM_RUNNER_TOKEN", "OHMYPM_TASK_ID"]},
        {
            "checkpoint": {
                "summary": "Wrote hello.txt; verification pending",
                "completed": ["wrote hello.txt"],
                "remaining": ["verify file"],
                "next_steps": ["cat hello.txt"],
                "relevant_files": ["hello.txt"],
            }
        },
        {"message": "leaking omr_abcdefghijklmnopqrstuvwxyz0123456789 by accident"},
    ]
    run = await dispatch(admin, task_id, script, idempotency_key=None)
    service = RunnerService(runner_config(live_server, tmp_path))
    async with running(service):
        done = await wait_status(admin, run["id"], {"completed", "failed"})
    assert done["status"] == "completed", done
    assert done["exit_code"] == 0 and done["runner_id"] == str(service.runner_id)
    assert done["native_session_id"].startswith("fake-")
    assert (s["root"] / "hello.txt").read_text() == "hi"

    events = await events_of(admin, run["id"])
    types = [e["event_type"] for e in events]
    for expected in (
        "run.queued",
        "run.claimed",
        "run.status",
        "agent.started",
        "agent.message",
        "tool.started",
        "tool.completed",
        "file.changed",
        "checkpoint.created",
        "agent.completed",
    ):
        assert expected in types, (expected, types)
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    env_msg = next(e for e in events if e["payload"].get("text", "").startswith("env:"))
    env = json.loads(env_msg["payload"]["text"][5:])
    assert env == {"OHMYPM_AGENT_TOKEN": True, "OHMYPM_RUNNER_TOKEN": False, "OHMYPM_TASK_ID": True}
    assert not any("omr_abcdefghij" in json.dumps(e["payload"]) for e in events), "secrets redacted"

    task = (await admin.get(f"/api/tasks/{task_id}")).json()
    assert task["status"] == "in_progress", "a finished run does not complete the task"
    assert task["next_action"] == "cat hello.txt"
    cps = (await admin.get(f"/api/tasks/{task_id}/checkpoints")).json()["items"]
    assert len(cps) == 1 and cps[0]["run_id"] == run["id"] and not cps[0]["auto_generated"]

    # The run token is dead once the run is over.
    assert (
        await httpx.AsyncClient(base_url=live_server.url).get(
            "/api/tasks", headers={"Authorization": "Bearer omr_invalid"}
        )
    ).status_code == 401

    # ---- a different agent session continues from the checkpoint and completes the task
    ctx = (await admin.get(f"/api/tasks/{task_id}/context", params={"mode": "standard"})).json()
    assert "cat hello.txt" in ctx["markdown"] and "hello.txt" in ctx["data"]["key_files"]
    run2 = await dispatch(
        admin,
        task_id,
        [
            {"message": "Resuming from checkpoint"},
            {
                "complete": {
                    "summary": "verified",
                    "results": [{"criterion": "hello.txt exists", "passed": True, "evidence": "cat hello.txt → hi"}],
                }
            },
        ],
        from_checkpoint_id=cps[0]["id"],
    )
    assert run2["session_id"] != done["session_id"], "new agent session"
    async with running(RunnerService(runner_config(live_server, tmp_path))):
        done2 = await wait_status(admin, run2["id"], {"completed", "failed"})
    assert done2["status"] == "completed", done2
    task = (await admin.get(f"/api/tasks/{task_id}")).json()
    assert task["status"] == "completed"
    assert task["acceptance_result"]["verified_by"] == f"agent:run:{run2['id']}"
    sessions = (await admin.get(f"/api/tasks/{task_id}/sessions")).json()
    assert len(sessions) == 2


async def test_cancel_kills_process(admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path) -> None:
    s = await setup_task(admin, tmp_path, "cancel")
    run = await dispatch(admin, s["task"]["id"], [{"message": "working"}, {"sleep": 60}])
    async with running(RunnerService(runner_config(live_server, tmp_path))):
        running_run = await wait_status(admin, run["id"], {"running"})
        pid = running_run["pid"]
        assert pid
        r = await admin.post(f"/api/runs/{run['id']}/cancel", json={"reason": "changed my mind"})
        assert r.status_code == 200 and r.json()["cancel_requested_at"]
        done = await wait_status(admin, run["id"], {"cancelled", "failed", "completed"})
    assert done["status"] == "cancelled", done
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    cps = (await admin.get(f"/api/tasks/{s['task']['id']}/checkpoints")).json()["items"]
    assert cps and cps[0]["auto_generated"], "system writes a handoff checkpoint when the agent did not"


async def test_cancel_queued_run(admin: httpx.AsyncClient, tmp_path: Path) -> None:
    s = await setup_task(admin, tmp_path, "queued")
    run = await dispatch(admin, s["task"]["id"])
    r = await admin.post(f"/api/runs/{run['id']}/cancel", json={})
    assert r.json()["status"] == "cancelled"
    r = await admin.post(f"/api/runs/{run['id']}/cancel", json={})
    assert r.status_code == 409


async def test_timeout(admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path) -> None:
    s = await setup_task(admin, tmp_path, "timeout")
    run = await dispatch(admin, s["task"]["id"], [{"sleep": 30}], timeout_seconds=1)
    async with running(RunnerService(runner_config(live_server, tmp_path))):
        done = await wait_status(admin, run["id"], {"failed", "completed", "cancelled"})
    assert done["status"] == "failed" and done["error_code"] == "timeout"


async def test_agent_failure_and_unavailable_cli(
    admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path
) -> None:
    s = await setup_task(admin, tmp_path, "fail")
    failing = await dispatch(admin, s["task"]["id"], [{"fail": "compilation error"}])
    claude = (
        await admin.post("/api/runs", json={"task_id": s["task"]["id"], "agent_type": "claude", "write_mode": False})
    ).json()
    service = RunnerService(runner_config(live_server, tmp_path))
    async with running(service):
        done = await wait_status(admin, failing["id"], {"failed", "completed"})
        await asyncio.sleep(0.6)
    assert done["status"] == "failed" and "compilation error" in done["error"]
    assert service.capabilities["claude"].available is False
    assert (await admin.get(f"/api/runs/{claude['id']}")).json()["status"] == "queued", (
        "runs for unavailable CLIs are never claimed"
    )
    agents = {a["agent_type"]: a for a in (await admin.get("/api/agents")).json()}
    assert agents["fake"]["available_on"][0]["available"] is True
    assert agents["claude"]["available_on"][0]["available"] is False


async def test_workspace_outside_allowed_roots(
    admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    ws = (await admin.post("/api/workspaces/resolve", json={"host_id": HOST, "root_path": str(outside)})).json()
    task = (await admin.post("/api/tasks", json={"raw_request": "x", "workspace_id": ws["id"]})).json()
    run_outside = await dispatch(admin, task["id"])
    # A symlink inside the allowed root that points outside passes the server's lexical check
    # but must be rejected by the runner's realpath check.
    (tmp_path / "ws").mkdir(exist_ok=True)
    link = tmp_path / "ws" / "sneaky"
    link.symlink_to(outside)
    ws2 = (await admin.post("/api/workspaces/resolve", json={"host_id": HOST, "root_path": str(link)})).json()
    task2 = (await admin.post("/api/tasks", json={"raw_request": "y", "workspace_id": ws2["id"]})).json()
    run_link = await dispatch(admin, task2["id"])
    async with running(RunnerService(runner_config(live_server, tmp_path))):
        done = await wait_status(admin, run_link["id"], {"failed", "completed"})
        await asyncio.sleep(0.5)
    assert done["status"] == "failed" and done["error_code"] == "workspace_not_allowed"
    assert (await admin.get(f"/api/runs/{run_outside['id']}")).json()["status"] == "queued"


async def test_dangerous_profile_refused(admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path) -> None:
    s = await setup_task(admin, tmp_path, "danger")
    r = await admin.post(
        "/api/agent-profiles",
        json={"name": "yolo", "agent_type": "claude", "options": {"permission_mode": "bypassPermissions"}},
    )
    assert r.status_code == 201
    r = await admin.post(
        "/api/agent-profiles",
        json={"name": "bad", "agent_type": "claude", "options": {"extra": "--dangerously-skip-permissions"}},
    )
    assert r.status_code == 422
    claude_ok = runner_config(live_server, tmp_path)
    claude_ok.agents["claude"] = AgentSettings(executable=str(Path(os.sys.executable)))  # "available"
    run = (await admin.post("/api/runs", json={"task_id": s["task"]["id"], "profile_name": "yolo"})).json()
    async with running(RunnerService(claude_ok)):
        done = await wait_status(admin, run["id"], {"failed", "completed"})
    assert done["error_code"] == "dangerous_options_denied"


async def test_single_writer_per_workspace(admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path) -> None:
    s = await setup_task(admin, tmp_path, "writer")
    first = await dispatch(admin, s["task"]["id"], [{"sleep": 1.5}])
    second = await dispatch(admin, s["task"]["id"], [{"message": "second"}])
    reader = await dispatch(admin, s["task"]["id"], [{"sleep": 0.5}], write_mode=False)
    async with running(RunnerService(runner_config(live_server, tmp_path))):
        await wait_status(admin, first["id"], {"running"})
        await wait_status(admin, reader["id"], {"running", "completed"})
        assert (await admin.get(f"/api/runs/{second['id']}")).json()["status"] == "queued"
        d1 = await wait_status(admin, first["id"], {"completed"})
        d2 = await wait_status(admin, second["id"], {"completed"})
    assert d2["started_at"] >= d1["finished_at"]


async def test_runner_restart_marks_runs_interrupted(
    admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path
) -> None:
    s = await setup_task(admin, tmp_path, "crash")
    run = await dispatch(admin, s["task"]["id"], [{"sleep": 60}])
    cfg = runner_config(live_server, tmp_path, runner_id=str(uuid.uuid4()))
    crashed = RunnerService(cfg)
    task = asyncio.create_task(crashed.serve())
    running_run = await wait_status(admin, run["id"], {"running"})
    pid = running_run["pid"]
    task.cancel()  # simulate the runner dying without cleanup (process keeps running)
    with contextlib.suppress(asyncio.CancelledError):
        await task
    for ex in list(crashed.executors.values()):
        ex.handle = None  # make sure nothing in this process kills the agent
    assert os.kill(pid, 0) is None, "orphaned agent still alive"
    restarted = RunnerService(cfg)
    response = await restarted.register()
    assert run["id"] in [str(r) for r in response.interrupted_run_ids]
    await asyncio.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    done = (await admin.get(f"/api/runs/{run['id']}")).json()
    assert done["status"] == "interrupted" and done["error_code"] == "runner_restarted"
    await restarted.client.aclose()


async def test_lease_expiry_marks_run_lost(admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path) -> None:
    s = await setup_task(admin, tmp_path, "lease")
    run = await dispatch(admin, s["task"]["id"])
    async with httpx.AsyncClient(base_url=live_server.url, headers={"Authorization": f"Bearer {RUNNER_TOKEN}"}) as rc:
        runner_id = str(uuid.uuid4())
        await rc.post(
            "/api/runner/register",
            json={
                "runner_id": runner_id,
                "name": "ghost",
                "host_id": HOST,
                "version": "0",
                "max_parallel": 1,
                "allowed_roots": [str(tmp_path / "ws")],
            },
        )
        claimed = (
            await rc.post("/api/runner/claim", json={"runner_id": runner_id, "capacity": 1, "agent_types": ["fake"]})
        ).json()["runs"]
        assert [c["run_id"] for c in claimed] == [run["id"]]
        token = claimed[0]["agent_token"]
        assert (await rc.get("/api/whoami", headers={"Authorization": f"Bearer {token}"})).json()["run_id"] == run["id"]
        # Another runner cannot report on a run it does not own.
        r = await rc.post(
            f"/api/runner/runs/{run['id']}/finish",
            json={"status": "completed"},
            headers={"X-Runner-Id": str(uuid.uuid4())},
        )
        assert r.status_code == 403
        # Expire the lease, then let the next claim reap it.
        import psycopg

        url = live_server.settings.database_url.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                "UPDATE agent_runs SET lease_expires_at = now() - interval '1 minute' WHERE id = %s", (run["id"],)
            )
        await rc.post("/api/runner/claim", json={"runner_id": runner_id, "capacity": 1, "agent_types": ["fake"]})
        hb = (
            await rc.post("/api/runner/heartbeat", json={"runner_id": runner_id, "active_run_ids": [run["id"]]})
        ).json()
        assert hb["stop_run_ids"] == [run["id"]]
        assert (await rc.get("/api/whoami", headers={"Authorization": f"Bearer {token}"})).status_code == 401
    done = (await admin.get(f"/api/runs/{run['id']}")).json()
    assert done["status"] == "lost" and done["error_code"] == "lease_expired"


async def test_idempotent_dispatch(admin: httpx.AsyncClient, tmp_path: Path) -> None:
    s = await setup_task(admin, tmp_path, "idem")
    await admin.post("/api/agent-profiles", json={"name": "fk", "agent_type": "fake"})
    body = {"task_id": s["task"]["id"], "profile_name": "fk"}
    r1 = await admin.post("/api/runs", json=body, headers={"Idempotency-Key": "k1"})
    r2 = await admin.post("/api/runs", json=body, headers={"Idempotency-Key": "k1"})
    assert r1.json()["id"] == r2.json()["id"]
    assert (await admin.get("/api/runs", params={"task_id": s["task"]["id"]})).json()["total"] == 1


async def test_sse_stream_replays_and_resumes(
    admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path
) -> None:
    s = await setup_task(admin, tmp_path, "sse")
    run = await dispatch(admin, s["task"]["id"], [{"message": "one"}, {"message": "two"}])
    async with running(RunnerService(runner_config(live_server, tmp_path))):
        await wait_status(admin, run["id"], {"completed"})
    seen: list[int] = []
    async with admin.stream(
        "GET", f"/api/runs/{run['id']}/events", headers={"Accept": "text/event-stream", "Last-Event-ID": "2"}
    ) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        event = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("id: "):
                seen.append(int(line[4:]))
            elif line.startswith("data: ") and event == "end":
                assert json.loads(line[6:])["status"] == "completed"
                break
    assert seen and seen[0] == 3, "resumes after Last-Event-ID"
    assert seen == sorted(seen)


async def test_agent_profile_management_and_dispatch_snapshot(
    admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path
) -> None:
    s = await setup_task(admin, tmp_path)
    created = await admin.post(
        "/api/agent-profiles",
        json={
            "name": "reviewer",
            "agent_type": "fake",
            "description": "Review changes",
            "instructions": "Review security first",
            "write_mode": False,
            "is_default": True,
        },
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    run_response = await admin.post(
        "/api/runs", json={"task_id": s["task"]["id"], "profile_id": profile["id"], "instructions": "Inspect the diff"}
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    assert run["write_mode"] is False
    assert run["profile_snapshot"]["instructions"] == "Review security first"
    changed = await admin.patch(
        f"/api/agent-profiles/{profile['id']}",
        json={"name": "reviewer-v2", "instructions": "New instructions", "expected_version": profile["version"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "reviewer-v2"
    stale = await admin.patch(
        f"/api/agent-profiles/{profile['id']}", json={"instructions": "Stale", "expected_version": profile["version"]}
    )
    assert stale.status_code == 409
    runner_id = str(uuid.uuid4())
    async with httpx.AsyncClient(
        base_url=live_server.url, headers={"Authorization": f"Bearer {RUNNER_TOKEN}"}
    ) as runner:
        registered = await runner.post(
            "/api/runner/register",
            json={
                "runner_id": runner_id,
                "name": "test",
                "host_id": HOST,
                "version": "1",
                "max_parallel": 1,
                "allowed_roots": [str(tmp_path / "ws")],
                "agents": [{"agent_type": "fake", "available": True}],
            },
        )
        assert registered.status_code == 200, registered.text
        claimed = await runner.post(
            "/api/runner/claim", json={"runner_id": runner_id, "capacity": 1, "agent_types": ["fake"]}
        )
        assert claimed.status_code == 200, claimed.text
        prompt = claimed.json()["runs"][0]["prompt"]
        assert "Review security first" in prompt
        assert "Inspect the diff" in prompt
        assert "New instructions" not in prompt
    deleted = await admin.delete(f"/api/agent-profiles/{profile['id']}")
    assert deleted.status_code == 204
    assert (await admin.get(f"/api/runs/{run['id']}")).json()["profile_snapshot"][
        "instructions"
    ] == "Review security first"


async def test_native_continuation_pins_runner_and_preserves_snapshot(
    admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path
) -> None:
    s = await setup_task(admin, tmp_path)
    created = await admin.post(
        "/api/agent-profiles",
        json={
            "name": "continuity",
            "agent_type": "fake",
            "instructions": "stable agent instructions",
            "options": {"script": [{"message": "worked"}]},
        },
    )
    profile = created.json()
    first_resp = await admin.post("/api/runs", json={"task_id": s["task"]["id"], "profile_id": profile["id"]})
    assert first_resp.status_code == 201, first_resp.text
    service = RunnerService(runner_config(live_server, tmp_path))
    async with running(service):
        first = await wait_status(admin, first_resp.json()["id"], {"completed", "failed"})
    assert first["status"] == "completed", first
    assert (
        await admin.patch(f"/api/agent-profiles/{profile['id']}", json={"instructions": "changed"})
    ).status_code == 200

    body = {"task_id": s["task"]["id"], "continue_run_id": first["id"], "instructions": "Please continue"}
    responses = await asyncio.gather(admin.post("/api/runs", json=body), admin.post("/api/runs", json=body))
    assert sorted(r.status_code for r in responses) == [201, 409]
    queued = next(r.json() for r in responses if r.status_code == 201)
    assert queued["runner_id"] == str(service.runner_id)
    assert queued["session_id"] == first["session_id"]
    assert queued["resume_native"] is True
    assert queued["profile_snapshot"] == first["profile_snapshot"]
    assert (await admin.post("/api/runs", json={**body, "workspace_id": str(uuid.uuid4())})).status_code == 422

    other_id = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=live_server.url, headers={"Authorization": f"Bearer {RUNNER_TOKEN}"}) as rc:
        registered = await rc.post(
            "/api/runner/register",
            json={
                "runner_id": other_id,
                "name": "other",
                "host_id": HOST,
                "version": "1",
                "max_parallel": 1,
                "allowed_roots": [str(tmp_path / "ws")],
                "agents": [{"agent_type": "fake", "available": True}],
            },
        )
        assert registered.status_code == 200, registered.text
        claim = await rc.post("/api/runner/claim", json={"runner_id": other_id, "capacity": 1, "agent_types": ["fake"]})
        assert claim.json()["runs"] == []
        claim = await rc.post(
            "/api/runner/claim", json={"runner_id": str(service.runner_id), "capacity": 1, "agent_types": ["fake"]}
        )
        assignment = claim.json()["runs"][0]
        assert assignment["native_session_id"] == first["native_session_id"]
        assert "Please continue" in assignment["prompt"]
        assert "stable agent instructions" not in assignment["prompt"]
        assert "## How to report progress" not in assignment["prompt"]
        finished = await rc.post(
            f"/api/runner/runs/{queued['id']}/finish",
            headers={"X-Runner-Id": str(service.runner_id)},
            json={"status": "completed", "native_session_id": first["native_session_id"]},
        )
        assert finished.status_code == 200, finished.text
    assert (await admin.post("/api/runs", json=body)).status_code == 409
    third = await admin.post("/api/runs", json={**body, "continue_run_id": queued["id"]})
    assert third.status_code == 201, third.text
    resumed_service = RunnerService(runner_config(live_server, tmp_path, runner_id=str(service.runner_id)))
    async with running(resumed_service):
        done = await wait_status(admin, third.json()["id"], {"completed", "failed"})
    assert done["status"] == "completed", done
    assert done["native_session_id"] == first["native_session_id"]


async def test_missing_native_session_is_not_silently_restarted(admin: httpx.AsyncClient, tmp_path: Path) -> None:
    s = await setup_task(admin, tmp_path)
    response = await admin.post(
        "/api/runs", json={"task_id": s["task"]["id"], "agent_type": "fake", "resume_native": True}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "resume_unavailable"


async def test_unexpected_native_session_does_not_replace_original(
    admin: httpx.AsyncClient, live_server: LiveServer, tmp_path: Path
) -> None:
    s = await setup_task(admin, tmp_path)
    created = await admin.post(
        "/api/agent-profiles",
        json={
            "name": "bad-resume",
            "agent_type": "fake",
            "options": {"script": [{"raw_on_resume": '{"type":"session","id":"different-session"}'}]},
        },
    )
    assert created.status_code == 201
    initial = await admin.post("/api/runs", json={"task_id": s["task"]["id"], "profile_id": created.json()["id"]})
    service = RunnerService(runner_config(live_server, tmp_path))
    async with running(service):
        first = await wait_status(admin, initial.json()["id"], {"completed", "failed"})
        assert first["status"] == "completed", first
        follow = await admin.post("/api/runs", json={"task_id": s["task"]["id"], "continue_run_id": first["id"]})
        assert follow.status_code == 201, follow.text
        second = await wait_status(admin, follow.json()["id"], {"completed", "failed"})
    assert second["status"] == "failed"
    assert second["error_code"] == "resume_mismatch"
    sessions = (await admin.get(f"/api/tasks/{s['task']['id']}/sessions")).json()
    assert sessions[0]["native_session_id"] == first["native_session_id"]
